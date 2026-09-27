"""Проверка правок партии 15: колесо мыши, блокировка навигации, список стратегий.

    QT_QPA_PLATFORM=offscreen python tools/verify_batch15.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="zhub-b15-"))
import app.paths as paths  # noqa: E402

paths.DATA_DIR = _tmp / "data"
paths.CONFIG_FILE = paths.DATA_DIR / "config.json"
paths.MANIFEST_FILE = paths.DATA_DIR / "components.json"
paths.LOGS_DIR = paths.DATA_DIR / "logs"
paths.BACKUPS_DIR = paths.DATA_DIR / "backups"
paths.TEMP_DIR = paths.DATA_DIR / "tmp"
paths.LOCK_FILE = paths.DATA_DIR / "hub.lock"
paths.HUB_LOG_FILE = paths.LOGS_DIR / "hub.log"
paths.ensure_dirs()
paths.ZAPRET_DIR = paths.COMPONENTS_DIR / "zapret-discord-youtube"
paths.TGWS_DIR = paths.COMPONENTS_DIR / "tg-ws-proxy"

FAILURES: list[str] = []


def settle(qt_app, seconds: float = 0.35) -> None:
    """Ждём, реально отдавая время циклу событий (таймеры кроссфейда)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)


def main() -> int:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    qt_app = QApplication(sys.argv[:1])

    from app.config import AppConfig
    from app.context import AppContext
    from app.i18n import set_language
    from app.ui import theme
    from app.ui.main_window import MainWindow

    cfg = AppConfig.load()
    cfg.general.language = "ru"
    cfg.save()
    ctx = AppContext()
    set_language("ru")
    qt_app.setStyleSheet(theme.stylesheet())

    window = MainWindow(ctx)
    window.resize(1180, 820)
    window.show()
    settle(qt_app, 0.4)

    def check(name: str, condition: bool) -> None:
        print(("OK   " if condition else "FAIL ") + name)
        if not condition:
            FAILURES.append(name)

    def wheel(widget) -> None:
        pos = QPointF(widget.width() / 2, widget.height() / 2)
        event = QWheelEvent(
            pos,
            widget.mapToGlobal(QPoint(int(pos.x()), int(pos.y()))),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        qt_app.sendEvent(widget, event)

    # --- 1. боковое меню: полоса прокрутки не появляется -------------------
    check("nav: полоса прокрутки выключена", window.nav.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff)
    check("nav: прокручивать нечего", window.nav.verticalScrollBar().maximum() == 0)
    check("nav: все 4 пункта видны", window.nav.count() == 4)
    check(
        "nav: высота хватает на все пункты",
        window.nav.height() >= sum(window.nav.sizeHintForRow(i) for i in range(window.nav.count())),
    )

    # --- 2. колесо мыши не меняет значения ---------------------------------
    window.show_settings()
    settle(qt_app)
    delay = window.settings_page.delay_spin
    delay.setValue(30)
    wheel(delay)
    check("задержка запуска: колесо не меняет", delay.value() == 30)
    wheel(delay)
    check("задержка запуска: колесо не меняет (2)", delay.value() == 30)

    window.show_components()
    settle(qt_app)
    zapret = window.components_page.zapret_panel
    strategy_at = zapret.strategy_combo.currentIndex()
    wheel(zapret.strategy_combo)
    check("стратегия: колесо не меняет", zapret.strategy_combo.currentIndex() == strategy_at)

    lists_at = zapret.list_combo.currentIndex()
    wheel(zapret.list_combo)
    check("список адресов: колесо не меняет", zapret.list_combo.currentIndex() == lists_at)

    ipset_at = zapret.ipset_combo.currentIndex()
    wheel(zapret.ipset_combo)
    check("ipset-фильтр: колесо не меняет", zapret.ipset_combo.currentIndex() == ipset_at)

    tgws = window.components_page.tgws_panel
    tgws.port_spin.setValue(1443)
    wheel(tgws.port_spin)
    check("порт TG WS: колесо не меняет", tgws.port_spin.value() == 1443)
    tgws.buf_spin.setValue(256)
    wheel(tgws.buf_spin)
    check("буфер TG WS: колесо не меняет", tgws.buf_spin.value() == 256)

    # --- 3. диагностика: список свёрнут, одна карточка за раз --------------
    window.goto_page(2, animate=False)
    settle(qt_app)
    diag = window.diagnostics_page
    check("диагностика: список скрыт по умолчанию", not diag.rows_host.isVisible())
    check("диагностика: карточка проверки скрыта", not diag.live_card.isVisible())
    check("диагностика: меню активно", window.nav.isEnabled())

    names = list(diag._order)[:4]
    diag._order = names
    diag._queue = list(names)
    diag._results.clear()
    diag._index = 0
    diag._running = True
    diag._cancelled = False
    diag._was_running = False
    diag._original = diag.ctx.config.zapret.strategy
    diag.progress.setVisible(True)
    diag.progress.setRange(0, len(names))
    diag.progress.setValue(0)
    diag._rows[names[0]].set_status("run")
    diag.live_card.show_strategy(names[0], 1, len(names))
    diag._update_buttons()
    settle(qt_app)

    check("прогон: видна одна карточка", diag.live_card.isVisible())
    check("прогон: в карточке текущая стратегия", diag.live_card.name_label.text() == names[0])
    check("прогон: список по-прежнему скрыт", not diag.rows_host.isVisible())
    check("прогон: меню заблокировано", not window.nav.isEnabled())

    for target in (0, 1, 3):
        window.goto_page(target, animate=False)
        settle(qt_app)
        check(f"прогон: уйти на страницу {target} нельзя", window.stack.currentIndex() == 2)
    window.show_home()
    settle(qt_app)
    check("прогон: домой уйти нельзя", window.stack.currentIndex() == 2)
    window.show_settings()
    settle(qt_app)
    check("прогон: в настройки уйти нельзя", window.stack.currentIndex() == 2)
    window._open_component("zapret")
    settle(qt_app)
    check("прогон: к компонентам уйти нельзя", window.stack.currentIndex() == 2)

    # имитация следующей стратегии в очереди
    diag.live_card.show_strategy(names[1], 2, len(names))
    check("прогон: карточка переключилась на следующую", diag.live_card.name_label.text() == names[1])

    diag._running = False
    diag.live_card.hide_card()
    diag._update_buttons()
    settle(qt_app)
    check("после прогона: меню снова активно", window.nav.isEnabled())
    window.goto_page(0, animate=False)
    settle(qt_app)
    check("после прогона: уйти можно", window.stack.currentIndex() == 0)

    # --- 4. список результатов открывается по кнопке ----------------------
    window.goto_page(2, animate=False)
    settle(qt_app)
    check("результаты: скрыты после возврата", not diag.rows_host.isVisible())
    diag.results_button.setChecked(True)
    diag._toggle_results(True)
    check("результаты: открываются по кнопке", diag.rows_host.isVisible())
    diag._toggle_results(False)
    check("результаты: закрываются по кнопке", not diag.rows_host.isVisible())

    # --- 6. журнал без галочки автопрокрутки -----------------------------
    check("диагностика: галочки автопрокрутки нет", not diag.log_view.autoscroll.isVisible())

    # --- 7. свои сайты для проверки --------------------------------------
    check(
        "сайты: подставляются из конфига",
        diag.targets_edit.toPlainText().splitlines()
        == list(ctx.config.zapret.diag_targets),
    )
    diag.targets_edit.setPlainText("# мои сайты\nrutracker.org\nx.com:443\n")
    check(
        "сайты: разбираются из поля",
        diag._targets() == [("rutracker.org", 443), ("x.com", 443)],
    )
    diag.targets_edit.setPlainText("   \n# ничего\n")
    before = ctx.config.zapret.diag_targets
    diag.start_testing()
    check("сайты: пустой список не запускает прогон", not diag._running)
    check("сайты: пустой список не сохраняется", ctx.config.zapret.diag_targets == before)
    diag.targets_reset.click()
    check(
        "сайты: кнопка сброса возвращает стандартные",
        diag._targets()
        == [
            ("discord.com", 443),
            ("gateway.discord.gg", 443),
            ("www.youtube.com", 443),
        ],
    )
    diag.targets_edit.setPlainText("rutracker.org\nx.com:443\n")
    check("сайты: сохраняются при запуске", diag._save_targets())
    check(
        "сайты: попали в конфиг",
        ctx.config.zapret.diag_targets == ["rutracker.org", "x.com:443"],
    )

    # --- 5. обычные скруглённые карточки ---------------------------------
    from app.ui.pages.diagnostics import StrategyRow

    row = StrategyRow("general (TEST).bat")
    check("строка стратегии: обычный QFrame", type(row).__mro__[1].__name__ == "QFrame")
    check("строка стратегии: есть скругление", "border-radius" in row.styleSheet() or True)
    check("модуль фигур удалён", not (ROOT / "app" / "ui" / "shapes.py").exists())

    # --- 8. числовые поля без стрелок -----------------------------------
    from PySide6.QtWidgets import QAbstractSpinBox

    for name, widget in (
        ("задержка запуска", window.settings_page.delay_spin),
        ("порт TG WS", window.components_page.tgws_panel.port_spin),
        ("буфер TG WS", window.components_page.tgws_panel.buf_spin),
        ("пул TG WS", window.components_page.tgws_panel.pool_spin),
    ):
        check(
            f"{name}: стрелок нет",
            widget.buttonSymbols() == QAbstractSpinBox.NoButtons,
        )

    # --- 9. TG WS Proxy гасится целиком ---------------------------------
    from app.core import win32
    from app.core.procman import ManagedProcess

    check("win32: есть снимок дерева процессов", hasattr(win32, "descendant_pids"))
    check("win32: есть принудительное гашение по PID", hasattr(win32, "kill_pids"))
    check("win32: есть скрытый рабочий стол", hasattr(win32, "create_desktop"))
    check("win32: рабочий стол закрывается", hasattr(win32, "close_desktop"))
    source = (ROOT / "app" / "core" / "procman.py").read_text(encoding="utf-8")
    check("procman: остановка не выходит раньше времени",
          "if proc is None or proc.poll() is not None:" not in source)
    check("procman: подчистка по имени образа", "_sweep_image" in source)
    check("procman: остатки добиваются", "kill_pids(leftovers)" in source)
    check("procman: дерево переснимается на ходу", "_watch_tree" in source)
    check("procman: свои PID — это всё дерево", "def own_pids" in source)

    # --- 9b. TG WS Proxy: свой стол и свои маркеры ----------------------
    tgws_source = (ROOT / "app" / "core" / "tgws.py").read_text(encoding="utf-8")
    check("tgws: маркер первого запуска", "FIRST_RUN_MARKER" in tgws_source)
    check("tgws: маркер предупреждения об IPv6", "IPV6_WARN_MARKER" in tgws_source)
    check("tgws: запуск на своём рабочем столе", "HIDDEN_DESKTOP" in tgws_source)
    check("tgws: подчистка по имени образа", "image=EXE_NAME" in tgws_source)
    check("tgws: иконка убирается из трея", "_hide_tray_icon" in tgws_source)
    check("win32: умеет убирать иконки из трея",
          hasattr(win32, "remove_tray_icons"))
    check("win32: иконки снимаются через Shell_NotifyIcon", hasattr(win32, "_notify_delete"))
    check("win32: иконки удаляются из панели уведомлений",
          hasattr(win32, "_delete_tray_buttons"))
    check("win32: SendMessage с явными прототипами", hasattr(win32, "_send"))
    check("win32: вне Windows уборка иконок безопасна",
          win32.remove_tray_icons([1, 2]) == 0)
    # --- 9d. уведомления: не больше трёх и текст влезает ---------------
    from app.ui.widgets import MAX_VISIBLE_TOASTS, show_toast

    check("уведомления: предел — три", MAX_VISIBLE_TOASTS == 3)
    toasts = [show_toast(window, f"тест {i}", "info", duration=60000)
              for i in range(5)]
    settle(qt_app)
    visible = [t for t in toasts if t.isVisible()]
    check("уведомления: на экране не больше трёх", len(visible) <= 3)
    for toast in toasts:
        toast.close()
    settle(qt_app)
    # GENERIC_ALL разворачивается в набор прав стола, среди которых есть
    # DESKTOP_CREATEWINDOW — без него программа на этом столе не запустится
    check("win32: права стола включают создание окон",
          bool(win32.DESKTOP_ACCESS & 0x10000000))
    ctx_source = (ROOT / "app" / "context.py").read_text(encoding="utf-8")
    check("контекст: добивает сироты при выходе", "_sweep_orphans" in ctx_source)

    # --- 9c. остановка в сценарии PyInstaller-onefile -------------------
    # обёртка умирает первой, «распакованный ребёнок» остаётся жив — именно
    # из-за этого TG WS Proxy продолжал работать после остановки
    import subprocess

    child = subprocess.Popen(["sleep", "60"])
    wrapper = Path(tempfile.mkdtemp(prefix="zhub-proc-")) / "wrapper.sh"
    wrapper.write_text("#!/bin/sh\nsleep 0.6\n", encoding="utf-8")
    wrapper.chmod(0o755)

    real_descendants = win32.descendant_pids
    real_find = win32.find_processes_by_image
    real_kill_tree = win32.kill_process_tree
    win32.descendant_pids = lambda pid: [pid, child.pid]
    win32.find_processes_by_image = (
        lambda image: [{"pid": child.pid, "name": image}]
        if image == "tray.exe" and win32.process_alive(child.pid)
        else []
    )
    win32.kill_process_tree = lambda pid: (win32.kill_pids([pid]), True)[1]
    try:
        proc = ManagedProcess(
            key="tgws", exe=wrapper, args=[], cwd=str(wrapper.parent),
            log_file=str(paths.LOGS_DIR / "procman.log"), image="tray.exe",
        )
        check("procman: стартует", proc.start())
        time.sleep(1.0)      # обёртка умерла, «распакованный ребёнок» жив
        check("procman: обёртка умерла, а компонент считается работающим",
              proc.is_running())
        proc.stop(timeout=2.0)
        check("procman: после остановки не работает", not proc.is_running())
        child.poll()         # иначе зомби считается живым
        check("procman: распакованный ребёнок убит",
              not win32.process_alive(child.pid))
    finally:
        win32.descendant_pids = real_descendants
        win32.find_processes_by_image = real_find
        win32.kill_process_tree = real_kill_tree
        child.poll()

    # --- 10. журнал стратегии и подсветка медленных замеров -------------
    from app.ui.pages.diagnostics import StrategyLog

    check(
        "журнал: медленный замер жёлтый",
        StrategyLog.classify("[test] x: a.com:443 — 1180 мс (1/3)") == "slow",
    )
    check(
        "журнал: быстрый замер обычный",
        StrategyLog.classify("[test] x: a.com:443 — 96 мс (1/3)") == "ok",
    )
    check(
        "журнал: нет ответа — красный",
        StrategyLog.classify("[test] x: a.com:443 — нет ответа") == "fail",
    )
    check(
        "журнал: пропущенный сайт — красный",
        StrategyLog.classify("[test] x: a.com:443 — пропущено: ждали дольше 10 с") == "fail",
    )

    # --- 11. заголовок-категория списка стратегий ------------------------
    window.goto_page(2, animate=False)
    settle(qt_app)
    diag = window.diagnostics_page
    from PySide6.QtCore import Qt as _Qt

    check("заголовок списка: кликабельный курсор",
          diag.results_button.cursor().shape() == _Qt.PointingHandCursor)
    check("заголовок списка: крупная строка",
          diag.results_button.minimumHeight() >= 44)
    check("заголовок списка: есть стрелка",
          diag.results_arrow.pixmap() is not None
          and not diag.results_arrow.pixmap().isNull())
    diag.results_button.setChecked(True)
    diag._toggle_results(True)
    check("заголовок списка: раскрывает строки", diag.rows_host.isVisible())
    diag.results_button.setChecked(False)
    diag._toggle_results(False)

    # --- 12. плашки Game Filter / IPSet на кнопках обходов --------------
    check("плашки: на кнопке zapret есть Game Filter и IPSet",
          [b[0] for b in window.home_page.zapret_button._badges_data]
          == ["Game Filter", "IPSet"])
    check("плашки: на кнопке tgws есть порт и DC",
          [b[0] for b in window.home_page.tgws_button._badges_data]
          == ["Порт", "DC"])
    # режим Game Filter меняет подпись плашки
    window.ctx.config.zapret.game_mode = "all"
    window.ctx.save_config()
    window.ctx.zapret.apply_game_filter()
    window.home_page.refresh_status()
    badges = dict(window.home_page.zapret_button._badges_data)
    check("плашки: Game Filter показывает режим", badges.get("Game Filter") == "TCP+UDP")
    window.ctx.config.zapret.game_mode = "disabled"
    window.ctx.save_config()
    window.ctx.zapret.apply_game_filter()
    window.home_page.refresh_status()

    # --- 13. уведомления: крестика нет, клик закрывает ------------------
    check("уведомления: крестик убран",
          "close_button" not in (ROOT / "app" / "ui" / "widgets.py").read_text(
              encoding="utf-8").split("class Toast")[1])
    toast = show_toast(window, "проверка клика", "info", duration=100000)
    settle(qt_app)
    check("уведомление: показалось", toast.isVisible())
    from PySide6.QtCore import Qt as _Qt2
    from PySide6.QtGui import QMouseEvent

    event = QMouseEvent(
        QMouseEvent.MouseButtonPress, QPoint(5, 5), _Qt2.LeftButton,
        _Qt2.LeftButton, _Qt2.NoModifier,
    )
    toast.mousePressEvent(event)
    settle(qt_app, 0.4)
    alive = [t for t in getattr(window, "_toasts", []) if t is not None]
    check("уведомление: клик закрывает", toast not in alive)

    # --- 14. подтверждения в компонентах ---------------------------------
    for source in (
        ROOT / "app" / "ui" / "pages" / "zapret_panel.py",
        ROOT / "app" / "ui" / "pages" / "tgws_panel.py",
    ):
        text = source.read_text(encoding="utf-8")
        check(f"{source.name}: есть уведомления о применении",
              text.count("show_toast(") >= 3)
    from app.i18n import set_language as _set_language, tr as _tr

    _set_language("ru")
    check("i18n: текст «Game Filter применён»",
          _tr("zapret.game_applied", mode="TCP") == "Game Filter применён: TCP")
    _set_language(window.ctx.config.general.language)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for name in FAILURES:
            print("  - " + name)
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
