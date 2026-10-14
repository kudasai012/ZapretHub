"""Дымовой тест: собирает UI в offscreen-режиме и проверяет ключевую логику.

    QT_QPA_PLATFORM=offscreen python tools/smoke_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    # --- временное окружение ---
    tmp = Path(tempfile.mkdtemp(prefix="zhub-test-"))
    os.environ["ZAPRET_HUB_DATA"] = str(tmp)
    import app.paths as paths

    paths.COMPONENTS_DIR = tmp / "components"
    paths.ZAPRET_DIR = paths.COMPONENTS_DIR / "zapret-discord-youtube"
    paths.TGWS_DIR = paths.COMPONENTS_DIR / "tg-ws-proxy"
    paths.DATA_DIR = tmp / "data"
    paths.CONFIG_FILE = paths.DATA_DIR / "config.json"
    paths.MANIFEST_FILE = paths.DATA_DIR / "components.json"
    paths.LOGS_DIR = paths.DATA_DIR / "logs"
    paths.BACKUPS_DIR = paths.DATA_DIR / "backups"
    paths.TEMP_DIR = paths.DATA_DIR / "tmp"
    paths.LOCK_FILE = paths.DATA_DIR / "hub.lock"
    paths.HUB_LOG_FILE = paths.LOGS_DIR / "hub.log"
    paths.ensure_dirs()

    qt_app = QApplication(sys.argv[:1])

    from app.config import AppConfig
    from app.context import AppContext
    from app.i18n import set_language, tr
    from app.ui import theme
    from app.ui.main_window import MainWindow

    # --- конфиг ---
    cfg = AppConfig.load()
    check("config default load", cfg.general.language in ("ru", "en"))
    check("config save", cfg.save())
    cfg2 = AppConfig.load()
    check("config roundtrip", cfg2.tgws.port == cfg.tgws.port)

    # --- i18n ---
    set_language("ru")
    check("i18n ru", tr("common.start") == "Запустить")
    set_language("en")
    check("i18n en", tr("common.start") == "Start")
    set_language("ru")

    # --- контекст и UI ---
    ctx = AppContext()
    qt_app.setStyleSheet(theme.stylesheet())
    window = MainWindow(ctx)
    check("main window built", window is not None)

    pages = (
        window.home_page,
        window.components_page,
        window.diagnostics_page,
        window.settings_page,
    )
    for index, page in enumerate(pages):
        window.goto_page(index, animate=False)
        page.on_show()
        check(f"page {type(page).__name__} renders", True)

    # панели компонентов и диалог обновлений
    for panel in (window.components_page.zapret_panel, window.components_page.tgws_panel):
        panel.refresh_status()
        panel.on_show()
        check(f"panel {type(panel).__name__} renders", True)
        # сворачивание панели до заголовка и обратно
        panel.set_collapsed(True)
        panel.set_collapsed(False)
    check("component panel collapse", True)

    from app.ui.update_dialog import UpdateDialog

    dialog = UpdateDialog(ctx, parent=window)
    dialog.show()
    check("update dialog renders", dialog._rows)
    dialog.close()

    # --- новое в 1.0.2 ---
    from app.ui.app_update_dialog import AppUpdateDialog

    app_dialog = AppUpdateDialog(ctx, parent=window)
    app_dialog.show()
    check("app update dialog renders", app_dialog.notes is not None)
    app_dialog.close()

    # полукруг статуса: все состояния должны переживать перекраску
    arc = window.state_arc
    for state in ((0, 2, False, False), (1, 2, True, False), (2, 2, True, True)):
        arc.set_state(*state)
        arc.set_compact(False)
        arc.set_compact(True)
        arc.repaint()
    check("status arc paints", True)

    # кликабельные подпись и иконка бокового меню
    check("sidebar title clickable", window.brand_title.clicked is not None)
    check("sidebar icon clickable", window.brand_icon.clicked is not None)

    # свои чекбоксы
    from app.ui.widgets import PickCheckBox

    box = PickCheckBox("тест")
    box.setChecked(True)
    box.repaint()
    box.setChecked(False)
    box.repaint()
    check("PickCheckBox paints", True)

    # диагностика: сетка, выбор, раскрытие
    diag = window.diagnostics_page
    diag.reload()
    # в тестовом окружении zapret не установлен, поэтому стратегий может
    # не быть — проверяем, что reload не падает, а не количество
    check("diagnostics reload", isinstance(diag._order, list))
    diag._set_all_picked(False)
    check("diagnostics pick none", not diag._picked_names())
    diag._set_all_picked(True)
    check("diagnostics pick all", len(diag._picked_names()) == len(diag._order))
    if diag._order:
        row = diag._rows[diag._order[0]]
        row.set_expanded(True)
        row.set_expanded(False)
    check("diagnostics card expand", True)
    diag._toggle_targets(True)
    diag._toggle_targets(False)
    check("diagnostics targets toggle", True)

    # статусы компонентов (не установлены в тестовом окружении)
    check("zapret not installed in sandbox", not ctx.zapret.installed())
    check("tgws not installed in sandbox", not ctx.tgws.installed())
    check(
        "zapret start refuses gracefully",
        ctx.zapret.start() is False and ctx.zapret.status == "stopped",
    )
    check(
        "tgws start refuses gracefully",
        ctx.tgws.start() is False and ctx.tgws.status == "stopped",
    )

    # --- разбор стратегий на поставляемом пакете zapret ---
    shipped_zapret = ROOT / "components" / "zapret-discord-youtube"
    if shipped_zapret.exists():
        import app.paths as p2

        original_zapret = p2.ZAPRET_DIR
        p2.ZAPRET_DIR = shipped_zapret
        try:
            from app.core.zapret import ZapretComponent

            comp = ZapretComponent(ctx.config)
            strategies = comp.strategies()
            check("strategies found", len(strategies) > 5, f"{len(strategies)} шт.")
            exe, args = comp.parse_strategy("general.bat")
            check("winws exe resolved", exe.name == "winws.exe", str(exe))
            check("args parsed", "--wf-tcp=80,443,2053,2083,2087,2096,8443,12" in args)
            check(
                "hostlist arg expanded",
                any(a.startswith("--hostlist=") and a.endswith("list-general.txt") for a in args),
            )
            check("no unresolved vars", not any("%" in a for a in args))
            check("version parsed", comp.version() is not None, str(comp.version()))
            for name in strategies:
                try:
                    comp.parse_strategy(name)
                except Exception as exc:  # noqa: BLE001
                    check(f"parse {name}", False, str(exc))
                    break
            else:
                check("all strategies parse", True, f"{len(strategies)} шт.")

            # game filter / ipset не пишем на диск поставляемого пакета
            values = comp.game_filter_values()
            check("game filter values", values["GAMEFILTERTCP"] == "12", str(values))
            ctx.config.zapret.game_mode = "udp"
            values = comp.game_filter_values()
            check("game filter udp mode", values["GAMEFILTERTCP"] == "12" and values["GAMEFILTERUDP"] == "1024-65535")
            ctx.config.zapret.game_mode = "disabled"
        finally:
            p2.ZAPRET_DIR = original_zapret

    # --- списки: доступны все .txt из lists/ ---
    p2.ZAPRET_DIR = shipped_zapret
    try:
        from app.core.zapret import ZapretComponent as _ZC

        comp2 = _ZC(ctx.config)
        files = comp2.list_files()
        check("all list files listed", "list-general.txt" in files and "ipset-all.txt" in files, f"{len(files)} шт.")
        check(
            "user lists included",
            all(name in files for name in ("list-general-user.txt", "ipset-exclude-user.txt")),
            ", ".join(files),
        )
    finally:
        p2.ZAPRET_DIR = original_zapret

    # --- сборщик IP по ASN (RIPE Stat, небольшой набор) ---
    try:
        from app.core.asn import ASN_LIST, collect, render

        subset = [("Cloudflare", ASN_LIST["Cloudflare"])]
        v4, v6 = collect(subset, log=lambda _line: None)
        check("asn collect v4", len(v4) > 0, f"{len(v4)} сетей")
        check("asn collect v6", len(v6) > 0, f"{len(v6)} сетей")
        text_out = render(v4, v6)
        check("asn render", text_out.strip().startswith("1.") or "\n" in text_out.strip(), f"{len(text_out)} симв.")
    except Exception as exc:  # noqa: BLE001
        check("asn collect", False, str(exc))

    # --- поставляемый TG WS Proxy ---
    shipped_tgws = ROOT / "components" / "tg-ws-proxy"
    if (shipped_tgws / "TgWsProxy_windows.exe").exists():
        import app.paths as p3

        original_tgws = p3.TGWS_DIR
        p3.TGWS_DIR = shipped_tgws
        try:
            from app.core.tgws import TgWsComponent

            tgws = TgWsComponent(ctx.config)
            check("tgws shipped", tgws.installed())
            check("tgws version marker", tgws.version_display() != "—", tgws.version_display())
            cfg_dict = tgws.build_config()
            check(
                "tgws config keys",
                {"host", "port", "secret", "dc_ip"} <= set(cfg_dict),
                ",".join(sorted(cfg_dict)[:4]),
            )
            check("tgws autostart disabled in its config", cfg_dict.get("autostart") is False)
            check("tgws link", tgws.proxy_link().startswith("tg://proxy?server=127.0.0.1&port="))
        finally:
            p3.TGWS_DIR = original_tgws

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)} — {failures}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
