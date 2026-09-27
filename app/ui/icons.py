"""Профессиональные векторные иконки (стиль Feather/Lucide).

Рисуются кодом через QPainter — никаких внешних файлов и шрифтов,
поэтому иконки всегда доступны и масштабируются без потерь.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

ICON_SIZE = 24  # виртуальный viewBox

_CACHE: Dict[Tuple[str, str, int, float], QIcon] = {}


# ------------------------------------------------------------ помощники

def _pen(p: QPainter, color: QColor, width: float) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


def _polygon(p: QPainter, points, fill: bool = False) -> None:
    from PySide6.QtGui import QPolygonF

    poly = QPolygonF([QPointF(float(x), float(y)) for x, y in points])
    if fill:
        p.setBrush(p.pen().color())
        p.drawPolygon(poly)
        p.setBrush(Qt.NoBrush)
    else:
        p.drawPolyline(poly + QPolygonF([poly[0]]))


def _line(p: QPainter, x1, y1, x2, y2) -> None:
    p.drawLine(QPointF(float(x1), float(y1)), QPointF(float(x2), float(y2)))


def _circle(p: QPainter, cx, cy, r, fill: bool = False) -> None:
    if fill:
        p.setBrush(p.pen().color())
    p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    p.setBrush(Qt.NoBrush)


def _rrect(p: QPainter, x, y, w, h, r=2.0, fill: bool = False) -> None:
    if fill:
        p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)
    p.setBrush(Qt.NoBrush)


def _arc(p: QPainter, cx, cy, r, start_deg: float, span_deg: float) -> None:
    """Дуга: 0° — вправо, положительные углы против часовой (экранные координаты)."""
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    p.drawArc(rect, int(start_deg * 16), int(span_deg * 16))


def _arrow_head(p: QPainter, x, y, direction_deg: float, size: float = 3.2) -> None:
    """Закрашенный треугольник-наконечник стрелки."""
    import math

    ang = math.radians(direction_deg)
    tip = (x + math.cos(ang) * size, y + math.sin(ang) * size)
    left = (
        x + math.cos(ang + 2.5) * size,
        y + math.sin(ang + 2.5) * size,
    )
    right = (
        x + math.cos(ang - 2.5) * size,
        y + math.sin(ang - 2.5) * size,
    )
    _polygon(p, [tip, left, right], fill=True)


# ------------------------------------------------------------ иконки

def _i_grid(p):
    _rrect(p, 3, 3, 7.5, 7.5, 1.6)
    _rrect(p, 13.5, 3, 7.5, 7.5, 1.6)
    _rrect(p, 3, 13.5, 7.5, 7.5, 1.6)
    _rrect(p, 13.5, 13.5, 7.5, 7.5, 1.6)


def _i_shield(p):
    path_pts = [(12, 21.8), (3.8, 18.4), (3.8, 5.4), (12, 2.2), (20.2, 5.4), (20.2, 18.4)]
    _polygon(p, path_pts)


def _i_shield_check(p):
    _i_shield(p)
    _polygon(p, [(8.6, 11.8), (11.1, 14.3), (15.6, 9.3)])


def _i_send(p):
    _polygon(p, [(21.5, 2.5), (14.5, 21.5), (11, 13), (2.5, 9.5)], fill=True)
    _line(p, 21.5, 2.5, 11, 13)


def _i_refresh(p):
    _arc(p, 12, 12, 8.5, 95, 275)
    _arrow_head(p, 19.4, 12, 90)
    _arrow_head(p, 4.6, 12, 270)


def _i_download(p):
    _line(p, 12, 3.5, 12, 15.5)
    _polygon(p, [(7, 11), (12, 16), (17, 11)])
    _polygon(p, [(3.5, 15.5), (3.5, 20), (20.5, 20), (20.5, 15.5)])


def _i_gear(p):
    _circle(p, 12, 12, 3.2)
    _circle(p, 12, 12, 7.6)
    import math

    for i in range(8):
        ang = math.radians(i * 45)
        x1, y1 = 12 + math.cos(ang) * 9.2, 12 + math.sin(ang) * 9.2
        x2, y2 = 12 + math.cos(ang) * 11.6, 12 + math.sin(ang) * 11.6
        _line(p, x1, y1, x2, y2)


def _i_power(p):
    _arc(p, 12, 12.5, 7.5, -55, 250)
    _line(p, 12, 2.5, 12, 11.5)


def _i_square(p):
    _rrect(p, 6, 6, 12, 12, 2.6)


def _i_play(p):
    _polygon(p, [(7.5, 4.5), (19.5, 12), (7.5, 19.5)], fill=True)


def _i_pause(p):
    _line(p, 9, 5.5, 9, 18.5)
    _line(p, 15, 5.5, 15, 18.5)


def _i_folder(p):
    _polygon(p, [(3, 6.5), (9.5, 6.5), (11.8, 9.2), (21, 9.2), (21, 19.5), (3, 19.5)])


def _i_layers(p):
    _polygon(p, [(12, 2.8), (21.5, 7.5), (12, 12.2), (2.5, 7.5)])
    _polygon(p, [(2.5, 12.3), (12, 17), (21.5, 12.3)])
    _polygon(p, [(2.5, 16.9), (12, 21.6), (21.5, 16.9)])


def _i_copy(p):
    _rrect(p, 8.5, 8.5, 12, 12, 2.4)
    _polygon(p, [(4.5, 15.5), (4.5, 4.5), (15.5, 4.5), (15.5, 6.2)])


def _i_external(p):
    _polygon(p, [(14, 3.5), (20.5, 3.5), (20.5, 10)])
    _line(p, 20.5, 3.5, 12.5, 11.5)
    _polygon(p, [(18, 13.5), (18, 19), (5, 19), (5, 6), (10.5, 6)])


def _i_check(p):
    _polygon(p, [(20, 6.5), (9.5, 17), (4, 11.5)])


def _i_check_square(p):
    _rrect(p, 4, 4, 16, 16, 3.4)
    _polygon(p, [(16.6, 8.6), (10.6, 14.6), (7.4, 11.4)])


def _i_check_circle(p):
    _circle(p, 12, 12, 9)
    _polygon(p, [(8.2, 12.2), (11, 15), (16, 9.4)])


def _i_alert(p):
    _polygon(p, [(12, 3.5), (21.5, 19.5), (2.5, 19.5)])
    _line(p, 12, 9.5, 12, 14)
    _circle(p, 12, 17, 0.9, fill=True)


def _i_info(p):
    _circle(p, 12, 12, 9)
    _line(p, 12, 11, 12, 16.5)
    _circle(p, 12, 7.8, 0.9, fill=True)


def _i_minimize(p):
    """Свернуть: горизонтальная черта в рамке окна."""
    _line(p, 5, 12, 19, 12)


def _i_close(p):
    _line(p, 18, 6, 6, 18)
    _line(p, 6, 6, 18, 18)


def _i_trash(p):
    _polygon(p, [(3.5, 6.5), (20.5, 6.5)])
    _polygon(p, [(5.5, 6.5), (6.5, 20), (17.5, 20), (18.5, 6.5)])
    _line(p, 9.5, 6.5, 9.5, 3.8)
    _line(p, 14.5, 6.5, 14.5, 3.8)
    _line(p, 10, 10, 10, 16)
    _line(p, 14, 10, 14, 16)


def _i_clock(p):
    _circle(p, 12, 12, 9)
    _polygon(p, [(12, 6.8), (12, 12), (16, 14)])


def _i_bolt(p):
    _polygon(p, [(13.5, 2.5), (3.5, 13.8), (11.5, 13.8), (10.5, 21.5), (20.5, 10.2), (12.5, 10.2)], fill=True)


def _i_terminal(p):
    _rrect(p, 2.8, 4, 18.4, 16, 2.4)
    _polygon(p, [(7, 9.5), (10.2, 12.4), (7, 15.3)])
    _line(p, 12.5, 15.6, 17, 15.6)


def _i_file(p):
    _polygon(p, [(13.5, 2.8), (13.5, 8.5), (19.5, 8.5), (19.5, 20), (4.5, 20), (4.5, 2.8)])
    _polygon(p, [(13.5, 2.8), (19.5, 8.5), (13.5, 8.5)])
    _line(p, 8, 12.5, 16, 12.5)
    _line(p, 8, 16, 13.5, 16)


def _i_key(p):
    _circle(p, 8, 12, 4.2)
    _line(p, 11.5, 12, 20.5, 12)
    _line(p, 17, 12, 17, 15.5)
    _line(p, 20, 12, 20, 15)


def _i_globe(p):
    _circle(p, 12, 12, 9)
    _line(p, 3, 12, 21, 12)
    _polygon(p, [(12, 3), (7.2, 5.2), (7.2, 18.8), (12, 21)])
    _polygon(p, [(12, 3), (16.8, 5.2), (16.8, 18.8), (12, 21)])


def _i_search(p):
    _circle(p, 10.5, 10.5, 6.8)
    _line(p, 15.6, 15.6, 20.5, 20.5)


def _i_activity(p):
    _polygon(p, [(2.5, 12.5), (7, 12.5), (9.5, 6), (14, 18.5), (16.5, 12.5), (21.5, 12.5)])


def _i_eye(p):
    _polygon(p, [(2.5, 12), (6.8, 6), (17.2, 6), (21.5, 12), (17.2, 18), (6.8, 18)])
    _circle(p, 12, 12, 3)


def _i_settings_sliders(p):
    _line(p, 4, 6.5, 20, 6.5)
    _line(p, 4, 12, 20, 12)
    _line(p, 4, 17.5, 20, 17.5)
    _circle(p, 15, 6.5, 2.6, fill=True)
    _circle(p, 9, 12, 2.6, fill=True)
    _circle(p, 17, 17.5, 2.6, fill=True)


def _i_database(p):
    _polygon(p, [(12, 2.8), (20, 6.2), (20, 12), (12, 15.4), (4, 12), (4, 6.2)])
    _polygon(p, [(4, 12), (12, 15.4), (20, 12)])
    _polygon(p, [(4, 17.6), (12, 21), (20, 17.6)])


def _i_chevron_left(p):
    _polygon(p, [(14.5, 4.5), (6.5, 12), (14.5, 19.5)])


def _i_chevron_right(p):
    _polygon(p, [(9.5, 4.5), (17.5, 12), (9.5, 19.5)])


def _i_chevron_down(p):
    _polygon(p, [(4.5, 9.5), (12, 17.5), (19.5, 9.5)])


ICONS = {
    "grid": _i_grid,
    "shield": _i_shield,
    "shield-check": _i_shield_check,
    "send": _i_send,
    "refresh": _i_refresh,
    "download": _i_download,
    "gear": _i_gear,
    "power": _i_power,
    "stop": _i_square,
    "play": _i_play,
    "pause": _i_pause,
    "folder": _i_folder,
    "layers": _i_layers,
    "copy": _i_copy,
    "external": _i_external,
    "check": _i_check,
    "check-square": _i_check_square,
    "check-circle": _i_check_circle,
    "alert": _i_alert,
    "info": _i_info,
    "close": _i_close,
    "minimize": _i_minimize,
    "trash": _i_trash,
    "clock": _i_clock,
    "bolt": _i_bolt,
    "terminal": _i_terminal,
    "file": _i_file,
    "key": _i_key,
    "globe": _i_globe,
    "search": _i_search,
    "activity": _i_activity,
    "eye": _i_eye,
    "sliders": _i_settings_sliders,
    "database": _i_database,
    "chevron-left": _i_chevron_left,
    "chevron-right": _i_chevron_right,
    "chevron-down": _i_chevron_down,
}


# ------------------------------------------------------------ рендер

def icon_pixmap(
    name: str,
    color: str = "#e8ecf4",
    size: int = 20,
    width: float = 1.8,
    dpr: int = 2,
) -> QPixmap:
    pixmap = QPixmap(size * dpr, size * dpr)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    rect = QRectF(0, 0, size, size)
    painter.translate(rect.center().x(), rect.center().y())
    scale = size / ICON_SIZE
    painter.scale(scale, scale)
    painter.translate(-ICON_SIZE / 2, -ICON_SIZE / 2)
    _pen(painter, QColor(color), width / scale)
    draw = ICONS.get(name, ICONS["info"])
    draw(painter)
    painter.end()
    return pixmap


def get_icon(name: str, color: Optional[str] = None, size: int = 20, width: float = 1.8) -> QIcon:
    color = color or "#e8ecf4"
    key = (name, color, size, width)
    icon = _CACHE.get(key)
    if icon is None:
        icon = QIcon(icon_pixmap(name, color, size, width))
        _CACHE[key] = icon
    return icon


def colored(name: str, theme_color: str, size: int = 20, width: float = 1.8) -> QIcon:
    """Иконка цветом из темы (ключ палитры)."""
    from . import theme

    color = theme.palette_color(theme_color)
    return get_icon(name, color, size, width)
