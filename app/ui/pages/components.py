"""Страница компонентов: настройки всех запретов."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ...i18n import tr
from ..widgets import HintLabel, IconButton
from .base import BasePage
from .component_panel import ComponentPanel
from .tgws_panel import TgwsPanel
from .zapret_panel import ZapretPanel


class ComponentsPage(BasePage):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.zapret_panel = ZapretPanel(ctx)
        self.tgws_panel = TgwsPanel(ctx)
        self._panels: tuple[ComponentPanel, ...] = (self.zapret_panel, self.tgws_panel)
        self._build()

        for panel in self._panels:
            panel.update_requested.connect(self._open_update)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start()

    def _build(self) -> None:
        header = QVBoxLayout()
        header.setSpacing(3)
        title = QLabel(tr("components.title"))
        title.setObjectName("h1")
        subtitle = HintLabel(tr("components.subtitle"))
        header.addWidget(title)
        header.addWidget(subtitle)
        self.add_layout(header)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.update_all_button = IconButton("refresh", tr("upd.check_all"), "ghost")
        self.update_all_button.clicked.connect(self._update_all)
        actions.addWidget(self.update_all_button)
        self.add_layout(actions)

        self.add(self.zapret_panel)
        self.add(self.tgws_panel)

        self._layout.addStretch(1)

    # ------------------------------------------------------------ фокус

    def focus_component(self, key: str) -> None:
        """Прокручивает к панели компонента и подсвечивает её."""
        panels = {"zapret": self.zapret_panel, "tgws": self.tgws_panel}
        panel = panels.get(key)
        if panel is None:
            return
        self.scroll.ensureWidgetVisible(panel, 20, 40)
        panel.flash()

    # ------------------------------------------------------------ обновления

    def _update_all(self) -> None:
        self._open_update(None)

    def _open_update(self, key: str | None = None) -> None:
        from ..update_dialog import UpdateDialog

        dialog = UpdateDialog(self.ctx, key=key, parent=self)
        dialog.exec()

    # ------------------------------------------------------------ статус

    def refresh_status(self) -> None:
        for panel in self._panels:
            panel.refresh_status()
        self._refresh_header_button()

    def _refresh_header_button(self) -> None:
        """Ничего не установлено — кнопка предлагает установить всё сразу."""
        nothing_installed = not any(panel.installed() for panel in self._panels)
        if nothing_installed:
            self.update_all_button.setText(tr("components.install_all"))
            self.update_all_button.set_icon("download")
            self.update_all_button.setObjectName("primary")
        else:
            self.update_all_button.setText(tr("upd.check_all"))
            self.update_all_button.set_icon("refresh")
            self.update_all_button.setObjectName("ghost")
        self.update_all_button.style().unpolish(self.update_all_button)
        self.update_all_button.style().polish(self.update_all_button)

    def on_show(self) -> None:
        self.refresh_status()
        self.zapret_panel.on_show()
        self.tgws_panel.on_show()
