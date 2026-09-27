"""Единственное место, откуда берётся иконка Zapret Hub.

Раньше иконка искалась только файлом ``assets/icon.ico`` рядом с exe.
Если файла не оказывалось (например, программа запускалась из ``dist\\``
без папки ``assets``, или её снес антивирус), в трее появлялась
нарисованная программно «молния» — и после перезагрузки компьютера она
оставалась там навсегда, потому что Windows запоминает иконку трея.

Теперь иконка вшита в сам исполняемый файл как ресурс Qt
(``app/assets.qrc`` -> ``app/resources_rc.py``) и доступна всегда, даже
если рядом с программой нет ни одного файла. Порядок такой:

1. встроенный ресурс ``:/zapret/icon.ico`` — работает всегда;
2. файл ``assets/icon.ico`` — если программу распаковали вручную;
3. иконка, нарисованная кодом — только если ресурс не скомпилировался.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator, Optional

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap

from .. import paths

#: путь иконки внутри скомпилированного ресурса Qt
RESOURCE_ICON = ":/zapret/icon.ico"

_RESOURCE_READY = False


def _ensure_resource() -> bool:
    """Импортирует сгенерированный модуль ресурса (один раз)."""
    global _RESOURCE_READY
    if _RESOURCE_READY:
        return True
    try:
        from .. import resources_rc as _resources_rc  # noqa: F401  (регистрирует ресурс)
    except Exception:  # noqa: BLE001 - ресурс мог не скомпилироваться
        return False
    _RESOURCE_READY = True
    del _resources_rc
    return True


def _file_candidates(*names: str) -> Iterator[Path]:
    """Файлы иконки: сначала внутрь onefile-сборки, потом папка программы."""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(paths.BASE_DIR)
    for root in roots:
        for name in names:
            candidate = root / "assets" / name
            if candidate.exists():
                yield candidate


def _drawn_icon() -> QIcon:
    """Запасной вариант: рисуем «молнию» кодом."""
    from . import theme
    from .icons import icon_pixmap

    return QIcon(icon_pixmap("bolt", theme.PALETTE["accent"], 64, 2.0))


def app_icon() -> QIcon:
    """Иконка программы: встроенный ресурс, затем файл, затем рисунок."""
    if _ensure_resource():
        icon = QIcon(RESOURCE_ICON)
        if not icon.isNull():
            return icon
    for candidate in _file_candidates("icon.ico", "icon.png"):
        icon = QIcon(str(candidate))
        if not icon.isNull():
            return icon
    return _drawn_icon()


def app_pixmap(size: int = 256) -> Optional[QPixmap]:
    """Пиксмап иконки нужного размера (сайдбар, «О программе»)."""
    icon = app_icon()
    pixmap = icon.pixmap(icon.actualSize(QSize(size, size)))
    if pixmap.isNull():
        pixmap = icon.pixmap(size, size)
    return None if pixmap.isNull() else pixmap


def icon_path() -> Optional[Path]:
    """Путь к файлу иконки на диске — нужен установщику и «О программе»."""
    for candidate in _file_candidates("icon.ico", "icon.png"):
        return candidate
    return None


def apply_app_icon(qt_app) -> None:
    """Ставит иконку на QApplication: окно, панель задач, трей, уведомления."""
    try:
        icon = app_icon()
        if not icon.isNull():
            qt_app.setWindowIcon(icon)
    except Exception:  # noqa: BLE001
        pass
