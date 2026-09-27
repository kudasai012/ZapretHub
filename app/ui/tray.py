"""Иконка в системном трее."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..i18n import tr


def _app_icon() -> QIcon:
    """Иконка трея: встроенный ресурс, иначе файл, иначе рисунок.

    Файла рядом с программой может не быть вовсе — поэтому первым делом
    смотрим в ресурс, вшитый в exe (см. app/ui/app_icon.py).
    """
    from .app_icon import app_icon

    return app_icon()


class TrayManager(QObject):
    def __init__(self, window, ctx, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.window = window
        self.ctx = ctx

        self.icon = QSystemTrayIcon(QIcon(_app_icon()), window)
        self.icon.setToolTip(tr("app.name"))
        self.icon.activated.connect(self._on_activated)

        menu = QMenu()
        self.show_action = QAction(tr("tray.show"), menu)
        self.show_action.triggered.connect(self.show_window)
        # один пункт вместо двух: он же запускает всё, же останавливает всё
        self.toggle_all_action = QAction(tr("tray.start_all"), menu)
        self.toggle_all_action.triggered.connect(self._toggle_all)
        self.quit_action = QAction(tr("tray.quit"), menu)
        self.quit_action.triggered.connect(self._quit)

        for action in (self.show_action, self.toggle_all_action, self.quit_action):
            menu.addAction(action)
        self.icon.setContextMenu(menu)
        self.icon.show()
        self.refresh()

    # ------------------------------------------------------------ действия

    def refresh(self) -> None:
        """Подпись пункта меню зависит от того, запущено ли что-то."""
        running = False
        try:
            running = bool(self.ctx.any_running())
        except Exception:  # noqa: BLE001 - контекст может быть ещё не готов
            running = False
        self.toggle_all_action.setText(
            tr("tray.stop_all") if running else tr("tray.start_all")
        )

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self.window.isVisible():
                self.window.hide()
            else:
                self.show_window()

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _toggle_all(self) -> None:
        """Если что-то работает — остановить всё, иначе запустить всё."""
        self.ctx.toggle_all()
        self.refresh()

    def _quit(self) -> None:
        self.icon.hide()
        self.ctx.shutdown()
        QApplication.quit()

    def notify(self, title: str, message: str, msec: int = 4000) -> None:
        try:
            self.icon.showMessage(title, message, msec=msec)
        except Exception:
            pass
