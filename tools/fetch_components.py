"""CLI-утилита: скачать/обновить компоненты без запуска интерфейса.

    python tools/fetch_components.py            # оба компонента
    python tools/fetch_components.py zapret     # только zapret
    python tools/fetch_components.py tgws       # только TG WS Proxy
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.config import AppConfig
    from app.core import github
    from app.core.updater import TGWS_REPO, ZAPRET_REPO, Updater

    wanted = [a.lower() for a in sys.argv[1:]] or ["zapret", "tgws"]
    cfg = AppConfig.load()
    updater = Updater(cfg)
    client = github.GitHubClient(proxy=cfg.updates.proxy)

    for component in ("zapret", "tgws"):
        if component not in wanted:
            continue
        repo = ZAPRET_REPO if component == "zapret" else TGWS_REPO
        print(f"== {component}: проверка {repo}")
        try:
            release = client.latest_release(repo)
        except github.GitHubError as exc:
            print(f"   ошибка: {exc}")
            return 1
        installed = updater.installed_versions().get(component)
        print(f"   установлено: {installed or '—'} · доступно: {release.tag}")
        if installed and not github.is_newer(release.tag, installed):
            print("   уже актуальная версия")
            continue

        from app.core.updater import UpdateInfo

        info = UpdateInfo(
            component=component,
            installed=installed,
            latest=release.tag.lstrip("v"),
            release=release,
            update_available=True,
        )

        def progress(done: int, total: int) -> None:
            if total:
                print(f"\r   скачивание {done * 100 // total:3d}%", end="", flush=True)

        updater.progress.connect(lambda c, d, t: progress(d, t))
        try:
            version = updater._do_install(component, info)
        except Exception as exc:  # noqa: BLE001
            print(f"\n   ошибка установки: {exc}")
            return 1
        print(f"\n   установлено: {version}")
    print("Готово")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
