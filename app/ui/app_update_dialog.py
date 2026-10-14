"""Диалог обновления самой программы Zapret Hub.

Устроен как диалог обновления компонентов: та же frameless-карточка,
та же таблица «было / стало», но вместо компонентов — версия Hub, а
рядом — описание релиза из GitHub (markdown). Кнопка «Обновить» качает
`ZapretHub-Setup-*.exe`, запускает его и закрывает программу: дальше
работает установщик.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from ..i18n import tr
from . import anim
from .markdown import markdown_to_html
from .widgets import Banner, IconButton


class AppUpdateDialog(QDialog):
    """Окно «Обновление программы»."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._drag_offset = None
        self._checking = False
        self._downloading = False
        self._elapsed = 0
        self._release = None
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._on_watchdog)

        self.setObjectName("AppUpdateDialog")
        self.setWindowTitle(tr("appupd.title"))
        self.setMinimumWidth(660)
        self.setMinimumHeight(460)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        # фон — тот же градиент, что у приложения, плюс скруглённая маска:
        # квадратных уголков по краям не видно
        self.setStyleSheet(
            "QDialog#AppUpdateDialog {"
            " background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,"
            " stop: 0 #0e1524, stop: 1 #080b12);"
            " border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 20px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # --- шапка: заголовок и красная кнопка закрытия ---
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(tr("appupd.dialog_title"))
        title.setObjectName("h2")
        head.addWidget(title)
        head.addStretch(1)
        close = IconButton("close", tr("action.close"), "glassDanger")
        # ширина по содержимому: с фиксированными 38x38 подпись «Закрыть»
        # не влезала и кнопка выглядела обрезанной. Ровно та же беда была с
        # жёстко заданными 96 px — они меньше, чем нужно под «Закрыть»
        # (текст ~58 px + значок 16 + отступы 34), поэтому ширину теперь
        # целиком считает IconButton, а здесь только высота.
        close.setMinimumHeight(38)
        close.setToolTip(tr("action.close"))
        close.clicked.connect(self.reject)
        head.addWidget(close)
        outer.addLayout(head)

        self.banner = Banner(tr("common.loading"), "info")
        outer.addWidget(self.banner)

        self.hint_label = QLabel(tr("appupd.network_hint"))
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(False)
        outer.addWidget(self.hint_label)

        # --- версии ---
        versions = QHBoxLayout()
        versions.setSpacing(16)
        # ссылки на подписи держим прямо: вытаскивать виджеты потом из
        # вложенных лейаутов ненадёжно
        self.installed_label = QLabel(self._installed_version())
        self.latest_label = QLabel("—")
        for caption_text, value_label in (
            (tr("appupd.installed"), self.installed_label),
            (tr("appupd.latest"), self.latest_label),
        ):
            box = QVBoxLayout()
            box.setSpacing(2)
            caption = QLabel(caption_text)
            caption.setObjectName("statLabel")
            box.addWidget(caption)
            value_label.setObjectName("rowTitle")
            value_label.setWordWrap(True)
            box.addWidget(value_label)
            versions.addLayout(box, 1)
        outer.addLayout(versions)

        # --- описание релиза ---
        notes_caption = QLabel(tr("appupd.whats_new"))
        notes_caption.setObjectName("sectionLabel")
        outer.addWidget(notes_caption)

        from PySide6.QtWidgets import QTextBrowser

        self.notes = QTextBrowser()
        self.notes.setObjectName("ReleaseNotes")
        self.notes.setOpenExternalLinks(True)
        self.notes.setReadOnly(True)
        self.notes.setMinimumHeight(150)
        self.notes.setHtml(
            '<div style="color:#8b96ad;font-size:10pt;">'
            + tr("common.loading")
            + "</div>"
        )
        outer.addWidget(self.notes, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setValue(0)
        self.progress.setAlignment(Qt.AlignCenter)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        outer.addWidget(self.progress)

        # --- кнопки ---
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.open_button = IconButton("external", tr("appupd.open_page"), "glass")
        self.open_button.clicked.connect(self._open_release_page)
        self.open_button.setVisible(False)
        buttons.addWidget(self.open_button)
        self.check_button = IconButton("refresh", tr("upd.check"), "glass")
        self.check_button.clicked.connect(lambda: self.check() if not self._checking else None)
        buttons.addWidget(self.check_button)
        self.install_button = IconButton(
            "download", tr("appupd.install"), "glassPrimary"
        )
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self._install)
        buttons.addWidget(self.install_button)
        outer.addLayout(buttons)

        updater = self.ctx.app_updater
        updater.check_started.connect(self._on_check_started)
        updater.check_finished.connect(self._on_check_finished)
        updater.check_failed.connect(self._on_check_failed)
        updater.progress.connect(self._on_progress)
        updater.downloaded.connect(self._on_downloaded)
        updater.failed.connect(self._on_failed)

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

    @staticmethod
    def _installed_version() -> str:
        from .. import __version__

        return __version__

    def check(self) -> None:
        if self._checking or self._downloading:
            return
        self._checking = True
        self.install_button.setEnabled(False)
        self.open_button.setVisible(False)
        self.check_button.setText(tr("common.cancel"))
        self.banner.set_kind("info")
        self.banner.set_text(tr("upd.checking"))
        self.banner.setVisible(True)
        self.hint_label.setVisible(False)
        self._elapsed = 0
        self._watchdog.start(1000)
        self.ctx.app_updater.check(proxy=self.ctx.config.updates.proxy)

    def _on_check_started(self) -> None:
        self.banner.set_kind("info")
        self.banner.set_text(tr("upd.checking"))
        self.banner.setVisible(True)

    def _on_watchdog(self) -> None:
        """Если проверка зависла — честно пишем об этом."""
        self._elapsed += 1
        if self._elapsed >= 15:
            self._stop_checking()
            self.banner.set_kind("error")
            self.banner.set_text(tr("appupd.check_timeout"))
            self.hint_label.setVisible(True)
        elif self._elapsed >= 5:
            self.banner.set_text(
                f"{tr('upd.checking')} {self._elapsed} {tr('common.seconds')}"
            )

    def _on_check_finished(self, release) -> None:
        self._release = release
        self._stop_checking()
        self.latest_label.setText(release.version or release.tag)
        self.notes.setHtml(
            markdown_to_html(release.body)
            if release.body.strip()
            else '<div style="color:#8b96ad;">' + tr("appupd.no_notes") + "</div>"
        )
        if release.update_available:
            self.banner.set_kind("success")
            self.banner.set_text(
                tr("appupd.available", version=release.version)
            )
            self.banner.setVisible(True)
            self.install_button.setEnabled(True)
            self.open_button.setVisible(True)
        else:
            self.banner.set_kind("success")
            self.banner.set_text(tr("appupd.up_to_date"))
            self.banner.setVisible(True)
            self.open_button.setVisible(True)

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

    def _open_release_page(self) -> None:
        from .. import paths

        url = self._release.html_url if self._release else None
        paths.open_url(url or "https://github.com")

    def _install(self) -> None:
        if self._release is None or self._downloading:
            return
        asset = self._release.setup_asset() or self._release.portable_asset()
        if asset is None:
            self.banner.set_kind("error")
            self.banner.set_text(tr("appupd.no_asset"))
            self.banner.setVisible(True)
            return
        self._downloading = True
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.install_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.banner.set_kind("info")
        self.banner.set_text(tr("appupd.downloading"))
        self.banner.setVisible(True)
        self.ctx.app_updater.download(asset)

    def _on_progress(self, name: str, done: int, total: int) -> None:
        self.progress.setVisible(True)
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(min(done, total))
            self.progress.setFormat(f"{name} · %p%")
        else:
            self.progress.setMaximum(0)
            self.progress.setValue(0)
            self.progress.setFormat(f"{name} · …")

    def _on_downloaded(self, path: str) -> None:
        """Файл скачан — запускаем установщик и закрываем программу."""
        self._downloading = False
        self.progress.setVisible(False)
        self.banner.set_kind("success")
        self.banner.set_text(tr("appupd.launching"))
        self.banner.setVisible(True)
        from ..core import win32

        if win32.launch_installer(Path(path)):
            # маркер закрытия: окно закроется молча, даже если компоненты
            # работают, и установщик сможет заменить файлы
            win32.request_quit()
            QTimer.singleShot(600, self._quit)
        else:
            self.banner.set_kind("error")
            self.banner.set_text(tr("appupd.launch_failed"))
            win32.clear_quit_request()
            self.install_button.setEnabled(True)
            self.check_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self._downloading = False
        self.progress.setVisible(False)
        self.banner.set_kind("error")
        self.banner.set_text(f"{tr('appupd.download_failed')}: {message}")
        self.banner.setVisible(True)
        self.install_button.setEnabled(True)
        self.check_button.setEnabled(True)

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        # установщик новой версии сейчас заменит файлы: обходы надо
        # остановить, иначе winws.exe и TgWsProxy держат их занятыми
        self.ctx.shutdown(stop_components=True)
        app = QApplication.instance()
        if app is not None:
            app.quit()
