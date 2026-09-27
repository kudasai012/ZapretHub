"""Интеграционный тест: установка/обновление zapret через GitHub (нужна сеть).

    QT_QPA_PLATFORM=offscreen python tools/integration_test.py
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
    print(f"[{'OK ' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="zhub-itest-"))
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
    paths.HUB_LOG_FILE = paths.LOGS_DIR / "hub.log"
    paths.ensure_dirs()


    from app.config import AppConfig, load_manifest
    from app.core import github
    from app.core.updater import (
        TGWS_REPO,
        ZAPRET_REPO,
        UpdateInfo,
        Updater,
        tgws_asset_name,
    )
    from app.core.zapret import ZapretComponent

    cfg = AppConfig.load()
    updater = Updater(cfg)

    # --- GitHub API ---
    client = github.GitHubClient(proxy=cfg.updates.proxy)
    try:
        release = client.latest_release(ZAPRET_REPO)
        check("github zapret latest", bool(release.tag), f"tag={release.tag}")
        zip_asset = release.find_asset(lambda n: n.endswith(".zip"))
        check("github zapret zip asset", zip_asset is not None, zip_asset.name if zip_asset else "")
    except github.GitHubError as exc:
        check("github zapret latest", False, str(exc))
        print("Сеть к GitHub недоступна — остальные проверки пропущены")
        return 1

    tgws_release = client.latest_release(TGWS_REPO)
    check("github tgws latest", bool(tgws_release.tag), f"tag={tgws_release.tag}")
    check(
        "tgws asset name for this platform",
        tgws_asset_name().startswith("TgWsProxy_windows"),
        tgws_asset_name(),
    )

    # --- установка zapret ---
    info = UpdateInfo(component="zapret", installed=None, latest=release.tag.lstrip("v"), release=release)
    version = updater._do_install("zapret", info)
    check("zapret installed", (paths.ZAPRET_DIR / "bin" / "winws.exe").exists(), f"v{version}")
    manifest = load_manifest()
    check("manifest updated", manifest.get("zapret", {}).get("version") == version, str(manifest.get("zapret")))

    # --- пользовательские настройки ---
    comp = ZapretComponent(cfg)
    comp.ensure_user_lists()
    comp.write_user_list("list-general-user.txt", "# мой список\nmy-domain.example\n")
    comp.apply_game_filter()
    cfg.zapret.game_mode = "all"
    cfg.zapret.game_tcp_range = "1000-2000"
    comp.apply_game_filter()
    comp.apply_ipset_mode("none")
    check("game filter written", comp.game_filter_state()["mode"] == "all")
    check("ipset none applied", comp.ipset_state() == "none")

    user_list_before = comp.read_user_list("list-general-user.txt")
    strategies_before = comp.strategies()

    # --- повторная установка (обновление на ту же версию) ---
    version2 = updater._do_install("zapret", info)
    check("zapret reinstalled", (paths.ZAPRET_DIR / "bin" / "winws.exe").exists(), f"v{version2}")
    check(
        "user list preserved",
        comp.read_user_list("list-general-user.txt") == user_list_before,
        comp.read_user_list("list-general-user.txt")[:40].replace("\n", "|"),
    )
    check("game filter preserved", comp.game_filter_state()["mode"] == "all")
    check("ipset mode preserved", comp.ipset_state() == "none")
    check("strategies still there", comp.strategies() == strategies_before)
    backups = [p for p in paths.BACKUPS_DIR.iterdir() if p.name.startswith("zapret-")]
    check("backup created", len(backups) >= 1, f"{len(backups)} шт.")

    # --- запуск на Linux должен завершаться корректно ---
    started = comp.start()
    check("zapret start fails gracefully on Linux", started is False)
    check("status not stuck", comp.status in ("stopped", "crashed"), comp.status)

    # --- разбор стратегий на установленном пакете ---
    try:
        exe, args = comp.parse_strategy("general.bat")
        check("parse installed strategy", exe.exists() and len(args) > 10, f"{len(args)} арг.")
        check(
            "game filter in command line",
            any("1000-2000" in a for a in args),
            next((a for a in args if "wf-tcp" in a), ""),
        )
    except Exception as exc:  # noqa: BLE001
        check("parse installed strategy", False, str(exc))

    # --- tgws: подготовка портативного режима ---
    from app.core.tgws import TgWsComponent

    tgws = TgWsComponent(cfg)
    tgws.ensure_portable()
    check("portable dir created", tgws.portable_dir.is_dir())
    check("first-run marker", (tgws.portable_dir / ".first_run_done_mtproto").exists())
    check("proxy link format", tgws.proxy_link().startswith("tg://proxy?server="), tgws.proxy_link())
    check("tgws start fails gracefully on Linux", tgws.start() is False)

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)} — {failures}")
        return 1
    print("ВСЕ ИНТЕГРАЦИОННЫЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
