"""Страница диагностики: перебор всех general*.bat и выбор лучшей стратегии.

Страница переделана в **список**: одна стратегия — одна строка. Раньше
стратегии были карточками по три в ряду, и из-за этого ломался макет: при
раскрытии карточка оставалась «сплющенной», часть содержимого не вмещалась.

Как теперь устроено:

* клик по самой строке (по имени или пустому месту) — отметить стратегию
  для прогона, это же показывает галочка;
* кнопка с иконкой справа от статуса — показать журнал этой стратегии;
* если отмечены не все стратегии, во время прогона неотмеченные скрыты;
* после прогона показываются все: отмеченные — с местом в рейтинге,
  неотмеченные — красные, с крестом вместо места.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core import win32
from ...core.zapret import SERVICE_NAME
from ...core.strategy_test import (
    DEAD_PROCESS_ERROR,
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
    PickCheckBox,
    StatusPill,
    show_toast,
)
from .base import BasePage

WAIT, RUN, DONE, FAIL = "wait", "run", "done", "fail"

# цвета графика проверок: быстрый ответ, медленный ответ, нет ответа
BAR_COLORS = {"ok": "green", "slow": "amber", "fail": "red"}

# высота строки стратегии с закрытым журналом
ROW_HEIGHT = 56


# Признаки того, что строка журнала объясняет провал, а не информирует.
# «already running» — сообщение самого winws.exe о второй копии: фильтр
# WinDivert один на систему, и вторая копия сразу умирает.
_ERROR_MARKERS = (
    "ошибка",
    "не удал",
    "нужны",
    "активна",
    "не найден",
    "не запустил",
    "уже запущ",
    "already running",
    "error",
    "failed",
    "denied",
    "доступ",
)


def _error_text(error: str) -> str:
    """Человеческая причина провала стратегии.

    Ядро отдаёт стабильные токены, а не текст: иначе при переключении языка
    в строках стратегий оставался бы русский текст, вшитый в core. Обычная
    строка от компонента (например «нужны права администратора») уже готовая.
    """
    if error == DEAD_PROCESS_ERROR:
        return tr("diag.dead_process")
    return error


def _short_name(name: str) -> str:
    """Имя стратегии без расширения — для компактной строки.

    «general (ALT10).bat» → «general (ALT10)». Расширение у всех одно,
    а в списке по одной стратегии в строке каждая буква на счету.
    """
    text = (name or "").strip()
    if text.lower().endswith(".bat"):
        text = text[:-4]
    return text


class ResultBar(QWidget):
    """График проверок одной стратегии: по отрезку на каждый ответ.

    Каждая проверка занимает свою долю ширины, поэтому полоска показывает
    не только «сколько получилось», но и «где» стратегия подводит: обрывы
    чередуются с ответами, если сайт «мигает».
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ResultBar")
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setVisible(False)
        self._states: List[str] = []

    def set_states(self, states) -> None:
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


class StrategyRow(QFrame):
    """Одна стратегия в списке: галочка, место, статус, журнал.

    Строка, а не карточка: по одной стратегии в ряд, и в этом главное
    отличие от прежней сетки. В строке —

    * галочка: участвует ли стратегия в общем прогоне;
    * место: номер в рейтинге после прогона, либо красный крест, если
      стратегия не проверялась;
    * статус: ожидание / проверка / готово / ошибка;
    * «Выбрать»: появляется у стратегии, которая хоть что-то открыла;
    * кнопка с иконкой: журнал проверки по каждой цели.

    Клик по самой строке ставит и снимает галочку — не нужно целиться в
    маленький квадратик.
    """

    chosen = Signal(str)
    test_requested = Signal(str)       # протестировать только эту стратегию
    pick_changed = Signal(str, bool)   # галочку поставили или сняли
    log_toggled = Signal(str, bool)    # журнал раскрыли или свернули

    def __init__(self, name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.strategy = name
        self._result: Optional[StrategyResult] = None
        self._log_open = False
        self._tested = False
        # общий со страницей словарь «стратегия -> строки компонента»
        self._start_log: Dict[str, List[str]] = {}

        self.setObjectName("StrategyRow")
        self.setProperty("selected", "no")
        self.setProperty("busy", "no")
        self.setProperty("active", "no")
        self.setProperty("untested", "no")
        # picked — «отмечена галочкой»: рамка и лёгкий синий фон, чтобы
        # выбранные стратегии были видны в списке без чтения подписей
        self.setProperty("picked", "no")
        # Вертикальная политика — Preferred, а не Fixed: строка меняет
        # высоту, когда под ней раскрывается журнал. С Fixed она оставалась
        # 56 px, журнал вылезал за её пределы и ложился поверх соседних
        # строк — именно это и выглядело как «стиль багнулся, не всё
        # вместилось».
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(56)
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------- сама строка ----------
        top = QHBoxLayout()
        top.setContentsMargins(11, 9, 11, 9)
        top.setSpacing(9)

        self.pick = PickCheckBox()
        self.pick.setObjectName("RowPick")
        self.pick.setChecked(True)
        self.pick.setToolTip(tr("diag.pick_hint"))
        self.pick.setCursor(Qt.PointingHandCursor)
        self.pick.toggled.connect(self._on_pick_toggled)
        top.addWidget(self.pick, 0, Qt.AlignVCenter)

        self.rank_label = QLabel("—")
        self.rank_label.setObjectName("StrategyRank")
        self.rank_label.setFixedWidth(22)
        self.rank_label.setAlignment(Qt.AlignCenter)
        self.rank_label.setToolTip(tr("diag.rank_hint"))
        top.addWidget(self.rank_label, 0, Qt.AlignVCenter)

        names = QVBoxLayout()
        names.setSpacing(1)
        # имя показываем без .bat: расширение у всех одинаковое
        self.name_label = QLabel(_short_name(name))
        self.name_label.setObjectName("rowTitle")
        self.name_label.setWordWrap(True)
        self.name_label.setToolTip(name)
        names.addWidget(self.name_label)
        self.summary_label = QLabel(tr("diag.not_tested_short"))
        self.summary_label.setObjectName("muted")
        self.summary_label.setWordWrap(True)
        names.addWidget(self.summary_label)
        top.addLayout(names, 1)

        self.pill = StatusPill()
        top.addWidget(self.pill, 0, Qt.AlignVCenter)

        self.choose_button = IconButton("check", tr("diag.choose"), "glassPrimary")
        self.choose_button.setToolTip(tr("diag.choose_hint"))
        self.choose_button.setEnabled(False)
        self.choose_button.setVisible(False)
        self.choose_button.clicked.connect(self._emit_chosen)
        top.addWidget(self.choose_button, 0, Qt.AlignVCenter)

        # кнопка журнала — справа от статуса, с иконкой
        self.log_button = IconButton("terminal", "", "iconButton", 15)
        self.log_button.setFixedSize(34, 34)
        self.log_button.setCheckable(True)
        self.log_button.setToolTip(tr("diag.log"))
        self.log_button.clicked.connect(self._on_log_clicked)
        top.addWidget(self.log_button, 0, Qt.AlignVCenter)

        # кнопка «протестировать только эту» — рядом с журналом
        self.test_button = IconButton("refresh", "", "iconButton", 14)
        self.test_button.setFixedSize(34, 34)
        self.test_button.setToolTip(tr("diag.test_one"))
        self.test_button.clicked.connect(
            lambda: self.test_requested.emit(self.strategy)
        )
        top.addWidget(self.test_button, 0, Qt.AlignVCenter)

        outer.addLayout(top)

        # ---------- журнал под строкой ----------
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("StrategyLogView")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setVisible(False)
        outer.addWidget(self.log_view)
        # текст есть всегда: иначе раскрытый журнал до первого замера
        # выглядит как пустая дырка
        self._fill_log()

        self.set_status(WAIT)
        self._sync_height()

    def bind_start_log(self, store: Dict[str, List[str]]) -> None:
        """Делит журнал запуска со страницей: она пишет, строка показывает."""
        self._start_log = store

    # ---------- мышь ----------

    def mousePressEvent(self, event) -> None:
        """Клик по строке = отметить стратегию для прогона.

        Кнопки и галочка съедают событие сами, поэтому сюда доходит только
        клик по имени или по пустому месту — как раз то, что нужно.
        Во время общего прогона клик игнорируется: состав стратегий
        меняется только до старта или после финиша.
        """
        if self.property("busy") == "yes":
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self.pick.setChecked(not self.pick.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_pick_toggled(self, checked: bool) -> None:
        # клик по галочке журнал не раскрывает
        self.setProperty("picked", "yes" if checked else "no")
        self._restyle()
        self.pick_changed.emit(self.strategy, bool(checked))

    def _on_log_clicked(self, checked: bool) -> None:
        self.set_log_open(bool(checked))

    def set_log_open(self, opened: bool) -> None:
        opened = bool(opened)
        if opened == self._log_open:
            return
        self._log_open = opened
        self.log_view.setVisible(opened)
        self._fill_log()
        self.log_button.setChecked(opened)
        self.log_button.setToolTip(
            tr("diag.log_hide") if opened else tr("diag.log")
        )
        self._sync_height()
        self._restyle()
        self.log_toggled.emit(self.strategy, opened)

    def _log_height(self) -> int:
        """Высота журнала по его содержимому — но в разумных пределах.

        Считаем по числу строк, а не по `document().size()`: у скрытого
        виджета документ ещё не разложен, и размер выходит заниженным.
        Перенос строк выключен, поэтому число блоков равно числу строк.
        """
        lines = max(1, self.log_view.document().blockCount())
        need = lines * self.log_view.fontMetrics().lineSpacing() + 24
        return int(max(96, min(300, need)))

    def _sync_height(self) -> None:
        """Считает высоту строки самой, а не через sizeHint макета.

        Через sizeHint не работает: макет внутри прокручиваемой страницы
        кеширует размеры, и раскрытый журнал оставался за пределами строки —
        ложился поверх соседних. Отсюда и «стиль багнулся, не всё
        вместилось». Минимальная высота надёжна: макет не даёт строке
        стать ниже неё, а прокрутка берёт остальное на себя.
        """
        extra = self._log_height() + 6 if self._log_open else 0
        self.log_view.setFixedHeight(self._log_height())
        self.setMinimumHeight(ROW_HEIGHT + extra)
        self._relayout_self()

    def _relayout_self(self) -> None:
        """Заставляет родительский макет пересчитать геометрию строки.

        Одной `setMinimumHeight` не хватает: `QVBoxLayout` держит кеш
        структуры строк, и раскрытый журнал остаётся за пределами строки —
        ложится поверх соседних. Удаление и повторная вставка виджета в тот
        же индекс сбрасывают этот кеш, макет строит структуру заново.
        """
        parent = self.parentWidget()
        lay = parent.layout() if parent is not None else None
        if lay is None:
            return
        idx = lay.indexOf(self)
        if idx < 0:
            return
        lay.removeWidget(self)
        lay.insertWidget(idx, self)

    # ---------- состояние ----------

    def _emit_chosen(self) -> None:
        self.chosen.emit(self.strategy)

    def set_picked(self, picked: bool) -> None:
        picked = bool(picked)
        self.pick.setChecked(picked)
        self.setProperty("picked", "yes" if picked else "no")
        self._restyle()

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
        """Показывает итог одной стратегии в её строке."""
        self._result = result
        self._tested = True
        parts = [f"{tr('diag.ok')}: {result.ok}/{result.total}"]
        if result.site_count:
            parts.append(
                f"{tr('diag.targets_covered')}: {result.covered}/{result.site_count}"
            )
        if result.average is not None:
            parts.append(f"{tr('diag.avg')}: {result.average:.0f} мс")
        self.summary_label.setText(" · ".join(parts))
        if result.ok == 0:
            # «Нет доступа» вслепую бесполезно: показываем настоящую причину,
            # если компонент её назвал, иначе честно «сайты не открылись»
            self.set_status(
                FAIL, _error_text(result.error) or self._failure_reason()
            )
            self.choose_button.setEnabled(False)
            self.choose_button.setVisible(False)
        else:
            self.set_status(DONE)
            self.choose_button.setEnabled(True)
            self.choose_button.setVisible(True)
        self._fill_log()
        if self._log_open:
            # журнал открыт — содержимое уже обновилось, размер тот же
            self._restyle()

    def _fill_log(self) -> None:
        """Журнал стратегии: что ответило по каждой цели проверки."""
        result = self._result
        if result is None:
            # стратегия ещё не проверена, но компонент уже мог сказать
            # что-то важное — показываем, а не пустой экран
            start_log = self._start_log_lines()
            if start_log:
                self.log_view.setPlainText(
                    tr("diag.log_start") + "\n" + "\n".join(f"  {t}" for t in start_log)
                )
            else:
                self.log_view.setPlainText(tr("diag.not_tested_yet"))
            self._sync_height()
            return
        lines = [
            f"{_short_name(result.name)}",
            f"{tr('diag.ok')}: {result.ok}/{result.total}",
            f"{tr('diag.targets_covered')}: {result.covered}/{result.site_count}",
            f"{tr('diag.bar_hint', percent=result.percent, count=len(result.checks), slow=SLOW_MS)}",
        ]
        if result.best is not None:
            lines.append(f"{tr('diag.fastest')}: {result.best:.0f} мс")
        if result.average is not None:
            lines.append(f"{tr('diag.avg')}: {result.average:.0f} мс")
        protos = result.protocol_summary()
        if protos:
            lines.append("")
            lines.extend(f"  {name}: {ok}/{total}" for name, ok, total in protos)
        start_log = self._start_log_lines()
        if start_log:
            lines.append("")
            lines.append(tr("diag.log_start"))
            lines.extend(f"  {text}" for text in start_log)
        if result.details:
            lines.append("")
            lines.append(tr("diag.log_targets"))
            for outcome in result.details.values():
                target = outcome.target
                label = target.name or target.host
                lines.append(f"  {label}: {outcome.summary()}")
        if result.error:
            lines.append("")
            lines.append(f"{tr('common.error')}: {result.error}")
        self.log_view.setPlainText("\n".join(lines))
        self._sync_height()

    def _failure_reason(self) -> str:
        """Почему стратегия не открыла ни одного сайта.

        Берём последнюю осмысленную строку из журнала компонента: там
        оказывается «нужны права администратора» или «служба zapret
        активна» — то, чего в самой стратегии не видно. Если компонент
        молчал, значит сайты правда не ответили.
        """
        result = self._result
        if result is not None and result.total == 0:
            # нечего было проверять: пустой список целей — это не «нет
            # доступа», и раньше row выглядела ровно так же
            return tr("diag.no_targets")

        lines = [t for t in self._start_log_lines() if t.strip()]
        for text in reversed(lines):
            low = text.lower()
            if any(marker in low for marker in _ERROR_MARKERS):
                return text

        # Метка не совпала, но журнал не пуст. Последняя строка почти
        # всегда и есть причина: winws пишет «A copy of winws is already
        # running» — ровно тот случай, когда служба пакета и прямой запуск
        # дерутся за один фильтр WinDivert. Без этого шага такая строка
        # не находилась по меткам, и стратегия получала общее «сайты не
        # открылись», хотя причина названа прямым текстом.
        if lines:
            return lines[-1]
        return tr("diag.sites_unreachable")

    def _start_log_lines(self) -> List[str]:
        """Строки, которые компонент выдал при запуске этой стратегии."""
        box = self._start_log.get(self.strategy)
        return list(box) if box else []

    def set_rank(self, number: int) -> None:
        self.rank_label.setText(str(number) if number else "—")

    def set_untested(self, untested: bool) -> None:
        """Серая строка с прочерком: стратегия не проверялась в этом прогоне.

        Раньше такая строка горела красным с крестом — точно так же, как
        стратегия, которая честно проверена и не сработала. После прогона
        половины отмеченных стратегий список выглядел как сплошной провал,
        хотя эти стратегии просто не запускались.
        """
        untested = bool(untested)
        self.setProperty("untested", "yes" if untested else "no")
        self.rank_label.setText("—" if untested else "—")
        self.rank_label.setProperty("untested", "yes" if untested else "no")
        self.rank_label.style().unpolish(self.rank_label)
        self.rank_label.style().polish(self.rank_label)
        self._restyle()

    def mark_best(self, best: bool) -> None:
        self.setProperty("selected", "yes" if best else "no")
        self.rank_label.setProperty("best", "yes" if best else "no")
        self.rank_label.style().unpolish(self.rank_label)
        self.rank_label.style().polish(self.rank_label)
        self._restyle()

    def set_active(self, active: bool) -> None:
        """Голубая рамка — стратегия проверяется прямо сейчас."""
        self.setProperty("active", "yes" if active else "no")
        self._restyle()

    def set_busy(self, busy: bool) -> None:
        """Идёт общий прогон: строку нельзя трогать.

        Раньше свойство ``busy`` только перекрашивало рамку, а галочка
        оставалась живой — во время прогона состав стратегий менялся
        на глазах, и в отчёт попадало не то, что показывал список.
        Теперь галочка и клик по строке заблокированы до конца прогона.
        """
        busy = bool(busy)
        if self.property("busy") == ("yes" if busy else "no"):
            return
        self.setProperty("busy", "yes" if busy else "no")
        self.pick.setEnabled(not busy)
        self.pick.setCursor(
            Qt.ArrowCursor if busy else Qt.PointingHandCursor
        )
        self.setCursor(Qt.ArrowCursor if busy else Qt.PointingHandCursor)
        self._restyle()

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        # макет внутри прокручиваемой страницы не всегда пересчитывает
        # размер сам — просим явно, иначе строка остаётся «сплющенной»
        self.updateGeometry()
        parent = self.parentWidget()
        while parent is not None:
            if parent.layout() is not None:
                parent.layout().invalidate()
            parent.updateGeometry()
            parent = parent.parentWidget()


class LiveCard(QFrame):
    """Карточка «сейчас проверяется» — а после прогона «Лучший выбор»."""

    apply_requested = Signal(str)
    admin_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LiveCard")
        self.setProperty("mode", "run")
        self.setVisible(False)
        # полное имя стратегии (с .bat): в строке показываем короткое,
        # а применять надо именно полное
        self._full_name = ""
        # лидер текущего прогона: показываем под индикатором
        self._leader_text = ""

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
        self.name_label.setWordWrap(True)
        text_box.addWidget(self.name_label)
        top.addLayout(text_box, 1)

        self.position_label = QLabel("")
        self.position_label.setObjectName("muted")
        top.addWidget(self.position_label, 0, Qt.AlignVCenter)
        self.pill = StatusPill()
        top.addWidget(self.pill, 0, Qt.AlignVCenter)
        self.apply_button = IconButton("check", tr("diag.choose"), "glassPrimary")
        self.apply_button.setToolTip(tr("diag.choose_hint"))
        self.apply_button.setVisible(False)
        self.apply_button.clicked.connect(self._emit_apply)
        top.addWidget(self.apply_button, 0, Qt.AlignVCenter)
        # кнопка «Предоставить доступ»: показывается только в режиме
        # ошибки, когда причина — отсутствие прав администратора. Раньше
        # пользователь видел «нет доступа» и не понимал, что делать.
        self.admin_button = IconButton(
            "power", tr("diag.admin_relaunch"), "glassPrimary"
        )
        self.admin_button.setToolTip(tr("diag.admin_relaunch_hint"))
        self.admin_button.clicked.connect(self.admin_requested.emit)
        self.admin_button.setVisible(False)
        top.addWidget(self.admin_button, 0, Qt.AlignVCenter)
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
        # полное имя храним отдельно: в строке показываем короткое
        name = self._full_name or self.name_label.text().strip()
        if name and name != "—":
            self.apply_requested.emit(name)

    def set_leader(self, result: Optional[StrategyResult]) -> None:
        """Показывает лидера прогона, пока идёт перебор стратегий.

        Без этого девять минут прогона — это просто бегущая строка: не
        понятно, есть ли вообще смысл ждать. Лидер отвечает на вопрос
        «уже есть чем пользоваться».
        """
        if result is None or result.ok == 0:
            self._leader_text = ""
        else:
            self._leader_text = tr("diag.leader_now", name=_short_name(result.name),
                                   percent=result.percent)
        if self.property("mode") == "run":
            self.detail_label.setText(self._leader_text)

    def show_strategy(self, name: str, position: int, total: int) -> None:
        """Режим прогона: голубая карточка «сейчас проверяется»."""
        self._full_name = name
        self.setProperty("mode", "run")
        self._restyle()
        self.caption.setText(tr("diag.now_testing"))
        self.name_label.setText(_short_name(name))
        self.name_label.setToolTip(name)
        self.name_label.setVisible(True)
        self.position_label.setText(f"{position} / {total}")
        self.position_label.setVisible(True)
        self.pill.set_status("starting", tr("diag.testing"))
        self.detail_label.setText(self._leader_text)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.apply_button.setVisible(False)
        self.admin_button.setVisible(False)
        self.setVisible(True)

    def show_result(self, result: StrategyResult) -> None:
        """Промежуточный итог по одной стратегии (прогон ещё идёт)."""
        # карточка могла краснеть от предыдущей стратегии, которая не
        # запустилась — возвращаем её в режим прогона, иначе «лидер»
        # перестаёт обновляться до конца перебора
        self.setProperty("mode", "run")
        self._restyle()
        self.pill.set_status(
            "running" if result.ok else "error",
            tr("diag.done") if result.ok else tr("common.error"),
        )
        self.detail_label.setText(self._detail_text(result))
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setVisible(False)

    def show_probe_started(self, name: str) -> None:
        """Проверка запуска пошла: карточка переходит в режим ожидания."""
        self._full_name = name
        self.setProperty("mode", "run")
        self._restyle()
        self.caption.setText(tr("diag.probe_running"))
        self.name_label.setText(_short_name(name))
        self.name_label.setToolTip(name)
        self.name_label.setVisible(True)
        self.position_label.setVisible(False)
        self.pill.set_status("starting", tr("diag.testing"))
        self.detail_label.setText(tr("diag.probe_wait"))
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.apply_button.setVisible(False)
        self.admin_button.setVisible(False)
        self.setVisible(True)

    def show_probe(self, report: dict, name: str) -> None:
        """Итог проверки запуска: зелёная, если стратегия держится.

        ``report`` приходит из ``ZapretComponent.probe_start``: это факты —
        стартовал ли процесс, жив ли, код выхода, что он сам написал. Без
        них оставалось только «нет доступа», и разобраться было негде.
        """
        started = bool(report.get("started"))
        alive = bool(report.get("alive"))
        reason = str(report.get("reason") or "")
        output = list(report.get("output") or [])
        command = str(report.get("command") or "")

        if started and alive:
            self.setProperty("mode", "best")
            self._restyle()
            self.caption.setText(tr("diag.probe_ok_title"))
            self.pill.set_status("running", tr("diag.ok"))
            self.detail_label.setText(tr("diag.probe_ok_body"))
        else:
            self.setProperty("mode", "fail")
            self._restyle()
            self.caption.setText(tr("diag.probe_fail_title"))
            self.pill.set_status("error", tr("common.error"))
            if reason:
                body = reason
            elif report.get("exit_code") is not None:
                body = tr("diag.probe_exit", code=report.get("exit_code"))
            else:
                body = tr("diag.probe_died")
            # Сырой лог winws идёт отдельным блоком под причиной, а не
            # сливается с ней в одну простыню: причина — то, что читают,
            # лог — то, что читают, только если причины мало.
            if output:
                body += "\n\n" + "\n".join(f"  {line}" for line in output[-8:])
            if command:
                body += "\n" + tr("diag.probe_command", command=command)
            self.detail_label.setText(body)
            # не хватило прав — сразу предлагаем их выдать
            self.admin_button.setVisible("администратор" in reason.lower())

        self._full_name = name
        self.name_label.setText(_short_name(name))
        self.name_label.setToolTip(name)
        self.name_label.setVisible(True)
        self.position_label.setVisible(False)
        self.progress.setVisible(False)
        self.apply_button.setVisible(False)
        self.setVisible(True)

    def show_failure(self, message: str) -> None:
        """Прогон не идёт: карточка краснеет и объясняет почему.

        Без этого пользователь видел только «Нет доступа» в каждой строке
        и не понимал, что дело в правах, а не в стратегиях. Если причина
        действительно в правах — тут же предлагаем их выдать.
        """
        if not message:
            return
        self._full_name = ""
        self.setProperty("mode", "fail")
        self._restyle()
        self.caption.setText(tr("diag.cannot_test"))
        self.name_label.setText("")
        self.name_label.setVisible(False)
        self.position_label.setVisible(False)
        self.pill.set_status("error", tr("common.error"))
        self.detail_label.setText(message)
        self.progress.setVisible(False)
        self.apply_button.setVisible(False)
        self.admin_button.setVisible(message == tr("diag.admin_needed"))
        self.setVisible(True)

    def show_best(
        self,
        result: Optional[StrategyResult],
        runners_up: Sequence[StrategyResult] = (),
    ) -> None:
        """Итог прогона: карточка становится зелёной «Лучшим выбором».

        ``runners_up`` — следующие за лучшей стратегии. Без них победителя
        видно, а сравнить не с чем: чтобы понять, насколько он лучше,
        приходилось листать все двадцать с лишним строк.
        """
        if result is None or result.ok == 0:
            self.setVisible(False)
            return
        self.setProperty("mode", "best")
        self._restyle()
        self.caption.setText(tr("diag.best_choice"))
        self.name_label.setText(_short_name(result.name))
        self.name_label.setToolTip(result.name)
        self._full_name = result.name
        self.position_label.setVisible(False)
        self.pill.set_status("running", tr("diag.best_pill"))
        detail = self._detail_text(result)
        others = [
            tr("diag.runner_up", position=position + 2, name=_short_name(item.name),
               percent=item.percent)
            for position, item in enumerate(runners_up[:2])
            if item.ok > 0
        ]
        if others:
            detail = detail + "\n" + " · ".join(others)
        self.detail_label.setText(detail)
        self.progress.setVisible(False)
        self.apply_button.setVisible(True)
        self.admin_button.setVisible(False)
        self.setVisible(True)

    def hide_card(self) -> None:
        self.setVisible(False)

    # --- помощники ---

    @staticmethod
    def _detail_text(result: StrategyResult) -> str:
        # Стратегия не запустилась: «0 из 0» выглядит как настоящий провал,
        # поэтому вместо счётчиков показываем причину — winws умер сразу
        # после старта, и замерять было нечего.
        if result.error:
            return _error_text(result.error)
        parts = [
            f"{tr('diag.ok')}: {result.ok}/{result.total}",
            f"{tr('diag.targets_covered')}: {result.covered}/{result.site_count}",
            f"{tr('diag.bar_hint', percent=result.percent, count=len(result.checks), slow=SLOW_MS)}",
        ]
        if result.average is not None:
            parts.append(f"{tr('diag.avg')}: {result.average:.0f} мс")
        return " · ".join(parts)

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


# ------------------------------------------------------------ страница


class DiagnosticsPage(BasePage):
    """Перебирает все стратегии и предлагает выбрать самую быструю."""

    # True — прогон идёт, и уйти со страницы нельзя
    busy_changed = Signal(bool)

    # Пауза между стратегиями. 150 мс хватало на выход процесса, но не на
    # освобождение фильтра WinDivert: следующая копия winws.exe успевала
    # стартовать раньше, чем ядро убирало предыдущий фильтр, и получала
    # «The object is referenced by other objects so cannot be deleted».
    # В журнале это выглядело как внезапные «windivert: error opening filter»
    # пачками по пять-шесть стратегий подряд.
    _NEXT_DELAY_MS = 900
    # Ещё длиннее — когда стратегия всё-таки не запустилась: повтор должен
    # начаться с заведомо чистого состояния.
    _RESTART_DELAY_MS = 2000

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        # Заметки страницы (служба остановлена / возвращена и т.п.).
        # Страница больше не держит собственный журнал — текст уходит в
        # журнал текущей стратегии и в итог прогона.
        self._page_notes: List[str] = []
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
        # отмечены не все стратегии — во время прогона остальные скрыты
        self._partial_pick = False
        # почему последняя стратегия не смогла запуститься: после прогона
        # это показываем в карточке вместо молчаливого «рабочих не найдено»
        self._last_failure = ""
        # хронометраж прогона: без него нельзя сказать, сколько осталось
        # ждать, и девять минут перебора выглядят как зависание
        self._durations: Dict[str, float] = {}
        # True, когда текущую стратегию пропускаем кнопкой «Пропустить»
        self._skipping = False
        # сколько повторов ушло на стратегию, которая не смогла запуститься:
        # один повтор на стратегию, иначе прогон растягивается вдвое
        self._retries: Dict[str, int] = {}
        # перестраивать ли список стратегий после прогона. Для одиночной
        # проверки — нет: сравнивать одну стратегию не с чем, а прыгающий
        # список выглядит как поломка.
        self._reorder_after_run = True
        # службу zapret пришлось погасить ради прогона — её надо вернуть.
        # Пакет zapret-discord-youtube штатно ставит winws.exe службой, и
        # служба со standalone-запуском не уживаются: фильтр WinDivert один.
        self._service_stopped = False
        self._started_at = 0.0
        self._step_started_at = 0.0
        # что сам компонент сказал при запуске каждой стратегии: «нужны
        # права администратора», «служба zapret активна» и т.п. Раньше эти
        # строки уходили только в общий журнал, и в строке стратегии
        # оставалось «Нет доступа» без объяснения причины.
        self._start_log: Dict[str, List[str]] = {}
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

        # Без прав администратора winws.exe не запускается вообще, и все
        # стратегии сразу получают «нет доступа» — выглядит как поломка
        # диагностики. Поэтому причина называется прямо, с кнопкой.
        self.admin_banner = self._build_admin_banner()
        self.add(self.admin_banner)

        self.add(self._build_controls())
        self.live_card = LiveCard()
        self.live_card.apply_requested.connect(self._choose)
        self.live_card.admin_requested.connect(self._relaunch_as_admin)
        self.add(self.live_card)

        # --- заголовок списка стратегий: счётчик + «отметить все/снять все» ---
        self.add(self._build_strategies_header())

        # --- список: одна стратегия в строке ---
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        self.add(self.rows_host, 1)

        self.add(self._build_targets())

    def _build_admin_banner(self) -> QWidget:
        """Предупреждение: без прав администратора диагностика бессмысленна."""
        card = QFrame()
        card.setObjectName("AdminBanner")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(12)

        icon = QLabel()
        icon.setFixedSize(22, 22)
        icon.setPixmap(
            icons.icon_pixmap("alert", theme.PALETTE["amber"], 22, 1.9)
        )
        layout.addWidget(icon, 0, Qt.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(tr("diag.admin_title"))
        title.setObjectName("cardTitle")
        text.addWidget(title)
        hint = HintLabel(tr("diag.admin_hint"))
        hint.setWordWrap(True)
        text.addWidget(hint)
        layout.addLayout(text, 1)

        self.admin_button = IconButton(
            "power", tr("diag.admin_relaunch"), "glassPrimary"
        )
        self.admin_button.setToolTip(tr("diag.admin_relaunch_hint"))
        self.admin_button.clicked.connect(self._relaunch_as_admin)
        layout.addWidget(self.admin_button, 0, Qt.AlignVCenter)
        return card

    def _refresh_admin_banner(self) -> None:
        """Показывает предупреждение, пока программа без прав администратора."""
        from ...core import win32

        need = bool(win32.IS_WINDOWS) and not win32.is_admin()
        self.admin_banner.setVisible(need)

    def _relaunch_as_admin(self) -> None:
        """Перезапуск программы с повышением прав (UAC)."""
        from PySide6.QtWidgets import QApplication

        from ...core import win32

        if not win32.IS_WINDOWS:
            show_toast(self, tr("status.windows_only"), "warning")
            return
        if win32.relaunch_elevated():
            show_toast(self, tr("status.admin_restarting"), "info", duration=2000)
            QApplication.quit()
            return
        show_toast(self, tr("diag.admin_failed"), "error", duration=6000)

    def _build_controls(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        layout = QHBoxLayout()
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
        # «Пропустить» — убрать зависшую стратегию из прогона, не бросая
        # его целиком: раньше единственным выходом был «Остановить».
        self.skip_button = IconButton("skip-forward", tr("diag.skip"), "glass")
        self.skip_button.setToolTip(tr("diag.skip_hint"))
        self.skip_button.clicked.connect(self._skip_current)
        self.skip_button.setVisible(False)
        buttons.addWidget(self.skip_button)
        # проверка запуска: показывает, почему стратегии не измеряются
        self.probe_button = IconButton("terminal", tr("diag.probe"), "glass")
        self.probe_button.setToolTip(tr("diag.probe_hint"))
        self.probe_button.clicked.connect(self._run_probe)
        buttons.addWidget(self.probe_button)
        # одна кнопка на два состояния: «Протестировать» ↔ «Остановить».
        self.start_button = IconButton("activity", tr("diag.start"), "glassPrimary")
        self.start_button.clicked.connect(self._on_start_clicked)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)
        outer.addLayout(layout)

        # --- прогресс прогона ---
        # Прогон 22 стратегий — это около девяти минут. Без счётчика и
        # оценки времени окно выглядело зависшим: строки просто мигали.
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("RunProgress")
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        self.progress_text = QLabel("")
        self.progress_text.setObjectName("muted")
        self.progress_text.setVisible(False)
        outer.addWidget(self.progress_text)
        return card

    def _build_strategies_header(self) -> QWidget:
        """Строка над списком: сколько стратегий и кнопки выбора.

        Кнопки «Отметить все» / «Снять все» раньше были крошечными
        иконками без подписей — их почти не видели. Теперь это обычные
        кнопки с текстом.
        """
        bar = QWidget()
        bar.setObjectName("SectionBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        self.results_icon = QLabel()
        self.results_icon.setFixedSize(20, 20)
        layout.addWidget(self.results_icon, 0, Qt.AlignVCenter)

        self.results_text = QLabel(tr("diag.strategies"))
        self.results_text.setObjectName("sectionTitle")
        self.results_text.setWordWrap(True)
        layout.addWidget(self.results_text, 1)

        self.pick_all = IconButton("check-square", tr("diag.pick_all"), "glass")
        self.pick_all.setToolTip(tr("diag.pick_all_hint"))
        self.pick_all.clicked.connect(lambda: self._set_all_picked(True))
        layout.addWidget(self.pick_all, 0, Qt.AlignVCenter)

        self.pick_none = IconButton("square", tr("diag.pick_none"), "glass")
        self.pick_none.setToolTip(tr("diag.pick_none_hint"))
        self.pick_none.clicked.connect(lambda: self._set_all_picked(False))
        layout.addWidget(self.pick_none, 0, Qt.AlignVCenter)
        return bar

    def _set_all_picked(self, picked: bool) -> None:
        """Ставит или снимает галочки у всех стратегий сразу."""
        if picked:
            self._picked.update(self._order)
        else:
            self._picked.clear()
        for name, row in self._rows.items():
            row.set_picked(name in self._picked)
        self._update_buttons()

    def _build_targets(self) -> QWidget:
        """Карточка проверяемых целей: список только для чтения.

        Править его вручную нельзя — он приходит из utils/targets.txt пакета
        zapret, чтобы наши тесты совпадали с тестами самого пакета. Вернуть
        стандартный список можно кнопкой ниже. Карточка свёрнута: это
        дополнительная настройка, а не то, чем пользуются каждый запуск.
        """
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        label = QLabel(tr("diag.targets_title"))
        label.setObjectName("cardTitle")
        head.addWidget(label, 1)
        self.targets_toggle = IconButton(
            "chevron-down", tr("diag.targets_show"), "glass"
        )
        self.targets_toggle.setCheckable(True)
        self.targets_toggle.clicked.connect(self._toggle_targets)
        head.addWidget(self.targets_toggle, 0, Qt.AlignVCenter)
        layout.addLayout(head)

        self.targets_hint = HintLabel(tr("diag.targets_hint"))
        self.targets_hint.setVisible(False)
        layout.addWidget(self.targets_hint)

        self.targets_edit = QPlainTextEdit()
        self.targets_edit.setObjectName("TargetsEdit")
        self.targets_edit.setReadOnly(True)
        self.targets_edit.setMinimumHeight(120)
        self.targets_edit.setMaximumHeight(200)
        self.targets_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.targets_edit.setPlainText(self._targets_text())
        self.targets_edit.setVisible(False)
        layout.addWidget(self.targets_edit)

        # Счётчик «Целей: N · проверок на стратегию: M» и кнопка
        # «Стандартные сайты» убраны по просьбе: список править нельзя,
        # поэтому оба элемента только занимали место и путали.

        self.targets_edit.textChanged.connect(self._on_targets_changed)
        return card

    def _toggle_targets(self, expanded: bool) -> None:
        self.targets_hint.setVisible(expanded)
        self.targets_edit.setVisible(expanded)
        self.targets_toggle.setChecked(expanded)
        self.targets_toggle.setText(
            tr("diag.targets_hide") if expanded else tr("diag.targets_show")
        )
        self.targets_toggle.set_icon(
            "chevron-up" if expanded else "chevron-down"
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

        self._refresh_admin_banner()
        self._order = strategies
        self._results.clear()
        self._index = 0
        # новые стратегии отмечаем сразу: снимать галочки по одной —
        # лишняя возня
        self._picked.update(
            name for name in strategies if name not in self._picked
        )
        self._clear_rows()
        for name in strategies:
            row = StrategyRow(name)
            row.bind_start_log(self._start_log)
            row.chosen.connect(self._choose)
            row.test_requested.connect(self.test_one)
            row.pick_changed.connect(self._on_pick_changed)
            row.log_toggled.connect(self._on_row_log_toggled)
            row.set_picked(name in self._picked)
            self._rows[name] = row

        self.live_card.hide_card()
        self._layout_rows()
        self._update_buttons()

    def _layout_rows(self) -> None:
        """Раскладывает стратегии списком: проверенные сверху, по рейтингу."""
        ordered = rank(list(self._results.values())) if self._results else []
        names = [result.name for result in ordered]
        names += [name for name in self._order if name not in names]

        # Снимаем строки с макета и раскладываем заново. Раньше здесь
        # ещё и вызывался setParent(None) — виджет на миг становился
        # отдельным окном, и после возврата в макет пересчёт размеров
        # ломался: строка не растягивалась под раскрытый журнал. takeAt
        # родителя не меняет, поэтому setParent не нужен.
        while self.rows_layout.count() > 1:
            widget = self.rows_layout.takeAt(0).widget()
            if widget is not None:
                self.rows_layout.removeWidget(widget)

        for position, name in enumerate(names):
            row = self._rows.get(name)
            if row is None:
                continue
            self.rows_layout.insertWidget(position, row)
        # список не тянется по вертикали: строки держат свой размер
        self.rows_host.updateGeometry()
        self.rows_layout.invalidate()
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        """Во время прогона показывает только отмеченные стратегии.

        Если отмечены не все, прогон идёт долго, и листать чужие строки
        смысла нет — они просто мешают. После прогона возвращаются все.
        """
        for name, row in self._rows.items():
            if self._running and self._partial_pick:
                row.setVisible(name in self._picked)
            else:
                row.setVisible(True)

    def _on_row_log_toggled(self, name: str, opened: bool) -> None:
        """После раскрытия журнала просим страницу пересчитать размер.

        Раньше из-за этого и ломался стиль: строка оставалась сплющенной
        или оставляла за собой пустоту.
        """
        widget = self.rows_host
        widget.updateGeometry()
        self.scroll.widget().updateGeometry()
        self.scroll.updateGeometry()

    def _clear_rows(self) -> None:
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    def on_show(self) -> None:
        self.reload()

    def refresh_status(self) -> None:
        self._update_buttons()

    # ------------------------------------------------------------ цели

    def _targets(self) -> list:
        # splitlines() обязателен: parse_targets принимает список строк, а
        # строка для него — последовательность символов. Без разбивки
        # каждая буква текста становилась целью, и замер отвечал
        # «сайты не открылись» по всем стратегиям.
        return parse_targets(self.targets_edit.toPlainText().splitlines())

    def _component_targets_file(self):
        """utils/targets.txt пакета zapret, если пакет уже установлен."""
        try:
            return self.ctx.zapret.utils_dir / "targets.txt"
        except Exception:  # noqa: BLE001 - компонент может быть не готов
            return None

    def _targets_text(self) -> str:
        text = self._component_targets_file()
        lines = default_target_lines(text) if text else default_target_lines()
        return "\n".join(lines) + "\n"

    def _on_targets_changed(self) -> None:
        """Список целей тронули — свой текст больше не подтягиваем из пакета."""
        self.targets_dirty = True

    def _save_targets(self) -> bool:
        targets = self._targets()
        if not targets:
            show_toast(self, tr("diag.targets_empty"), "warning")
            return False
        return True

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
        # отмечены не все — во время прогона остальные скрываем
        self._partial_pick = len(self._queue) < len(self._order)
        self._reorder_after_run = len(self._queue) > 1
        self._begin()

    def test_one(self, name: str) -> None:
        """Прогон одной стратегии — кнопка на её строке."""
        if self._running or name not in self._rows:
            return
        if not self._save_targets():
            return
        self._queue = [name]
        self._partial_pick = False
        # одну стратегию сравнивать не с чем: после её проверки список не
        # перестраивается, иначе единственная проверенная строка прыгает
        # наверх, а все остальные съезжают вниз — выглядит как поломка
        self._reorder_after_run = False
        self._begin()

    def _begin(self) -> None:
        self._running = True
        self._cancelled = False
        self._skipping = False
        self._last_failure = ""
        # Чистим на месте, а не подменяем словарь: строки получают ссылку
        # на него один раз в reload() (bind_start_log). Подмена отвязывала
        # их — журнал компонента уходил в новый словарь, а строка читала
        # старый и всегда видела пустоту. Из-за этого «почему стратегия не
        # поехала» не находилось в журнале и причина молча подменялась
        # общим «сайты не открылись».
        self._start_log.clear()
        # ловим строки компонента: они и объясняют, почему стратегия не
        # поехала. Отписываемся в _finish, иначе накапливаются подключения.
        try:
            self.ctx.zapret.log_line.connect(self._on_component_log)
        except Exception:  # noqa: BLE001 - сигнал может быть недоступен
            pass
        self._was_running = self.ctx.zapret.is_running()
        self._original = self.ctx.config.zapret.strategy
        self._results.clear()
        self._retries.clear()
        self._index = 0
        self._durations.clear()
        self._started_at = time.monotonic()
        self._step_started_at = self._started_at
        self._show_progress()
        for name in self._order:
            row = self._rows[name]
            row.set_status(WAIT)
            row.set_rank(0)
            row.mark_best(False)
            row.set_active(False)
            row.set_untested(False)
            row.set_log_open(False)
        self._layout_rows()
        if self._was_running:
            self.ctx.zapret.stop()
        self._stop_service_for_run()
        self._update_buttons()
        self._run_current()

    def _stop_service_for_run(self) -> None:
        """Гасит службу zapret на время прогона.

        Пакет zapret-discord-youtube штатно работает через службу
        (``service.bat``), а служба и прямой запуск ``winws.exe`` не
        уживаются — фильтр WinDivert один на систему. Свой же ``service.bat``
        в этом случае пишет: «use service.bat and choose Remove Services
        first if you want to run standalone bat».

        Раньше Hub этого не делал: ``_start_reason`` честно сообщал «служба
        активна» по каждой стратегии, и прогон не давал ничего — хотя
        достаточно было остановить службу на время замера и вернуть её после.
        """
        self._service_stopped = False
        try:
            state = self.ctx.zapret.service_state()
        except Exception:  # noqa: BLE001 - проверка может быть недоступна
            return
        if not state or state in ("STOPPED", "STOP_PENDING"):
            return
        self._page_note(
            tr("diag.stopping_service", state=state)
        )
        try:
            if win32.stop_service(SERVICE_NAME):
                self._service_stopped = True
                self._page_note(tr("diag.service_stopped"))
            else:
                self._page_note(tr("diag.service_stop_failed"))
        except Exception as exc:  # noqa: BLE001
            self._page_note(f"[hub] {exc}")

    def _restore_service_after_run(self) -> None:
        """Возвращает службу zapret, если мы её гасили ради прогона.

        Обёрнуто целиком: этот метод зовут из ``_finish``, и любая ошибка
        здесь оборвала бы показ результатов — прогон уже отработал, а
        пользователь не увидел бы итог.
        """
        if not self._service_stopped:
            return
        self._service_stopped = False
        self._page_note(tr("diag.restoring_service"))
        try:
            if win32.start_service(SERVICE_NAME):
                self._page_note(tr("diag.service_restored"))
            else:
                self._page_note(tr("diag.service_restore_failed"))
        except Exception as exc:  # noqa: BLE001 - итог прогона важнее
            self._page_note(f"[hub] {exc}")

    def stop_testing(self) -> None:
        if not self._running:
            return
        self._cancelled = True
        if self._tester is not None:
            self._tester.cancel()

    def _start_reason(self, name: str) -> str:
        """Причина, по которой стратегию нельзя проверить. Пусто — можно.

        Раньше здесь не было ничего: `zapret.start()` молча возвращал
        False, и все 22 стратегии получали «Нет доступа». Теперь причина
        проверяется заранее и называется словами.
        """
        from ...core import win32

        if not self.ctx.zapret.installed():
            return tr("diag.not_installed")
        if win32.IS_WINDOWS and not win32.is_admin():
            return tr("diag.admin_needed")
        conflict = ""
        try:
            conflict = self.ctx.zapret.service_conflict() or ""
        except Exception:  # noqa: BLE001 - проверка может быть недоступна
            conflict = ""
        if conflict:
            return tr("diag.service_conflict", name=conflict)
        try:
            exe, _args = self.ctx.zapret.parse_strategy()
        except Exception as exc:  # noqa: BLE001 - битый .bat
            return str(exc) or tr("diag.start_failed")
        if not exe.exists():
            return tr("diag.exe_missing", name=exe.name)
        return ""

    def _run_next(self) -> None:
        self._index += 1
        self._run_current()

    def _run_current(self) -> None:
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

        self._step_started_at = time.monotonic()
        self._show_progress()
        self.ctx.config.zapret.strategy = name
        reason = self._start_reason(name)
        if reason:
            # запускать нечего или нечем: причина называется прямо, иначе
            # все стратегии подряд получали «нет доступа», и выглядело это
            # как поломка диагностики, а не как отсутствие прав
            self._last_failure = reason
            row.set_status(FAIL, reason)
            row.set_active(False)
            self.live_card.show_failure(reason)
            self._note_duration()
            self._show_progress()
            QTimer.singleShot(self._NEXT_DELAY_MS, self._run_next)
            return

        # Стратегия обязана меняться физически. ZapretComponent.start()
        # возвращает True, если winws уже жив, и тогда новый процесс не
        # поднимается вовсе: остаётся winws от прошлой стратегии, и все
        # стратегии подряд мерили бы один и тот же процесс — ровно та
        # картина, когда «сайты не открылись» на каждой строке.
        # _on_measured гасит процесс штатно, но если замер не завершился
        # (сбой, отмена), здесь страховка. restart() добивает процесс
        # даже когда winws не реагирует на terminate.
        try:
            started = self.ctx.zapret.restart()
        except Exception as exc:  # noqa: BLE001 - компонент может не подняться
            started = False
            reason = str(exc) or tr("diag.start_failed")
            self._last_failure = reason
        if not started:
            # не смогли запустить — считаем стратегию непроверенной.
            # Индекс двигает _run_next: здесь инкремент означал бы, что
            # следующая стратегия пропускается.
            row.set_status(FAIL, reason or tr("diag.start_failed"))
            row.set_active(False)
            self.live_card.show_failure(reason or tr("diag.start_failed"))
            self._note_duration()
            self._show_progress()
            QTimer.singleShot(self._NEXT_DELAY_MS, self._run_next)
            return

        self._tester = StrategyTester(
            name,
            targets=self._targets(),
            alive=self.ctx.zapret.is_running,
        )
        self._tester.log.connect(self._on_test_log)
        self._tester.measured.connect(self._on_measured)
        self._tester.start()

    def _show_leader(self) -> None:
        """Обновляет «лидера на данный момент» в карточке прогона."""
        if not self._results:
            self.live_card.set_leader(None)
            return
        ordered = rank(list(self._results.values()))
        self.live_card.set_leader(ordered[0] if ordered else None)

    def _show_progress(self) -> None:
        """Счётчик прогона: сколько готово, сколько прошло и сколько осталось.

        Оценка — по среднему времени уже проверенных стратегий, поэтому
        она становится точнее с каждой следующей.
        """
        total = len(self._queue)
        # индекс не должен убежать за очередь: показывать «5 из 4» глупо
        done = min(self._index, total)
        if not self._running or not total:
            self.progress_bar.setVisible(False)
            self.progress_text.setVisible(False)
            return
        self.progress_bar.setVisible(True)
        self.progress_text.setVisible(True)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(min(done, total))

        parts = [tr("diag.progress_count", done=done, total=total)]
        elapsed = time.monotonic() - self._started_at
        if done and elapsed > 1.0:
            average = elapsed / done
            left = average * (total - done)
            parts.append(tr("diag.progress_spent", minutes=elapsed / 60.0))
            if left >= 1.0:
                parts.append(tr("diag.progress_left", minutes=left / 60.0))
        self.progress_text.setText(" · ".join(parts))

    def _run_probe(self) -> None:
        """Запускает стратегию один раз и показывает, что с ней не так.

        Прогон всех стратегий занимает минуты, и если ``winws.exe`` не
        держится по общей причине (права, служба, занятый файл), все они
        получают отказ — и выглядит это как «диагностика сломалась». Эта
        кнопка отвечает за секунды и говорит прямо, в чём дело.
        """
        from PySide6.QtWidgets import QApplication

        if self._running:
            return
        name = self.ctx.config.zapret.strategy
        self.live_card.show_probe_started(name)
        self.probe_button.setEnabled(False)
        QApplication.processEvents()

        report = self.ctx.zapret.probe_start(3.0)
        self.probe_button.setEnabled(True)
        self.live_card.show_probe(report, name)

    def _skip_current(self) -> None:
        """Пропустить стратегию, которая проверяется прямо сейчас.

        Сам замер останавливаем через ``cancel()`` — поток сам доработает
        до конца и пришлёт ``measured``. Дальше ведёт себя ``_on_measured``:
        если стоял флаг пропуска, partial-результат выбрасывается. Иначе
        получилось бы два потока замера одновременно.
        """
        if not self._running or self._tester is None:
            return
        self._skipping = True
        self._tester.cancel()

    def _note_duration(self) -> None:
        """Запоминает, сколько ушло на только что снятую стратегию."""
        if self._step_started_at:
            self._durations[self._index - 1] = time.monotonic() - self._step_started_at
        self._step_started_at = time.monotonic()

    def _page_note(self, text: str) -> None:
        """Сообщение страницы, не привязанное к стратегии.

        У страницы нет своего виджета журнала: ``log_view`` принадлежит
        строке стратегии, и обращение к нему с уровня страницы — это
        AttributeError. Раньше такие сообщения (остановка службы) уходили
        в несуществующий ``self.log_line`` и роняли прогон на середине.
        Теперь текст копится в список и попадает в журнал текущей
        стратегии, чтобы его можно было открыть и прочитать.
        """
        text = (text or "").strip()
        if not text:
            return
        self._page_notes.append(text)
        if len(self._page_notes) > 40:
            del self._page_notes[:-40]
        if 0 <= self._index < len(self._queue):
            name = self._queue[self._index]
            box = self._start_log.setdefault(name, [])
            box.append(text)
            if len(box) > 40:
                del box[:-40]
            row = self._rows.get(name)
            if row is not None and row._log_open:
                row._fill_log()

    def _on_component_log(self, line: str) -> None:
        """Строка из журнала zapret — в журнал той стратегии, что запускается.

        Именно здесь появляется «нужны права администратора»: самая частая
        причина, почему все стратегии сразу уходили в «Нет доступа».
        """
        text = (line or "").strip()
        if not text:
            return
        if self._index >= len(self._queue):
            return
        name = self._queue[self._index]
        box = self._start_log.setdefault(name, [])
        box.append(text)
        if len(box) > 40:
            del box[:-40]
        row = self._rows.get(name)
        if row is not None and row._log_open:
            row._fill_log()

    def _on_test_log(self, line: str) -> None:
        """Строка журнала: страница её больше не показывает.

        Оставлена только как приёмник сигнала тестера — журнал самой
        проверки собран из результатов и открывается кнопкой в строке.
        """
        del line

    def _on_measured(self, result: StrategyResult) -> None:
        tester, self._tester = self._tester, None
        if tester is not None:
            if tester.wait(1500):
                tester.deleteLater()
            else:
                tester.finished.connect(tester.deleteLater)
        try:
            self.ctx.zapret.stop()
        except Exception:  # noqa: BLE001
            pass

        row = self._rows.get(result.name)
        # Стратегия не дожила до замера: процесс умер сразу после старта.
        # Это почти всегда гонка — предыдущая копия winws.exe ещё не отпустила
        # фильтр WinDivert, и новая не смогла его открыть. Один повтор с
        # увеличенной паузой такие случаи вытягивает, и стратегия получает
        # честный замер вместо «winws не запустился».
        if (
            not self._cancelled
            and result.error == DEAD_PROCESS_ERROR
            and self._retries.get(result.name, 0) < 1
        ):
            self._retries[result.name] = 1
            self._page_note(tr("diag.retry_dead", name=result.name))
            QTimer.singleShot(self._RESTART_DELAY_MS, self._run_current)
            return

        if self._skipping:
            # стратегию пропустили: partial-результат не показываем, иначе
            # «0 из 64» выглядел бы как настоящий провал стратегии
            self._skipping = False
            if row is not None:
                row.set_status(FAIL, tr("diag.skipped"))
                row.set_active(False)
        else:
            if row is not None:
                if result.error:
                    row.set_status(FAIL, _error_text(result.error))
                else:
                    row.set_result(result)
                row.set_active(False)
            self.live_card.show_result(result)
            self._results[result.name] = result
            self._show_leader()
        self._note_duration()
        self._show_progress()
        if self._cancelled:
            self._finish()
        else:
            # индекс двигает _run_next; повтор (см. выше) уходит напрямую
            # в _run_current и тем самым остаётся на той же стратегии
            QTimer.singleShot(self._NEXT_DELAY_MS, self._run_next)

    def _finish(self) -> None:
        """Итог прогона: лучшая стратегия становится текущей сама."""
        self._running = False
        self._cancelled = False
        self._skipping = False
        try:
            self.ctx.zapret.log_line.disconnect(self._on_component_log)
        except Exception:  # noqa: BLE001 - могло не подключиться
            pass
        try:
            self.ctx.zapret.stop()
        except Exception:  # noqa: BLE001
            pass
        # службу возвращаем до применения результата: если прогон шёл со
        # службой, вернуть её надо в любом случае — хоть с лучшей стратегией,
        # хоть нет
        self._restore_service_after_run()

        best = self.apply_results(list(self._results.values()))
        self._apply_best_after_run(best)
        self._update_buttons()
        self._show_progress()

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
                except Exception:  # noqa: BLE001
                    pass
            return

        self.ctx.config.zapret.strategy = best.name
        self.ctx.save_config()
        if self._was_running:
            try:
                self.ctx.zapret.start()
            except Exception:  # noqa: BLE001
                pass
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

        Стратегии, которых не было в прогоне, горят красным и получают
        крест вместо места в рейтинге — сразу видно, что сравнивать нечего.
        """
        self._results = {result.name: result for result in results}
        ordered = rank(results)
        best = ordered[0] if ordered else None

        for name in self._order:
            row = self._rows.get(name)
            if row is None:
                continue
            if name in self._results:
                row.set_untested(False)
            else:
                row.set_untested(True)
                row.mark_best(False)
                row.set_active(False)

        if best is not None and best.ok > 0:
            for position, result in enumerate(ordered, start=1):
                row = self._rows.get(result.name)
                if row is None:
                    continue
                row.set_rank(position)
                row.mark_best(position == 1)
            if self._reorder_after_run:
                self._layout_rows()
            self.live_card.show_best(best, ordered[1:])
        else:
            show_toast(self, tr("diag.no_best"), "error", duration=6000)
            # «рабочих не найдено» без объяснения бесполезно: если всё
            # свалилось из-за прав, об этом и надо сказать
            self.live_card.show_failure(self._last_failure or tr("diag.no_best"))
        self._update_buttons()
        return best if (best is not None and best.ok > 0) else None

    def _update_buttons(self) -> None:
        picked = len(self._picked_names())
        has_rows = bool(self._order)
        if self._running:
            self.start_button.set_icon("stop", theme.PALETTE["red"])
            self.start_button.setText(tr("diag.stop"))
            self.start_button.setToolTip(tr("diag.stop_hint"))
            self.start_button.setEnabled(True)
            self.skip_button.setVisible(True)
        else:
            self.start_button.set_icon("activity")
            self.start_button.setText(
                tr("diag.start_count", count=picked) if picked else tr("diag.start")
            )
            self.start_button.setToolTip(tr("diag.start_hint"))
            self.start_button.setEnabled(has_rows)
            self.skip_button.setVisible(False)
        self.pick_all.setEnabled(has_rows and not self._running)
        self.pick_none.setEnabled(has_rows and not self._running)
        for row in self._rows.values():
            row.set_busy(self._running)
        self._update_results_text()
        self.busy_changed.emit(self._running)

    def _update_results_text(self) -> None:
        count = len(self._order)
        picked = len(self._picked_names())
        checked = len(self._results)
        text = tr("diag.strategies")
        parts = [f"{text}", f"{picked}/{count}"]
        if checked:
            parts.append(tr("diag.tested_count", count=checked))
        if self._running and self._partial_pick:
            # пока идёт прогон, в списке только отмеченные — сказать об
            # этом надо, иначе непроверенные стратегии выглядит потерянными
            parts.append(tr("diag.only_picked"))
        self.results_text.setText(" · ".join(parts))
        tone = theme.PALETTE["accent"]
        self.results_icon.setPixmap(icons.icon_pixmap("layers", tone, 20, 1.8))

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
        restarted = False
        error = ""
        if self.ctx.zapret.is_running():
            try:
                self.ctx.zapret.restart()
                restarted = True
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
        # выбор стратегии — важное событие, поэтому всегда с уведомлением
        if error:
            show_toast(
                self,
                tr("diag.chosen_error", name=name, error=error),
                "error",
            )
        elif restarted:
            show_toast(self, tr("diag.chosen_restarted", name=name), "success")
        else:
            show_toast(self, tr("diag.chosen", name=name), "success")
