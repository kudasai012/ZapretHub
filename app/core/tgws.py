"""Компонент TG WS Proxy (TgWsProxy_windows.exe).

Приложение Flowseal — это tray-программа на Python. Мы запускаем её
дочерним процессом в портативном режиме (`--portable`), поэтому её конфиг и
логи лежат рядом с ней в TgWsProxy_data/ и полностью управляются из нашего Hub.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .. import paths
from ..config import AppConfig
from . import win32
from .procman import STATUS_STOPPED, ManagedProcess

EXE_NAME = "TgWsProxy_windows.exe"
PORTABLE_DIR = "TgWsProxy_data"
FIRST_RUN_MARKER = ".first_run_done_mtproto"
IPV6_WARN_MARKER = ".ipv6_warned"
CONFIG_NAME = "config.json"
LOG_NAME = "proxy.log"
# отдельный рабочий стол: сторонняя tray-программа не светится в трее
HIDDEN_DESKTOP = "ZapretHub"


class TgwsError(Exception):
    pass


def default_config() -> Dict:
    return {
        "host": "127.0.0.1",
        "port": 1443,
        "secret": os.urandom(16).hex(),
        "dc_ip": ["2:149.154.167.220", "4:149.154.167.220"],
        "verbose": False,
        "buf_kb": 256,
        "pool_size": 4,
        "cfproxy": True,
        "force_test_dc": False,
        "no_secure": False,
        "check_updates": False,
        "log_max_mb": 5,
        "language": "ru",
    }


class TgWsComponent(QObject):
    status_changed = Signal(str)
    log_line = Signal(str)

    def __init__(self, config: AppConfig, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.config = config
        self._proc: Optional[ManagedProcess] = None
        self._log_pos = 0
        self._tail_timer = QTimer(self)
        self._tail_timer.setInterval(1000)
        self._tail_timer.timeout.connect(self._tail_log)
        # TgWsProxy_windows.exe — tray-программа: она сама добавляет свою
        # иконку в область уведомлений. Управление остаётся в Hub, поэтому
        # иконка убирается, как только появится.
        self._tray_timer = QTimer(self)
        self._tray_timer.setInterval(1500)
        self._tray_timer.timeout.connect(self._hide_tray_icon)
        self._tray_hidden = False

    # ------------------------------------------------------------ пути

    @property
    def dir(self) -> Path:
        return paths.TGWS_DIR

    @property
    def exe(self) -> Path:
        return self.dir / EXE_NAME

    @property
    def portable_dir(self) -> Path:
        return self.dir / PORTABLE_DIR

    @property
    def config_file(self) -> Path:
        return self.portable_dir / CONFIG_NAME

    @property
    def log_file(self) -> Path:
        return self.portable_dir / LOG_NAME

    def installed(self) -> bool:
        return self.exe.exists()

    def version_display(self) -> str:
        from ..config import load_manifest
        from .updater import read_version_marker

        manifest = load_manifest()
        entry = manifest.get("tgws") or {}
        version = entry.get("version") or read_version_marker(self.dir)
        return str(version or "—")

    # ------------------------------------------------------------ конфигурация

    def ensure_portable(self) -> None:
        """Создаёт портативную папку и маркер первого запуска (без окна-инструкции).

        Заодно создаём маркер предупреждения об IPv6: на нашем скрытом рабочем
        столе это окно всё равно никто не увидит, а поток с messagebox просто
        повиснет. Маркер гасит предупреждение навсегда.
        """
        try:
            self.portable_dir.mkdir(parents=True, exist_ok=True)
            for name in (FIRST_RUN_MARKER, IPV6_WARN_MARKER):
                marker = self.portable_dir / name
                if not marker.exists():
                    marker.touch()
        except OSError:
            pass

    def read_component_config(self) -> Dict:
        """Читает config.json компонента (или отдаёт значения из нашего конфига)."""
        data: Dict = {}
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        return data

    def build_config(self) -> Dict:
        """Собирает конфиг компонента из настроек Hub (сохраняя чужие ключи)."""
        cfg = default_config()
        cfg.update(self.read_component_config())
        t = self.config.tgws
        cfg.update(
            {
                "host": t.host,
                "port": int(t.port),
                "secret": t.secret,
                "dc_ip": list(t.dc_ip),
                "verbose": bool(t.verbose),
                "buf_kb": int(t.buf_kb),
                "pool_size": int(t.pool_size),
                "cfproxy": bool(t.cfproxy),
                "force_test_dc": bool(t.force_test_dc),
                "no_secure": bool(t.no_secure),
                "check_updates": bool(t.check_updates),
                "log_max_mb": float(t.log_max_mb),
                "autostart": False,  # автозапуском управляет Hub
            }
        )
        return cfg

    def write_config(self) -> bool:
        self.ensure_portable()
        try:
            self.config_file.write_text(
                json.dumps(self.build_config(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True
        except OSError:
            return False

    def import_config_from_component(self) -> Dict:
        """Подтягивает настройки из config.json компонента в наш конфиг."""
        data = self.read_component_config()
        t = self.config.tgws
        t.host = str(data.get("host", t.host))
        try:
            t.port = int(data.get("port", t.port))
        except (TypeError, ValueError):
            pass
        if data.get("secret"):
            t.secret = str(data["secret"])
        dc_ip = data.get("dc_ip")
        if isinstance(dc_ip, list) and dc_ip:
            t.dc_ip = [str(x) for x in dc_ip]
        t.verbose = bool(data.get("verbose", t.verbose))
        t.buf_kb = int(data.get("buf_kb", t.buf_kb) or t.buf_kb)
        t.pool_size = int(data.get("pool_size", t.pool_size) or t.pool_size)
        t.cfproxy = bool(data.get("cfproxy", t.cfproxy))
        t.force_test_dc = bool(data.get("force_test_dc", t.force_test_dc))
        t.no_secure = bool(data.get("no_secure", t.no_secure))
        return data

    # ------------------------------------------------------------ ссылка

    def proxy_link(self) -> str:
        host = self.config.tgws.host or "127.0.0.1"
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        port = int(self.config.tgws.port)
        secret = self.config.tgws.secret
        return f"tg://proxy?server={host}&port={port}&secret=dd{secret}"

    # ------------------------------------------------------------ запуск

    def _log(self, text: str) -> None:
        self.log_line.emit(text)

    def start(self) -> bool:
        if self.is_running():
            return True
        if not self.installed():
            self._log("[hub] TgWsProxy_windows.exe не найден")
            self.status_changed.emit(STATUS_STOPPED)
            return False
        if not win32.IS_WINDOWS:
            self._log("[hub] TG WS Proxy собирается только под Windows")
            self.status_changed.emit(STATUS_STOPPED)
            return False

        # чужой TgWsProxy (запущен не нами) держит порт — гасим и запускаем свой
        self._kill_foreign_processes()

        self.write_config()
        self._log_pos = 0
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        self._proc = ManagedProcess(
            key="tgws",
            exe=self.exe,
            args=["--portable"],
            cwd=self.dir,
            log_file=paths.LOGS_DIR / "tgws.log",
            parent=self,
            image=EXE_NAME,
            desktop=HIDDEN_DESKTOP,
        )
        self._proc.status_changed.connect(self.status_changed)
        self._proc.log_line.connect(self._log)
        ok = self._proc.start()
        if ok:
            self._log(
                f"[hub] TG WS Proxy запущен: {self.config.tgws.host}:{self.config.tgws.port}"
            )
            self._log(f"[hub] ссылка: {self.proxy_link()}")
            self._tail_timer.start()
            self._tray_timer.start()
        return ok

    def _hide_tray_icon(self) -> None:
        """Убирает иконку TgWsProxy из трея — она там не нужна."""
        if self._tray_hidden:
            return
        try:
            removed = win32.remove_tray_icons(self.own_pids())
        except Exception:
            return
        if removed:
            self._tray_hidden = True
            self._log("[hub] иконка TgWsProxy убрана из трея — управление в Zapret Hub")

    def own_pids(self) -> set:
        """PID наших собственных дочерних процессов — их никогда не гасим.

        TgWsProxy_windows.exe — PyInstaller-onefile: процесс, который мы
        запустили, распаковывает себя во временную папку и передаёт дело
        второму процессу с тем же именем. Поэтому «свои» — это всё дерево,
        а не только главный PID.
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
        """Останавливает TgWsProxy, запущенный не Zapret Hub."""
        try:
            killed = win32.kill_foreign_processes(EXE_NAME, self.own_pids())
        except Exception as exc:  # noqa: BLE001
            self._log(f"[hub] не удалось проверить сторонние процессы: {exc}")
            return
        if killed:
            self._log(
                "[hub] остановлен сторонний TgWsProxy (PID "
                + ", ".join(str(pid) for pid in killed)
                + ") — запускаю свой"
            )
            time.sleep(0.6)

    def stop(self) -> None:
        self._tail_timer.stop()
        self._tray_timer.stop()
        if self._proc:
            self._proc.stop()
        self.status_changed.emit(STATUS_STOPPED)

    def restart(self) -> bool:
        self.stop()
        time.sleep(0.8)
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

    # ------------------------------------------------------------ лог компонента

    def _tail_log(self) -> None:
        """Читает новые строки proxy.log компонента и показывает их в нашем журнале."""
        try:
            if not self.log_file.exists():
                return
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._log_pos)
                chunk = f.read()
                self._log_pos = f.tell()
        except OSError:
            return
        for line in chunk.splitlines():
            line = line.strip()
            if line:
                self._log(f"[tgws] {line}")

    def tail_log_lines(self, count: int = 200) -> List[str]:
        try:
            if not self.log_file.exists():
                return []
            text = self.log_file.read_text(encoding="utf-8", errors="replace")
            return text.splitlines()[-count:]
        except OSError:
            return []
