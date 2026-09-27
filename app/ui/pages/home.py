"""Главная страница: одна общая кнопка + статусы запретов."""
from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from ... import paths
from ...i18n import tr
from .. import icons, theme
from ..widgets import (
    Banner,
    BypassButton,
    HintLabel,
    IconButton,
    MasterButton,
    SectionLabel,
)
from .base import BasePage


class HomePage(BasePage):
    goto_components = Signal(str)
    goto_settings = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._build()

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start()

    # ------------------------------------------------------------ построение

    def _build(self) -> None:
        header = QVBoxLayout()
        header.setSpacing(3)
        title = QLabel(tr("dash.title"))
        title.setObjectName("h1")
        subtitle = HintLabel(tr("dash.subtitle"))
        header.addWidget(title)
        header.addWidget(subtitle)
        self.add_layout(header)

        # --- единственная общая кнопка ---
        self.master_button = MasterButton()
        self.master_button.setMinimumHeight(92)
        self.master_button.clicked.connect(self.ctx.toggle_all)
        self.add(self.master_button)

        self.hero_caption = HintLabel()
        self.add(self.hero_caption)

        # --- отдельная кнопка на каждый обход ---
        self.add_layout(self._bypass_header())
        bypasses = QHBoxLayout()
        bypasses.setSpacing(12)

        self.zapret_button = BypassButton(
            tr("home.bypass_zapret"), tr("home.bypass_zapret_sub"), "shield"
        )
        self.zapret_button.setMinimumHeight(104)
        self.zapret_button.toggle_button.clicked.connect(self._toggle_zapret)
        self.zapret_button.clicked.connect(self._toggle_zapret)
        self.zapret_button.settings_button.clicked.connect(
            lambda: self._open_component("zapret")
        )
        bypasses.addWidget(self.zapret_button, 1)

        self.tgws_button = BypassButton(
            tr("home.bypass_tgws"), tr("home.bypass_tgws_sub"), "send"
        )
        self.tgws_button.setMinimumHeight(104)
        self.tgws_button.toggle_button.clicked.connect(self._toggle_tgws)
        self.tgws_button.clicked.connect(self._toggle_tgws)
        self.tgws_button.settings_button.clicked.connect(
            lambda: self._open_component("tgws")
        )
        self.tgws_button.add_extra_button(
            IconButton("send", "", "iconButton", 15, tooltip=tr("tgws.open_tg")),
            self._open_telegram,
        )
        bypasses.addWidget(self.tgws_button, 1)

        self.add_layout(bypasses)

        # --- подсказки ---
        self.not_installed_banner = Banner(tr("dash.not_installed_text"), "warning")
        goto_button = IconButton("layers", tr("dash.goto_components"), "primary")
        goto_button.clicked.connect(lambda: self.goto_components.emit(""))
        self.not_installed_banner.layout().addWidget(goto_button)
        self.add(self.not_installed_banner)

        # --- быстрые действия ---
        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addWidget(SectionLabel(tr("dash.quick_actions")))
        actions.addStretch(1)
        open_components = IconButton("layers", tr("dash.open_components"), "ghost")
        open_components.clicked.connect(
            lambda: paths.open_in_file_manager(paths.COMPONENTS_DIR)
        )
        open_logs = IconButton("folder", tr("dash.open_logs"), "ghost")
        open_logs.clicked.connect(lambda: paths.open_in_file_manager(paths.LOGS_DIR))
        actions.addWidget(open_components)
        actions.addWidget(open_logs)
        self.add_layout(actions)

        # свободное место — сверху и снизу, контент по центру
        self.center_content()

    def _bypass_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.addWidget(SectionLabel(tr("home.bypasses")))
        header.addStretch(1)
        return header

    # ------------------------------------------------------------ действия

    def _toggle_zapret(self) -> None:
        if self.ctx.zapret.is_running():
            self.ctx.zapret.stop()
        else:
            self._maybe_elevate_and_start(self.ctx.zapret)

    def _toggle_tgws(self) -> None:
        if self.ctx.tgws.is_running():
            self.ctx.tgws.stop()
        else:
            self._maybe_elevate_and_start(self.ctx.tgws)

    def _open_component(self, key: str) -> None:
        self.goto_components.emit(key)

    def _open_telegram(self) -> None:
        link = self.ctx.tgws.proxy_link()
        if link:
            QDesktopServices.openUrl(QUrl(link))

    def _maybe_elevate_and_start(self, component) -> None:
        from PySide6.QtWidgets import QApplication, QMessageBox

        from ...core import win32

        if component is self.ctx.zapret and component.installed() and not win32.is_admin():
            answer = QMessageBox.question(
                self,
                tr("app.name"),
                tr("status.admin_relaunch"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes and win32.relaunch_elevated():
                QApplication.quit()
                return
        component.start()

    # ------------------------------------------------------------ статус

    def refresh_status(self) -> None:
        zapret, tgws = self.ctx.zapret, self.ctx.tgws

        running = self.ctx.any_running()
        active = sum(1 for c in (zapret, tgws) if c.is_running())
        zapret_error = self._is_error(zapret)
        tgws_error = self._is_error(tgws)
        self.master_button.set_state(
            running,
            caption=tr("dash.summary", active=active, total=2),
            error=self._all_broken(),
        )
        self.zapret_button.set_state(
            zapret.is_running(),
            self._bypass_subtitle(zapret, "zapret"),
            error=zapret_error,
        )
        self.tgws_button.set_state(
            tgws.is_running(),
            self._bypass_subtitle(tgws, "tgws"),
            error=tgws_error,
        )

        # плашки с ключевыми настройками: Game Filter и IPSet — сразу видно,
        # чем именно ограничен обход, не заходя в «Компоненты»
        self.zapret_button.set_badges(self._zapret_badges())
        self.tgws_button.set_badges(self._tgws_badges())

        if not self.ctx.components_installed():
            self.hero_caption.setText(tr("dash.not_installed_text"))
        else:
            # лишнего текста тут нет: состояние видно по самой кнопке
            self.hero_caption.setText("")

        self.not_installed_banner.setVisible(not self.ctx.components_installed())

    @staticmethod
    def _is_error(component) -> bool:
        """Компонент запущен, но подключиться не смог (упал при старте)."""
        return component.status in ("crashed", "error")

    def _all_broken(self) -> bool:
        """Мастер-кнопка желтеет, только если ни один обход не подключился."""
        installed = [c for c in (self.ctx.zapret, self.ctx.tgws) if c.installed()]
        return bool(installed) and all(self._is_error(c) for c in installed)

    def _zapret_badges(self) -> list:
        """Game Filter и режим IPSet для плашек на кнопке zapret."""
        state = self.ctx.zapret.game_filter_state()
        mode = state.get("mode", "disabled")
        if mode == "all":
            game = tr("home.badge_game_all")
        elif mode == "tcp":
            game = tr("home.badge_game_tcp")
        elif mode == "udp":
            game = tr("home.badge_game_udp")
        else:
            game = tr("home.badge_game_off")
        ipset = self.ctx.zapret.ipset_state()
        return [
            (tr("home.badge_game"), game),
            (tr("home.badge_ipset"), tr("home.badge_ipset_" + ipset)),
        ]

    def _tgws_badges(self) -> list:
        """Порт и число DC для плашек на кнопке tg-ws-proxy."""
        cfg = self.ctx.config.tgws
        return [
            (tr("home.badge_port"), str(cfg.port)),
            (tr("home.badge_dc"), str(len(cfg.dc_ip or []))),
        ]

    def _bypass_subtitle(self, component, key: str) -> str:
        """Подпись на кнопке обхода: состояние и ключевой параметр."""
        if self._is_error(component):
            return tr("dash.connect_error")
        if not component.installed():
            return tr("common.not_installed")
        if component.is_running():
            uptime = _format_uptime(component.uptime())
            if key == "zapret":
                strategy = self.ctx.config.zapret.strategy or tr("common.unknown")
                return f"{tr('common.running')} · {strategy} · {uptime}"
            return (
                f"{tr('common.running')} · "
                f"{self.ctx.config.tgws.host}:{self.ctx.config.tgws.port} · {uptime}"
            )
        return tr("common.stopped")

    def on_show(self) -> None:
        self.refresh_status()


class StatCard(QFrame):
    """Компактная карточка с ключевым параметром компонента."""

    def __init__(self, title: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("CardFlat")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(96)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(9)
        icon_label = QLabel()
        icon_label.setFixedSize(20, 20)
        icon_label.setPixmap(icons.icon_pixmap(icon_name, theme.PALETTE["accent"], 19, 1.9))
        head.addWidget(icon_label, 0)
        label = QLabel(title)
        label.setObjectName("statLabel")
        head.addWidget(label, 1)
        layout.addLayout(head)

        self.value_label = QLabel("—")
        self.value_label.setObjectName("statValue")
        layout.addWidget(self.value_label)

        self.hint_label = HintLabel()
        layout.addWidget(self.hint_label)

    def set_value(self, value: str, hint: str = "") -> None:
        self.value_label.setText(value)
        self.hint_label.setText(hint)


def _format_uptime(seconds: float) -> str:
    """Человекочитаемый аптайм: 1 ч 05 мин / 12 мин / 45 с."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    if minutes:
        return f"{minutes} мин {secs:02d} с"
    return f"{secs} с"
