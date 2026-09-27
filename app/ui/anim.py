"""Анимации интерфейса: кроссфейд страниц, появление, пульс, тосты."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QTimer,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


# ------------------------------------------------------------ эффекты

def _opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    return effect


def fade_in(widget: QWidget, duration: int = 240, start: float = 0.0, end: float = 1.0):
    effect = _opacity_effect(widget)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    return anim


def fade_out(widget: QWidget, duration: int = 180, on_finished: Optional[Callable] = None):
    effect = _opacity_effect(widget)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    if on_finished:
        anim.finished.connect(on_finished)
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    return anim


def crossfade(stack, index: int, duration: int = 200):
    """Плавный переход между страницами QStackedWidget.

    Текущая страница растворяется, затем проявляется новая — эффект
    «растворения», а не затемнения всего стека.
    """
    if stack.currentIndex() == index:
        return None
    old_page = stack.currentWidget()
    new_page = stack.widget(index)
    if old_page is None or new_page is None:
        stack.setCurrentIndex(index)
        return None

    def _fade(widget: QWidget, start: float, end: float, on_finished=None):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _cleanup() -> None:
            widget.setGraphicsEffect(None)
            if on_finished:
                on_finished()

        anim.finished.connect(_cleanup)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        return anim

    _fade(old_page, 1.0, 0.0)
    # Запоминаем цель: если пользователь успел переключиться дальше, отложенный
    # показ уже не нужен — иначе стек возвращался бы на прошлую страницу.
    stack._crossfade_target = index
    QTimer.singleShot(duration, lambda: _reveal())

    def _reveal() -> None:
        if getattr(stack, "_crossfade_target", None) != index:
            return
        stack.setCurrentIndex(index)
        _fade(new_page, 0.0, 1.0)

    return None


def appear_from_bottom(widget: QWidget, distance: int = 16, duration: int = 280):
    """Появление снизу вверх (только для виджетов вне layout — например тостов)."""
    effect = _opacity_effect(widget)
    opacity = QPropertyAnimation(effect, b"opacity", widget)
    opacity.setDuration(duration)
    opacity.setStartValue(0.0)
    opacity.setEndValue(1.0)
    opacity.setEasingCurve(QEasingCurve.OutCubic)

    start_pos = widget.pos() + QPoint(0, distance)
    move = QPropertyAnimation(widget, b"pos", widget)
    move.setDuration(duration)
    move.setStartValue(start_pos)
    move.setEndValue(widget.pos())
    move.setEasingCurve(QEasingCurve.OutCubic)

    group = QParallelAnimationGroup(widget)
    group.addAnimation(opacity)
    group.addAnimation(move)
    group.start(QAbstractAnimation.DeleteWhenStopped)
    return group


def slide_out_to_top(widget: QWidget, distance: int = 18, duration: int = 220):
    effect = _opacity_effect(widget)
    opacity = QPropertyAnimation(effect, b"opacity", widget)
    opacity.setDuration(duration)
    opacity.setStartValue(1.0)
    opacity.setEndValue(0.0)
    opacity.setEasingCurve(QEasingCurve.InCubic)

    move = QPropertyAnimation(widget, b"pos", widget)
    move.setDuration(duration)
    move.setStartValue(widget.pos())
    move.setEndValue(widget.pos() - QPoint(0, distance))
    move.setEasingCurve(QEasingCurve.InCubic)

    group = QParallelAnimationGroup(widget)
    group.addAnimation(opacity)
    group.addAnimation(move)
    group.start(QAbstractAnimation.DeleteWhenStopped)
    return group


def grow_width(widget: QWidget, start: int, end: int, duration: int = 260):
    anim = QPropertyAnimation(widget, b"maximumWidth", widget)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    return anim


def stop_position_animation(widget: QWidget) -> None:
    """Останавливает анимации виджета, иначе они перебивают move().

    Анимации appear_from_bottom/slide_out_to_top собраны в группы-дети
    виджета, поэтому гасим и сами группы, и вложенные анимации.
    """
    from PySide6.QtCore import QAbstractAnimation

    def _walk(node) -> None:
        for child in node.children():
            if isinstance(child, QAbstractAnimation):
                child.stop()
            _walk(child)

    _walk(widget)


def animate_property(
    target: QWidget,
    name: bytes,
    start: float,
    end: float,
    duration: int = 260,
    easing=QEasingCurve.OutCubic,
) -> QPropertyAnimation:
    anim = QPropertyAnimation(target, name, target)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(easing)
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    return anim
