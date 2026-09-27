"""Точка входа Zapret Hub.

Запускается четырьмя способами:
    python run.pyw            (рекомендуется — без консоли)
    python -m app
    python app/main.py
    dist/ZapretHub.exe        (собранный PyInstaller)
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Optional

# разрешаем прямой запуск файла: python app/main.py
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "app"

# ------------------------------------------------------------ инициализация путей

from . import paths


def _setup_logging() -> logging.Logger:
    if paths.migrate_portable_data():
        # данные лежали рядом с прежней сборкой — перенесли в профиль
        print("[hub] данные перенесены в " + str(paths.DATA_ROOT))
    paths.ensure_dirs()
    logger = logging.getLogger("zapret_hub")
    logger.setLevel(logging.INFO)
    try:
        handler = logging.handlers.RotatingFileHandler(
            paths.HUB_LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)
    except OSError:
        pass
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    logger.addHandler(stream)
    return logger


LOG = _setup_logging()


# ------------------------------------------------------------ single instance

#: имя именованного мьютекса Windows. Он же стоит в AppMutex установщика
#: Inno Setup — благодаря этому программа закрывается перед обновлением.
MUTEX_NAME = "ZapretHubRunning"


class SingleInstance:
    """Защитник от повторного запуска: именованный мьютекс + lock-файл.

    Мьютекс главный: он виден всей системе (и установщику), переживает
    аварийное завершение и не мешает, если папку данных переставили.
    Lock-файл остался как запасной вариант для тех сред, где мьютекс
    создать не удалось.
    """

    def __init__(self, lock_path: Path):
        self.lock_path = Path(lock_path)
        self._acquired = False
        self._mutex = None

    # --- мьютекс ---

    def _open_mutex(self) -> Optional[str]:
        """Создаёт именованный мьютекс.

        Возвращает ``"created"`` — мьютекс наш, ``"exists"`` — программа
        уже запущена, ``None`` — не вышло (не Windows, нет прав).
        """
        if not sys.platform.startswith("win"):
            return None
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        ERROR_ALREADY_EXISTS = 183
        try:
            handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
            if not handle:
                return None
            if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
                # дескриптор закрываем: мьютекс и так чужой
                kernel32.CloseHandle(handle)
                return "exists"
            self._mutex = handle
            return "created"
        except Exception:  # noqa: BLE001
            return None

    def acquire(self) -> bool:
        from .core import win32

        mutex = self._open_mutex()
        if mutex == "exists":
            # запуск уже идёт — второго быть не должно
            return False
        if mutex == "created":
            self._acquired = True
            return True

        # мьютекс не создался — работаем по lock-файлу, как раньше
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return True
        for _ in range(3):
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
            except FileExistsError:
                pid = self._read_pid()
                if pid and pid != os.getpid() and win32.process_alive(pid):
                    return False
                try:
                    self.lock_path.unlink(missing_ok=True)
                except OSError:
                    return True
                continue
            except OSError:
                return True
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            self._acquired = True
            return True
        return True

    def _read_pid(self) -> int:
        try:
            return int(self.lock_path.read_text(encoding="utf-8").strip())
        except Exception:
            return 0

    def release(self) -> None:
        if not self._acquired:
            return
        if self._mutex is not None:
            try:
                import ctypes

                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._mutex)
            except Exception:  # noqa: BLE001
                pass
            self._mutex = None
        else:
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
                pass


# ------------------------------------------------------------ аргументы

def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Zapret Hub")
    parser.add_argument(
        "--tray",
        action="store_true",
        help="запуск свёрнутым в трей с автозапуском компонентов (используется автозапуском Windows)",
    )
    parser.add_argument(
        "--minimized", action="store_true", help="стартовать свёрнутым в трей"
    )
    parser.add_argument("--no-admin-check", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _components_to_start(ctx) -> tuple[bool, bool]:
    """Какие компоненты поднимать при старте приложения (настройки автозапуска)."""
    autostart = ctx.config.autostart
    return bool(autostart.start_zapret), bool(autostart.start_tgws)


def _needs_admin(ctx) -> bool:
    """Админ нужен, если при старте планируется запуск zapret."""
    from .core import win32

    if not win32.IS_WINDOWS or win32.is_admin():
        return False
    zapret, _ = _components_to_start(ctx)
    return zapret


def _offer_elevation(ctx) -> bool:
    """Предлагает перезапуск от имени администратора. True — значит выходим."""
    from PySide6.QtWidgets import QMessageBox

    from .core import win32
    from .i18n import set_language, tr

    set_language(ctx.config.general.language)
    answer = QMessageBox.question(
        None,
        tr("app.name"),
        tr("status.admin_relaunch"),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if answer == QMessageBox.Yes:
        if win32.relaunch_elevated():
            LOG.info("перезапуск от имени администратора")
            return True
        QMessageBox.warning(None, tr("common.error"), "UAC отклонён или недоступен")
    return False


# ------------------------------------------------------------ запуск

def _apply_app_icon(app) -> None:
    """Ставит иконку приложения всюду: окно, панель задач, трей, уведомления.

    Иконка берётся из ресурса, вшитого в exe (см. app/ui/app_icon.py),
    поэтому она есть всегда — даже если рядом с программой нет assets/.
    """
    from .ui.app_icon import apply_app_icon

    apply_app_icon(app)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .context import AppContext
    from .i18n import set_language, tr
    from .ui import theme
    from .ui.main_window import MainWindow

    lock = SingleInstance(paths.LOCK_FILE)
    if not lock.acquire():
        LOG.warning("Zapret Hub уже запущен")
        try:
            QMessageBox.information(None, tr("app.name"), "Приложение уже запущено (см. трей)")
        except Exception:
            pass
        return 0

    qt_app = QApplication(sys.argv[:1] + argv)
    qt_app.setApplicationName("ZapretHub")
    qt_app.setOrganizationName("ZapretHub")
    qt_app.setQuitOnLastWindowClosed(False)
    _apply_app_icon(qt_app)

    ctx = AppContext()
    set_language(ctx.config.general.language)
    qt_app.setStyleSheet(theme.stylesheet())
    qt_app.setStyle(theme.ScrollbarStyle(qt_app.style()))

    if _needs_admin(ctx) and not args.no_admin_check and _offer_elevation(ctx):
        return 0

    window = MainWindow(ctx)

    # ---- автозапуск компонентов ----
    def _start_components() -> None:
        delay = max(0, int(ctx.config.autostart.delay_seconds))
        if delay:
            time.sleep(delay)
        zapret, tgws = _components_to_start(ctx)
        ctx.start_selected(zapret=zapret, tgws=tgws)

    tray_mode = args.tray or args.minimized or ctx.config.general.start_minimized
    if tray_mode:
        window.hide()
        zapret, tgws = _components_to_start(ctx)
        if zapret or tgws:
            QTimer.singleShot(1200, _start_components)
    else:
        window.show()

    # ---- проверка обновлений при старте ----
    if ctx.config.general.check_updates_on_start:
        def _auto_check() -> None:
            last = ctx.config.updates.last_check or 0.0
            interval = ctx.config.updates.interval_hours * 3600
            if last == 0.0 or time.time() - last >= interval:
                window.background_check_updates()

        QTimer.singleShot(2500, _auto_check)

    try:
        exit_code = qt_app.exec()
    finally:
        lock.release()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
