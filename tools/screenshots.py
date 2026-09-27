"""Скриншоты интерфейса (offscreen) для визуальной проверки.

    QT_QPA_PLATFORM=offscreen python tools/screenshots.py [out_dir]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "screenshots")


def settle(qt_app, iterations: int = 4) -> None:
    """Дать интерфейсу время на layout и анимации (offscreen)."""
    for _ in range(iterations):
        qt_app.processEvents()
        time.sleep(0.05)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    qt_app = QApplication(sys.argv[:1])

    # тестовое окружение: компоненты из проекта, данные во временной папке
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="zhub-shot-"))
    import app.paths as paths

    paths.DATA_DIR = tmp / "data"
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

    from app.config import AppConfig
    from app.i18n import tr as tr_text
    from app.context import AppContext
    from app.i18n import set_language
    from app.ui import theme
    from app.ui.main_window import MainWindow
    from app.ui.update_dialog import UpdateDialog

    cfg = AppConfig.load()
    cfg.general.language = "ru"
    cfg.general.theme = "dark"
    cfg.save()

    ctx = AppContext()
    set_language("ru")
    qt_app.setStyleSheet(theme.stylesheet())
    qt_app.setStyle(theme.ScrollbarStyle(qt_app.style()))

    window = MainWindow(ctx)
    window.resize(1180, 820)
    window.show()
    settle(qt_app)

    OUT.mkdir(parents=True, exist_ok=True)

    def save(name: str) -> None:
        settle(qt_app)
        window.grab().save(str(OUT / f"{name}.png"))
        print(f"сохранён {OUT / f'{name}.png'}")

    def show(index: int) -> None:
        window.goto_page(index, animate=False)
        settle(qt_app)

    # 1. главная: мастер-кнопка, статусы, сводка
    show(0)
    save("dashboard")

    # 0b. вид предупреждения/рекомендации на главной
    banner = window.home_page.not_installed_banner
    banner.set_kind("warning")
    banner.set_text(tr_text("dash.not_installed_text"))
    banner.setVisible(True)
    save("dashboard_banner")
    banner.setVisible(False)

    # 1b. главная в работающем состоянии (эмуляция запущенных компонентов)
    def fake_running() -> None:
        ctx.any_running = lambda: True  # type: ignore[method-assign]
        for component in (ctx.zapret, ctx.tgws):
            component.is_running = lambda: True  # type: ignore[method-assign]
            component.pid = lambda: 8412  # type: ignore[method-assign]
            component.uptime = lambda: 3725.0  # type: ignore[method-assign]
            type(component).status = property(lambda self: "running")

    fake_running()
    show(0)
    save("dashboard_running")

    # 2. компоненты: обе панели с настройками
    show(1)
    save("components")

    # 3. компоненты с раскрытым журналом zapret
    zapret_panel = window.components_page.zapret_panel
    zapret_panel._toggle_log()
    for line in (
        "winws.exe: стратегия general (ALT) загружена",
        "winws.exe: 88 аргументов командной строки",
        "winws.exe: отслеживание 8431 потока активно",
    ):
        zapret_panel.log_view.append(line)
    window.components_page.scroll.ensureWidgetVisible(zapret_panel.log_view, 40, 300)
    save("components_log")
    zapret_panel._toggle_log()

    # 3b. панель TG WS Proxy (прокрутка к ней)
    window.components_page.scroll.ensureWidgetVisible(window.components_page.tgws_panel, 30, 30)
    save("components_tgws")

    # 3c. диагностика до прогона: автоподбор стратегий и список
    #     проверяемых целей из utils/targets.txt (только чтение)
    show(2)
    diag = window.diagnostics_page
    diag.targets_edit.setPlainText(diag._targets_text())
    save("diagnostics_targets")

    # 3a. диагностика: идёт прогон — карточка «сейчас проверяется»,
    # проверяемая стратегия обведена голубым, кнопка стала «Остановить»
    live_name = diag._order[1] if len(diag._order) > 1 else "general (ALT2).bat"
    diag._running = True
    diag._queue = list(diag._order)
    diag._index = 1
    for name in diag._order:
        diag._rows[name].set_status("wait")
        diag._rows[name].set_rank(0)
        diag._rows[name].set_active(False)
    diag._rows[live_name].set_status("run")
    diag._rows[live_name].set_rank(2)
    diag._rows[live_name].set_active(True)
    diag.live_card.show_strategy(live_name, 2, len(diag._order))
    diag._update_buttons()
    save("diagnostics_live")

    # 3b. диагностика: прогон закончен — карточка стала зелёной
    # «Лучшим выбором» с кнопкой «Применить», стратегии отранжированы
    from app.core.probe import (
        FAIL,
        OK,
        PROTO_HTTP11,
        PROTO_TLS12,
        PROTO_TLS13,
        UNSUP,
        HttpResult,
    )
    from app.core.strategy_test import (
        StrategyResult,
        TargetOutcome,
        parse_targets,
    )

    diag = window.diagnostics_page
    diag._running = False
    diag._cancelled = False
    diag.live_card.hide_card()
    targets = parse_targets(diag._targets_text().splitlines())
    all_sites = {target.key for target in targets}

    def _details(position: int, targets):
        """Подробности по целям для строки стратегии: протоколы и ping.

        Слабая стратегия отличается не только числом отказов, но и их
        раскладкой: у лучшей почти всё зелёное и один медленный ответ, у
        следующих отказы и «не поддержан» выстраиваются в полоску.
        """
        details = {}
        for index, target in enumerate(targets):
            http = {}
            if target.kind == "http":
                for name in (PROTO_HTTP11, PROTO_TLS12, PROTO_TLS13):
                    if position >= 4 and index % 3 == 0 and name == PROTO_TLS13:
                        http[name] = HttpResult(name, UNSUP, 0, 0.0)
                    elif position >= 2 and index % 4 == 1 and name == PROTO_TLS12:
                        http[name] = HttpResult(name, FAIL, 0, 0.0)
                    elif index == 6 and name == PROTO_TLS13:
                        http[name] = HttpResult(name, OK, 200, 620.0)
                    elif position >= 3 and index % 5 == 2 and name == PROTO_HTTP11:
                        http[name] = HttpResult(name, FAIL, 0, 0.0)
                    else:
                        http[name] = HttpResult(name, OK, 200, 60.0 + 12.0 * index)
            details[target.key] = TargetOutcome(
                target=target,
                http=http,
                ping=None if position >= 6 else 11.0 + 3.0 * index,
            )
        return details

    def _counts(details):
        """Успешные и неудачные проверки — чтобы подписи сходились с графиком."""
        ok = fail = 0
        values = []
        for outcome in details.values():
            for _, result in outcome.protocols():
                if result is None:
                    continue
                if result.ok:
                    ok += 1
                    if result.ms:
                        values.append(result.ms)
                else:
                    fail += 1
            if outcome.ping is not None:
                ok += 1
                values.append(outcome.ping)
            else:
                fail += 1
        return ok, fail, values

    fake_results = []
    for position, name in enumerate(diag._order[:9]):
        if position == 8:
            # стратегия не работает вообще: ни одной успешной проверки
            details = _details(8, targets)
            fake_results.append(
                StrategyResult(
                    name=name, ok=0, fail=len(all_sites) * 4,
                    sites={k: 0 for k in all_sites}, details=details,
                )
            )
            continue
        details = _details(position, targets)
        ok, fail, values = _counts(details)
        sites = {key: 4 for key in all_sites}
        if position in (3, 4, 5):
            # цель «мигает»: открылась, но не всеми протоколами
            keys = sorted(all_sites)
            if keys:
                sites[keys[0]] = 2
        fake_results.append(
            StrategyResult(
                name=name, ok=ok, fail=fail,
                latencies=values or [0.0], sites=sites, details=details,
            )
        )
    # обычное завершение: результаты + автоподбор лучшей (и её синяя обводка)
    diag._was_running = False
    best = diag.apply_results(fake_results)
    diag._apply_best_after_run(best)
    # сначала даём_layout'у пересчитать высоту: пока список был свёрнут,
    # полоса прокрутки не знает, насколько он велик
    settle(qt_app, 8)

    # список результатов мог уехать за нижнюю кромку окна — прокручиваем
    diag.scroll.ensureWidgetVisible(diag._rows[best.name], 40, 40)
    settle(qt_app, 8)

    # журнал лучшей стратегии: раскрытый по клику, отказы и медленные
    # замеры покрашены в свой цвет
    best_name = fake_results[0].name
    for line in (
        "[test] %s: discord.com — HTTP/1.1 200 · 96 мс" % best_name,
        "[test] %s: discord.com — TLS 1.2 200 · 101 мс" % best_name,
        "[test] %s: discord.com — TLS 1.3 200 · 94 мс" % best_name,
        "[test] %s: discord.com — ping 12 мс" % best_name,
        "[test] %s: gateway.discord.gg — HTTP/1.1 404 · 188 мс" % best_name,
        "[test] %s: gateway.discord.gg — TLS 1.2 404 · 201 мс" % best_name,
        "[test] %s: gateway.discord.gg — TLS 1.3 нет ответа" % best_name,
        "[test] %s: www.youtube.com — HTTP/1.1 200 · 399 мс" % best_name,
        "[test] %s: www.youtube.com — TLS 1.2 200 · 412 мс" % best_name,
        "[test] %s: i.ytimg.com — TLS 1.3 не поддержан" % best_name,
        "[test] %s: redirector.googlevideo.com — HTTP/1.1 ошибка SSL" % best_name,
        "[test] %s: 8.8.8.8 — ping 14 мс" % best_name,
        "[test] %s: 1.0.0.1 — ping нет ответа" % best_name,
    ):
        diag._logs.setdefault(best_name, []).append(line)
        diag._rows[best_name].log.add_line(line)
    diag._rows[best_name].toggle_log()
    for line in (
        "[hub] Автоподбор: 9",
        "[hub] %s: %s" % (tr_text("diag.auto_applied"), best_name),
    ):
        diag.log_view.append(line)
    save("diagnostics_results")

    # прогон закончен: снимаем блокировку навигации, иначе show_settings()
    # упирается в _locked_by_diagnostics() и страница не переключается
    diag._update_buttons()
    settle(qt_app)

    # 4. настройки (через шестерёнку в верхней панели)
    window.show_settings()
    settle(qt_app)
    save("settings")

    # 4b. блок «О программе» (авторы исходников)
    about = getattr(window.settings_page, "about", None)
    if about is not None:
        window.settings_page.scroll.ensureWidgetVisible(about, 30, 200)
        save("settings_about")

    # 5. диалог обновлений
    dialog = UpdateDialog(ctx, parent=window)
    dialog.resize(680, 660)
    dialog.move(window.x() + 250, window.y() + 70)
    dialog.show()
    settle(qt_app, 8)
    dialog.grab().save(str(OUT / "updates.png"))
    print(f"сохранён {OUT / 'updates.png'}")
    dialog.close()

    # 6. английский язык
    set_language("en")
    window._build_ui()
    qt_app.setStyleSheet(theme.stylesheet())
    show(1)
    save("components_en")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
