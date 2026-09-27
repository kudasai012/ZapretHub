"""Страница диагностики: перебор всех general*.bat и выбор лучшей стратегии."""
from __future__ import annotations

import html
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...config import LEGACY_DIAG_TARGETS
from ...core.strategy_test import (
    SLOW_MS,
    StrategyResult,
    StrategyTester,
    default_target_lines,
    parse_targets,
    rank,
)
from ...i18n import tr
from .. import icons, theme
from ..widgets import (
    Banner,
    HintLabel,
    IconButton,
    LogView,
    StatusPill,
    show_toast,
)
from .base import BasePage

WAIT, RUN, DONE, FAIL = "wait", "run", "done", "fail"

# подписи исходов проверки: по ним журнал раскрашивает строки
FAIL_MARKERS = (
    "нет ответа",
    "пропущено",
    "ошибка ssl",
    "не поддержан",
    "сбой проверки",
)

# цвета графика проверок: быстрый ответ, медленный ответ, нет ответа
BAR_COLORS = {"ok": "green", "slow": "amber", "fail": "red"}


class ResultBar(QWidget):
    """График проверок одной стратегии: по отрезку на каждый ответ.

    Каждая проверка занимает свою долю ширины, поэтому полоска показывает
    не только «сколько получилось», но и «где» стратегия подводит: обрывы
    чередуются с ответами, если сайт «мигает».
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ResultBar")
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setVisible(False)
        self._states: List[str] = []

    def set_states(self, states: Sequence[str]) -> None:
        """Задаёт состояния проверок по порядку: ok / slow / fail."""
        self._states = [state for state in states if state in BAR_COLORS]
        self.setVisible(bool(self._states))
        self.update()

    def clear(self) -> None:
        self._states = []
        self.setVisible(False)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D102 - рисование Qt
        if not self._states:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        total = len(self._states)
        gap = 1.0 if total > 1 else 0.0
        width = max(1.0, (rect.width() - gap * (total - 1)) / total)
        radius = min(2.0, width / 2.0)
        palette = theme.PALETTE
        painter.setPen(Qt.NoPen)
        x = 0.0
        for state in self._states:
            painter.setBrush(QColor(palette[BAR_COLORS[state]]))
            painter.drawRoundedRect(
                QRectF(x, 0.0, width, float(rect.height())), radius, radius
            )
            x += width + gap
        painter.end()


class StrategyLog(QFrame):
    """Журнал проверки одной стратегии — раскрывается по клику по строке.

    Медленные замеры (много миллисекунд) подсвечиваются жёлтым, отсутствие
    ответа — красным, поэтому сразу видно, где стратегия тормозит.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StrategyLog")
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 12)
        layout.setSpacing(4)

        self.view = QTextEdit()
        self.view.setObjectName("StrategyLogView")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QTextEdit.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.view.setFont(font)
        self.view.setMinimumHeight(96)
        self.view.setMaximumHeight(200)
        layout.addWidget(self.view)

        self._lines: List[Tuple[str, str]] = []

    # --- данные ---

    @staticmethod
    def classify(line: str) -> str:
        """Тип строки журнала: ok / slow / fail."""
        low = line.lower()
        if any(marker in low for marker in FAIL_MARKERS):
            return "fail"
        # «HTTP/1.1 200 · 145 мс», «ping 12 мс» — берём число перед «мс»
        marker = " мс"
        index = line.find(marker)
        if index < 0:
            return "ok"
        digits = ""
        for char in reversed(line[:index]):
            if char.isdigit():
                digits = char + digits
            else:
                break
        if digits and int(digits) >= SLOW_MS:
            return "slow"
        return "ok"

    def add_line(self, line: str) -> None:
        self._lines.append((line, self.classify(line)))
        self._render()

    def clear(self) -> None:
        self._lines.clear()
        self._render()

    def _render(self) -> None:
        palette = theme.PALETTE
        colors = {
            "ok": palette["muted"],
            "slow": palette["amber"],
            "fail": palette["red"],
        }
        parts = []
        for line, kind in self._lines:
            parts.append(
                f'<div style="color:{colors[kind]};white-space:pre">{html.escape(line)}</div>'
            )
        self.view.setHtml("<html><body>" + "".join(parts) + "</body></html>")


class StrategyRow(QFrame):
    """Строка-карточка одной стратегии: статус, замеры, кнопки и журнал.

    Обычная скруглённая карточка на QSS — своей формы у неё нет. Клик по
    строке раскрывает журнал проверки именно этой стратегии.
    """

    chosen = Signal(str)
    clicked = Signal(str)          # раскрыть/свернуть журнал
    test_requested = Signal(str)   # протестировать только эту стратегию
    pick_changed = Signal(str, bool)   # галочку поставили или сняли

    def __init__(self, name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.strategy = name
        self.setMinimumHeight(66)
        self.setObjectName("StrategyRow")
        self.setProperty("selected", "no")
        self.setProperty("busy", "no")
        self.setProperty("expanded", "no")
        self.setProperty("active", "no")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("diag.row_hint"))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 12, 14, 12)
        layout.setSpacing(10)

        # галочка «проверять эту стратегию»: свой набор запретов
        self.pick = QCheckBox()
        self.pick.setObjectName("RowPick")
        self.pick.setChecked(True)
        self.pick.setToolTip(tr("diag.pick_hint"))
        self.pick.setCursor(Qt.PointingHandCursor)
        self.pick.toggled.connect(self._on_pick_toggled)
        layout.addWidget(self.pick, 0, Qt.AlignVCenter)

        self.rank_label = QLabel("—")
        self.rank_label.setObjectName("StrategyRank")
        self.rank_label.setFixedWidth(24)
        self.rank_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.rank_label, 0, Qt.AlignVCenter)

        names = QVBoxLayout()
        names.setSpacing(2)
        self.name_label = QLabel(name)
        self.name_label.setObjectName("rowTitle")
        names.addWidget(self.name_label)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("muted")
        self.detail_label.setWordWrap(True)
        names.addWidget(self.detail_label)
        self.result_bar = ResultBar()
        names.addWidget(self.result_bar)
        layout.addLayout(names, 1)

        self.pill = StatusPill()
        layout.addWidget(self.pill, 0, Qt.AlignVCenter)

        self.test_button = IconButton("refresh", "", "iconButton", 15)
        self.test_button.setToolTip(tr("diag.test_one"))
        self.test_button.setFixedSize(30, 30)
        self.test_button.clicked.connect(lambda: self.test_requested.emit(self.strategy))
        layout.addWidget(self.test_button, 0, Qt.AlignVCenter)

        self.choose_button = IconButton("check", tr("diag.choose"), "ghost")
        self.choose_button.setToolTip(tr("diag.choose_hint"))
        self.choose_button.setEnabled(False)
        self.choose_button.clicked.connect(self._emit_chosen)
        layout.addWidget(self.choose_button, 0, Qt.AlignVCenter)

        outer.addLayout(layout)

        self.log = StrategyLog()
        outer.addWidget(self.log)

        self.set_status(WAIT)

    # --- мышь ---

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() != Qt.LeftButton:
            return
        # клик по галочке — это её собственное дело, журнал не трогаем
        child = self.childAt(event.position().toPoint())
        if child is not None and child is self.pick:
            return
        self.toggle_log()

    def toggle_log(self) -> None:
        expanded = self.property("expanded") == "yes"
        self.setProperty("expanded", "no" if expanded else "yes")
        self.style().unpolish(self)
        self.style().polish(self)
        self.log.setVisible(not expanded)
        self.clicked.emit(self.strategy)

    # --- состояние ---

    def _emit_chosen(self) -> None:
        self.chosen.emit(self.strategy)

    def _on_pick_toggled(self, checked: bool) -> None:
        # клик по галочке не должен раскрывать журнал стратегии
        self.pick_changed.emit(self.strategy, bool(checked))

    def set_picked(self, picked: bool) -> None:
        self.pick.setChecked(bool(picked))

    def set_status(self, status: str, text: str = "") -> None:
        if status == RUN:
            self.pill.set_status("starting", text or tr("diag.testing"))
        elif status == DONE:
            self.pill.set_status("running", text or tr("diag.done"))
        elif status == FAIL:
            self.pill.set_status("error", text or tr("common.error"))
        else:
            self.pill.set_status("stopped", text or tr("diag.waiting"))

    def set_result(self, result: StrategyResult) -> None:
        parts = [f"{tr('diag.ok')}: {result.ok}/{result.total}"]
        if result.site_count:
            parts.append(f"{tr('diag.targets_covered')}: {result.covered}/{result.site_count}")
        if result.best is not None:
            parts.append(f"{tr('diag.fastest')}: {result.best:.0f} мс")
        if result.average is not None:
            parts.append(f"{tr('diag.avg')}: {result.average:.0f} мс")
        text = " · ".join(parts)
        # второй строкой — сколько целей ответило по каждому протоколу:
        # видно, где именно стратегия не дожимает (HTTP/TLS1.2/TLS1.3/ping)
        protos = result.protocol_summary()
        if protos:
            text += "\n" + " · ".join(
                f"{name} {ok}/{total}" for name, ok, total in protos
            )
        self.detail_label.setText(text)
        # график проверок: доля быстрых ответов и есть процент готовности
        self.result_bar.set_states(result.checks)
        self.result_bar.setToolTip(
            tr(
                "diag.bar_hint",
                percent=result.percent,
                count=len(result.checks),
                slow=SLOW_MS,
            )
        )
        if result.ok == 0:
            self.set_status(FAIL, result.error or tr("diag.no_access"))
            self.choose_button.setEnabled(False)
            self.result_bar.clear()
        else:
            self.set_status(DONE)
            self.choose_button.setEnabled(True)

    def set_rank(self, number: int) -> None:
        self.rank_label.setText(str(number) if number else "—")

    def mark_best(self, best: bool) -> None:
        self.set_selected(best)
        self.rank_label.setProperty("best", "yes" if best else "no")
        self.rank_label.style().unpolish(self.rank_label)
        self.rank_label.style().polish(self.rank_label)
        self.choose_button.setObjectName("primary" if best else "ghost")
        self.choose_button.style().unpolish(self.choose_button)
        self.choose_button.style().polish(self.choose_button)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "yes" if selected else "no")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_active(self, active: bool) -> None:
        """Голубая рамка — стратегия проверяется прямо сейчас."""
        self.setProperty("active", "yes" if active else "no")
        self.style().unpolish(self)
        self.style().polish(self)


class LiveCard(QFrame):
    """Карточка «сейчас проверяется» — а после прогона «Лучший выбор».

    Пока идёт перебор, полный список стратегий скрыт: пользователь видит
    только ту, которая проверяется прямо сейчас. Когда прогон закончен,
    та же карточка превращается в «Лучший выбор»: подсвечивается зелёным и
    показывает кнопку «Применить» — отдельная сводка с «Текущая / Лучшая /
    Проверено» больше не нужна.
    """

    apply_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LiveCard")
        self.setProperty("mode", "run")
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(12)
        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self.caption = QLabel(tr("diag.now_testing"))
        self.caption.setObjectName("statLabel")
        text_box.addWidget(self.caption)
        self.name_label = QLabel("—")
        self.name_label.setObjectName("h2")
        text_box.addWidget(self.name_label)
        top.addLayout(text_box, 1)

        self.position_label = QLabel("")
        self.position_label.setObjectName("muted")
        top.addWidget(self.position_label, 0, Qt.AlignVCenter)
        self.pill = StatusPill()
        top.addWidget(self.pill, 0, Qt.AlignVCenter)
        self.apply_button = IconButton("check", tr("diag.choose"), "primary")
        self.apply_button.setToolTip(tr("diag.choose_hint"))
        self.apply_button.setVisible(False)
        self.apply_button.clicked.connect(self._emit_apply)
        top.addWidget(self.apply_button, 0, Qt.AlignVCenter)
        layout.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setObjectName("LiveBar")
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("muted")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

    # --- состояние ---

    def _emit_apply(self) -> None:
        name = self.name_label.text().strip()
        if name and name != "—":
            self.apply_requested.emit(name)

    def show_strategy(self, name: str, position: int, total: int) -> None:
        """Режим прогона: голубая карточка «сейчас проверяется»."""
        self.setProperty("mode", "run")
        self._restyle()
        self.caption.setText(tr("diag.now_testing"))
        self.name_label.setText(name)
        self.position_label.setText(f"{position} / {total}")
        self.position_label.setVisible(True)
        self.pill.set_status("starting", tr("diag.testing"))
        self.detail_label.setText(tr("common.loading"))
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.apply_button.setVisible(False)
        self.setVisible(True)

    def show_result(self, result: StrategyResult) -> None:
        """Промежуточный итог по одной стратегии (прогон ещё идёт)."""
        self.pill.set_status(
            "running" if result.ok else "error",
            tr("diag.done") if result.ok else tr("common.error"),
        )
        self.detail_label.setText(self._detail_text(result))
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setVisible(False)

    def show_best(self, result: Optional[StrategyResult]) -> None:
        """Итог прогона: карточка становится зелёной «Лучшим выбором»."""
        if result is None or result.ok == 0:
            self.setVisible(False)
            return
        self.setProperty("mode", "best")
        self._restyle()
        self.caption.setText(tr("diag.best_choice"))
        self.name_label.setText(result.name)
        self.position_label.setVisible(False)
        self.pill.set_status("running", tr("diag.best_pill"))
        self.detail_label.setText(self._detail_text(result))
        self.progress.setVisible(False)
        self.apply_button.setVisible(True)
        self.setVisible(True)

    def hide_card(self) -> None:
        self.setVisible(False)

    # --- помощники ---

    @staticmethod
    def _detail_text(result: StrategyResult) -> str:
        parts = [
            f"{tr('diag.ok')}: {result.ok}/{result.total}",
            f"{tr('diag.targets_covered')}: {result.covered}/{result.site_count}",
            f"{tr('diag.bar_hint', percent=result.percent, count=len(result.checks), slow=SLOW_MS)}",
        ]
        if result.average is not None:
            parts.append(f"{tr('diag.avg')}: {result.average:.0f} мс")
        return "\n".join(parts)

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


# ------------------------------------------------------------ помощники


class DiagnosticsPage(BasePage):
    """Перебирает все стратегии и предлагает выбрать самую быструю."""

    # True — прогон идёт, и уйти со страницы нельзя
    busy_changed = Signal(bool)

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._rows: Dict[str, StrategyRow] = {}
        self._order: List[str] = []
        self._queue: List[str] = []
        self._results: Dict[str, StrategyResult] = {}
        self._index = 0
        self._running = False
        self._cancelled = False
        self._tester: Optional[StrategyTester] = None
        self._was_running = False
        self._original = ""
        self._logs: Dict[str, List[Tuple[str, str]]] = {}
        # список сайтов ещё не трогали — его можно обновлять из пакета
        self.targets_dirty = False
        # какие стратегии пользователь отметил галочками
        self._picked: set = set()
        self._build()

    # ------------------------------------------------------------ построение

    def _build(self) -> None:
        header = QVBoxLayout()
        header.setSpacing(3)
        title = QLabel(tr("diag.title"))
        title.setObjectName("h1")
        header.addWidget(title)
        header.addWidget(HintLabel(tr("diag.subtitle")))
        self.add_layout(header)

        self.not_installed = Banner("", "warning")
        self.not_installed.setVisible(False)
        self.add(self.not_installed)

        self.add(self._build_controls())
        self.add(self._build_targets())
        self.live_card = LiveCard()
        self.live_card.apply_requested.connect(self._choose)
        self.add(self.live_card)

        # Заголовок-категория: крупная строка с иконкой, счётчиком и
        # стрелкой — видно, что она кликабельная и что за ней список.
        self.results_button = QPushButton()
        self.results_button.setObjectName("SectionToggle")
        self.results_button.setCheckable(True)
        self.results_button.setChecked(False)
        self.results_button.setCursor(Qt.PointingHandCursor)
        self.results_button.setMinimumHeight(46)
        self.results_button.clicked.connect(self._toggle_results)
        row = QHBoxLayout(self.results_button)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(10)
        self.results_icon = QLabel()
        self.results_icon.setFixedSize(20, 20)
        self.results_icon.setPixmap(icons.icon_pixmap("layers", "#e8ecf4", 20, 1.8))
        row.addWidget(self.results_icon, 0, Qt.AlignVCenter)
        self.results_text = QLabel(tr("diag.strategies"))
        self.results_text.setObjectName("SectionToggleText")
        self.results_text.setStyleSheet(
            f"color: {theme.PALETTE['text']}; background: transparent;"
            " font-size: 11pt; font-weight: 700;"
        )
        row.addWidget(self.results_text, 1)
        # выбрать все / снять все: быстрее, чем тыкать галочки по одной
        self.pick_all = IconButton("check-square", "", "iconButton", 15)
        self.pick_all.setFixedSize(30, 30)
        self.pick_all.setToolTip(tr("diag.pick_all"))
        self.pick_all.clicked.connect(lambda: self._set_all_picked(True))
        row.addWidget(self.pick_all, 0, Qt.AlignVCenter)
        self.pick_none = IconButton("square", "", "iconButton", 15)
        self.pick_none.setFixedSize(30, 30)
        self.pick_none.setToolTip(tr("diag.pick_none"))
        self.pick_none.clicked.connect(lambda: self._set_all_picked(False))
        row.addWidget(self.pick_none, 0, Qt.AlignVCenter)
        self.results_arrow = QLabel()
        self.results_arrow.setFixedSize(20, 20)
        row.addWidget(self.results_arrow, 0, Qt.AlignVCenter)
        self.add(self.results_button)

        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.add(self.rows_host)
        self.rows_host.setVisible(False)

        self.log_view = LogView(tr("diag.log"), autoscroll=False)
        self.log_view.setMinimumHeight(160)
        # журнал растягивается на всё свободное место, поэтому страница
        # не выглядит недоделанной, когда список стратегий свёрнут
        self.log_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.add(self.log_view, 1)

    def _set_all_picked(self, picked: bool) -> None:
        """Ставит или снимает галочки у всех стратегий сразу."""
        if picked:
            self._picked.update(self._order)
        else:
            self._picked.clear()
        for name, row in self._rows.items():
            row.set_picked(name in self._picked)
        self._update_buttons()
        show_toast(
            self,
            tr("diag.picked_count", count=len(self._picked_names())),
            "info",
            duration=2200,
        )

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def _build_controls(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        label = QLabel(tr("diag.run_title"))
        label.setObjectName("cardTitle")
        text_box.addWidget(label)
        text_box.addWidget(HintLabel(tr("diag.run_hint")))
        layout.addLayout(text_box, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        # одна кнопка на два состояния: «Протестировать» ↔ «Остановить».
        # Так на карточке меньше кнопок, а смысл не теряется
        self.start_button = IconButton("activity", tr("diag.start"), "primary")
        self.start_button.clicked.connect(self._on_start_clicked)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)
        return card

    def _build_targets(self) -> QWidget:
        """Карточка проверяемых целей: список только для чтения.

        Править его вручную нельзя — он приходит из utils/targets.txt пакета
        zapret, чтобы наши тесты совпадали с тестами самого пакета. Вернуть
        стандартный список можно кнопкой ниже.
        """
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        label = QLabel(tr("diag.targets_title"))
        label.setObjectName("cardTitle")
        layout.addWidget(label)
        layout.addWidget(HintLabel(tr("diag.targets_hint")))

        self.targets_edit = QPlainTextEdit()
        self.targets_edit.setObjectName("TargetsEdit")
        self.targets_edit.setReadOnly(True)
        self.targets_edit.setMinimumHeight(130)
        self.targets_edit.setMaximumHeight(210)
        self.targets_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.targets_edit.setPlainText(self._targets_text())
        layout.addWidget(self.targets_edit)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.targets_reset = IconButton("undo", tr("diag.targets_reset"), "ghost")
        self.targets_reset.setToolTip(tr("diag.targets_reset_hint"))
        self.targets_reset.clicked.connect(self._reset_targets)
        row.addWidget(self.targets_reset)
        self.targets_info = QLabel("")
        self.targets_info.setObjectName("muted")
        self.targets_info.setWordWrap(True)
        row.addWidget(self.targets_info, 1)
        layout.addLayout(row)

        self.targets_edit.textChanged.connect(self._on_targets_changed)
        self._update_targets_info()
        return card

    def _targets(self) -> list:
        """Цели проверки — сайты и адреса, которые написал пользователь."""
        return parse_targets(self.targets_edit.toPlainText().splitlines())

    def _component_targets_file(self):
        """utils/targets.txt пакета zapret — источник списка сайтов."""
        try:
            return self.ctx.zapret.utils_dir / "targets.txt"
        except Exception:  # noqa: BLE001 - пакет может быть не распакован
            return None

    def _targets_text(self) -> str:
        """Текст списка целей: свой, иначе — из targets.txt пакета."""
        saved = list(self.ctx.config.zapret.diag_targets or [])
        if saved and set(saved) != set(LEGACY_DIAG_TARGETS):
            return "\n".join(saved)
        # список по умолчанию: сайты из самого пакета, а не наш запасной
        return "\n".join(default_target_lines(self._component_targets_file()))

    def _update_targets_info(self) -> None:
        targets = self._targets()
        if not targets:
            self.targets_info.setText(tr("diag.targets_empty"))
            return
        http_count = sum(1 for t in targets if t.kind == "http")
        ping_count = len(targets) - http_count
        # сколько отдельных проверок сделаем: по три протокола на сайт,
        # плюс ping каждого сайта и ping каждого адреса из списка
        checks = http_count * 4 + ping_count
        self.targets_info.setText(
            tr("diag.targets_count", count=len(targets), checks=checks)
        )

    def _on_targets_changed(self) -> None:
        # как только пользователь тронул список, сами его больше не правим
        self._targets_dirty = True
        self._update_targets_info()

    def _save_targets(self) -> bool:
        """Сохраняет список целей в конфиг. False, если целей нет."""
        targets = self._targets()
        if not targets:
            show_toast(self, tr("diag.targets_empty"), "error")
            return False
        # список только для чтения, поэтому сохраняем ровно то, что
        # показывает карточка (без комментариев)
        lines = [
            line.strip()
            for line in self.targets_edit.toPlainText().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ][:48]
        self.ctx.config.zapret.diag_targets = lines
        self.ctx.save_config()
        self._update_targets_info()
        return True

    def _reset_targets(self) -> None:
        """Возвращает список целей из utils/targets.txt пакета."""
        self.targets_dirty = False
        self.targets_edit.setPlainText(self._targets_text())
        if self._save_targets():
            show_toast(
                self, tr("diag.targets_restored"), "success", duration=2600
            )

    # ------------------------------------------------------------ данные

    def reload(self) -> None:
        strategies = [
            name
            for name in self.ctx.zapret.strategies()
            if name.lower().startswith("general")
        ]
        installed = self.ctx.zapret.installed()
        self.not_installed.setVisible(not installed)
        if not installed:
            self.not_installed.set_kind("warning")
            self.not_installed.set_text(tr("diag.not_installed"))

        # пакет мог установиться уже после открытия страницы — тогда
        # подтягиваем его список сайтов из utils/targets.txt
        if not self.targets_dirty and not self._running:
            current = self.targets_edit.toPlainText()
            fresh = self._targets_text()
            if fresh != current:
                self.targets_edit.setPlainText(fresh)
                self._update_targets_info()

        self._order = strategies
        self._results.clear()
        self._index = 0
        self._logs = {name: [] for name in strategies}
        # новые стратегии отмечаем сразу: снимать галочки по одной —
        # лишняя возня, а полный перебор и так кнопка «выбрать все»
        fresh = [name for name in strategies if name not in self._picked]
        self._picked.update(fresh)
        self._clear_rows()
        for name in strategies:
            row = StrategyRow(name)
            row.chosen.connect(self._choose)
            row.clicked.connect(self._on_row_clicked)
            row.test_requested.connect(self.test_one)
            row.pick_changed.connect(self._on_pick_changed)
            row.set_picked(name in self._picked)
            self._rows[name] = row
            self.rows_layout.addWidget(row)

        self.live_card.hide_card()
        self._update_buttons()

    def _reorder_rows(self, ordered: List[StrategyResult]) -> None:
        """Лучшие стратегии поднимаются наверх списка.

        Места в списке распределяются по результатам: чем выше стратегия
        в рейтинге, тем выше её строка. Стратегии, которых не было в
        прогоне (например, снятые галочкой), остаются внизу в своём
        исходном порядке — они не «хуже», они просто не проверялись.
        """
        names = [result.name for result in ordered]
        names += [name for name in self._order if name not in names]
        # снимаем виджеты с макета и раскладываем заново: сами виджеты
        # остаются детьми rows_host, поэтому никто не удаляется
        while self.rows_layout.count():
            self.rows_layout.takeAt(0)
        for name in names:
            row = self._rows.get(name)
            if row is not None:
                self.rows_layout.addWidget(row)

    def _clear_rows(self) -> None:
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    def on_show(self) -> None:
        self.reload()

    def refresh_status(self) -> None:
        """Тикер окна: подписи текущей стратегии на странице больше нет —
        её показывает «Главная» и панель zapret, поэтому только правим
        подпись выбора в заголовке списка."""
        self._update_results_button()

    # ------------------------------------------------------------ список

    def _toggle_results(self, expanded: bool) -> None:
        self.rows_host.setVisible(expanded)
        self._update_results_button()

    def _update_results_button(self) -> None:
        checked = self.results_button.isChecked()
        count = len(self._order)
        picked = len(self._picked_names())
        label = tr("diag.hide_strategies") if checked else tr("diag.strategies")
        # в подписи видно, сколько стратегий реально пойдёт в прогон
        self.results_text.setText(f"{label} · {picked}/{count}")
        # стрелка смотрит вниз, когда список раскрыт
        tone = theme.PALETTE["accent"] if checked else theme.PALETTE["text"]
        self.results_arrow.setPixmap(icons.icon_pixmap("chevron-down", tone, 20, 2.0))
        self.results_icon.setPixmap(
            icons.icon_pixmap("layers", tone, 20, 1.8)
        )
        # цвет задаём инлайном: `color: inherit` в QSS внутри QPushButton
        # работает не везде, и текст оказывался чёрным
        self.results_text.setStyleSheet(
            f"color: {tone}; background: transparent; font-size: 11pt; font-weight: 700;"
        )
        self.results_button.setChecked(checked)

    # ------------------------------------------------------------ прогон

    def _on_start_clicked(self) -> None:
        """Одна кнопка на два состояния: запустить прогон или остановить."""
        if self._running:
            self.stop_testing()
        else:
            self.start_testing()

    def start_testing(self) -> None:
        """Прогон отмеченных стратегий general*.bat."""
        if self._running or not self._order:
            return
        if not self._save_targets():
            return
        self._queue = [name for name in self._order if name in self._picked]
        if not self._queue:
            show_toast(self, tr("diag.nothing_picked"), "warning")
            return
        self._begin(all_rows=True)

    def test_one(self, name: str) -> None:
        """Прогон одной стратегии — клик по её строке."""
        if self._running or name not in self._rows:
            return
        if not self._save_targets():
            return
        self._queue = [name]
        self._begin(all_rows=False)

    def _begin(self, all_rows: bool) -> None:
        self._running = True
        self._cancelled = False
        self._was_running = self.ctx.zapret.is_running()
        self._original = self.ctx.config.zapret.strategy
        self._results.clear()
        self._index = 0
        self._logs = {name: [] for name in self._order}
        for name in self._order:
            row = self._rows[name]
            row.set_status(WAIT)
            row.set_rank(0)
            row.mark_best(False)
            row.set_active(False)
            row.log.clear()
        # список скрыт: пока идёт прогон, показываем одну стратегию за раз
        self.results_button.setChecked(False)
        self.rows_host.setVisible(False)
        if all_rows:
            self.log_view.append(f"[hub] {tr('diag.started')}: {len(self._queue)}")
        if self._was_running:
            self.ctx.zapret.stop()
        self._update_buttons()
        self._run_next()

    def stop_testing(self) -> None:
        if not self._running:
            return
        self._cancelled = True
        if self._tester is not None:
            self._tester.cancel()
        self.log_view.append(f"[hub] {tr('diag.stopped')}")

    def _run_next(self) -> None:
        if self._cancelled or self._index >= len(self._queue):
            self._finish()
            return
        name = self._queue[self._index]
        row = self._rows[name]
        row.set_status(RUN)
        row.set_rank(self._index + 1)
        # та же голубая рамка, что у карточки «сейчас проверяется»
        row.set_active(True)
        self.live_card.show_strategy(name, self._index + 1, len(self._queue))
        self.log_view.append(f"[hub] {tr('diag.trying')}: {name}")

        self.ctx.config.zapret.strategy = name
        try:
            started = self.ctx.zapret.start()
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")
            started = False
        if not started:
            self.log_view.append(f"[hub] {tr('diag.start_failed')}: {name}")

        self._tester = StrategyTester(name, targets=self._targets())
        self._tester.log.connect(self._on_test_log)
        self._tester.measured.connect(self._on_measured)
        self._tester.start()

    def _on_test_log(self, line: str) -> None:
        """Строка журнала: и общий журнал страницы, и журнал своей стратегии."""
        self.log_view.append(line)
        name = self._queue[self._index] if self._index < len(self._queue) else ""
        if not name:
            return
        self._logs.setdefault(name, []).append(line)
        row = self._rows.get(name)
        if row is not None:
            row.log.add_line(line)

    def _on_row_clicked(self, name: str) -> None:
        """Клик по строке раскрывает журнал проверки этой стратегии."""
        row = self._rows.get(name)
        if row is None:
            return
        if row.property("expanded") == "yes" and not self._logs.get(name):
            show_toast(self, tr("diag.no_log"), "info")

    def _on_measured(self, result: StrategyResult) -> None:
        tester, self._tester = self._tester, None
        if tester is not None:
            if tester.wait(1500):
                tester.deleteLater()
            else:
                tester.finished.connect(tester.deleteLater)
        try:
            self.ctx.zapret.stop()
        except Exception as exc:  # noqa: BLE001
            self.log_view.append(f"[hub] {exc}")

        row = self._rows.get(result.name)
        if row is not None:
            row.set_result(result)
            row.set_active(False)
        self.live_card.show_result(result)
        self._results[result.name] = result
        self._index += 1
        if self._cancelled:
            self._finish()
        else:
            QTimer.singleShot(150, self._run_next)

    def _finish(self) -> None:
        """Итог прогона: лучшая стратегия становится текущей сама.

        Так же и при остановке: раз прогон уже дал результаты, глупо
        возвращать ту стратегию, с которой пришли, — применяется лучшая
        из тех, что успели провериться.
        """
        self._running = False
        self._cancelled = False
        try:
            self.ctx.zapret.stop()
        except Exception:  # noqa: BLE001
            pass

        best = self.apply_results(list(self._results.values()))
        self._apply_best_after_run(best)
        self._update_buttons()

    def _apply_best_after_run(self, best: Optional[StrategyResult]) -> None:
        """Ставит лучшую стратегию текущей и перезапускает её, если надо."""
        if best is None or best.ok == 0:
            # провериться не успело ничего — оставляем как было
            if self._original:
                self.ctx.config.zapret.strategy = self._original
                self.ctx.save_config()
            if self._was_running:
                try:
                    self.ctx.zapret.start()
                except Exception as exc:  # noqa: BLE001
                    self.log_view.append(f"[hub] {exc}")
            return

        self.log_view.append(
            f"[hub] {tr('diag.auto_applied')}: {best.name}"
        )
        self.ctx.config.zapret.strategy = best.name
        self.ctx.save_config()
        if self._was_running:
            try:
                self.ctx.zapret.start()
            except Exception as exc:  # noqa: BLE001
                self.log_view.append(f"[hub] {exc}")
            show_toast(
                self,
                tr("diag.auto_applied_toast", name=best.name, percent=best.percent),
                "success",
                duration=6000,
            )
        else:
            show_toast(
                self,
                tr("diag.chosen", name=best.name),
                "success",
                duration=6000,
            )

    def apply_results(self, results: List[StrategyResult]) -> Optional[StrategyResult]:
        """Показывает итоги прогона: работоспособные — вверх, лучшая первой.

        Возвращает лучшую стратегию, чтобы вызывающий мог применить её.
        """
        self._results = {result.name: result for result in results}
        ordered = rank(results)
        best = ordered[0] if ordered else None
        if best is not None and best.ok > 0:
            for position, result in enumerate(ordered, start=1):
                row = self._rows.get(result.name)
                if row is None:
                    continue
                row.set_result(result)
                row.set_rank(position)
                row.mark_best(position == 1)
            # лучшие поднимаются наверх
            self._reorder_rows(ordered)
            self.log_view.append(f"[hub] {tr('diag.best_found')}: {best.name}")
            # карточка «сейчас проверяется» превращается в «Лучший выбор»
            self.live_card.show_best(best)
        else:
            self.log_view.append(f"[hub] {tr('diag.no_best')}")
            show_toast(self, tr("diag.no_best"), "error", duration=6000)
            self.live_card.hide_card()
        # результаты готовы — список можно открыть
        if results:
            self.results_button.setChecked(True)
            self.rows_host.setVisible(True)
        self._update_results_button()
        return best if (best is not None and best.ok > 0) else None

    def _update_buttons(self) -> None:
        picked = len(self._picked_names())
        has_rows = bool(self._order)
        # одна кнопка: пока идёт прогон — «Остановить», иначе «Протестировать»
        if self._running:
            self.start_button.set_icon("stop", theme.PALETTE["red"])
            self.start_button.setText(tr("diag.stop"))
            self.start_button.setToolTip(tr("diag.stop_hint"))
            self.start_button.setEnabled(True)
        else:
            self.start_button.set_icon("activity")
            self.start_button.setText(
                tr("diag.start_count", count=picked) if picked else tr("diag.start")
            )
            self.start_button.setToolTip(tr("diag.start_hint"))
            self.start_button.setEnabled(has_rows)
        self.results_button.setEnabled(has_rows)
        for row in self._rows.values():
            row.setProperty("busy", "yes" if self._running else "no")
            row.style().unpolish(row)
            row.style().polish(row)
        self._update_results_button()
        self.busy_changed.emit(self._running)

    def _picked_names(self) -> List[str]:
        """Отмеченные галочками стратегии в порядке списка."""
        return [name for name in self._order if name in self._picked]

    def _on_pick_changed(self, name: str, picked: bool) -> None:
        """Галочку поставили или сняли — запоминаем и правим подписи."""
        if picked:
            self._picked.add(name)
        else:
            self._picked.discard(name)
        self._update_buttons()

    # ------------------------------------------------------------ выбор

    def _choose(self, name: str) -> None:
        self.ctx.config.zapret.strategy = name
        self.ctx.save_config()
        self.log_view.append(f"[hub] {tr('diag.applied')}: {name}")
        restarted = False
        error = ""
        if self.ctx.zapret.is_running():
            try:
                self.ctx.zapret.restart()
                restarted = True
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                self.log_view.append(f"[hub] {exc}")
        # выбор стратегии — важное событие, поэтому всегда с уведомлением
        if error:
            show_toast(
                self,
                tr("diag.chosen_error", name=name, error=error),
                "error",
            )
        elif restarted:
            show_toast(
                self, tr("diag.chosen_restarted", name=name), "success"
            )
        else:
            show_toast(self, tr("diag.chosen", name=name), "success")
