"""Базовая панель компонента (запрета) с заголовком, статусом и кнопкой обновления."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QSplitter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from .. import icons, theme
from ..widgets import HintLabel, IconButton, LogView, StatusPill


class PanelHeader(QWidget):
    """Заголовок панели, по которому можно щёлкнуть, чтобы её свернуть.

    Раньше свернуть панель можно было только маленькой кнопкой-шевроном в
    самом углу — попадать по ней неудобно. Теперь щёлчок по любому месту
    заголовка (название, версия, статус, пустое место) сворачивает и
    разворачивает панель. Кнопки внутри заголовка перехватывают нажатие
    сами, поэтому «Обновить» и «Журнал» по-прежнему работают как обычно.
    """

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ComponentPanel(QFrame):
    """Панель одного компонента: заголовок со статусом и кнопкой обновления."""

    update_requested = Signal(str)

    def __init__(
        self,
        ctx,
        key: str,
        title: str,
        subtitle: str,
        icon_name: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.key = key
        self._installed_shown = True
        self._collapsed = False

        self.setObjectName("Panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- заголовок ---
        header_host = PanelHeader()
        header_host.clicked.connect(self._toggle_collapsed)
        header = QHBoxLayout(header_host)
        header.setContentsMargins(18, 16, 14, 14)
        header.setSpacing(13)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(42, 42)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet(
            f"background-color: {theme.PALETTE['surface_alt']};"
            f"border: 1px solid {theme.PALETTE['border']}; border-radius: 13px;"
        )
        self.icon_label.setPixmap(
            icons.icon_pixmap(icon_name, theme.PALETTE["accent"], 21, 1.9)
        )
        header.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.subtitle_label = HintLabel(subtitle)
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        header.addLayout(titles, 1)

        self.version_label = QLabel("")
        self.version_label.setObjectName("muted")
        header.addWidget(self.version_label, 0, Qt.AlignVCenter)

        self.pill = StatusPill()
        header.addWidget(self.pill, 0, Qt.AlignVCenter)

        # --- кнопка обновления рядом с запретом ---
        self.update_button = IconButton("refresh", "", "iconButton", 16)
        self.update_button.setFixedSize(38, 38)
        self.update_button.setToolTip(tr("upd.check"))
        self.update_button.clicked.connect(lambda: self.update_requested.emit(self.key))
        header.addWidget(self.update_button, 0, Qt.AlignVCenter)

        # --- кнопка установки (видна, пока компонент не установлен) ---
        self.install_button = IconButton("download", tr("upd.install"), "glassPrimary")
        self.install_button.clicked.connect(lambda: self.update_requested.emit(self.key))
        self.install_button.setVisible(False)
        header.addWidget(self.install_button, 0, Qt.AlignVCenter)

        # --- кнопка журнала ---
        self.log_button = IconButton("terminal", "", "iconButton", 15)
        self.log_button.setFixedSize(38, 38)
        self.log_button.setToolTip(tr("log.title"))
        self.log_button.setCheckable(True)
        self.log_button.clicked.connect(self._toggle_log)
        header.addWidget(self.log_button, 0, Qt.AlignVCenter)

        # --- сворачивание панели: виден только заголовок ---
        # Треугольник, а не шеврон: ровно такой же значок остаётся в углу,
        # но теперь он читается как «стрелка состояния», а весь заголовок
        # слева от кнопок сворачивает панель так же.
        self.collapse_button = IconButton(
            "triangle-up" if not self._collapsed else "triangle-down",
            "",
            "iconButton",
            13,
        )
        # тот же размер и тот же стиль, что у «Обновить» и «Журнал» рядом
        self.collapse_button.setFixedSize(38, 38)
        self.collapse_button.setCheckable(True)
        self.collapse_button.setToolTip(tr("components.collapse"))
        self.collapse_button.clicked.connect(self.set_collapsed)
        header.addWidget(self.collapse_button, 0, Qt.AlignVCenter)

        root.addWidget(header_host)

        self.separator = QFrame()
        self.separator.setFixedHeight(1)
        self.separator.setStyleSheet(f"background-color: {theme.PALETTE['border']}; border: none;")
        root.addWidget(self.separator)

        # --- содержимое настроек ---
        # --- заглушка «компонент не установлен» ---
        self.placeholder = QFrame()
        self.placeholder.setObjectName("InstallPlaceholder")
        placeholder_layout = QVBoxLayout(self.placeholder)
        placeholder_layout.setContentsMargins(24, 26, 24, 26)
        placeholder_layout.setSpacing(12)

        placeholder_icon = QLabel()
        placeholder_icon.setFixedSize(46, 46)
        placeholder_icon.setAlignment(Qt.AlignCenter)
        placeholder_icon.setPixmap(icons.icon_pixmap("download", theme.PALETTE["muted"], 24, 1.9))
        placeholder_layout.addWidget(placeholder_icon, 0, Qt.AlignHCenter)

        self.placeholder_title = QLabel(tr("upd.not_installed"))
        self.placeholder_title.setObjectName("h2")
        placeholder_layout.addWidget(self.placeholder_title, 0, Qt.AlignHCenter)

        self.placeholder_hint = HintLabel(tr("components.install_hint"))
        self.placeholder_hint.setAlignment(Qt.AlignCenter)
        placeholder_layout.addWidget(self.placeholder_hint)

        self.placeholder_button = IconButton(
            "download", tr("upd.install"), "glassPrimary"
        )
        self.placeholder_button.clicked.connect(lambda: self.update_requested.emit(self.key))
        placeholder_layout.addWidget(self.placeholder_button, 0, Qt.AlignHCenter)

        # --- содержимое: настройки слева, журнал справа ---
        content = QHBoxLayout()
        content.setContentsMargins(16, 14, 16, 16)
        content.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("PanelSplitter")
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(10)

        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)
        self.splitter.addWidget(body)

        # --- журнал (справа, раскрывается кнопкой) ---
        self.log_view = LogView()
        self.log_view.setMinimumWidth(330)
        self.log_view.setVisible(False)
        self.splitter.addWidget(self.log_view)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self._log_sizes = [10000, 330]

        content.addWidget(self.splitter)
        root.addLayout(content)
        root.addWidget(self.placeholder)
        self.placeholder.setVisible(False)

        # --- таймер обновления статуса ---
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start()

    # ------------------------------------------------------------ API для наследников

    def add_widget(self, widget, stretch: int = 0) -> None:
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def flash(self, duration: int = 1400) -> None:
        """Кратковременно подсвечивает панель (её открыли с главной)."""
        self.setProperty("flash", "yes")
        self.style().unpolish(self)
        self.style().polish(self)
        QTimer.singleShot(duration, self._unflash)

    def _unflash(self) -> None:
        self.setProperty("flash", "no")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_collapsed(self, collapsed: bool) -> None:
        """Сворачивает панель до одного заголовка.

        Заголовок несёт всё нужное: название, версию, статус, кнопку
        проверки обновлений и кнопку журнала. Настройки скрыты, поэтому
        на странице остаётся только то, что действительно нужно.
        """
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.separator.setVisible(not collapsed)
        self.splitter.setVisible(not collapsed and self._installed_shown)
        self.placeholder.setVisible(not collapsed and not self._installed_shown)
        self.collapse_button.setChecked(collapsed)
        self.collapse_button.set_icon(
            "triangle-down" if collapsed else "triangle-up"
        )
        self.collapse_button.setToolTip(
            tr("components.expand") if collapsed else tr("components.collapse")
        )
        # размер панели зависит от содержимого: просим пересчитать
        self.updateGeometry()
        self.setMinimumHeight(0)
        parent = self.parentWidget()
        while parent is not None:
            if parent.layout() is not None:
                parent.layout().invalidate()
            parent.updateGeometry()
            parent = parent.parentWidget()

    def _toggle_collapsed(self) -> None:
        """Щёлчок по заголовку: свернуть или развернуть панель."""
        self.set_collapsed(not self._collapsed)

    def _toggle_log(self) -> None:
        visible = not self.log_view.isVisible()
        self.log_view.setVisible(visible)
        handle = self.splitter.handle(1)
        if handle is not None:
            handle.setVisible(visible)
        self.log_button.setChecked(visible)
        self.log_button.setObjectName("iconButtonActive" if visible else "iconButton")
        self.log_button.style().unpolish(self.log_button)
        self.log_button.style().polish(self.log_button)
        if visible:
            # журнал раскрывается справа и занимает треть ширины панели
            total = max(self.splitter.width(), 900)
            self._log_sizes = [int(total * 0.62), int(total * 0.38)]
            self.splitter.setSizes(self._log_sizes)
            from .. import anim

            anim.fade_in(self.log_view, duration=200)
        else:
            self.splitter.setSizes([max(self.splitter.width(), 900), 0])

    # ------------------------------------------------------------ статус

    def component(self):
        raise NotImplementedError

    def installed(self) -> bool:
        return self.component().installed()

    def version_display(self) -> str:
        return self.component().version_display()

    def refresh_status(self) -> None:
        component = self.component()
        installed = component.installed()
        status = component.status if installed else "stopped"
        self.pill.set_status(status)
        self.version_label.setText(
            f"{tr('app.version')}: "
            f"{self.version_display() if installed else tr('common.not_installed')}"
        )
        self.update_button.setEnabled(True)
        self.set_controls_enabled(installed)
        self._apply_installed_state(installed)

    def _apply_installed_state(self, installed: bool) -> None:
        """Если компонента нет — показываем кнопку установки вместо настроек."""
        if self._installed_shown == installed:
            return
        self._installed_shown = installed
        self.placeholder.setVisible(not installed and not self._collapsed)
        self.install_button.setVisible(not installed)
        self.log_button.setVisible(installed)
        self.splitter.setVisible(installed and not self._collapsed)

    def set_controls_enabled(self, enabled: bool) -> None:
        """Настройки доступны только если компонент установлен."""
        self.placeholder_button.setEnabled(True)

    def on_show(self) -> None:
        self.refresh_status()
