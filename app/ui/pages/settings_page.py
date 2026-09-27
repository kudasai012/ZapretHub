"""Страница настроек приложения."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ... import paths
from ...core import win32
from ...i18n import current_language, tr
from ..widgets import (
    FormRow,
    HintLabel,
    IconButton,
    PickComboBox,
    PickSpinBox,
    show_toast,
)
from .base import BasePage

APP_VERSION = "1.0.0"


class SettingsPage(BasePage):
    settings_applied = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._build()
        self._refresh_autostart_state()

    def _build(self) -> None:
        title = QLabel(tr("set.title"))
        title.setObjectName("h1")
        title.setWordWrap(True)
        self.add(title)

        # --- общие ---
        general = QGroupBox(tr("set.general"))
        g_layout = QVBoxLayout(general)
        self.language_combo = PickComboBox()
        self.language_combo.addItem("Русский", "ru")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(0 if self.ctx.config.general.language == "ru" else 1)
        g_layout.addWidget(FormRow(tr("set.language"), self.language_combo))

        self.minimize_check = QCheckBox(tr("set.minimize_to_tray"))
        self.minimize_check.setChecked(bool(self.ctx.config.general.minimize_to_tray))
        self.start_minimized_check = QCheckBox(tr("set.start_minimized"))
        self.start_minimized_check.setChecked(bool(self.ctx.config.general.start_minimized))
        self.check_start_check = QCheckBox(tr("set.check_on_start"))
        self.check_start_check.setChecked(bool(self.ctx.config.general.check_updates_on_start))
        for box in (self.minimize_check, self.start_minimized_check, self.check_start_check):
            g_layout.addWidget(box)

        save_button = IconButton("check", tr("common.save"), "primary")
        save_button.clicked.connect(self._save_general)
        g_layout.addWidget(save_button, 0)
        self.add(general)

        # --- автозапуск ---
        autostart = QGroupBox(tr("set.autostart"))
        a_layout = QVBoxLayout(autostart)
        self.autostart_check = QCheckBox(tr("set.autostart_enable"))
        self.autostart_zapret_check = QCheckBox(tr("set.autostart_zapret"))
        self.autostart_zapret_check.setChecked(bool(self.ctx.config.autostart.start_zapret))
        self.autostart_tgws_check = QCheckBox(tr("set.autostart_tgws"))
        self.autostart_tgws_check.setChecked(bool(self.ctx.config.autostart.start_tgws))
        self.autostart_elevated_check = QCheckBox(tr("set.autostart_elevated"))
        self.autostart_elevated_check.setChecked(bool(self.ctx.config.autostart.elevated))
        for box in (
            self.autostart_check,
            self.autostart_zapret_check,
            self.autostart_tgws_check,
            self.autostart_elevated_check,
        ):
            a_layout.addWidget(box)

        self.delay_spin = PickSpinBox()
        self.delay_spin.setMinimumWidth(110)
        self.delay_spin.setMaximumWidth(150)
        self.delay_spin.setRange(0, 600)
        self.delay_spin.setValue(int(self.ctx.config.autostart.delay_seconds))
        a_layout.addWidget(FormRow(tr("set.autostart_delay"), self.delay_spin))

        hint = QLabel(tr("set.autostart_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        a_layout.addWidget(hint)

        self.autostart_command_edit = QLineEdit()
        self.autostart_command_edit.setReadOnly(True)
        a_layout.addWidget(FormRow("Run:", self.autostart_command_edit))

        apply_button = IconButton("check", tr("common.apply"), "primary")
        apply_button.clicked.connect(self._save_autostart)
        a_layout.addWidget(apply_button, 0)
        self.add(autostart)

        # --- расположение ---
        location = QGroupBox(tr("set.paths"))
        l_layout = QVBoxLayout(location)
        for label, path in (
            (tr("set.components_dir"), paths.COMPONENTS_DIR),
            (tr("set.data_dir"), paths.DATA_DIR),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            value = QLineEdit(str(path))
            value.setReadOnly(True)
            row.addWidget(value, 1)
            button = IconButton("folder", tr("common.open_folder"), "ghost")
            button.clicked.connect(lambda _=False, p=path: paths.open_in_file_manager(p))
            row.addWidget(button)
            l_layout.addLayout(row)
        mode = QLabel(
            tr("set.mode_portable" if paths.is_portable() else "set.mode_installed")
        )
        mode.setObjectName("hintLabel")
        mode.setWordWrap(True)
        l_layout.addWidget(mode)
        self.add(location)

        # --- о программе ---
        self.about = QGroupBox(tr("set.about"))
        about = self.about
        ab_layout = QVBoxLayout(about)
        grid = QGridLayout()
        grid.addWidget(QLabel(f"{tr('app.version')}: {APP_VERSION}"), 0, 0)
        grid.addWidget(QLabel(f"{tr('set.language')}: {current_language().upper()}"), 0, 1)
        ab_layout.addLayout(grid)

        credit = HintLabel(tr("about.credit"))
        ab_layout.addWidget(credit)

        versions = HintLabel(tr("about.versions"))
        ab_layout.addWidget(versions)
        links = QHBoxLayout()
        for text, url in (
            ("zapret-discord-youtube", "https://github.com/Flowseal/zapret-discord-youtube"),
            ("tg-ws-proxy", "https://github.com/Flowseal/tg-ws-proxy"),
        ):
            button = IconButton("external", text, "ghost")
            button.clicked.connect(lambda _=False, u=url: paths.open_url(u))
            links.addWidget(button)
        links.addStretch(1)
        ab_layout.addLayout(links)
        self.add(about)

        self.add_stretch()

    def add_stretch(self) -> None:
        self._layout.addStretch(1)

    # ------------------------------------------------------------ обработчики

    def _save_general(self) -> None:
        cfg = self.ctx.config.general
        cfg.language = str(self.language_combo.currentData())
        cfg.theme = "dark"
        cfg.minimize_to_tray = self.minimize_check.isChecked()
        cfg.start_minimized = self.start_minimized_check.isChecked()
        cfg.check_updates_on_start = self.check_start_check.isChecked()
        self.ctx.save_config()
        self.settings_applied.emit()
        self._flash(tr("set.settings_saved"))

    def _save_autostart(self) -> None:
        cfg = self.ctx.config.autostart
        cfg.start_zapret = self.autostart_zapret_check.isChecked()
        cfg.start_tgws = self.autostart_tgws_check.isChecked()
        cfg.delay_seconds = self.delay_spin.value()
        cfg.elevated = self.autostart_elevated_check.isChecked()
        enabled = self.autostart_check.isChecked()

        if not win32.IS_WINDOWS:
            QMessageBox.information(self, tr("common.info"), tr("status.windows_only"))
            return

        ok = win32.autostart_set(enabled)
        if not ok:
            self._flash(tr("set.autostart_registry_error"), "error")
            return
        cfg.enabled = enabled
        self.ctx.save_config()
        self._refresh_autostart_state()
        self._flash(tr("set.autostart_applied"))

    def _refresh_autostart_state(self) -> None:
        enabled = win32.autostart_is_enabled()
        self.autostart_check.setChecked(enabled)
        self.ctx.config.autostart.enabled = enabled
        self.autostart_command_edit.setText(win32.autostart_command() or "—")

    def _flash(self, text: str, kind: str = "success") -> None:
        """Результат сохранения — всплывающее уведомление, а не баннер внизу."""
        show_toast(self.window(), text, kind, duration=3200)

    def on_show(self) -> None:
        self._refresh_autostart_state()
