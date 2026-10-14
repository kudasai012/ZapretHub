"""Панель настроек TG WS Proxy (MTProto-прокси для Telegram)."""
from __future__ import annotations

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...i18n import tr
from ..widgets import (
    Banner,
    FormRow,
    HintLabel,
    IconButton,
    PickSpinBox,
    show_toast,
)
from .component_panel import ComponentPanel


class TgwsPanel(ComponentPanel):
    def __init__(self, ctx, parent=None):
        super().__init__(
            ctx,
            key="tgws",
            title="TG WS Proxy · Telegram",
            subtitle="tg-ws-proxy · MTProto-прокси",
            icon_name="send",
            parent=parent,
        )
        self._build()
        ctx.tgws.status_changed.connect(self.pill.set_status)
        ctx.tgws.log_line.connect(self.log_view.append)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_runtime)
        self.timer.start()

    def component(self):
        return self.ctx.tgws

    # ------------------------------------------------------------ построение

    def _build(self) -> None:
        conn = QGroupBox(tr("tgws.connection"))
        c_layout = QVBoxLayout(conn)
        c_layout.setSpacing(8)

        self.host_edit = QLineEdit()
        self.host_edit.setText(self.ctx.config.tgws.host)
        c_layout.addWidget(FormRow(tr("tgws.host"), self.host_edit))

        self.port_spin = PickSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(self.ctx.config.tgws.port))
        self.port_spin.setMinimumWidth(110)
        self.port_spin.setMaximumWidth(150)
        c_layout.addWidget(FormRow(tr("tgws.port"), self.port_spin))

        self.secret_edit = QLineEdit()
        self.secret_edit.setText(self.ctx.config.tgws.secret)
        generate = IconButton("key", tr("tgws.generate"), "glass")
        generate.clicked.connect(self._generate_secret)
        c_layout.addWidget(FormRow(tr("tgws.secret"), self.secret_edit, generate))

        self.dc_edit = QPlainTextEdit()
        self.dc_edit.setPlainText(chr(10).join(self.ctx.config.tgws.dc_ip))
        self.dc_edit.setMaximumHeight(80)
        c_layout.addWidget(FormRow(tr("tgws.dc_ip"), self.dc_edit))

        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        self.link_edit = QLineEdit()
        self.link_edit.setReadOnly(True)
        self.link_edit.setText(self.ctx.tgws.proxy_link())
        self.link_edit.setMinimumWidth(300)
        link_row.addWidget(self.link_edit, 1)
        copy_button = IconButton("copy", tr("tgws.copy_link"), "glass")
        copy_button.setMinimumWidth(150)
        open_button = IconButton("send", tr("tgws.open_tg"), "glassPrimary")
        open_button.setMinimumWidth(180)
        copy_button.clicked.connect(self._copy_link)
        open_button.clicked.connect(self._open_telegram)
        link_row.addWidget(copy_button, 0)
        link_row.addWidget(open_button, 0)
        c_layout.addLayout(link_row)

        hint = HintLabel(tr("tgws.manual_hint"))
        c_layout.addWidget(hint)
        self.add_widget(conn)

        # --- дополнительно ---
        adv = QGroupBox(tr("tgws.advanced"))
        a_layout = QVBoxLayout(adv)
        a_layout.setSpacing(8)
        self.buf_spin = PickSpinBox()
        self.buf_spin.setRange(4, 4096)
        self.buf_spin.setValue(int(self.ctx.config.tgws.buf_kb))
        self.buf_spin.setMinimumWidth(110)
        self.buf_spin.setMaximumWidth(150)
        a_layout.addWidget(FormRow(tr("tgws.buf_kb"), self.buf_spin))
        self.pool_spin = PickSpinBox()
        self.pool_spin.setRange(0, 64)
        self.pool_spin.setValue(int(self.ctx.config.tgws.pool_size))
        self.pool_spin.setMinimumWidth(110)
        self.pool_spin.setMaximumWidth(150)
        a_layout.addWidget(FormRow(tr("tgws.pool_size"), self.pool_spin))

        checks = QGridLayout()
        checks.setHorizontalSpacing(18)
        checks.setVerticalSpacing(8)
        self.verbose_check = QCheckBox(tr("tgws.verbose"))
        self.verbose_check.setChecked(bool(self.ctx.config.tgws.verbose))
        self.cfproxy_check = QCheckBox(tr("tgws.cfproxy"))
        self.cfproxy_check.setChecked(bool(self.ctx.config.tgws.cfproxy))
        self.testdc_check = QCheckBox(tr("tgws.force_test_dc"))
        self.testdc_check.setChecked(bool(self.ctx.config.tgws.force_test_dc))
        self.nosecure_check = QCheckBox(tr("tgws.no_secure"))
        self.nosecure_check.setChecked(bool(self.ctx.config.tgws.no_secure))
        self.selfupdate_check = QCheckBox(tr("tgws.its_check_updates"))
        self.selfupdate_check.setChecked(bool(self.ctx.config.tgws.check_updates))
        for index, box in enumerate(
            (
                self.verbose_check,
                self.cfproxy_check,
                self.testdc_check,
                self.nosecure_check,
                self.selfupdate_check,
            )
        ):
            checks.addWidget(box, index // 3, index % 3)
        a_layout.addLayout(checks)

        apply_button = IconButton("check", tr("common.apply"), "glassPrimary")
        apply_button.clicked.connect(self._apply)
        a_layout.addWidget(apply_button, 0)
        self.add_widget(adv)

        self.info_banner = Banner("", "info")
        self.info_banner.setVisible(False)
        self.add_widget(self.info_banner)

    # ------------------------------------------------------------ обработчики

    def _generate_secret(self) -> None:
        import os

        self.secret_edit.setText(os.urandom(16).hex())
        self._refresh_link()
        show_toast(self, tr("tgws.secret_generated"), "success")

    def _refresh_link(self) -> None:
        self.ctx.config.tgws.host = self.host_edit.text().strip() or "127.0.0.1"
        self.ctx.config.tgws.port = self.port_spin.value()
        self.ctx.config.tgws.secret = self.secret_edit.text().strip()
        self.link_edit.setText(self.ctx.tgws.proxy_link())

    def _copy_link(self) -> None:
        from PySide6.QtWidgets import QApplication

        self._refresh_link()
        QApplication.clipboard().setText(self.ctx.tgws.proxy_link())
        self.info_banner.set_kind("success")
        self.info_banner.set_text(tr("common.copied"))
        show_toast(self, tr("tgws.link_copied"), "success")

    def _open_telegram(self) -> None:
        self._refresh_link()
        QDesktopServices.openUrl(QUrl(self.ctx.tgws.proxy_link()))

    def _apply(self) -> None:
        cfg = self.ctx.config.tgws
        cfg.host = self.host_edit.text().strip() or "127.0.0.1"
        cfg.port = self.port_spin.value()
        cfg.secret = self.secret_edit.text().strip() or cfg.secret
        cfg.dc_ip = [
            line.strip()
            for line in self.dc_edit.toPlainText().splitlines()
            if line.strip()
        ] or ["2:149.154.167.220", "4:149.154.167.220"]
        cfg.buf_kb = self.buf_spin.value()
        cfg.pool_size = self.pool_spin.value()
        cfg.verbose = self.verbose_check.isChecked()
        cfg.cfproxy = self.cfproxy_check.isChecked()
        cfg.force_test_dc = self.testdc_check.isChecked()
        cfg.no_secure = self.nosecure_check.isChecked()
        cfg.check_updates = self.selfupdate_check.isChecked()
        self.ctx.save_config()
        self._refresh_link()
        self.info_banner.set_kind("success")
        self.info_banner.set_text(tr("tgws.config_applied"))
        show_toast(self, tr("tgws.config_applied"), "success")
        if self.ctx.tgws.is_running():
            self.ctx.tgws.restart()

    def _refresh_runtime(self) -> None:
        tgws = self.ctx.tgws
        installed = tgws.installed()
        for widget in (
            self.host_edit,
            self.port_spin,
            self.secret_edit,
            self.dc_edit,
            self.buf_spin,
            self.pool_spin,
            self.verbose_check,
            self.cfproxy_check,
            self.testdc_check,
            self.nosecure_check,
            self.selfupdate_check,
        ):
            widget.setEnabled(installed)

    def on_show(self) -> None:
        self._refresh_runtime()
        self.refresh_status()
        for line in self.ctx.tgws.tail_log_lines(30):
            self.log_view.append(f"[tgws] {line}")
