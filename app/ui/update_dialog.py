"""Диалог обновления одного или всех компонентов."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)


from ..i18n import tr
from . import anim
from .widgets import Banner, IconButton
from ..core.updater import UpdateInfo

COMPONENTS = ("zapret", "tgws")
TITLES = {
    "zapret": "zapret-discord-youtube",
    "tgws": "TG WS Proxy",
}


class UpdateDialog(QDialog):
    def __init__(self, ctx, key: str | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.key = key
        self.infos: list[UpdateInfo] = []
        self._drag_offset = None
        self._checking = False
        self._elapsed = 0
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._on_watchdog)
        self.setObjectName("UpdateDialog")
        self.setWindowTitle(tr("upd.title"))
        self.setMinimumWidth(620)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        # Фон окна — тот же градиент, что у приложения, плюс скруглённая маска:
        # квадратных «чёрных уголков» по краям больше не видно.
        self.setStyleSheet(
            "QDialog#UpdateDialog {"
            " background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,"
            " stop: 0 #0e1524, stop: 1 #080b12);"
            " border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 20px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(tr("upd.dialog_title"))
        title.setObjectName("h2")
        head.addWidget(title)
        head.addStretch(1)
        close = IconButton("close", tr("action.close"))
        close.clicked.connect(self.reject)
        head.addWidget(close)
        outer.addLayout(head)

        self.banner = Banner(tr("common.loading"), "info")
        outer.addWidget(self.banner)

        self.hint_label = QLabel(tr("upd.network_hint"))
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(False)
        outer.addWidget(self.hint_label)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        outer.addLayout(self.grid)

        # шапка таблицы
        labels = [
            tr("upd.component"),
            tr("upd.installed"),
            tr("upd.latest"),
            tr("common.status"),
        ]
        for column, text in enumerate(labels):
            label = QLabel(text)
            label.setObjectName("muted")
            self.grid.addWidget(label, 0, column)

        self._rows: dict[str, dict[str, QLabel]] = {}
        for offset, component in enumerate(COMPONENTS):
            if self.key and component != self.key:
                continue
            row = offset + 1
            name = QLabel(TITLES[component])
            name.setObjectName("rowTitle")
            installed = QLabel("—")
            installed.setObjectName("muted")
            latest = QLabel("—")
            latest.setObjectName("muted")
            state = QLabel("")
            state.setObjectName("muted")
            self.grid.addWidget(name, row, 0)
            self.grid.addWidget(installed, row, 1)
            self.grid.addWidget(latest, row, 2)
            self.grid.addWidget(state, row, 3)
            self._rows[component] = {
                "installed": installed,
                "latest": latest,
                "state": state,
            }

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setValue(0)
        self.progress.setAlignment(Qt.AlignCenter)
        self.progress.setFormat("%p%")
        self.progress.setTextVisible(True)
        outer.addWidget(self.progress)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.check_button = IconButton("refresh", tr("upd.check"), "ghost")
        self.check_button.clicked.connect(lambda: self.check() if not self._checking else None)
        buttons.addWidget(self.check_button)
        self.install_button = IconButton("download", tr("upd.install"), "glassAccent")
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self._install)
        buttons.addWidget(self.install_button)
        outer.addLayout(buttons)

        ctx.updater.check_started.connect(self._on_check_started)
        ctx.updater.check_finished.connect(self._on_check_finished)
        ctx.updater.check_failed.connect(self._on_check_failed)
        ctx.updater.progress.connect(self._on_progress)
        ctx.updater.status.connect(self._on_status)
        ctx.updater.installed.connect(self._on_installed)
        ctx.updater.failed.connect(self._on_failed)

        anim.fade_in(self)
        self.check()

    # ------------------------------------------------------------ форма окна

    def _apply_round_mask(self) -> None:
        """Скругляет углы окна: без маски видны квадратные чёрные края."""
        if not self.isVisible():
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 20, 20)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_round_mask()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_round_mask()

    # ------------------------------------------------------------ перетаскивание

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ проверка

    def check(self) -> None:
        if self._checking:
            return
        self._checking = True
        self.install_button.setEnabled(False)
        self.check_button.setText(tr("common.cancel"))
        self.banner.set_kind("info")
        self.banner.set_text(tr("upd.checking"))
        self.banner.setVisible(True)
        self.hint_label.setVisible(False)
        self._elapsed = 0
        self._watchdog.start(1000)
        self.ctx.updater.check_all()

    def _on_check_started(self) -> None:
        self.banner.set_kind("info")
        self.banner.set_text(tr("upd.checking"))
        self.banner.setVisible(True)

    def _on_watchdog(self) -> None:
        """Если проверка зависла — честно пишем об этом, а не крутим «вечную» проверку."""
        self._elapsed += 1
        if self._elapsed >= 15:
            self._stop_checking()
            self.banner.set_kind("error")
            self.banner.set_text(tr("upd.check_timeout"))
            self.hint_label.setVisible(True)
        elif self._elapsed >= 5:
            self.banner.set_text(f"{tr('upd.checking')} {self._elapsed} {tr('common.seconds')}")

    def _on_check_finished(self, infos: list) -> None:
        self.infos = list(infos)
        self._stop_checking()
        self.banner.setVisible(False)
        errors = [info for info in self.infos if info.error]
        if errors:
            self.banner.set_kind("warning")
            self.banner.set_text(tr("upd.partial_error"))
            self.banner.setVisible(True)
            self.hint_label.setVisible(True)
        pending = []
        for info in self.infos:
            if self.key and info.component != self.key:
                continue
            row = self._rows.get(info.component)
            if not row:
                continue
            row["installed"].setText(info.installed or tr("common.not_installed"))
            row["latest"].setText(info.latest or "—")
            if info.error:
                row["state"].setText(tr("upd.github_error"))
            elif info.not_installed:
                row["state"].setText(tr("upd.not_installed"))
            elif info.update_available:
                row["state"].setText(tr("upd.update_available"))
            else:
                row["state"].setText(tr("upd.up_to_date"))
            if info.release and not info.error and (info.update_available or info.not_installed):
                pending.append(info)
        self.install_button.setEnabled(bool(pending))
        self.ctx.config.updates.last_check = time.time()
        self.ctx.save_config()

    def _on_check_failed(self, message: str) -> None:
        self._stop_checking()
        self.banner.set_kind("error")
        self.banner.set_text(f"{tr('upd.github_error')}: {message}")
        self.banner.setVisible(True)
        self.hint_label.setVisible(True)

    def _stop_checking(self) -> None:
        self._checking = False
        self._watchdog.stop()
        self.check_button.setText(tr("upd.check"))

    # ------------------------------------------------------------ установка

    def _install(self) -> None:
        targets = [
            info
            for info in self.infos
            if info.release
            and (info.update_available or info.not_installed)
            and (not self.key or info.component == self.key)
        ]
        if not targets:
            return
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.install_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.banner.set_kind("info")
        self.banner.set_text(tr("upd.installing"))
        self.banner.setVisible(True)
        self._queue = list(targets)
        self._install_next()

    def _install_next(self) -> None:
        if not self._queue:
            self.banner.set_kind("success")
            self.banner.set_text(tr("upd.done"))
            self.progress.setVisible(False)
            self.install_button.setEnabled(True)
            self.check_button.setEnabled(True)
            return
        info = self._queue.pop(0)
        was_running = (
            self.ctx.zapret.is_running()
            if info.component == "zapret"
            else self.ctx.tgws.is_running()
        )
        component = (
            self.ctx.zapret if info.component == "zapret" else self.ctx.tgws
        )
        if was_running:
            component.stop()

        def on_done(ok: bool, message: str) -> None:
            if ok:
                self.banner.set_kind("success")
                self.banner.set_text(
                    f"{TITLES.get(info.component, info.component)} {tr('upd.updated')} {message}. "
                    f"{tr('upd.user_data_kept')}"
                )
                self.check()
                if was_running:
                    component.start()
            else:
                self.banner.set_kind("error")
                self.banner.set_text(f"{tr('upd.update_failed')}: {message}")
            self._install_next()

        self.ctx.updater.install(info.component, info, on_done=on_done)

    def _on_progress(self, component: str, done: int, total: int) -> None:
        self.progress.setVisible(True)
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(min(done, total))
            self.progress.setFormat(f"{TITLES.get(component, component)} · %p%")
        else:
            self.progress.setMaximum(0)
            self.progress.setValue(0)
            self.progress.setFormat(f"{TITLES.get(component, component)} · …")

    def _on_status(self, message: str) -> None:
        self.banner.set_text(message)

    def _on_installed(self, component: str, version: str) -> None:
        row = self._rows.get(component)
        if row:
            row["installed"].setText(version)

    def _on_failed(self, component: str, message: str) -> None:
        row = self._rows.get(component)
        if row:
            row["state"].setText(tr("upd.update_failed"))
