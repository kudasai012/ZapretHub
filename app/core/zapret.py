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
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


class ZapretComponent(QObject):
    status_changed = Signal(str)
    log_line = Signal(str)

    def __init__(self, config: AppConfig, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.config = config
        self._proc: Optional[ManagedProcess] = None

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
        ok = self._proc.start()
        if ok:
            self._log("[hub] zapret запущен (winws.exe)")
        return ok

    def stop(self) -> None:
        if self._proc:
            self._proc.stop()
        self.status_changed.emit(STATUS_STOPPED)

    def restart(self) -> bool:
        self.stop()
        time.sleep(0.6)
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
