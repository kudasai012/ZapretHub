"""Компонент zapret-discord-youtube (winws.exe).

Ключевая идея: стратегии из .bat-файлов не запускаются через cmd.exe, а
разбираются и преобразуются в прямой запуск bin/winws.exe дочерним процессом
нашего приложения. Так мы:
  * знаем PID и можем корректно остановить компонент;
  * не зависим от консольных окон и служебных проверок service.bat;
  * управляем всем из одного интерфейса.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal

from .. import paths
from ..config import AppConfig
from . import netutil, win32
from .procman import STATUS_STOPPED, ManagedProcess

USER_LISTS = {
    "list-general-user.txt": "# Never leave this file empty\ndomain.example.abc\n",
    "list-exclude-user.txt": "domain.example.abc\n",
    "ipset-exclude-user.txt": "203.0.113.113/32\n",
}

IPSET_PLACEHOLDER = "203.0.113.113/32"
IPSET_URL = (
    "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/"
    "refs/heads/main/.service/ipset-service.txt"
)

SERVICE_NAME = "zapret"


class ZapretError(Exception):
    pass


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _tokenize_windows(line: str) -> List[str]:
    """Разбор командной строки Windows: кавычки обрамляют токен и удаляются."""
    tokens: List[str] = []
    cur: List[str] = []
    in_quotes = False
    has_token = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
            has_token = True
            continue
        if not in_quotes and ch in " \t":
            if has_token:
                tokens.append("".join(cur))
                cur = []
                has_token = False
            continue
        cur.append(ch)
        has_token = True
    if has_token:
        tokens.append("".join(cur))
    return tokens


# Сколько ждать после остановки zapret перед пробным запуском: процесс
# уже мёртв, но фильтр WinDivert освобождает ядро, и новая копия winws
# успевала стартовать раньше и получить отказ.
PROBE_SETTLE_SECONDS = 1.5

# Сколько ждать, пока winws.exe подтвердит, что он действительно работает.
# Отказ «A copy of winws is already running with the same filter» приходит
# через пару сотен миллисекунд, поэтому проверка короче секунды — уже
# достаточна, а пользователь задержки не замечает.
START_CONFIRM_SECONDS = 0.8

# Известные причины, по которым winws.exe умирает сразу после старта.
# Текст — как его пишет сам winws; он английский, а пользователю нужен
# прямой ответ по-русски. Код выхода при всех случаях 1, поэтому без
# этого сопоставления в интерфейсе оставалось бы «завершился с кодом 1».
WINWS_KNOWN_FAILURES: Tuple[Tuple[str, str], ...] = (
    (
        "A copy of winws is already running with the same filter",
        "уже запущена другая копия winws с тем же фильтром — "
        "выключите zapret (или снимите службу) и повторите",
    ),
    (
        "error opening filter",
        "фильтр WinDivert занят предыдущей копией winws — "
        "подождите пару секунд и повторите",
    ),
    (
        "could not read",
        "winws не смог прочитать свои файлы — "
        "переустановите компонент zapret",
    ),
)


def winws_failure_reason(output: Sequence[str]) -> str:
    """Человеческая причина провала по тому, что написал сам winws.

    Раньше причина провала в интерфейсе не отличалась от кода выхода:
    «завершился с кодом 1» и дальше простыня английского лога. Пользователю
    приходилось самому искать в ней строку, которая что-то значит.
    """
    for line in output:
        for needle, reason in WINWS_KNOWN_FAILURES:
            if needle in line:
                return reason
    return ""


class ZapretComponent(QObject):
    status_changed = Signal(str)
    log_line = Signal(str)

    def __init__(self, config: AppConfig, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.config = config
        self._proc: Optional[ManagedProcess] = None
        # причина, по которой последняя попытка запуска не удержалась:
        # winws.exe отказывается работать второй копией с тем же фильтром
        self._last_start_failed = ""

    # ------------------------------------------------------------ пути

    @property
    def dir(self) -> Path:
        return paths.ZAPRET_DIR

    @property
    def bin_dir(self) -> Path:
        return self.dir / "bin"

    @property
    def lists_dir(self) -> Path:
        return self.dir / "lists"

    @property
    def utils_dir(self) -> Path:
        return self.dir / "utils"

    @property
    def winws(self) -> Path:
        return self.bin_dir / "winws.exe"

    def installed(self) -> bool:
        return self.winws.exists() and (self.dir / "service.bat").exists()

    def version(self) -> Optional[str]:
        """LOCAL_VERSION из service.bat."""
        try:
            text = (self.dir / "service.bat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        m = re.search(r'set\s+"LOCAL_VERSION=([^"]+)"', text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"LOCAL_VERSION=([\d.]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def version_display(self) -> str:
        return self.version() or "—"

    # ------------------------------------------------------------ стратегии

    def strategies(self) -> List[str]:
        if not self.dir.exists():
            return []
        files = [
            p.name
            for p in self.dir.glob("*.bat")
            if not p.name.lower().startswith("service")
        ]
        return sorted(files, key=natural_key)

    def _read_bat(self, path: Path) -> List[str]:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        text = raw.replace("\r\n", "\n").replace("\r", "\n")
        return text.split("\n")

    @staticmethod
    def _join_continuations(lines: List[str]) -> List[str]:
        joined: List[str] = []
        buf = ""
        for line in lines:
            stripped = line.rstrip()
            if stripped.endswith("^"):
                buf += stripped[:-1] + " "
                continue
            buf += stripped
            joined.append(buf)
            buf = ""
        if buf:
            joined.append(buf)
        return joined

    def _bat_variables(self, lines: List[str]) -> Dict[str, str]:
        variables: Dict[str, str] = {}
        for line in lines:
            m = re.match(r'\s*set\s+"?([A-Za-z_][A-Za-z0-9_]*)=(.*?)"?\s*$', line, re.IGNORECASE)
            if not m:
                continue
            name, value = m.group(1).upper(), m.group(2).strip()
            value = value.replace("%~dp0", str(self.dir) + os.sep)
            if os.sep != "\\":
                # на не-Windows нормализуем обратные слеши из .bat
                value = value.replace("\\", os.sep)
            variables[name] = value
        variables.setdefault("BIN", str(self.bin_dir) + os.sep)
        variables.setdefault("LISTS", str(self.lists_dir) + os.sep)
        return variables

    @staticmethod
    def _expand(text: str, variables: Dict[str, str]) -> str:
        def repl(match: re.Match) -> str:
            name = match.group(1).upper()
            return variables.get(name, match.group(0))

        return re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", repl, text)

    def game_filter_values(self) -> Dict[str, str]:
        """Значения %GameFilterTCP% / %GameFilterUDP% (логика service.bat)."""
        state = self.config.zapret
        disabled = "12"
        mode = state.game_mode
        if mode == "all":
            return {"GAMEFILTERTCP": state.game_tcp_range, "GAMEFILTERUDP": state.game_udp_range}
        if mode == "tcp":
            return {"GAMEFILTERTCP": state.game_tcp_range, "GAMEFILTERUDP": disabled}
        if mode == "udp":
            return {"GAMEFILTERTCP": disabled, "GAMEFILTERUDP": state.game_udp_range}
        return {"GAMEFILTERTCP": disabled, "GAMEFILTERUDP": disabled}

    def parse_strategy(self, name: Optional[str] = None) -> Tuple[Path, List[str]]:
        """Возвращает (путь к winws.exe, список аргументов) для выбранной стратегии."""
        name = name or self.config.zapret.strategy
        bat_path = self.dir / name
        if not bat_path.exists():
            raise ZapretError(f"Файл стратегии не найден: {name}")

        lines = self._read_bat(bat_path)
        variables = self._bat_variables(lines)
        variables.update(self.game_filter_values())
        commands = self._join_continuations(lines)

        for cmd in commands:
            stripped = cmd.strip()
            if not stripped.lower().startswith("start"):
                continue
            expanded = self._expand(stripped, variables)
            tokens = _tokenize_windows(expanded)
            exe_index = None
            for i, tok in enumerate(tokens):
                if tok.lower().endswith("winws.exe"):
                    exe_index = i
                    break
            if exe_index is None:
                continue
            exe = Path(tokens[exe_index])
            args = [t for t in tokens[exe_index + 1:] if t]
            if not exe.is_absolute():
                exe = (self.bin_dir / exe).resolve()
            return exe, args

        raise ZapretError(f"Не удалось разобрать стратегию {name}: команда запуска winws.exe не найдена")

    def command_line_display(self, name: Optional[str] = None) -> str:
        try:
            exe, args = self.parse_strategy(name)
        except ZapretError as exc:
            return f"# {exc}"
        parts = [f'"{exe}"'] + [f'"{a}"' if (" " in a or "\t" in a) else a for a in args]
        return " ".join(parts)

    # ------------------------------------------------------------ game filter

    def game_filter_file(self) -> Path:
        return self.utils_dir / "game_filter.enabled"

    def game_filter_state(self) -> Dict[str, str]:
        """Текущее состояние из файла компонента (источник истины на диске)."""
        state = {"mode": "disabled", "tcp": "1024-65535", "udp": "1024-65535"}
        path = self.game_filter_file()
        if not path.exists():
            return state
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or "=" not in line:
                    if line.lower() in ("all", "tcp", "udp"):
                        state["mode"] = line.lower()
                    continue
                key, value = line.split("=", 1)
                key = key.strip().lower()
                value = value.strip()
                if key == "mode" and value.lower() in ("all", "tcp", "udp", "disabled"):
                    state["mode"] = value.lower()
                elif key == "tcp" and value:
                    state["tcp"] = value
                elif key == "udp" and value:
                    state["udp"] = value
        except OSError:
            pass
        return state

    def apply_game_filter(self) -> None:
        """Записывает состояние Game Filter из конфига в файл компонента."""
        z = self.config.zapret
        if z.game_mode == "disabled":
            try:
                self.game_filter_file().unlink(missing_ok=True)
            except OSError:
                pass
            return
        content = f"mode={z.game_mode}\ntcp={z.game_tcp_range}\nudp={z.game_udp_range}\n"
        try:
            self.utils_dir.mkdir(parents=True, exist_ok=True)
            self.game_filter_file().write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ZapretError(f"Не удалось записать game_filter.enabled: {exc}") from exc

    # ------------------------------------------------------------ ipset

    def ipset_file(self) -> Path:
        return self.lists_dir / "ipset-all.txt"

    def ipset_state(self) -> str:
        path = self.ipset_file()
        if not path.exists():
            return "any"
        try:
            lines = [l.strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        except OSError:
            return "any"
        if not lines:
            return "any"
        if len(lines) == 1 and lines[0] == IPSET_PLACEHOLDER:
            return "none"
        return "loaded"

    def apply_ipset_mode(self, mode: Optional[str] = None) -> None:
        mode = mode or self.config.zapret.ipset_mode
        path = self.ipset_file()
        backup = path.with_suffix(path.suffix + ".backup")
        try:
            self.lists_dir.mkdir(parents=True, exist_ok=True)
            current = ""
            if path.exists():
                current = path.read_text(encoding="utf-8", errors="replace")
            if mode == "none":
                stripped = "\n".join(
                    l for l in current.splitlines() if l.strip() and l.strip() != IPSET_PLACEHOLDER
                )
                if stripped.strip() and not backup.exists():
                    backup.write_text(current, encoding="utf-8")
                path.write_text(IPSET_PLACEHOLDER + "\n", encoding="utf-8")
            elif mode == "any":
                if current.strip() and not backup.exists():
                    backup.write_text(current, encoding="utf-8")
                path.write_text("", encoding="utf-8")
            else:  # loaded
                if backup.exists():
                    path.write_text(backup.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                elif not path.exists():
                    path.write_text("", encoding="utf-8")
        except OSError as exc:
            raise ZapretError(f"Не удалось применить IPSet-режим: {exc}") from exc
        self.config.zapret.ipset_mode = mode

    # ------------------------------------------------------------ пользовательские списки

    def ensure_user_lists(self) -> None:
        try:
            self.lists_dir.mkdir(parents=True, exist_ok=True)
            for name, default in USER_LISTS.items():
                path = self.lists_dir / name
                if not path.exists():
                    path.write_text(default, encoding="utf-8")
        except OSError:
            pass

    def list_files(self) -> List[str]:
        """Все .txt-списки из lists/ — и общие, и пользовательские."""
        try:
            names = sorted(
                entry.name
                for entry in self.lists_dir.glob("*.txt")
                if entry.is_file()
            )
        except OSError:
            names = []
        # пользовательские списки всегда доступны, даже если их ещё нет на диске
        for name in USER_LISTS:
            if name not in names:
                names.append(name)
        return sorted(names)

    def read_user_list(self, name: str) -> str:
        path = self.lists_dir / name
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def write_user_list(self, name: str, text: str) -> None:
        path = self.lists_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if text and not text.endswith("\n"):
            text += "\n"
        path.write_text(text, encoding="utf-8")

    # ------------------------------------------------------------ служба Windows

    def service_state(self) -> Optional[str]:
        return win32.query_service(SERVICE_NAME)

    def service_conflict(self) -> Optional[str]:
        state = self.service_state()
        if state and state not in ("STOPPED",):
            return state
        return None

    def remove_service(self) -> bool:
        return win32.remove_service(SERVICE_NAME)

    # ------------------------------------------------------------ запуск

    def own_pids(self) -> set:
        """PID наших собственных дочерних процессов — их никогда не гасим.

        winws.exe тоже может распаковывать себя и запускать второй процесс
        с тем же именем, поэтому «свои» — это всё дерево, а не только главный
        PID.
        """
        pids = set()
        proc = getattr(self, "_proc", None)
        if proc is not None:
            try:
                pids |= proc.own_pids()
            except Exception:
                pass
        return pids

    def _kill_foreign_processes(self) -> None:
        """Останавливает winws.exe, запущенный не Zapret Hub."""
        try:
            killed = win32.kill_foreign_processes("winws.exe", self.own_pids())
        except Exception as exc:  # noqa: BLE001
            self._log(f"[hub] не удалось проверить сторонние процессы: {exc}")
            return
        if killed:
            self._log(
                "[hub] остановлен сторонний winws.exe (PID "
                + ", ".join(str(pid) for pid in killed)
                + ") — запускаю свой"
            )
            time.sleep(0.6)

    def _log(self, text: str) -> None:
        self.log_line.emit(text)

    def start(self) -> bool:
        if self.is_running():
            return True
        if not self.installed():
            self._log("[hub] компонент не установлен")
            self.status_changed.emit(STATUS_STOPPED)
            return False
        if not win32.IS_WINDOWS:
            self._log("[hub] zapret работает только в Windows")
            self.status_changed.emit(STATUS_STOPPED)
            return False
        if not win32.is_admin():
            self._log(
                "[hub] нужны права администратора: перезапустите Zapret Hub от имени администратора"
            )
            self.status_changed.emit(STATUS_STOPPED)
            return False

        conflict = self.service_conflict()
        if conflict:
            self._log(
                f"[hub] служба Windows «zapret» активна ({conflict}) — "
                "уберите её, иначе winws.exe не запустится"
            )
            self.status_changed.emit(STATUS_STOPPED)
            return False

        # чужой winws.exe (запущен не нами) мешает: гасим его и запускаем свой
        self._kill_foreign_processes()

        # применяем настройки из интерфейса к файлам компонента
        try:
            self.ensure_user_lists()
            self.apply_game_filter()
            self.apply_ipset_mode()
        except ZapretError as exc:
            self._log(f"[hub] {exc}")
            return False

        win32.enable_tcp_timestamps()

        try:
            exe, args = self.parse_strategy()
        except ZapretError as exc:
            self._log(f"[hub] {exc}")
            return False

        if not exe.exists():
            self._log(f"[hub] не найден {exe}")
            return False

        ok = self._launch(exe, args)
        if not ok:
            # winws.exe мог умереть сразу: «A copy of winws is already
            # running with the same filter» — своя же предыдущая копия ещё
            # держит фильтр WinDivert. Раньше это выглядело как успешный
            # старт, и обход просто молча не работал. Один повтор с паузой
            # такие случаи вытягивает.
            if self._last_start_failed:
                time.sleep(PROBE_SETTLE_SECONDS)
                ok = self._launch(exe, args)
        if ok:
            self._log("[hub] zapret запущен (winws.exe)")
        elif self._last_start_failed:
            self._log(f"[hub] {self._last_start_failed}")
        return ok

    def _launch(self, exe: Path, args: List[str]) -> bool:
        """Один реальный запуск winws.exe + проверка, что он дожил.

        ``ManagedProcess.start()`` возвращает успех, если процесс создан, —
        но не если он уцелел. winws.exe отказывается работать второй копией
        с тем же фильтром и выходит с кодом 1 через пару сотен миллисекунд,
        то есть уже после того, как ``start()`` отрапортовал успех.
        """
        self._last_start_failed = ""
        self._proc = ManagedProcess(
            key="zapret",
            exe=exe,
            args=args,
            cwd=exe.parent,
            log_file=paths.LOGS_DIR / "zapret.log",
            parent=self,
            image="winws.exe",
        )
        self._proc.status_changed.connect(self.status_changed)
        self._proc.log_line.connect(self._log)
        self._log(f"[hub] стратегия: {self.config.zapret.strategy}")
        if not self._proc.start():
            return False

        # winws пишет причину отказа в лог и умирает. Ждём ровно столько,
        # чтобы отказ успел произойти, но недостаточно, чтобы пользователь
        # заметил задержку при нормальном старте.
        deadline = time.time() + START_CONFIRM_SECONDS
        while time.time() < deadline:
            if not self._proc.is_running():
                break
            time.sleep(0.05)

        if self._proc.is_running():
            return True

        # процесс умер: причина — из его же последних строк
        tail = self._recent_log_lines()
        self._last_start_failed = winws_failure_reason(tail) or (
            "winws.exe завершился сразу после запуска"
        )
        return False

    def _recent_log_lines(self, count: int = 40) -> List[str]:
        """Последние строки журнала winws — для разбора причины отказа."""
        try:
            text = paths.LOGS_DIR.joinpath("zapret.log").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return []
        return [line for line in text.splitlines() if line.strip()][-count:]

    def stop(self) -> None:
        if self._proc:
            self._proc.stop()
        self.status_changed.emit(STATUS_STOPPED)

    def restart(self) -> bool:
        """Перезапуск с гарантированно новым процессом.

        Обычный ``start()`` возвращает True, если winws уже жив, и новый
        процесс при этом не поднимается. Для смены стратегии это неверно:
        остаётся winws от прошлой стратегии, и замеры идут по нему. Поэтому
        здесь стоп обязателен, а если стоп не добил процесс (winws держит
        фильтр WinDivert и может не реагировать на terminate) — гасим по имени
        образа и ждём, пока PID действительно исчезнет.
        """
        self.stop()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not self.is_running():
                break
            try:
                win32.kill_foreign_processes("winws.exe", self.own_pids())
            except Exception:  # noqa: BLE001 - не роняем перезапуск
                pass
            time.sleep(0.3)
        else:
            self._log("[hub] winws не остановился, перезапуск отменён")
            return False
        time.sleep(0.4)
        return self.start()

    def is_running(self) -> bool:
        return bool(self._proc and self._proc.is_running())

    @property
    def status(self) -> str:
        if self._proc is None:
            return STATUS_STOPPED
        return self._proc.status

    def uptime(self) -> float:
        return self._proc.uptime() if self._proc else 0.0

    def pid(self) -> int:
        return self._proc.pid if self._proc else -1

    def command_line(self) -> str:
        return self._proc.command_line() if self._proc else ""

    # ------------------------------------------------------------ обслуживание

    def update_ipset_list(self, proxy: str = "") -> str:
        """Скачивает актуальный ipset-список (как пункт 8 в service.bat)."""
        data = netutil.http_get(IPSET_URL, proxy=proxy, timeout=30)
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            raise ZapretError("Получен пустой список IP")
        self.lists_dir.mkdir(parents=True, exist_ok=True)
        self.ipset_file().write_text(text, encoding="utf-8")
        self.config.zapret.ipset_mode = "loaded"
        lines = len([l for l in text.splitlines() if l.strip()])
        return f"IPSet обновлён: {lines} записей"

    def probe_start(self, seconds: float = 3.0) -> Dict[str, object]:
        """Однократная проверка: сможем ли мы вообще запустить стратегию.

        Диагностика стратегий перебирает все ``general*.bat`` и меряет сайты.
        Если по какой-то причине ``winws.exe`` не держится (нет прав, занят
        файл, служба ``zapret``, битый список), каждая стратегия получает
        отказ — и выглядит это как «диагностика сломалась», хотя причина
        одна и та же. Этот метод запускает стратегию один раз, ждёт
        ``seconds`` и возвращает факты: жив ли процесс, чем завершился,
        что он сам написал. Дальше UI показывает их словами.

        Раньше такой проверки не было: пользователь видел только «нет
        доступа» в каждой строке и не мог понять, где именно ошибка.
        """
        result: Dict[str, object] = {
            "started": False,
            "alive": False,
            "exit_code": None,
            "reason": "",
            "output": [],
            "command": "",
        }
        # Служба zapret и standalone-запуск не уживаются: фильтр WinDivert
        # один на систему. Пакет штатно ставит winws.exe службой
        # (service.bat), и его же service.bat в этом случае отказывается
        # запускать стратегию напрямую. Раньше проба просто сообщала
        # «служба активна» — и пользователь оставался без ответа, хотя
        # достаточно остановить службу на время проверки и вернуть после.
        service_was_running = False
        try:
            state = self.service_state()
        except Exception:  # noqa: BLE001 - проверка может быть недоступна
            state = None
        if state and state not in ("STOPPED", "STOP_PENDING"):
            if win32.stop_service(SERVICE_NAME):
                service_was_running = True
                time.sleep(PROBE_SETTLE_SECONDS)
            else:
                result["reason"] = (
                    f"служба zapret активна ({state}) и не остановилась — "
                    "уберите её через service.bat"
                )
                return result

        # Службу возвращаем через finally, а не в каждой ветке выхода:
        # в теле пробы есть ранние return (не найден exe, битый .bat,
        # не удалось запустить), и на любом из них служба обязана вернуться
        # на место. Иначе кнопка диагностики тихо оставляла бы обход
        # отключённым.
        try:
            return self._probe_body(result, seconds)
        finally:
            if service_was_running:
                self._restore_service()

    def _probe_body(
        self, result: Dict[str, object], seconds: float
    ) -> Dict[str, object]:
        """Сама проба: запустить winws.exe и посмотреть, доживёт ли.

        Вынесено из ``probe_start``, чтобы остановка и возврат службы zapret
        жили в одном месте (``finally``) и не дублировались по веткам.
        """
        reason = self.start_block_reason()
        if reason:
            result["reason"] = reason
            return result

        # winws.exe сам отказывается работать второй копией: «A copy of
        # winws is already running with the same filter» и код 1. Раньше
        # проба запускалась поверх уже включённого zapret, и пользователь
        # видел «завершился с кодом 1» с простынёй английского текста, из
        # которого надо было самому догадаться, что мешает своя же копия.
        # Теперь перед пробой гасим компонент и ждём, пока ядро отпустит
        # фильтр WinDivert, а после неё возвращаем всё как было.
        was_running = self.is_running()
        if was_running:
            self.stop()
            # процесс мёртв, но фильтр WinDivert ещё держится ядром: без
            # этой паузы следующая копия получает отказ по той же причине
            time.sleep(PROBE_SETTLE_SECONDS)
        try:
            exe, args = self.parse_strategy()
            result["command"] = " ".join([str(exe)] + [str(a) for a in args])
        except ZapretError as exc:
            result["reason"] = str(exc)
            return result
        if not exe.exists():
            result["reason"] = f"не найден {exe}"
            return result

        raw = paths.LOGS_DIR / "zapret-probe.out.log"
        try:
            raw.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        handle = None
        try:
            handle = open(raw, "wb")
        except OSError:
            handle = None

        proc = None
        try:
            proc = subprocess.Popen(
                [str(exe)] + [str(a) for a in args],
                cwd=str(exe.parent),
                stdout=handle if handle is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=win32.creation_flags(),
            )
        except Exception as exc:  # noqa: BLE001 - причина и есть ответ
            result["reason"] = f"не удалось запустить: {exc}"
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
            return result
        finally:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass

        result["started"] = True
        result["pid"] = proc.pid
        deadline = time.time() + max(0.5, seconds)
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.1)

        if proc.poll() is None:
            result["alive"] = True
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        else:
            result["exit_code"] = proc.returncode

        try:
            text = raw.read_text(encoding="utf-8", errors="replace")
            lines = [line for line in text.splitlines() if line.strip()]
            result["output"] = lines[-25:]
        except OSError:
            pass

        # Причина провала называется словами, а не кодом выхода. Проверка
        # запуска существует ровно для этого: сказать, что не так.
        if not result["alive"] and not result["reason"]:
            known = winws_failure_reason(result["output"])
            if known:
                result["reason"] = known

        # Возвращаем zapret в то состояние, в котором он был до пробы:
        # кнопка диагностическая, а не выключатель обхода. Свою пробную
        # копию мы к этому моменту уже погасили (или она умерла сама), так
        # что фильтр свободен — но ядро отпускает его не мгновенно.
        if was_running:
            time.sleep(PROBE_SETTLE_SECONDS)
            self.start()

        return result

    def _restore_service(self) -> bool:
        """Возвращает службу zapret, которую гасили ради проверки."""
        self._log("[hub] возвращаю службу zapret")
        ok = win32.start_service(SERVICE_NAME)
        self._log(
            "[hub] служба zapret снова запущена"
            if ok
            else "[hub] не удалось вернуть службу zapret — запустите её вручную"
        )
        return ok

    def start_block_reason(self) -> str:
        """Почему стратегию нельзя запустить прямо сейчас. Пусто — можно.

        Вынесено из ``start()``: раньше причина проверялась только внутри
        него и уходила в общий журнал, а в интерфейсе оставалось «нет
        доступа».
        """
        if not self.installed():
            return "компонент zapret не установлен"
        if not win32.IS_WINDOWS:
            return "zapret работает только в Windows"
        if not win32.is_admin():
            return (
                "нужны права администратора: winws.exe работает через "
                "WinDivert и без повышения не запускается"
            )
        conflict = self.service_conflict()
        if conflict:
            return f"служба Windows «zapret» активна ({conflict}) — уберите её"
        return ""

    def run_diagnostics(self) -> bool:
        """Запускает utils/test zapret.ps1 в отдельном окне PowerShell."""
        script = self.utils_dir / "test zapret.ps1"
        if not script.exists():
            self._log("[hub] test zapret.ps1 не найден")
            return False
        try:
            import subprocess

            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                creationflags=win32.CREATE_NEW_PROCESS_GROUP,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            self._log(f"[hub] не удалось запустить диагностику: {exc}")
            return False
