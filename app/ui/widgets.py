"""Виджеты интерфейса: мастер-кнопка, статусы, журнал, баннеры, тосты."""
from __future__ import annotations

import math
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QRegion,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from . import anim, icons, theme


# ------------------------------------------------------------ иконка + текст

class IconButton(QPushButton):
    """Кнопка с векторной иконкой."""

    def __init__(
        self,
        icon_name: str,
        text: str = "",
        object_name: str = "",
        icon_size: int = 16,
        parent: Optional[QWidget] = None,
        tooltip: str = "",
    ):
        super().__init__(text, parent)
        self._icon_name = icon_name
        self._icon_size = icon_size
        if object_name:
            self.setObjectName(object_name)
        self.setIcon(icons.get_icon(icon_name, theme.PALETTE["muted"], icon_size))
        self.setIconSize(QSize(icon_size, icon_size))
        if not text:
            self.setFixedSize(icon_size + 14, icon_size + 14)
        else:
            # Кнопка с подписью: раньше ширину иногда задавали вручную
            # (например 38x38 у «Закрыть»), и текст не влезал — кнопка
            # выглядела обрезанной. Здесь минимальная ширина считается по
            # содержимому, поэтому подпись всегда помещается.
            # запас: padding 16+16 из QSS + рамка 2 + ещё 34 на «воздух».
            # Раньше запаса хватало только на padding, и подпись
            # обрезалась — «Закрыть» выглядела как «Закры…».
            fm = QFontMetrics(self.font())
            need = fm.horizontalAdvance(text) + icon_size + 52
            self.setMinimumWidth(max(need, 72))
            self.setMinimumHeight(max(icon_size + 22, 34))
        self.setToolTip(tooltip or text)

    def set_icon(self, icon_name: str, color: Optional[str] = None) -> None:
        self._icon_name = icon_name
        self.setIcon(
            icons.get_icon(icon_name, color or theme.PALETTE["muted"], self._icon_size)
        )


# ------------------------------------------------------------ список выбора

class PickCheckBox(QCheckBox):
    """Чекбокс с квадратным индикатором и нарисованной галочкой.

    Индикатор — **штатный**, а не саморисованный. Раньше квадрат рисовался
    вручную по координате x=0, а настоящий индикатор прятался нулевым
    размером. Отсюда шли обе жалобы: квадрат был виден, но щёлчок по нему
    не срабатывал (срабатывал только щёлчок по подписи), и квадрат уезжал
    под текст, выглядел обрезанным. Штатный индикатор стилизуется через
    QSS, поэтому всегда на своём месте, правильного размера и кликабельный.

    Галочку дорисовываем поверх: в QSS картинку подставить нечем (Qt не
    умеет data:-URI), а белая галочка на синей заливке читается лучше
    любого системного значка. Геометрию индикатора спрашиваем у стиля —
    так галочка попадает ровно в квадрат при любом размере шрифта.
    """

    #: сторона квадратика — должна совпадать с QSS (width/height)
    SIZE = 17

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        # свойство для QSS: правила применяются ко всем таким чекбоксам,
        # но не трогают прочие QCheckBox, если они появятся
        self.setProperty("check", "yes")
        self._hover = False

    # --- геометрия ---

    def _indicator_rect(self) -> QRectF:
        """Прямоугольник штатного индикатора в координатах виджета."""
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(
            QStyle.SE_CheckBoxIndicator, option, self
        )
        return QRectF(rect)

    # --- мышь ---

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def hitButton(self, pos) -> bool:
        """Щелчок по самому квадрату тоже переключает чекбокс.

        Штатный индикатор и так кликабельный, но на всякий случай
        добавляем его прямоугольник: подпись остаётся кликабельной целиком.
        """
        if self._indicator_rect().contains(QPointF(pos)):
            return True
        return super().hitButton(pos)

    # --- рисование ---

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        rect = self._indicator_rect()
        if rect.width() < 4 or rect.height() < 4:
            # индикатор ещё не размечен (виджет скрыт или только создан)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        palette = theme.PALETTE
        cx, cy = rect.center().x(), rect.center().y()
        size = rect.width()
        # галочка занимает примерно половину квадрата
        s = size * 0.30

        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(
                QColor("#ffffff") if self.isEnabled() else QColor(palette["faint"])
            )
            path = QPainterPath()
            path.moveTo(cx - s, cy + s * 0.05)
            path.lineTo(cx - s * 0.15, cy + s * 0.85)
            path.lineTo(cx + s * 1.05, cy - s * 0.85)
            path.lineTo(cx + s * 0.62, cy - s * 0.95)
            path.lineTo(cx - s * 0.15, cy + s * 0.15)
            path.lineTo(cx - s * 0.45, cy + s * 0.45)
            path.closeSubpath()
            painter.drawPath(path)
        elif self.checkState() == Qt.PartiallyChecked:
            # смешанное состояние — короткая черточка
            pen = QPen(QColor(palette["accent_hover"]))
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(rect.left() + size * 0.28, cy),
                QPointF(rect.right() - size * 0.28, cy),
            )
        painter.end()


class ClickLabel(QLabel):
    """Метка, по которой можно щёлкнуть.

    Нужна в боковом меню: подпись с названием программы и иконка
    сворачивают/разворачивают панель так же, как маленькая кнопка-шеврон.
    """

    clicked = Signal()

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class StatusDot(QFrame):
    """Статус обходов в боковом меню: точка и подпись.

    Раньше здесь был полукруг с тремя пузырьками по кромке. На широкой
    панели он всё равно не помещался: окружность уходила за виджет,
    обрезалась по нижней кромке, и вместо купола были видны только бледное
    пятно да пара кругов по бокам. Пользователю от него нужна одна вещь —
    работает обход или нет, — поэтому осталось ровно это: зелёная точка и
    «Активен», когда хоть один компонент запущен, серая точка и «Не
    активен», когда всё выключено. Разбор по компонентам — в подсказке.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusDot")
        self.setProperty("on", "no")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)

        self.dot = QFrame()
        self.dot.setObjectName("StatusDotMark")
        self.dot.setProperty("on", "no")
        self.dot.setFixedSize(10, 10)
        layout.addWidget(self.dot, 0, Qt.AlignVCenter)

        self.label = QLabel(tr("status.inactive"))
        self.label.setObjectName("StatusDotText")
        layout.addWidget(self.label, 1)

        self._running = 0
        self._total = 2
        self._zapret = False
        self._tgws = False
        self._refresh()

    # --- данные ---

    def set_state(self, running: int, total: int, zapret: bool, tgws: bool) -> None:
        running = max(0, int(running))
        total = max(0, int(total))
        if (running, total, bool(zapret), bool(tgws)) == (
            self._running,
            self._total,
            self._zapret,
            self._tgws,
        ):
            return
        self._running = running
        self._total = total
        self._zapret = bool(zapret)
        self._tgws = bool(tgws)
        self._refresh()

    def set_compact(self, compact: bool) -> None:
        """Свёрнутое меню: подпись не помещается, остаётся одна точка."""
        self.label.setVisible(not compact)
        self._refresh()

    # --- рисование состояния ---

    def _refresh(self) -> None:
        on = self._running > 0
        self.setProperty("on", "yes" if on else "no")
        self.dot.setProperty("on", "yes" if on else "no")
        self.label.setText(tr("status.active") if on else tr("status.inactive"))
        for widget in (self, self.dot, self.label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class PickComboBox(QComboBox):
    """Комбобокс, который меняет значение только по клику.

    Колесо мыши не меняет выбор никогда — даже когда комбобокс в фокусе:
    случайный поворот колеса над списком адресов сбрасывал выбор. Значение
    меняется только явно: клик по списку и выбор пункта. Стрелка вниз
    рисуется вручную — CSS-треугольники Qt не умеет, а картинка через QSS
    отрисовывается ненадёжно.
    """

    ARROW_IDLE = QColor("#8b96ad")
    ARROW_ACTIVE = QColor("#eaeef7")

    #: радиус скругления выпадающего списка — должен совпадать с QSS
    POPUP_RADIUS = 13

    def wheelEvent(self, event) -> None:
        event.ignore()

    def showPopup(self) -> None:
        """Показывает список и скругляет углы самого окна-поппапа.

        Выпадающий список комбо — отдельное окно Windows. У него
        прямоугольная рамка, поэтому скруглённая по QSS рамка списка
        «упиралась» углами в квадратный фон окна: видны были светлые
        треугольники. Здесь popup получает ту же скруглённую маску,
        что и диалог обновлений.
        """
        super().showPopup()
        self._round_popup()

    def _round_popup(self, attempt: int = 0) -> None:
        """Ставит маску на окно-поппап (с повтором: размер известен не сразу)."""
        view = self.view()
        if view is None:
            return
        window = view.window()
        if window is None or window is self:
            return
        rect = window.rect()
        if not rect.isValid() or rect.width() < 20:
            # размер ещё не посчитан — пробуем ещё раз на следующем тике
            if attempt < 5:
                QTimer.singleShot(0, lambda: self._round_popup(attempt + 1))
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self.POPUP_RADIUS, self.POPUP_RADIUS)
        window.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        color = self.ARROW_ACTIVE if self.underMouse() else self.ARROW_IDLE
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(color)
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        side = 16.0
        cx = self.width() - 22.0
        cy = self.height() / 2.0
        painter.drawPolyline(
            [
                QPointF(cx - side * 0.22, cy - side * 0.13),
                QPointF(cx, cy + side * 0.17),
                QPointF(cx + side * 0.22, cy - side * 0.13),
            ]
        )
        painter.end()


class PickSpinBox(QSpinBox):
    """Числовое поле, которое меняется только ручным вводом.

    Ни колесо мыши, ни стрелки у полей не работают: значение вводится с
    клавиатуры, потому что случайный поворот колеса или тык по стрелке сбивал
    уже введённое число. Клавиши «вверх»/«вниз» при выделенном поле остались
    — это клавиатура, а не элементы управления.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setAlignment(Qt.AlignCenter)
        self.setKeyboardTracking(True)

    def wheelEvent(self, event) -> None:
        event.ignore()


# ------------------------------------------------------------ мастер-кнопка

class MasterButton(QWidget):
    """Единая кнопка запуска/остановки обоих компонентов (свой рисунок + анимации)."""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._running = False
        self._error = False
        self._label = tr("action.start_all")
        self._icon = "power"
        self._hover = 0.0
        self._press = 0.0
        self._glow = 0.0
        self._pulse = 0.0
        self._sheen = 0.0
        self._caption = ""
        self._enabled = True

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._tick)
        self._pulse_timer.start()

    # --- свойства для анимации ---

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hoverAmount = Property(float, fget=_get_hover, fset=_set_hover)

    def _get_press(self) -> float:
        return self._press

    def _set_press(self, value: float) -> None:
        self._press = float(value)
        self.update()

    pressAmount = Property(float, fget=_get_press, fset=_set_press)

    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, value: float) -> None:
        self._glow = float(value)
        self.update()

    glowAmount = Property(float, fget=_get_glow, fset=_set_glow)

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, value: float) -> None:
        self._pulse = float(value)
        self.update()

    pulseAmount = Property(float, fget=_get_pulse, fset=_set_pulse)

    def _get_sheen(self) -> float:
        return self._sheen

    def _set_sheen(self, value: float) -> None:
        self._sheen = float(value)
        self.update()

    sheenAmount = Property(float, fget=_get_sheen, fset=_set_sheen)

    # --- состояние ---

    def set_state(
        self,
        running: bool,
        label: Optional[str] = None,
        caption: Optional[str] = None,
        error: bool = False,
    ) -> None:
        running = bool(running)
        error = bool(error) and not running
        changed = running != self._running or error != self._error
        self._running = running
        self._error = error
        self._label = label or (tr("action.stop_all") if running else tr("action.start_all"))
        self._icon = "stop" if running else "power"
        if caption is not None:
            self._caption = caption
        if changed:
            self._animate_glow()
            self._pulse_timer.start()
        self.update()

    def set_enabled_state(self, enabled: bool) -> None:
        self._enabled = enabled
        self.setEnabled(enabled)
        self.update()

    def _animate_glow(self) -> None:
        anim.animate_property(self, b"glowAmount", 0.0, 1.0, 420, QEasingCurve.OutCubic)
        QTimer.singleShot(420, self._glow_back)

    def _glow_back(self) -> None:
        anim.animate_property(self, b"glowAmount", self._glow, 0.0, 900, QEasingCurve.InOutSine)

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.05) % 1.0
        # бегущий блик по поверхности (эффект жидкости)
        if self._hover > 0.05 or self._running:
            self._sheen = (self._sheen + 0.018) % 1.4
        elif self._sheen > 0.0:
            self._sheen = 0.0
        self.update()
        # в покое таймер не нужен
        if not self._running and self._hover < 0.05 and self._press < 0.05:
            self._pulse_timer.stop()

    # --- события ---

    def enterEvent(self, event) -> None:
        anim.animate_property(self, b"hoverAmount", self._hover, 1.0, 180)
        self._pulse_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        anim.animate_property(self, b"hoverAmount", self._hover, 0.0, 220)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._enabled:
            anim.animate_property(self, b"pressAmount", 0.0, 1.0, 90)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._enabled:
            anim.animate_property(self, b"pressAmount", self._press, 0.0, 160)
            if self.rect().contains(event.pos()):
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    # --- отрисовка ---

    def paintEvent(self, event) -> None:
        """Стеклянная мастер-кнопка: матовое стекло, кромка, иконка, статус."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = 20.0
        palette = theme.PALETTE

        if self._running:
            tint = QColor(palette["green"])
            deep = QColor("#1f9d63")
        elif self._error:
            # ни один обход не подключился — кнопка горит жёлтым
            tint = QColor(palette["amber"])
            deep = QColor("#b8791a")
        else:
            tint = QColor(palette["accent"])
            deep = QColor(palette["accent_deep"])

        # ---- мягкое внешнее свечение ----
        if self._glow > 0.01 or self._running:
            strength = 0.05 + self._glow * 0.20 + (0.05 if self._running else 0.0)
            glow_rect = rect.adjusted(-28, -22, 28, 22)
            radial = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.9)
            c = QColor(tint)
            c.setAlphaF(strength)
            radial.setColorAt(0.0, c)
            c2 = QColor(tint)
            c2.setAlphaF(0.0)
            radial.setColorAt(1.0, c2)
            # Свечение шире самой кнопки, а рисование вне виджета Qt обрезает
            # по его прямоугольнику — раньше из-за этого по краям появлялись
            # светлые квадратные уголки. Рисуем свечение с обрезкой по
            # скруглённому контуру, тогда края остаются ровно круглыми.
            painter.save()
            painter.setClipPath(_rounded_path(QRectF(self.rect()), radius))
            painter.setPen(Qt.NoPen)
            painter.setBrush(radial)
            painter.drawRoundedRect(glow_rect, radius + 18, radius + 18)
            painter.restore()

        # ---- нажатие: кнопка «проваливается» ----
        scale = 1.0 - self._press * 0.010
        center = rect.center()
        painter.translate(center)
        painter.scale(scale, scale)
        painter.translate(-center)

        # ---- подложка: почти плоская, лёгкая подсветка только при наведении ----
        plate = QColor("#ffffff")
        plate.setAlphaF(0.020 + self._hover * 0.045)
        painter.setPen(Qt.NoPen)
        painter.setBrush(plate)
        painter.drawRoundedRect(rect, radius, radius)

        # ---- верхняя глянцевая полоса ----
        highlight = QLinearGradient(rect.topLeft(), rect.topLeft() + QPointF(0, rect.height() * 0.55))
        white = QColor("#ffffff")
        white.setAlphaF(0.05 + self._hover * 0.05)
        highlight.setColorAt(0.0, white)
        white2 = QColor("#ffffff")
        white2.setAlphaF(0.0)
        highlight.setColorAt(1.0, white2)
        painter.setBrush(highlight)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)

        # ---- бегущий блик при наведении ----
        if self._sheen > 0.001:
            sheen_w = rect.width() * 0.30
            x = rect.left() - sheen_w + self._sheen * (rect.width() + sheen_w * 2)
            band = QLinearGradient(x, rect.top(), x + sheen_w, rect.bottom())
            s1 = QColor("#ffffff")
            s1.setAlphaF(0.0)
            s2 = QColor("#ffffff")
            s2.setAlphaF(0.09 + self._hover * 0.05)
            s3 = QColor("#ffffff")
            s3.setAlphaF(0.0)
            band.setColorAt(0.0, s1)
            band.setColorAt(0.5, s2)
            band.setColorAt(1.0, s3)
            painter.save()
            painter.setClipPath(_rounded_path(rect, radius))
            painter.setBrush(band)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, radius, radius)
            painter.restore()

        # ---- стеклянная кромка ----
        border = QColor(tint if self._running else "#ffffff")
        border.setAlphaF(0.12 + self._hover * 0.12)
        painter.setPen(QPen(border, 1.1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        # ---- содержимое ----
        icon_size = 26
        well = 46.0
        pad = 16.0
        title_font = QFont(self.font())
        title_font.setPointSize(13)
        title_font.setWeight(QFont.DemiBold)
        caption_font = QFont(self.font())
        caption_font.setPointSize(9)

        title_metrics = QFontMetricsF(title_font)
        caption_metrics = QFontMetricsF(caption_font)
        text_left = rect.left() + pad + well + 14
        text_right = rect.right() - pad - 104
        text_width = max(60.0, text_right - text_left)

        fg = QColor(palette["text"])
        fg_soft = QColor(palette["muted"])
        if self._running:
            fg = QColor("#eafff6")
            fg_soft = QColor("#a9d9c6")

        # круглый «колодец» с иконкой
        well_rect = QRectF(rect.left() + pad, rect.center().y() - well / 2, well, well)
        well_fill = QLinearGradient(well_rect.topLeft(), well_rect.bottomLeft())
        if self._running:
            w1 = QColor("#ffffff")
            w1.setAlphaF(0.20)
            w2 = QColor("#ffffff")
            w2.setAlphaF(0.08)
        else:
            w1 = QColor(tint)
            w2 = QColor(deep)
        well_fill.setColorAt(0.0, w1)
        well_fill.setColorAt(1.0, w2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(well_fill)
        painter.drawEllipse(well_rect)

        icon_pixmap = icons.icon_pixmap(self._icon, "#ffffff", icon_size, 2.1)
        painter.drawPixmap(
            QRectF(
                well_rect.center().x() - icon_size / 2,
                well_rect.center().y() - icon_size / 2,
                icon_size,
                icon_size,
            ),
            icon_pixmap,
            QRectF(0, 0, icon_pixmap.width(), icon_pixmap.height()),
        )

        # заголовок и подпись
        painter.setFont(title_font)
        painter.setPen(fg)
        painter.drawText(
            QRectF(text_left, rect.top() + 16, text_width, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            title_metrics.elidedText(self._label, Qt.ElideRight, int(text_width)),
        )
        if self._caption:
            painter.setFont(caption_font)
            painter.setPen(fg_soft)
            painter.drawText(
                QRectF(text_left, rect.top() + 38, text_width, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                caption_metrics.elidedText(self._caption, Qt.ElideRight, int(text_width)),
            )

        # ---- состояние справа ----
        state_color = QColor(palette["green"]) if self._running else QColor(palette["muted"])
        state_text = tr("common.running") if self._running else tr("common.stopped")
        state_font = QFont(self.font())
        state_font.setPointSize(9)
        state_font.setWeight(QFont.DemiBold)
        state_metrics = QFontMetricsF(state_font)
        pill_w = state_metrics.horizontalAdvance(state_text) + 26
        pill_rect = QRectF(
            rect.right() - pad - pill_w, rect.center().y() - 12, pill_w, 24
        )
        pill_fill = QColor(state_color)
        pill_fill.setAlphaF(0.16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(pill_fill)
        painter.drawRoundedRect(pill_rect, 12, 12)
        painter.setPen(QPen(QColor(state_color), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(pill_rect, 12, 12)
        painter.setFont(state_font)
        painter.setPen(QColor(state_color))
        painter.drawText(pill_rect, Qt.AlignCenter, state_text)

        painter.end()


def _rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


# ------------------------------------------------------------ кнопка обхода

class BypassButton(QFrame):
    """Стеклянная кнопка одного обхода: запуск/остановка + состояние.

    Клик по любой части карточки переключает компонент; отдельная круглая
    кнопка справа делает то же самое и показывает направление действия.
    """

    clicked = Signal()
    open_clicked = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        icon_name: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("BypassCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._running = False
        self._error = False
        self._enabled = True
        self._badges_data: list = []
        self._badge_widgets: list = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(38, 38)
        self.icon_label.setObjectName("bypassIcon")
        layout.addWidget(self.icon_label)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("bypassTitle")
        text_box.addWidget(self.title_label)
        self.subtitle_label = HintLabel(subtitle)
        text_box.addWidget(self.subtitle_label)

        # ряд мелких плашек: Game Filter, IPSet и прочие ключевые настройки
        self.badges_row = QHBoxLayout()
        self.badges_row.setContentsMargins(0, 3, 0, 0)
        self.badges_row.setSpacing(6)
        text_box.addLayout(self.badges_row)
        layout.addLayout(text_box, 1)

        self.toggle_button = QPushButton("")
        self.toggle_button.setObjectName("bypassToggle")
        self.toggle_button.setFixedSize(38, 38)
        self.toggle_button.setCursor(Qt.PointingHandCursor)
        self.toggle_button.setToolTip(tr("action.toggle"))
        layout.addWidget(self.toggle_button, 0, Qt.AlignVCenter)

        self.settings_button = QPushButton("")
        self.settings_button.setObjectName("bypassGear")
        self.settings_button.setFixedSize(30, 30)
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setIcon(icons.get_icon("gear", theme.PALETTE["muted"], 16))
        self.settings_button.setIconSize(QSize(16, 16))
        self.settings_button.setToolTip(tr("components.open_settings"))
        layout.addWidget(self.settings_button, 0, Qt.AlignVCenter)

        self._set_icon(icon_name)
        self._set_running(False)

    # --- внешний вид ---

    def _set_icon(self, icon_name: str) -> None:
        self._icon_name = icon_name
        self.icon_label.setPixmap(
            icons.icon_pixmap(icon_name, theme.PALETTE["accent"], 21, 1.9)
        )

    def _set_running(self, running: bool) -> None:
        self._running = bool(running)
        color = theme.PALETTE["green"] if self._running else theme.PALETTE["accent"]
        self.icon_label.setPixmap(
            icons.icon_pixmap(self._icon_name, color, 21, 1.9)
        )
        self.toggle_button.setIcon(
            icons.get_icon(
                "stop" if self._running else "play",
                theme.PALETTE["green"] if self._running else theme.PALETTE["accent"],
                17,
            )
        )
        self.toggle_button.setIconSize(QSize(17, 17))
        self.setProperty("running", "yes" if self._running else "no")

    # --- API ---

    def set_state(
        self,
        running: bool,
        subtitle: Optional[str] = None,
        error: bool = False,
    ) -> None:
        running = bool(running)
        error = bool(error) and not running
        changed = (
            running != self._running
            or error != self._error
            or subtitle is not None
        )
        self._set_running(running)
        self._error = error
        self.setProperty("error", "yes" if error else "no")
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)
        if changed:
            self.style().unpolish(self)
            self.style().polish(self)
        self.update()

    def set_enabled_state(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.setEnabled(enabled)
        self.toggle_button.setEnabled(enabled)

    def set_badges(self, badges: Sequence[Tuple[str, str]]) -> None:
        """Плашки с ключевыми настройками: [(подпись, значение), ...].

        Показывают сразу на кнопке обхода, за что отвечает компонент, —
        не нужно заходить в «Компоненты», чтобы увидеть Game Filter или
        режим IPSet.
        """
        wanted = [(str(label), str(value)) for label, value in badges if value]
        if wanted == self._badges_data:
            return
        self._badges_data = wanted
        for badge in self._badge_widgets:
            self.badges_row.removeWidget(badge)
            badge.deleteLater()
        self._badge_widgets = []
        for label, value in wanted:
            badge = self._make_badge(label, value)
            self._badge_widgets.append(badge)
            self.badges_row.addWidget(badge)

    @staticmethod
    def _make_badge(label: str, value: str) -> QWidget:
        """Мелкая плашка «подпись: значение»."""
        badge = QFrame()
        badge.setObjectName("BypassBadge")
        badge.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(badge)
        row.setContentsMargins(7, 2, 7, 2)
        row.setSpacing(5)
        name = QLabel(label)
        name.setObjectName("BypassBadgeLabel")
        row.addWidget(name)
        text = QLabel(value)
        text.setObjectName("BypassBadgeValue")
        row.addWidget(text)
        return badge

    def set_open_handler(self, handler: Callable) -> None:
        self._open_handler = handler

    def add_extra_button(
        self, button: QPushButton, handler: Optional[Callable] = None
    ) -> None:
        """Дополнительная иконка-кнопка справа (например, «открыть в Telegram»)."""
        button.setParent(self)
        self.layout().addWidget(button, 0, Qt.AlignVCenter)
        if handler is not None:
            button.clicked.connect(handler)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._enabled:
            self.setProperty("pressed", "yes")
            self.style().unpolish(self)
            self.style().polish(self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._enabled:
            self.setProperty("pressed", "no")
            self.style().unpolish(self)
            self.style().polish(self)
            if self.rect().contains(event.pos()):
                self.clicked.emit()
        super().mouseReleaseEvent(event)


# ------------------------------------------------------------ точка состояния

class StatusLed(QWidget):
    """Анимированный индикатор состояния (точка у статус-пилюли)."""

    def __init__(self, size: int = 13, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(size + 8, size + 8)
        self._size = size
        self._state = "stopped"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        if state in ("running", "starting", "stopping", "crashed", "error"):
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.05) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        cx, cy = self.width() / 2, self.height() / 2
        r = self._size / 2

        state = self._state
        if state == "running":
            color = QColor(theme.PALETTE["green"])
            # расширяющееся кольцо
            ring = QColor(color)
            ring.setAlphaF((1.0 - self._phase) * 0.45)
            painter.setPen(QPen(ring, 1.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QRectF(cx - r - self._phase * 7, cy - r - self._phase * 7,
                                      2 * (r + self._phase * 7), 2 * (r + self._phase * 7)))
        elif state in ("starting", "stopping"):
            color = QColor(theme.PALETTE["amber"])
            # вращающаяся дуга
            pen = QPen(color, 2.0)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            span = 270 * 16
            start = int(-self._phase * 360 * 16)
            painter.drawArc(QRectF(cx - r - 1, cy - r - 1, 2 * r + 2, 2 * r + 2), start, span)
        elif state in ("crashed", "error"):
            color = QColor(theme.PALETTE["red"])
            blink = 0.45 + 0.55 * abs(math.sin(self._phase * math.pi * 2))
            color.setAlphaF(blink)
        else:
            color = QColor(theme.PALETTE["faint"])

        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        painter.end()


# ------------------------------------------------------------ строка статуса

class StatusRow(QFrame):
    """Строка состояния компонента на главной странице."""

    action_clicked = Signal()

    open_clicked = Signal()

    def __init__(self, title: str, subtitle: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusRow")
        self.setMinimumHeight(74)
        self.setCursor(Qt.PointingHandCursor)
        self._open_callback: Optional[Callable] = None
        self._subtitle_hint = ""
        self._extra_buttons: list = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 14, 12)
        layout.setSpacing(14)

        self.dot = StatusLed(13)
        layout.addWidget(self.dot, 0, Qt.AlignVCenter)

        icon_label = QLabel()
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(
            f"background-color: {theme.PALETTE['surface_alt']};"
            f"border: 1px solid {theme.PALETTE['border']}; border-radius: 11px;"
        )
        icon_label.setPixmap(
            icons.icon_pixmap(icon_name, theme.PALETTE["accent"], 19, 1.9)
        )
        layout.addWidget(icon_label, 0, Qt.AlignVCenter)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self._subtitle_base = subtitle
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("muted")
        texts.addWidget(self.title_label)
        texts.addWidget(self.subtitle_label)
        layout.addLayout(texts, 1)

        self.state_label = QLabel(tr("common.stopped"))
        self.state_label.setObjectName("stateLabel")
        layout.addWidget(self.state_label, 0, Qt.AlignVCenter)

        # дополнительные кнопки (например «открыть в Telegram»)
        self.extra_layout = QHBoxLayout()
        self.extra_layout.setSpacing(6)
        layout.addLayout(self.extra_layout, 0)

        self.action_button = IconButton("play", "", "iconButton", 15)
        self.action_button.setFixedSize(36, 36)
        layout.addWidget(self.action_button, 0, Qt.AlignVCenter)

        # «шестерёнка» — намёк, что строка открывает настройки
        self.open_button = IconButton("gear", "", "iconButton", 14)
        self.open_button.setFixedSize(30, 30)
        self.open_button.setToolTip(tr("dash.row_open_settings"))
        self.open_button.clicked.connect(self._on_open)
        layout.addWidget(self.open_button, 0, Qt.AlignVCenter)

    def set_state(self, status: str, text: Optional[str] = None) -> None:
        self.dot.set_state(status)
        label = text or tr(f"common.{status}")
        self.state_label.setText(label)
        color = theme.status_color(status)
        self.state_label.setStyleSheet(f"color: {color}; font-weight: 650;")
        running = status == "running"
        self.action_button.set_icon("stop" if running else "play")
        self.action_button.setToolTip(tr("common.stop") if running else tr("common.start"))

    def set_action_handler(self, callback: Callable) -> None:
        self._callback = callback
        self.action_button.clicked.connect(self._on_action)

    def _on_action(self) -> None:
        self.action_clicked.emit()
        callback = getattr(self, "_callback", None)
        if callback:
            callback()

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)

    def set_subtitle_hint(self, text: str) -> None:
        """Маленькая подсказка под названием: строка кликабельна."""
        self._subtitle_hint = text
        self._render_subtitle()

    def _render_subtitle(self) -> None:
        base = self._subtitle_base
        if self._subtitle_hint:
            base = f"{base} · {self._subtitle_hint}"
        self.subtitle_label.setText(base)

    def add_extra_button(self, button, callback: Callable) -> None:
        button.setFixedSize(36, 36)
        button.clicked.connect(callback)
        self.extra_layout.addWidget(button, 0, Qt.AlignVCenter)
        self._extra_buttons.append(button)

    def set_open_handler(self, callback: Callable) -> None:
        self._open_callback = callback

    def _on_open(self) -> None:
        self.open_clicked.emit()
        if self._open_callback:
            self._open_callback()

    def mousePressEvent(self, event) -> None:
        """Клик по строке открывает настройки этого запрета."""
        if event.button() == Qt.LeftButton:
            self._on_open()
            event.accept()
            return
        super().mousePressEvent(event)


# ------------------------------------------------------------ журнал

class LogView(QWidget):
    def __init__(
        self,
        title: str = "",
        parent: Optional[QWidget] = None,
        autoscroll: bool = True,
    ):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        if title:
            icon = QLabel()
            icon.setPixmap(icons.icon_pixmap("terminal", theme.PALETTE["muted"], 14, 1.9))
            toolbar.addWidget(icon)
            lbl = QLabel(title)
            lbl.setObjectName("sectionLabel")
            toolbar.addWidget(lbl)
        toolbar.addStretch(1)
        # автопрокрутка — по желанию: там, где журнал читают во время прогона,
        # галочка только мешает (см. страницу «Диагностика»)
        self.autoscroll = QCheckBox(tr("log.autoscroll"))
        self.autoscroll.setChecked(True)
        self.autoscroll.setVisible(bool(autoscroll))
        clear_button = IconButton("trash", "", "iconButton", 13)
        clear_button.setToolTip(tr("log.clear"))
        clear_button.clicked.connect(self.clear)
        toolbar.addWidget(self.autoscroll)
        toolbar.addWidget(clear_button)
        root.addLayout(toolbar)

        self.view = QPlainTextEdit()
        self.view.setObjectName("log")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(4000)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.view.setFont(font)
        root.addWidget(self.view, 1)

    def clear(self) -> None:
        self.view.clear()

    def append(self, text: str) -> None:
        if not text:
            return
        self.view.appendPlainText(text)
        if self.autoscroll.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def append_lines(self, lines) -> None:
        for line in lines:
            self.append(line)


# ------------------------------------------------------------ баннер

class Banner(QFrame):
    """Предупреждение / рекомендация: цветная полоса, иконка, текст, действие."""

    ICONS = {"info": "info", "warning": "alert", "error": "alert", "success": "check-circle"}

    def __init__(self, text: str, kind: str = "info", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 12, 14, 12)
        layout.setSpacing(12)

        self.bar = QFrame()
        self.bar.setFixedWidth(4)
        self.bar.setFixedHeight(22)
        layout.addWidget(self.bar, 0, Qt.AlignVCenter)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(20, 20)
        layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        self.label = QLabel(text)
        self.label.setObjectName("BannerText")
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)

        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        background, line, accent = theme.banner_tint(kind)
        self.setStyleSheet(
            f"QFrame#Banner {{ background-color: {background};"
            f" border: 1px solid {line}; border-radius: 14px; }}"
        )
        self.bar.setStyleSheet(
            f"background-color: {accent}; border-radius: 2px; border: none;"
        )
        self.icon_label.setPixmap(
            icons.icon_pixmap(self.ICONS.get(kind, "info"), accent, 20, 1.9)
        )

    def set_text(self, text: str) -> None:
        self.label.setText(text)
        # пустой баннер не занимает места на странице
        self.setVisible(bool(text))


# ------------------------------------------------------------ форма

class FormRow(QWidget):
    def __init__(self, label: str, widget: QWidget, button: Optional[QPushButton] = None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        lbl = QLabel(label)
        lbl.setObjectName("muted")
        lbl.setMinimumWidth(140)
        layout.addWidget(lbl)
        layout.addWidget(widget, 1)
        if button:
            layout.addWidget(button)


class HintLabel(QLabel):
    """Подпись-подсказка: переносится по словам и не раздувает минимальную ширину.

    Обычный QLabel с wordWrap заставляет layout считаться с шириной всего текста,
    из-за чего панели перестают сжиматься. Политика Ignored это лечит.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        # раньше здесь был objectName «muted» — подсказки выходили ярче и крупнее,
        # чем задумано правилом QLabel#hintLabel ($faint, 9pt). Оно оставалось мёртвым.
        self.setObjectName("hintLabel")
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)


class SectionLabel(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text.upper(), parent)
        self.setObjectName("sectionLabel")


# ------------------------------------------------------------ тост

# ширина уведомления считается по тексту: короткая фраза остаётся одной
# строкой и занимает столько места, сколько нужно
MIN_TOAST_WIDTH = 300
# предел одной строки: длиннее — переносим, а не обрезаем
MAX_TOAST_TEXT = 460
# запас ширины, чтобы текст гарантированно влезал в уведомление
TEXT_SLACK = 16
# одновременно на экране — не больше трёх уведомлений
MAX_VISIBLE_TOASTS = 3
# отступы, промежутки, полоска-метка и иконка вокруг текста
TOAST_CHROME = 12 + 10 + 9 + 3 + 9 + 16 + 9
# минимальная ширина текстовой части, если она переносится
MIN_WRAP_TEXT = 220


class Toast(QFrame):
    """Всплывающее уведомление (правый нижний угол, стеком)."""

    def __init__(self, parent: QWidget, text: str, kind: str = "info",
                 action_text: Optional[str] = None, action_cb: Optional[Callable] = None,
                 duration: int = 4200):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("kind", kind)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 10, 9)
        layout.setSpacing(9)

        # цветная полоса слева — метка типа уведомления
        accent = QFrame(self)
        accent.setObjectName("ToastAccent")
        accent.setFixedSize(3, 16)
        layout.addWidget(accent, 0, Qt.AlignVCenter)

        icon_label = QLabel()
        icon_label.setFixedSize(16, 16)
        color = {
            "info": theme.PALETTE["accent"],
            "warning": theme.PALETTE["amber"],
            "error": theme.PALETTE["red"],
            "success": theme.PALETTE["green"],
        }.get(kind, theme.PALETTE["accent"])
        accent.setStyleSheet("background-color: %s; border-radius: 2px;" % color)
        icon_label.setPixmap(
            icons.icon_pixmap(Banner.ICONS.get(kind, "info"), color, 16, 1.9)
        )
        layout.addWidget(icon_label, 0, Qt.AlignVCenter)

        label = QLabel(text)
        # Шрифт приходит из стиля приложения, а применяется он не сразу:
        # без ensurePolished() текст меряется стандартным шрифтом и потом
        # не влезает — уведомление получалось обрезанным.
        label.ensurePolished()
        layout.addWidget(label, 1)

        action_button = None
        if action_text and action_cb:
            action_button = IconButton("external", action_text, "primary")
            action_button.clicked.connect(lambda: (action_cb(), self.close()))
            layout.addWidget(action_button, 0, Qt.AlignVCenter)

        # Короткий текст остаётся одной строкой — уведомление выходит
        # компактным, а не во всю ширину окна. Длинный переносится.
        natural = QFontMetrics(label.font()).horizontalAdvance(text) + TEXT_SLACK
        available = self._available_width(action_button)
        if natural + TOAST_CHROME > available:
            # в одну строку не влезает — переносим, чтобы ничего не обрезать
            label.setWordWrap(True)
            label.setFixedWidth(max(MIN_WRAP_TEXT, available - TOAST_CHROME))
        else:
            label.setWordWrap(False)
            label.setFixedWidth(natural)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        # итоговая ширина — по факту: layout уже знает все свои виджеты
        layout.activate()
        self.adjustSize()
        self.setFixedWidth(
            min(max(MIN_TOAST_WIDTH, self.width() + TEXT_SLACK), available)
        )
        self.adjustSize()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start(duration)

        if not hasattr(parent, "_toasts"):
            parent._toasts = []
        parent._toasts.append(self)
        self._enforce_limit(parent)
        self._reposition()
        self.raise_()
        self.show()
        anim.appear_from_bottom(self, distance=14, duration=280)

    def mousePressEvent(self, event) -> None:
        """Любой клик по уведомлению закрывает его — крестик не нужен."""
        if event.button() in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
            self._dismiss()
            event.accept()
            return
        super().mousePressEvent(event)

    @staticmethod
    def _enforce_limit(parent: QWidget) -> None:
        """Оставляет не больше MAX_VISIBLE_TOASTS уведомлений: лишние закрываются."""
        toasts = list(getattr(parent, "_toasts", []))
        for extra in toasts[: max(0, len(toasts) - MAX_VISIBLE_TOASTS)]:
            extra.close()

    def _available_width(self, action_button=None) -> int:
        """Место под уведомление: ширина окна минус отступы и кнопка."""
        parent = self.parentWidget()
        room = (parent.width() - 36) if parent is not None else 0
        if action_button is not None:
            room -= action_button.sizeHint().width() + 9
        # даже в крошечном окне уведомление должно оставаться читаемым
        return max(MIN_TOAST_WIDTH, room)

    def _reposition(self) -> None:
        """Правый нижний угол: новые уведомления укладываются стеком вверх."""
        parent = self.parentWidget()
        if parent is None:
            return
        toasts = list(getattr(parent, "_toasts", []))
        y = parent.height() - 18
        for toast in reversed(toasts):
            y -= toast.height() + 8
            x = max(12, parent.width() - toast.width() - 18)
            top = max(12, y)
            if toast.pos() == QPoint(x, top):
                continue
            anim.stop_position_animation(toast)
            toast.move(x, top)
            # если уведомление ещё проявлялось — возвращаем ему непрозрачность
            effect = toast.graphicsEffect()
            if effect is not None and effect.opacity() < 0.99:
                anim.fade_in(toast, duration=200)

    def _dismiss(self) -> None:
        anim.slide_out_to_top(self, distance=16, duration=220)
        QTimer.singleShot(240, self._cleanup)

    def _cleanup(self) -> None:
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "_toasts"):
            try:
                parent._toasts.remove(self)
            except ValueError:
                pass
        self.close()
        self.deleteLater()

    def closeEvent(self, event) -> None:
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "_toasts"):
            try:
                parent._toasts.remove(self)
            except ValueError:
                pass
        super().closeEvent(event)


def show_toast(parent: QWidget, text: str, kind: str = "info",
               action_text: Optional[str] = None, action_cb: Optional[Callable] = None,
               duration: int = 4200) -> "Toast":
    return Toast(parent, text, kind, action_text, action_cb, duration)


# ------------------------------------------------------------ бейдж статуса

class StatusPill(QLabel):
    """Компактный бейдж состояния компонента (работа / стоп / ошибка)."""

    def __init__(self, text: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("pillStopped")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(104)
        self.setMinimumHeight(24)
        self._text = text
        if text:
            self.set_status_text(text)
        else:
            self.set_status("stopped")

    def set_status_text(self, text: str) -> None:
        self.setText(text)

    def set_status(self, status: str, text: Optional[str] = None) -> None:
        self.setObjectName(theme.status_object_name(status))
        if text:
            self.setText(text)
        elif self._text:
            self.setText(self._text)
        else:
            self.setText(tr(f"common.{status}"))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
