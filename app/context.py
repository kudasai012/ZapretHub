"""Контекст приложения: конфиг + компоненты + менеджер обновлений."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from . import paths
from .config import AppConfig
from .core.asn import AsnCollector
from .core.tgws import TgWsComponent
from .core.updater import Updater
from .core.zapret import ZapretComponent
from .i18n import set_language


class AppContext(QObject):
    """Связывает UI с ядром."""

    components_changed = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        paths.ensure_dirs()
        self.config = AppConfig.load()
        set_language(self.config.general.language)
        self.zapret = ZapretComponent(self.config)
        self.tgws = TgWsComponent(self.config)
        self.updater = Updater(self.config)
        self.asn = AsnCollector(self.config)

    # ------------------------------------------------------------ управление

    def save_config(self) -> bool:
        return self.config.save()

    def start_all(self) -> None:
        """Запускает оба установленных компонента."""
        if self.zapret.installed():
            self.zapret.start()
        if self.tgws.installed():
            self.tgws.start()

    def start_selected(self, zapret: bool = True, tgws: bool = True) -> None:
        if zapret and self.zapret.installed():
            self.zapret.start()
        if tgws and self.tgws.installed():
            self.tgws.start()

    def stop_all(self) -> None:
        self.zapret.stop()
        self.tgws.stop()

    def toggle_all(self) -> None:
        """Одна общая кнопка: если что-то работает — остановить всё, иначе запустить всё."""
        if self.any_running():
            self.stop_all()
        else:
            self.start_all()

    def any_running(self) -> bool:
        return self.zapret.is_running() or self.tgws.is_running()

    def components_installed(self) -> bool:
        return self.zapret.installed() or self.tgws.installed()

    def shutdown(self) -> None:
        self.asn.stop()
        self.stop_all()
        self._sweep_orphans()

    def _sweep_orphans(self) -> None:
        """Добивает процессы компонентов, оставшиеся после остановки.

        TgWsProxy_windows.exe — PyInstaller-onefile с графической подсистемой:
        он распаковывает себя во временную папку и запускает второй процесс с
        тем же именем. Дерево гасится целиком, но если что-то всё же уцелело
        (процесс перезапустился в момент остановки), здесь он добивается.
        """
        from .core import win32
        from .core.tgws import EXE_NAME as TGWS_EXE

        if not win32.IS_WINDOWS:
            return
        own = self.zapret.own_pids() | self.tgws.own_pids()
        for image in ("winws.exe", TGWS_EXE):
            try:
                win32.kill_foreign_processes(image, own)
            except Exception:
                pass
