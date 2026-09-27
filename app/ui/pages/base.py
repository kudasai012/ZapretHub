"""Базовый класс страницы (с прокруткой — контент никогда не сжимается)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


class BasePage(QWidget):
    def __init__(self, ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        container = QWidget()
        container.setObjectName("PageContainer")
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(2, 2, 6, 2)
        self._layout.setSpacing(12)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        self.scroll = scroll

    def center_content(self) -> None:
        """Располагает контент по центру: свободное место — сверху и снизу."""
        self._layout.insertStretch(0, 1)
        self._layout.addStretch(1)

    def add(self, widget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)

    def add_stretch(self) -> None:
        self._layout.addStretch(1)

    def on_show(self) -> None:
        """Вызывается при переключении на страницу."""

    def retranslate(self) -> None:
        """Вызывается после смены языка (страница может перестроиться)."""
