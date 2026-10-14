"""Единая тёмная тема интерфейса (премиальный веб/Electron-стиль)."""
from __future__ import annotations

import string

from PySide6.QtWidgets import QProxyStyle, QStyle


# минимальная длина бегунка полосы прокрутки, px
MIN_SLIDER = 46


class ScrollbarStyle(QProxyStyle):
    """Полоса прокрутки, бегунок которой не сжимается в одну точку.

    Чем длиннее список, тем короче бегунок — на списках адресов он уходил
    в один пиксель и перестать быть видимым. Здесь у него есть нижний предел,
    при этом пропорция «длиннее список — короче бегунок» сохраняется.
    """

    MIN_SLIDER = MIN_SLIDER

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_ScrollBarSliderMin:
            return self.MIN_SLIDER
        return super().pixelMetric(metric, option, widget)


PALETTE = {
    # фоны
    "bg": "#07090e",
    "bg_top": "#0e1524",
    "bg_bottom": "#06080d",
    "surface": "#101623",
    "surface_alt": "#171f2e",
    "surface_hover": "#1f2939",
    "surface_raise": "#18202f",
    "input_bg": "#0b0f18",
    # границы
    "border": "#232c3d",
    "border_strong": "#35425e",
    # текст
    "text": "#eaeef7",
    "muted": "#8b96ad",
    "faint": "#5d6880",
    # акценты
    "accent": "#5b8cff",
    "accent_hover": "#82a8ff",
    "accent_deep": "#3b6ae0",
    "accent_soft": "rgba(91, 140, 255, 0.14)",
    "accent_line": "rgba(91, 140, 255, 0.35)",
    "accent_text": "#ffffff",
    "green": "#3ecf8e",
    "green_soft": "rgba(62, 207, 142, 0.13)",
    "red": "#ff6b6b",
    "red_soft": "rgba(255, 107, 107, 0.13)",
    "amber": "#ffb84d",
    "amber_soft": "rgba(255, 184, 77, 0.13)",
    "selection": "#2b4a8f",
}

FONT_STACK = '"Inter", "Segoe UI Variable Display", "Segoe UI", "Noto Sans", sans-serif'
MONO_STACK = '"JetBrains Mono", "Cascadia Mono", "Consolas", monospace'

# тинты для предупреждений/рекомендаций: фон, рамка, акцент
BANNER_TINTS = {
    "info": ("accent_soft", "accent_line", "accent"),
    "warning": ("amber_soft", "rgba(255, 184, 77, 0.35)", "amber"),
    "error": ("red_soft", "rgba(255, 107, 107, 0.35)", "red"),
    "success": ("green_soft", "rgba(62, 207, 142, 0.35)", "green"),
}

_TEMPLATE = string.Template(
    """
* {
    font-family: $font_stack;
    font-size: 10pt;
    color: $text;
}

QWidget {
    background-color: transparent;
}

QMainWindow {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $bg_top, stop: 1 $bg_bottom);
}

QDialog {
    background-color: $bg;
}

QToolTip {
    background-color: $surface;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 10px;
    padding: 7px 10px;
}

/* ---------------- боковая панель ---------------- */

/* панель «приклеена» к окну: своего фона и рамки нет,
   отделена только тонкой вертикальной линией */
QWidget#Sidebar {
    background-color: transparent;
    border: none;
    border-radius: 0px;
}
QFrame#VLine {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(255, 255, 255, 0.0),
        stop: 0.5 rgba(255, 255, 255, 0.11),
        stop: 1 rgba(255, 255, 255, 0.0));
    border: none;
    min-width: 1px;
    max-width: 1px;
}
QLabel#BrandTitle { font-size: 12pt; font-weight: 700; color: $text; }
QLabel#BrandSub { color: $faint; font-size: 8pt; }
QLabel#BrandIcon {
    background: transparent;
    border: none;
    color: $accent;
    font-size: 10pt;
    font-weight: 700;
}
QPushButton#SidebarToggle {
    color: $muted;
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 0px;
}
QPushButton#SidebarToggle:hover {
    color: $text;
    background-color: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.12);
}

QListWidget#Nav {
    background-color: transparent;
    border: none;
    outline: none;
    font-size: 11pt;
}
QListWidget#Nav::item {
    padding: 13px 16px;
    border-radius: 12px;
    color: $muted;
    margin: 2px 0;
    border: 1px solid transparent;
    background-color: transparent;
}
QListWidget#Nav::item:hover:!selected {
    background-color: rgba(255, 255, 255, 0.05);
    color: $text;
    border-color: rgba(255, 255, 255, 0.10);
}
QListWidget#Nav::item:selected {
    background-color: rgba(255, 255, 255, 0.08);
    color: $text;
    border-color: rgba(255, 255, 255, 0.16);
    border-left: 3px solid $accent;
    padding-left: 13px;
    font-weight: 650;
}

/* ---------------- карточки и панели ---------------- */

QFrame#Card {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $surface_raise, stop: 1 $surface);
    border: 1px solid $border;
    border-radius: 18px;
}
QFrame#Card:hover { border-color: $border_strong; }
QFrame#CardFlat {
    background-color: $surface_alt;
    border: 1px solid $border;
    border-radius: 16px;
}
QFrame#Panel {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $surface_raise, stop: 1 $surface);
    border: 1px solid $border;
    border-radius: 18px;
}
QFrame#Panel[flash="yes"] {
    border-color: $accent;
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $accent_soft, stop: 1 $surface);
}
QFrame#StatusRow {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 16px;
}
QFrame#StatusRow:hover { background-color: $surface_alt; }
QFrame#StatusRow:hover { border-color: $border_strong; }

QGroupBox {
    background-color: $surface_alt;
    border: 1px solid $border;
    border-radius: 14px;
    margin-top: 16px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 1px;
    padding: 3px 10px;
    color: $muted;
    font-weight: 700;
    font-size: 8.5pt;
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 8px;
}

QSplitter#PanelSplitter::handle {
    background-color: transparent;
    width: 10px;
}
QSplitter#PanelSplitter::handle:horizontal {
    image: none;
    background-color: $border;
    border-radius: 1px;
    margin: 40px 4px;
}
QSplitter#PanelSplitter::handle:horizontal:hover { background-color: $accent; }

/* ---------------- текст ---------------- */

QLabel#h1 { font-size: 22pt; font-weight: 700; color: $text; }
QLabel#h2 { font-size: 13pt; font-weight: 650; color: $text; }
QLabel#cardTitle { font-size: 12pt; font-weight: 650; color: $text; }
QLabel#muted { color: $muted; }
QLabel#sectionLabel { color: $faint; font-size: 8.5pt; font-weight: 700; }
QLabel#hintLabel { color: $faint; font-size: 9pt; }
QLabel#stateLabel { font-weight: 650; }
QLabel#rowTitle { font-size: 10.5pt; font-weight: 650; color: $text; }
QLabel#statValue { font-size: 16pt; font-weight: 700; color: $text; }
QLabel#statLabel { color: $faint; font-size: 8pt; font-weight: 700; }

/* ---------------- кнопки: плоские, без заливки ---------------- */

QPushButton {
    background-color: transparent;
    color: $muted;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 8px 15px;
    font-weight: 600;
}
QPushButton:focus {
    border-color: rgba(91, 140, 255, 0.45);
    color: $text;
}
QPushButton:hover {
    background-color: rgba(255, 255, 255, 0.05);
    color: $text;
    border-color: rgba(255, 255, 255, 0.10);
}
QPushButton:pressed {
    background-color: rgba(255, 255, 255, 0.10);
    color: $text;
    border-color: rgba(255, 255, 255, 0.14);
}
QPushButton:disabled { color: $faint; background-color: transparent; border-color: transparent; }

/* главное действие: акцентный текст + тонкая акцентная линия снизу */
QPushButton#primary {
    background-color: transparent;
    color: $accent_hover;
    border: 1px solid rgba(91, 140, 255, 0.30);
    border-bottom: 2px solid rgba(91, 140, 255, 0.55);
    border-radius: 11px;
    font-weight: 650;
}
QPushButton#primary:hover {
    background-color: rgba(91, 140, 255, 0.10);
    color: #c3d6ff;
    border-color: rgba(130, 168, 255, 0.55);
    border-bottom: 2px solid rgba(130, 168, 255, 0.90);
}
QPushButton#primary:pressed {
    background-color: rgba(91, 140, 255, 0.18);
    color: #ffffff;
}
QPushButton#primary:disabled {
    background-color: transparent;
    color: $faint;
    border-color: $border;
    border-bottom: 2px solid $border;
}

QPushButton#ghost {
    background-color: transparent;
    border: 1px solid transparent;
    color: $muted;
}
QPushButton#ghost:hover {
    color: $text;
    background-color: rgba(255, 255, 255, 0.05);
    border-color: rgba(255, 255, 255, 0.10);
}

/* ---------------- стеклянная кнопка (как карточки обхода) ----------

   Тот же приём, что у BypassCard: полупрозрачная заливка + тонкая
   светлая рамка. Выглядит «стеклом» поверх тёмного фона окна и одинаково
   хорошо читается в настройках, компонентах и диагностике. */
QPushButton#glass {
    background-color: rgba(255, 255, 255, 0.045);
    border: 1px solid rgba(255, 255, 255, 0.11);
    border-radius: 13px;
    padding: 8px 16px;
    color: $text;
    font-weight: 650;
}
QPushButton#glass:hover {
    background-color: rgba(255, 255, 255, 0.085);
    border-color: rgba(255, 255, 255, 0.22);
}
QPushButton#glass:pressed {
    background-color: rgba(255, 255, 255, 0.04);
    border-color: rgba(255, 255, 255, 0.14);
}
QPushButton#glass:disabled {
    background-color: rgba(255, 255, 255, 0.02);
    border-color: rgba(255, 255, 255, 0.06);
    color: $faint;
}

/* акцентное стекло: та же основа, но синяя рамка и синый текст */
QPushButton#glassPrimary {
    background-color: rgba(91, 140, 255, 0.10);
    border: 1px solid rgba(130, 168, 255, 0.42);
    border-radius: 13px;
    padding: 8px 16px;
    color: #c3d6ff;
    font-weight: 650;
}
QPushButton#glassPrimary:hover {
    background-color: rgba(91, 140, 255, 0.17);
    border-color: rgba(130, 168, 255, 0.72);
    color: #e2ecff;
}
QPushButton#glassPrimary:pressed {
    background-color: rgba(91, 140, 255, 0.24);
    color: #ffffff;
}
QPushButton#glassPrimary:disabled {
    background-color: rgba(255, 255, 255, 0.02);
    border-color: rgba(255, 255, 255, 0.06);
    color: $faint;
}

/* опасное стекло: красная рамка, для «Удалить программу» и «Закрыть» */
QPushButton#glassDanger {
    background-color: rgba(255, 107, 107, 0.08);
    border: 1px solid rgba(255, 107, 107, 0.35);
    border-radius: 13px;
    padding: 8px 16px;
    color: #ff9b9b;
    font-weight: 650;
}
QPushButton#glassDanger:hover {
    background-color: rgba(255, 107, 107, 0.16);
    border-color: rgba(255, 107, 107, 0.68);
    color: #ffc4c4;
}
QPushButton#glassDanger:pressed {
    background-color: rgba(255, 107, 107, 0.24);
    color: #ffffff;
}
QPushButton#glassDanger:disabled {
    background-color: rgba(255, 255, 255, 0.02);
    border-color: rgba(255, 255, 255, 0.06);
    color: $faint;
}

/* иконка-кнопка: только значок, подсветка при наведении */
QPushButton#iconButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 11px;
    padding: 6px;
}
QPushButton#iconButton:hover {
    background-color: rgba(255, 255, 255, 0.07);
    border-color: rgba(255, 255, 255, 0.12);
}
/* ---------------- всплывающие уведомления ---------------- */

QFrame#Toast {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 rgba(38, 48, 66, 0.98), stop: 1 rgba(24, 31, 44, 0.98));
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 15px;
}
QFrame#Toast QLabel { color: $text; background: transparent; }

QFrame#InstallPlaceholder {
    background-color: rgba(255, 255, 255, 0.02);
    border: 1px dashed rgba(255, 255, 255, 0.16);
    border-radius: 18px;
    margin: 16px;
}

/* ---------------- кнопки обхода ---------------- */

QFrame#BypassCard {
    background-color: rgba(255, 255, 255, 0.035);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 18px;
}
QFrame#BypassCard:hover {
    background-color: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.20);
}
QFrame#BypassCard[pressed="yes"] {
    background-color: rgba(255, 255, 255, 0.03);
    border-color: rgba(255, 255, 255, 0.14);
}
QFrame#BypassCard[error="yes"] {
    border-color: rgba(245, 183, 74, 0.55);
    background-color: rgba(245, 183, 74, 0.12);
}
QFrame#BypassCard[error="yes"]:hover {
    border-color: rgba(245, 183, 74, 0.80);
    background-color: rgba(245, 183, 74, 0.18);
}
QFrame#BypassCard[running="yes"] {
    border-color: rgba(62, 214, 152, 0.45);
    background-color: rgba(62, 214, 142, 0.10);
}
QFrame#BypassCard[running="yes"]:hover {
    border-color: rgba(62, 214, 152, 0.70);
    background-color: rgba(62, 214, 152, 0.16);
}
QLabel#bypassIcon {
    background-color: transparent;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 13px;
    padding: 8px;
}
QLabel#bypassTitle { color: $text; font-size: 11pt; font-weight: 650; }
QFrame#BypassBadge {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 8px;
}
QLabel#BypassBadgeLabel {
    color: $faint;
    font-size: 7.5pt;
    font-weight: 600;
    background: transparent;
}
QLabel#BypassBadgeValue {
    color: $text;
    font-size: 7.5pt;
    font-weight: 700;
    background: transparent;
}
QFrame#BypassCard[running="yes"] QLabel#BypassBadgeValue { color: $green; }
QFrame#BypassCard[error="yes"] QLabel#BypassBadgeValue { color: $amber; }
QPushButton#bypassToggle {
    background-color: transparent;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 19px;
    padding: 0px;
}
QPushButton#bypassToggle:hover {
    background-color: rgba(255, 255, 255, 0.10);
    border-color: rgba(255, 255, 255, 0.30);
}
QPushButton#bypassToggle:pressed {
    background-color: rgba(255, 255, 255, 0.16);
    border-color: rgba(255, 255, 255, 0.30);
}
QPushButton#bypassGear {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 5px;
}
QPushButton#bypassGear:hover {
    background-color: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.14);
}

/* ---------------- диагностика: журнал одной стратегии ---------- */

/* строка-заголовок списка стратегий */
QWidget#SectionBar {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
}
QLabel#sectionTitle {
    color: $text;
    font-size: 11pt;
    font-weight: 700;
    background: transparent;
}

/* ---------------- диагностика: карточка текущей проверки ---------- */

QFrame#LiveCard {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $accent_soft, stop: 1 $surface);
    border: 1px solid $accent;
    border-radius: 18px;
}
QFrame#LiveCard[mode="best"] {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $green_soft, stop: 1 $surface);
    border: 1px solid $green;
}
/* проверять нечем: причина названа прямо, а не «нет доступа» в каждой строке */
QFrame#LiveCard[mode="fail"] {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $red_soft, stop: 1 $surface);
    border: 1px solid rgba(255, 107, 107, 0.55);
}

/* предупреждение о правах администратора на странице диагностики */
QFrame#AdminBanner {
    background-color: rgba(255, 184, 77, 0.09);
    border: 1px solid rgba(255, 184, 77, 0.38);
    border-radius: 16px;
}
QProgressBar#LiveBar {
    background-color: rgba(255, 255, 255, 0.06);
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}
QProgressBar#LiveBar::chunk {
    background-color: $accent;
    border-radius: 3px;
}

/* прогресс всего прогона в карточке «Автоподбор стратегии» */
QProgressBar#RunProgress {
    background-color: rgba(255, 255, 255, 0.07);
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}
QProgressBar#RunProgress::chunk {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 $accent_deep, stop: 1 $accent_hover);
    border-radius: 3px;
}

/* описание релиза в окне обновления программы */
QTextBrowser#ReleaseNotes {
    background-color: rgba(0, 0, 0, 0.24);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 10px 12px;
    color: #c9d2e4;
}
QTextBrowser#ReleaseNotes QScrollBar:vertical { margin: 4px 2px; }

QPlainTextEdit#TargetsEdit {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid $border;
    border-radius: 12px;
    padding: 6px 10px;
    color: $text;
    font-family: $mono_stack;
    font-size: 10pt;
    selection-background-color: $accent;
}
QPlainTextEdit#TargetsEdit:focus {
    border-color: $accent;
    background-color: rgba(255, 255, 255, 0.05);
}

/* ---------------- статус обходов в боковом меню ----------------

   Раньше здесь был полукруг с пузырьками. Он не помещался в панель,
   обрезался, и вместо купола виднелись только бледное пятно и пара
   кругов по бокам. Оставлена только суть: точка и подпись. */
QFrame#StatusDot {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#StatusDot[on="yes"] {
    background-color: rgba(62, 207, 142, 0.09);
    border-color: rgba(62, 207, 142, 0.35);
}
QFrame#StatusDotMark {
    border-radius: 5px;
    border: none;
}
QFrame#StatusDotMark[on="no"] { background-color: $faint; }
QFrame#StatusDotMark[on="yes"] { background-color: $green; }
QLabel#StatusDotText { color: $muted; background: transparent; }
QLabel#StatusDotText { font-weight: 600; }

/* ---------------- диагностика: строки стратегий ---------------- */

QFrame#StrategyRow {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 16px;
}
QFrame#StrategyRow:hover {
    background-color: $surface_alt;
    border-color: $border_strong;
}
QFrame#StrategyRow[busy="yes"] {
    background-color: $surface;
    border-color: $border;
}
/* стратегия проверяется прямо сейчас — та же голубая рамка,
   что у карточки «сейчас проверяется» */
QFrame#StrategyRow[active="yes"] {
    border-color: $accent;
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 $accent_soft, stop: 1 $surface);
}
/* стратегия не проверялась в этом прогоне: серая строка с прочерком.
   Не красная: это не провал, стратегия просто не запускалась. */
QFrame#StrategyRow[untested="yes"] {
    border-color: $border;
    background-color: rgba(255, 255, 255, 0.02);
}
QFrame#StrategyRow[untested="yes"]:hover {
    border-color: $border_strong;
}
QFrame#StrategyRow[untested="yes"] QLabel#rowTitle {
    color: $faint;
}
QFrame#StrategyRow[untested="yes"] QLabel#muted {
    color: $faint;
}
/* стратегию отметили галочкой — рамка и лёгкий синий фон */
QFrame#StrategyRow[picked="yes"] {
    border-color: rgba(130, 168, 255, 0.45);
    background-color: rgba(91, 140, 255, 0.06);
}
QFrame#StrategyRow[picked="yes"]:hover {
    border-color: rgba(130, 168, 255, 0.70);
}
/* лучшая стратегия — зелёная рамка */
QFrame#StrategyRow[selected="yes"] {
    border-color: rgba(62, 214, 152, 0.55);
    background-color: rgba(62, 214, 142, 0.09);
}
QFrame#StrategyRow[selected="yes"]:hover {
    border-color: rgba(62, 214, 152, 0.80);
}

/* квадратный чекбокс: штатный индикатор, стилизованный через QSS.

   Индикатор нарисован не вручную, а взят у стиля — поэтому он всегда на
   своём месте, нужного размера и, главное, кликабельный. Раньше квадрат
   рисовался сам по себе, а штатный индикатор прятался нулевым размером:
   квадрат был виден, но щёлчок по нему не срабатывал, и он уезжал под
   текст. Галочку внутри рисует код (QSS не умеет data:-URI). */
QCheckBox[check="yes"] {
    background: transparent;
    spacing: 9px;
    color: $text;
}
QCheckBox[check="yes"]::indicator {
    width: 17px;
    height: 17px;
    border: 1.5px solid $border_strong;
    border-radius: 5px;
    background-color: $input_bg;
}
QCheckBox[check="yes"]::indicator:hover {
    border-color: $accent;
}
QCheckBox[check="yes"]::indicator:checked {
    background-color: $accent;
    border-color: $accent;
}
QCheckBox[check="yes"]::indicator:unchecked {
    background-color: $input_bg;
}
QCheckBox[check="yes"]:disabled {
    color: $faint;
}
QCheckBox[check="yes"]::indicator:disabled {
    border-color: $border;
    background-color: rgba(255, 255, 255, 0.02);
}

QPlainTextEdit#StrategyLogView {
    background-color: rgba(0, 0, 0, 0.28);
    border: 1px solid $border;
    border-radius: 10px;
    padding: 6px 8px;
    color: $muted;
    selection-background-color: $accent;
}

QLabel#StrategyRank {
    color: $faint;
    font-size: 11pt;
    font-weight: 700;
    background: transparent;
}
QLabel#StrategyRank[best="yes"] { color: $green; }
QLabel#StrategyRank[untested="yes"] {
    color: $faint;
    font-size: 12pt;
}
QWidget#ResultBar {
    background-color: rgba(255, 255, 255, 0.05);
    border-radius: 3px;
}

/* ---------------- поля ввода ---------------- */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: $input_bg;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 7px 10px;
    selection-background-color: $selection;
}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover { border-color: $border_strong; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:read-only { color: $muted; background-color: $surface_alt; }

/* место под стрелку (её рисует PickComboBox), родная стрелка спрятана */
QComboBox::drop-down {
    width: 24px;
    border: none;
}
/* Выпадающий список комбо — отдельное окно. Без скруглённой маски
   (её ставит PickComboBox.showPopup) по углам видно квадратный фон,
   хотя сама рамка скруглена. Фон жёлоба здесь не рисуем: его задаёт
   прозрачный фон popup-окна. */
QComboBox QAbstractItemView {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #1b2434, stop: 1 #131a27);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 13px;
    padding: 6px;
    outline: none;
    selection-background-color: rgba(91, 140, 255, 0.30);
    selection-color: #ffffff;
}
QComboBox QAbstractItemView::scroller { border-radius: 13px; }
QComboBox QAbstractItemView::item {
    border-radius: 9px;
    padding: 8px 11px;
    margin: 1px 0px;
    color: $text;
    min-height: 22px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: rgba(255, 255, 255, 0.07);
    color: #ffffff;
}
QComboBox QAbstractItemView::item:selected {
    background-color: rgba(91, 140, 255, 0.30);
    color: #ffffff;
}

QCheckBox, QRadioButton { spacing: 9px; }
QCheckBox::indicator, QRadioButton::indicator { width: 17px; height: 17px; }
QRadioButton::indicator {
    border: 1px solid $border_strong;
    border-radius: 9px;
    background-color: $input_bg;
}
QRadioButton::indicator:hover { border-color: $accent; }
QRadioButton::indicator:checked {
    background-color: $accent;
    border-color: $accent_hover;
}
QCheckBox::indicator {
    border: 1px solid $border_strong;
    border-radius: 5px;
    background-color: $input_bg;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent_hover;
    image: none;
}

QProgressBar {
    background-color: $input_bg;
    border: 1px solid $border;
    border-radius: 11px;
    text-align: center;
    color: $text;
    font-weight: 650;
    font-size: 9pt;
    min-height: 22px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 $accent_deep, stop: 1 $accent_hover);
    border-radius: 10px;
    margin: 1px;
}

/* ---------------- прокрутка ---------------- */

QScrollArea { background-color: transparent; border: none; }

/* Полоса прокрутки: жёлоб и бегунок скруглены по краям, бегунок —
   капсула. Ширина 10px, чтобы его было проще схватить мышью. */
QScrollBar:vertical {
    background: rgba(255, 255, 255, 0.04);
    width: 10px;
    margin: 3px 3px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: $border_strong;
    border-radius: 5px;
    /* бегунок не сжимается в точку на длинных списках */
    min-height: 46px;
}
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::handle:vertical:pressed { background: $accent; }
QScrollBar:horizontal {
    background: rgba(255, 255, 255, 0.04);
    height: 10px;
    margin: 3px 3px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: $border_strong;
    border-radius: 5px;
    min-width: 46px;
}
QScrollBar::handle:horizontal:hover { background: $muted; }
QScrollBar::handle:horizontal:pressed { background: $accent; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* Список адресов TgWsProxy и подобные длинные списки: там бегунок
   особенно легко уходил в пиксель. Держим его крупным всегда. */
QPlainTextEdit QScrollBar::handle:vertical,
QTextEdit QScrollBar::handle:vertical,
QListWidget QScrollBar::handle:vertical,
QListView QScrollBar::handle:vertical {
    min-height: 56px;
}

/* ---------------- статусные пилюли ---------------- */

QLabel#pillRunning {
    background-color: $green_soft;
    color: $green;
    border: 1px solid rgba(62, 207, 142, 0.35);
    border-radius: 11px;
    padding: 4px 11px;
    font-weight: 650;
    font-size: 8.5pt;
}
QLabel#pillStopped {
    background-color: $surface_alt;
    color: $muted;
    border: 1px solid $border;
    border-radius: 11px;
    padding: 4px 11px;
    font-weight: 650;
    font-size: 8.5pt;
}
QLabel#pillWarn {
    background-color: $amber_soft;
    color: $amber;
    border: 1px solid rgba(255, 184, 77, 0.35);
    border-radius: 11px;
    padding: 4px 11px;
    font-weight: 650;
    font-size: 8.5pt;
}
QLabel#pillError {
    background-color: $red_soft;
    color: $red;
    border: 1px solid rgba(255, 107, 107, 0.35);
    border-radius: 11px;
    padding: 4px 11px;
    font-weight: 650;
    font-size: 8.5pt;
}

/* ---------------- предупреждения и рекомендации ---------------- */

QFrame#Banner {
    border-radius: 14px;
    border: 1px solid $border;
    background-color: $surface_alt;
}
QFrame#Banner QLabel#BannerText { color: $text; }

/* ---------------- тосты ---------------- */

QFrame#Toast {
    background-color: $surface;
    border: 1px solid $accent_line;
    border-radius: 16px;
}

QDialog#UpdateDialog {
    background-color: $bg;
    border: 1px solid $border;
    border-radius: 18px;
}
"""
)


def stylesheet() -> str:
    return _TEMPLATE.substitute(
        {**PALETTE, "font_stack": FONT_STACK, "mono_stack": MONO_STACK}
    )


def palette_color(key: str) -> str:
    return PALETTE.get(key, PALETTE["text"])


def banner_tint(kind: str) -> tuple[str, str, str]:
    """(фон, рамка, акцент) для предупреждения."""
    bg_key, line, accent_key = BANNER_TINTS.get(kind, BANNER_TINTS["info"])
    return PALETTE[bg_key], line, PALETTE[accent_key]


def status_color(status: str) -> str:
    if status == "running":
        return PALETTE["green"]
    if status in ("starting", "stopping"):
        return PALETTE["amber"]
    if status in ("crashed", "error"):
        return PALETTE["red"]
    return PALETTE["muted"]


def status_object_name(status: str) -> str:
    if status == "running":
        return "pillRunning"
    if status in ("starting", "stopping"):
        return "pillWarn"
    if status in ("crashed", "error"):
        return "pillError"
    return "pillStopped"
