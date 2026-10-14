"""Страница настроек приложения."""
from __future__ import annotations

import subprocess

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ... import __version__, paths
from ... import GITHUB_URL
from ...core import win32
from ...i18n import current_language, tr
from ..widgets import (
    FormRow,
    PickCheckBox,
    HintLabel,
    IconButton,
    PickComboBox,
    PickSpinBox,
    show_toast,
)
from .base import BasePage

IS_WINDOWS = win32.IS_WINDOWS


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

        self.minimize_check = PickCheckBox(tr("set.minimize_to_tray"))
        self.minimize_check.setChecked(bool(self.ctx.config.general.minimize_to_tray))
        self.start_minimized_check = PickCheckBox(tr("set.start_minimized"))
        self.start_minimized_check.setChecked(bool(self.ctx.config.general.start_minimized))
        self.check_start_check = PickCheckBox(tr("set.check_on_start"))
        self.check_start_check.setChecked(bool(self.ctx.config.general.check_updates_on_start))
        self.stop_on_quit_check = PickCheckBox(tr("settings.stop_on_quit"))
        self.stop_on_quit_check.setChecked(
            bool(self.ctx.config.general.stop_components_on_quit)
        )
        self.stop_on_quit_check.setToolTip(tr("settings.stop_on_quit_hint"))
        for box in (
            self.minimize_check,
            self.start_minimized_check,
            self.check_start_check,
            self.stop_on_quit_check,
        ):
            g_layout.addWidget(box)

        # --- права администратора ---
        # Без них winws.exe не запускается, и диагностика стратегий сразу
        # сыпет «нет доступа» — выглядит как поломка. Поэтому состояние
        # прав видно всегда, и его можно починить одной галочкой.
        self.admin_check = PickCheckBox(tr("set.run_as_admin"))
        self.admin_check.setToolTip(tr("set.run_as_admin_hint"))
        self.admin_check.toggled.connect(self._on_admin_check)
        g_layout.addWidget(self.admin_check)
        self._refresh_admin_row()

        save_button = IconButton("check", tr("common.save"), "glassPrimary")
        save_button.clicked.connect(self._save_general)
        g_layout.addWidget(save_button, 0)
        self.add(general)

        # --- автозапуск ---
        autostart = QGroupBox(tr("set.autostart"))
        a_layout = QVBoxLayout(autostart)
        self.autostart_check = PickCheckBox(tr("set.autostart_enable"))
        self.autostart_zapret_check = PickCheckBox(tr("set.autostart_zapret"))
        self.autostart_zapret_check.setChecked(bool(self.ctx.config.autostart.start_zapret))
        self.autostart_tgws_check = PickCheckBox(tr("set.autostart_tgws"))
        self.autostart_tgws_check.setChecked(bool(self.ctx.config.autostart.start_tgws))
        for box in (
            self.autostart_check,
            self.autostart_zapret_check,
            self.autostart_tgws_check,
        ):
            a_layout.addWidget(box)

        self.delay_spin = PickSpinBox()
        self.delay_spin.setMinimumWidth(110)
        self.delay_spin.setMaximumWidth(150)
        self.delay_spin.setRange(0, 600)
        self.delay_spin.setValue(int(self.ctx.config.autostart.delay_seconds))
        a_layout.addWidget(FormRow(tr("set.autostart_delay"), self.delay_spin))

        apply_button = IconButton("check", tr("common.apply"), "glassPrimary")
        apply_button.clicked.connect(self._save_autostart)
        a_layout.addWidget(apply_button, 0)
        self.add(autostart)

        # --- расположение ---
        location = QGroupBox(tr("set.paths"))
        l_layout = QVBoxLayout(location)
        for label, path in (
            (tr("set.components_dir"), paths.COMPONENTS_DIR),
            (tr("set.logs_dir"), paths.LOGS_DIR),
            (tr("set.data_dir"), paths.DATA_DIR),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            value = QLineEdit(str(path))
            value.setReadOnly(True)
            row.addWidget(value, 1)
            button = IconButton("folder", tr("common.open_folder"), "ghost")
            button.clicked.connect(
                lambda _=False, p=path: self._open_folder(p)
            )
            row.addWidget(button)
            l_layout.addLayout(row)
        self.add(location)

        # --- обслуживание ---
        maintenance = QGroupBox(tr("set.maintenance"))
        m_layout = QVBoxLayout(maintenance)
        self.uninstall_button = IconButton(
            "trash", tr("set.uninstall"), "glassDanger"
        )
        self.uninstall_button.setToolTip(tr("set.uninstall_hint"))
        self.uninstall_button.clicked.connect(self._uninstall_program)
        m_layout.addWidget(self.uninstall_button, 0)
        self.uninstall_note = HintLabel("")
        self.uninstall_note.setWordWrap(True)
        m_layout.addWidget(self.uninstall_note)
        self.add(maintenance)

        # --- о программе ---
        self.about = QGroupBox(tr("set.about"))
        about = self.about
        ab_layout = QVBoxLayout(about)
        grid = QGridLayout()
        grid.addWidget(
            QLabel(f"{tr('app.version')}: {__version__}"), 0, 0
        )
        grid.addWidget(QLabel(f"{tr('set.language')}: {current_language().upper()}"), 0, 1)
        ab_layout.addLayout(grid)

        credit = HintLabel(tr("about.credit"))
        ab_layout.addWidget(credit)

        versions = HintLabel(tr("about.versions"))
        ab_layout.addWidget(versions)

        update_row = QHBoxLayout()
        update_row.setSpacing(8)
        self.app_update_button = IconButton(
            "download", tr("set.app_update"), "glassPrimary"
        )
        self.app_update_button.setToolTip(tr("set.app_update_hint"))
        self.app_update_button.clicked.connect(self._check_app_update)
        update_row.addWidget(self.app_update_button)
        update_row.addStretch(1)
        ab_layout.addLayout(update_row)

        links = QHBoxLayout()
        for text, url in (
            ("zapret-discord-youtube", "https://github.com/Flowseal/zapret-discord-youtube"),
            ("tg-ws-proxy", "https://github.com/Flowseal/tg-ws-proxy"),
            (tr("set.app_repo"), GITHUB_URL),
        ):
            button = IconButton("external", text, "ghost")
            button.clicked.connect(lambda _=False, u=url: self._open_url(u))
            links.addWidget(button)
        links.addStretch(1)
        ab_layout.addLayout(links)
        self.add(about)

        self.add_stretch()

    def add_stretch(self) -> None:
        self._layout.addStretch(1)

    # ------------------------------------------------------------ помощники

    def _open_folder(self, path) -> None:
        """Открыть папку в проводнике; если не вышло — сказать об этом."""
        if not paths.open_in_file_manager(path):
            show_toast(
                self.window(),
                tr("set.folder_failed", path=str(path)),
                "error",
                duration=6000,
            )

    def _open_url(self, url: str) -> None:
        if not paths.open_url(url):
            show_toast(self.window(), tr("set.url_failed"), "error", duration=6000)

    def _uninstall_program(self) -> None:
        """Запустить деинсталлятор, лежащий рядом с программой."""
        uninstaller = paths.uninstaller_path()
        if uninstaller is None:
            show_toast(
                self.window(),
                tr("set.uninstall_missing"),
                "warning",
                duration=7000,
            )
            return
        answer = QMessageBox.question(
            self,
            tr("app.name"),
            tr("set.uninstall_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        # маркер закрытия: программа закроется молча, без вопроса «Выйти?»
        win32.request_quit()
        try:
            if IS_WINDOWS:
                # ShellExecute: unins000.exe сам просит повышение прав
                import ctypes

                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", str(uninstaller), None, str(paths.BASE_DIR), 1
                )
            else:
                subprocess.Popen([str(uninstaller)])
        except Exception as exc:  # noqa: BLE001
            win32.clear_quit_request()
            show_toast(self.window(), f"{tr('common.error')}: {exc}", "error")
            return
        # деинсталлятору тоже нужны свободные файлы
        self.ctx.shutdown(stop_components=True)
        QApplication.quit()

    def _refresh_admin_row(self) -> None:
        """Галочка «от имени администратора» отражает реальные права."""
        self._admin_refreshing = True
        self.admin_check.setChecked(IS_WINDOWS and win32.is_admin())
        # права уже есть — снять галочку нельзя, но состояние должно быть
        # видно, поэтому чекбокс остаётся включённым и просто неактивным
        self.admin_check.setEnabled(IS_WINDOWS and not win32.is_admin())
        self._admin_refreshing = False

    def _on_admin_check(self, checked: bool) -> None:
        """Галочку поставили — перезапускаем программу с повышением прав.

        Сами права появляются только после перезапуска через UAC, поэтому
        отмечать галочку без перезапуска было бы обманом.
        """
        if getattr(self, "_admin_refreshing", False):
            return
        if not checked:
            return
        if not IS_WINDOWS:
            show_toast(self.window(), tr("status.windows_only"), "warning")
            self._refresh_admin_row()
            return
        if win32.is_admin():
            # уже с правами — просто возвращаем галочку на место
            self._refresh_admin_row()
            return
        if win32.relaunch_elevated():
            show_toast(
                self.window(),
                tr("status.admin_restarting"),
                "info",
                duration=2000,
            )
            QApplication.quit()
            return
        show_toast(
            self.window(),
            tr("diag.admin_failed"),
            "error",
            duration=6000,
        )
        self._refresh_admin_row()

    def _relaunch_as_admin(self) -> None:
        """Перезапустить программу от имени администратора (UAC)."""
        if not IS_WINDOWS:
            show_toast(self.window(), tr("status.windows_only"), "warning")
            return
        if win32.relaunch_elevated():
            show_toast(
                self.window(),
                tr("status.admin_restarting"),
                "info",
                duration=2000,
            )
            QApplication.quit()
            return
        show_toast(
            self.window(),
            tr("diag.admin_failed"),
            "error",
            duration=6000,
        )

    def _check_app_update(self) -> None:
        """Кнопка «Обновление программы» в «О программе»."""
        from ..app_update_dialog import AppUpdateDialog

        dialog = AppUpdateDialog(self.ctx, parent=self.window())
        dialog.exec()

    # ------------------------------------------------------------ обработчики

    def _save_general(self) -> None:
        cfg = self.ctx.config.general
        cfg.language = str(self.language_combo.currentData())
        cfg.theme = "dark"
        cfg.minimize_to_tray = self.minimize_check.isChecked()
        cfg.start_minimized = self.start_minimized_check.isChecked()
        cfg.check_updates_on_start = self.check_start_check.isChecked()
        cfg.stop_components_on_quit = self.stop_on_quit_check.isChecked()
        self.ctx.save_config()
        self.settings_applied.emit()
        self._flash(tr("set.settings_saved"))

    def _save_autostart(self) -> None:
        cfg = self.ctx.config.autostart
        cfg.start_zapret = self.autostart_zapret_check.isChecked()
        cfg.start_tgws = self.autostart_tgws_check.isChecked()
        cfg.delay_seconds = self.delay_spin.value()
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
        self._refresh_maintenance()

    def _refresh_maintenance(self) -> None:
        """Кнопка удаления доступна только для установленной копии."""
        installed = paths.uninstaller_path() is not None
        self.uninstall_button.setEnabled(installed)
        self.uninstall_note.setText(
            tr("set.uninstall_ready" if installed else "set.uninstall_missing")
        )

    def _flash(self, text: str, kind: str = "success") -> None:
        """Результат сохранения — всплывающее уведомление, а не баннер внизу."""
        show_toast(self.window(), text, kind, duration=3200)

    def on_show(self) -> None:
        self._refresh_autostart_state()
        self._refresh_maintenance()
        self._refresh_admin_row()
