"""Панель настроек Zapret (обход блокировок Discord/YouTube)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QRadioButton,
    QVBoxLayout,
)

from ...i18n import tr
from ..widgets import (
    Banner,
    HintLabel,
    IconButton,
    PickComboBox,
    show_toast,
)
from .component_panel import ComponentPanel

GAME_MODES = [
    ("disabled", "zapret.game_disabled"),
    ("all", "zapret.game_all"),
    ("tcp", "zapret.game_tcp"),
    ("udp", "zapret.game_udp"),
]

IPSET_MODES = [
    ("loaded", "zapret.ipset_loaded"),
    ("none", "zapret.ipset_none"),
    ("any", "zapret.ipset_any"),
]

class ZapretPanel(ComponentPanel):
    def __init__(self, ctx, parent=None):
        super().__init__(
            ctx,
            key="zapret",
            title="Zapret · Discord / YouTube",
            subtitle="zapret-discord-youtube · winws.exe",
            icon_name="shield",
            parent=parent,
        )
        self._loading = False
        self._build()

        ctx.zapret.status_changed.connect(self._on_status)
        ctx.zapret.log_line.connect(self.log_view.append)

        collector = ctx.asn
        collector.progress.connect(self._on_asn_progress)
        collector.finished.connect(self._on_asn_finished)
        collector.failed.connect(self._on_asn_failed)
        collector.log_line.connect(self.log_view.append)
        collector.status.connect(self._on_asn_status)

    def component(self):
        return self.ctx.zapret

    # ------------------------------------------------------------ построение

    def _build(self) -> None:
        self.warning_banner = Banner("", "warning")
        self.warning_banner.setVisible(False)
        self.remove_service_button = IconButton("trash", tr("zapret.service_remove"), "danger")
        self.remove_service_button.setVisible(False)
        self.remove_service_button.clicked.connect(self._remove_service)
        self.warning_banner.layout().addWidget(self.remove_service_button)
        self.add_widget(self.warning_banner)

        # --- стратегия ---
        strategy_box = QGroupBox(tr("zapret.strategy"))
        s_layout = QVBoxLayout(strategy_box)
        s_layout.setSpacing(8)
        self.strategy_combo = PickComboBox()
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        s_layout.addWidget(self.strategy_combo)
        hint = HintLabel(tr("zapret.strategy_hint"))
        s_layout.addWidget(hint)
        self.add_widget(strategy_box)

        # --- game filter ---
        self.game_apply_button = IconButton("check", tr("common.apply"), "primary")
        self.game_apply_button.clicked.connect(self._apply_game_filter)
        game_box = QGroupBox(tr("zapret.game_filter"))
        g_layout = QVBoxLayout(game_box)
        g_layout.setSpacing(8)
        radios = QHBoxLayout()
        self.game_radios = {}
        for mode, label_key in GAME_MODES:
            radio = QRadioButton(tr(label_key))
            radio.setProperty("mode", mode)
            radio.toggled.connect(self._on_game_mode_toggled)
            self.game_radios[mode] = radio
            radios.addWidget(radio)
        radios.addStretch(1)
        g_layout.addLayout(radios)
        ranges = QHBoxLayout()
        self.game_tcp_edit = QLineEdit()
        self.game_udp_edit = QLineEdit()
        ranges.addWidget(QLabel(tr("zapret.game_tcp_range")))
        ranges.addWidget(self.game_tcp_edit)
        ranges.addWidget(QLabel(tr("zapret.game_udp_range")))
        ranges.addWidget(self.game_udp_edit)
        g_layout.addLayout(ranges)
        g_layout.addWidget(self.game_apply_button, 0, Qt.AlignLeft)
        self.add_widget(game_box)

        # --- ipset ---
        ipset_box = QGroupBox(tr("zapret.ipset"))
        i_layout = QVBoxLayout(ipset_box)
        i_layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.ipset_combo = PickComboBox()
        for mode, label_key in IPSET_MODES:
            self.ipset_combo.addItem(tr(label_key), mode)
        self.ipset_combo.currentIndexChanged.connect(self._on_ipset_changed)
        top.addWidget(self.ipset_combo, 1)
        self.ipset_update_button = IconButton("download", tr("zapret.ipset_update"))
        self.ipset_update_button.clicked.connect(self._update_ipset)
        top.addWidget(self.ipset_update_button)
        i_layout.addLayout(top)

        # --- сбор IP заблокированных провайдеров по ASN ---
        asn_row = QHBoxLayout()
        asn_row.setSpacing(10)
        self.asn_button = IconButton("globe", tr("zapret.asn_collect"), "ghost")
        self.asn_button.setToolTip(tr("zapret.asn_hint"))
        self.asn_button.clicked.connect(self._collect_asn)

        asn_row.addWidget(self.asn_button, 0)

        self.asn_progress = QProgressBar()
        self.asn_progress.setVisible(False)
        self.asn_progress.setMaximum(0)
        self.asn_progress.setValue(0)
        self.asn_progress.setTextVisible(False)
        self.asn_progress.setFixedHeight(6)
        asn_row.addWidget(self.asn_progress, 1)

        self.asn_label = QLabel("")
        self.asn_label.setObjectName("muted")
        self.asn_label.setWordWrap(True)
        self.asn_label.setVisible(False)
        asn_row.addWidget(self.asn_label, 1)
        i_layout.addLayout(asn_row)

        self.add_widget(ipset_box)

        # --- пользовательские списки ---
        lists_box = QGroupBox(tr("zapret.user_lists"))
        l_layout = QVBoxLayout(lists_box)
        l_layout.setSpacing(8)
        self.list_combo = PickComboBox()
        self.list_combo.currentIndexChanged.connect(self._on_list_changed)
        l_layout.addWidget(self.list_combo)
        hint2 = HintLabel(tr("zapret.user_lists_hint"))
        l_layout.addWidget(hint2)
        self.list_edit = QPlainTextEdit()
        self.list_edit.setMaximumHeight(130)
        l_layout.addWidget(self.list_edit)
        self.save_list_button = IconButton("check", tr("common.save"), "primary")
        self.save_list_button.clicked.connect(self._save_user_list)
        l_layout.addWidget(self.save_list_button, 0, Qt.AlignLeft)
        self.add_widget(lists_box)

    # ------------------------------------------------------------ данные

    def reload(self) -> None:
        zapret = self.ctx.zapret
        self._loading = True
        try:
            self.strategy_combo.clear()
            strategies = zapret.strategies()
            self.strategy_combo.addItems(strategies)
            current = self.ctx.config.zapret.strategy
            if current in strategies:
                self.strategy_combo.setCurrentText(current)
            elif strategies:
                self.ctx.config.zapret.strategy = strategies[0]
                self.strategy_combo.setCurrentIndex(0)

            state = zapret.game_filter_state()
            mode = state.get("mode", "disabled")
            if mode in self.game_radios:
                self.game_radios[mode].setChecked(True)
            self.ctx.config.zapret.game_mode = mode
            self.game_tcp_edit.setText(state.get("tcp", "1024-65535"))
            self.game_udp_edit.setText(state.get("udp", "1024-65535"))
            self.ctx.config.zapret.game_tcp_range = state.get("tcp", "1024-65535")
            self.ctx.config.zapret.game_udp_range = state.get("udp", "1024-65535")

            ipset = zapret.ipset_state()
            index = self.ipset_combo.findData(ipset)
            if index >= 0:
                self.ipset_combo.setCurrentIndex(index)
            self.ctx.config.zapret.ipset_mode = ipset

            self._reload_lists()
            self._update_warning()
        finally:
            self._loading = False

    def on_show(self) -> None:
        self.reload()
        self.refresh_status()

    def _reload_lists(self) -> None:
        """Заполняет список всех .txt-файлов из lists/ (общие и пользовательские)."""
        current = self.list_combo.currentText()
        files = self.ctx.zapret.list_files()
        self._loading = True
        try:
            self.list_combo.clear()
            self.list_combo.addItems(files)
            if current in files:
                self.list_combo.setCurrentText(current)
        finally:
            self._loading = False
        self._load_user_list()

    def _load_user_list(self) -> None:
        name = self.list_combo.currentText()
        if not name:
            return
        text = self.ctx.zapret.read_user_list(name)
        if not text:
            from ...core.zapret import USER_LISTS as DEFAULTS

            text = DEFAULTS.get(name, "")
        self.list_edit.setPlainText(text)

    def _update_warning(self) -> None:
        conflict = self.ctx.zapret.service_conflict()
        # Чужие winws.exe Hub гасит сам при запуске (см. core/zapret.py),
        # поэтому в предупреждении остаётся только конфликт со службой Windows.
        if conflict:
            self.warning_banner.set_kind("warning")
            self.warning_banner.set_text(
                f"{tr('zapret.service_conflict')} ({conflict})"
            )
            self.warning_banner.setVisible(True)
            self.remove_service_button.setVisible(True)
        else:
            self.warning_banner.setVisible(False)
            self.remove_service_button.setVisible(False)

    def _remove_service(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            tr("app.name"),
            tr("zapret.service_remove_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        if self.ctx.zapret.remove_service():
            self.log_view.append(f"[hub] {tr('zapret.service_removed')}")
        else:
            self.log_view.append("[hub] не удалось удалить службу (нужны права администратора)")
        self._update_warning()

    # ------------------------------------------------------------ обработчики

    def _on_strategy_changed(self, index: int) -> None:
        if self._loading:
            return
        name = self.strategy_combo.currentText()
        if not name:
            return
        self.ctx.config.zapret.strategy = name
        self.ctx.save_config()
        show_toast(self, tr("zapret.strategy_applied", name=name), "success")
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()

    def _on_game_mode_toggled(self, checked: bool) -> None:
        if self._loading or not checked:
            return
        radio = self.sender()
        if radio is None:
            return
        self.ctx.config.zapret.game_mode = str(radio.property("mode"))
        self.ctx.save_config()

    def _apply_game_filter(self) -> None:
        cfg = self.ctx.config.zapret
        cfg.game_tcp_range = self.game_tcp_edit.text().strip() or "1024-65535"
        cfg.game_udp_range = self.game_udp_edit.text().strip() or "1024-65535"
        self.ctx.save_config()
        try:
            self.ctx.zapret.apply_game_filter()
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            show_toast(self, tr("zapret.game_applied_error"), "error")
            return
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()
        self.log_view.append("[hub] Game Filter применён")
        show_toast(
            self,
            tr("zapret.game_applied", mode=tr("zapret.game_mode_" + cfg.game_mode)),
            "success",
        )

    def _on_ipset_changed(self, index: int) -> None:
        if self._loading:
            return
        mode = self.ipset_combo.currentData()
        if not mode:
            return
        self.ctx.config.zapret.ipset_mode = mode
        self.ctx.save_config()
        try:
            self.ctx.zapret.apply_ipset_mode(mode)
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            show_toast(self, tr("zapret.ipset_applied_error"), "error")
            return
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()
        show_toast(
            self, tr("zapret.ipset_applied", mode=tr("zapret.ipset_" + mode)), "success"
        )

    def _update_ipset(self) -> None:
        self.ipset_update_button.setEnabled(False)
        self.ipset_update_button.setText(tr("common.loading"))
        proxy = self.ctx.config.updates.proxy
        try:
            message = self.ctx.zapret.update_ipset_list(proxy=proxy)
            self.log_view.append(f"[hub] {message}")
            show_toast(self, message, "success")
            self.reload()
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            show_toast(self, str(exc), "error")
        finally:
            self.ipset_update_button.setText(tr("zapret.ipset_update"))
            self.ipset_update_button.setEnabled(True)

    def _on_list_changed(self, index: int) -> None:
        if self._loading:
            return
        self._load_user_list()

    def _save_user_list(self) -> None:
        name = self.list_combo.currentText()
        if not name:
            return
        self.ctx.zapret.write_user_list(name, self.list_edit.toPlainText())
        self.log_view.append(f"[hub] {tr('zapret.list_saved')}: {name}")
        show_toast(self, tr("zapret.list_saved_toast", name=name), "success")
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()


    # ------------------------------------------------------------ сбор IP по ASN

    def _collect_asn(self) -> None:
        collector = self.ctx.asn
        if collector.running:
            collector.stop()
            self.asn_button.setText(tr("zapret.asn_collect"))
            return
        target = self.ctx.zapret.ipset_file()
        self.asn_progress.setVisible(True)
        self.asn_progress.setMaximum(0)
        self.asn_label.setVisible(True)
        self.asn_label.setText(tr("common.loading"))
        self.asn_button.setText(tr("zapret.asn_stop"))
        collector.start(target)

    def _on_asn_progress(self, name: str, done: int, total: int) -> None:
        self.asn_progress.setMaximum(total)
        self.asn_progress.setValue(done)
        self.asn_label.setText(f"{name} — {done}/{total}")

    def _on_asn_status(self, message: str) -> None:
        self.asn_label.setText(message)

    def _on_asn_finished(self, v4: int, v6: int) -> None:
        self.asn_progress.setVisible(False)
        self.asn_label.setText(tr("zapret.asn_done", v4=v4, v6=v6))
        self.asn_button.setText(tr("zapret.asn_collect"))
        self._reload_lists()
        if self.ctx.zapret.is_running():
            self.ctx.zapret.restart()

    def _on_asn_failed(self, message: str) -> None:
        self.asn_progress.setVisible(False)
        self.asn_label.setText(f"{tr('common.error')}: {message}")
        self.asn_button.setText(tr("zapret.asn_collect"))

    def _on_status(self, status: str) -> None:
        self.pill.set_status(status)

    def set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.strategy_combo,
            self.ipset_combo,
            self.ipset_update_button,
            self.list_combo,
            self.list_edit,
            self.game_tcp_edit,
            self.game_udp_edit,
            self.game_apply_button,
            self.save_list_button,
            self.asn_button,
        ):
            widget.setEnabled(enabled)
        for radio in self.game_radios.values():
            radio.setEnabled(enabled)
