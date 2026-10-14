"""Проверка: закрытие программы НЕ гасит обходы, а установщик — гасит.

Запуск:  QT_QPA_PLATFORM=offscreen python tools/shutdown_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("[OK ] " if ok else "[FAIL] ") + label + (" - " + detail if detail else ""))
    if not ok:
        FAILS.append(label)


class FakeComp:
    """Компонент-заглушка: считает вызовы stop()."""

    def __init__(self, installed=True, running=True):
        self._installed = installed
        self._running = running
        self.stop_calls = 0

    def installed(self):
        return self._installed

    def is_running(self):
        return self._running

    def stop(self):
        self.stop_calls += 1
        self._running = False


def main():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(sys.argv)
    tmp = Path(tempfile.mkdtemp(prefix="zh-shutdown-"))
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

    from app.context import AppContext

    ctx = AppContext()
    check("контекст создан", ctx is not None)

    z = FakeComp()
    t = FakeComp()
    ctx.zapret = z
    ctx.tgws = t
    ctx.asn.stop()

    # --- обычный выход: обходы продолжают работать ---
    ctx.shutdown()
    check(
        "обычный выход не трогает компоненты",
        z.stop_calls == 0 and t.stop_calls == 0,
        "zapret.stop=%d, tgws.stop=%d" % (z.stop_calls, t.stop_calls),
    )

    # --- выход с гашением: установщик/деинсталлятор ---
    ctx.shutdown(stop_components=True)
    check(
        "stop_components=True останавливает компоненты",
        z.stop_calls == 1 and t.stop_calls == 1,
        "zapret.stop=%d, tgws.stop=%d" % (z.stop_calls, t.stop_calls),
    )

    # --- повторный обычный выход ничего не ломает ---
    z.stop_calls = 0
    t.stop_calls = 0
    ctx.shutdown()
    check(
        "повторный обычный выход безопасен",
        z.stop_calls == 0 and t.stop_calls == 0,
        "zapret.stop=%d, tgws.stop=%d" % (z.stop_calls, t.stop_calls),
    )

    # --- _sweep_orphans только при остановке компонентов ---
    swept = []
    ctx._sweep_orphans = lambda: swept.append(1)
    ctx.shutdown()
    check("без остановки компонентов sweep не зовётся", not swept)
    ctx.shutdown(stop_components=True)
    check("со остановкой компонентов sweep зовётся", swept == [1])

    # --- настройка по умолчанию: выключена ---
    from app.config import AppConfig

    cfg = AppConfig()
    check(
        "stop_components_on_quit по умолчанию False",
        cfg.general.stop_components_on_quit is False,
        str(cfg.general.stop_components_on_quit),
    )

    # --- галочка читается и сохраняется ---
    cfg.general.stop_components_on_quit = True
    saved = cfg.save()
    reloaded = AppConfig.load()
    check(
        "галочка сохраняется в конфиг",
        saved and reloaded.general.stop_components_on_quit is True,
        "save=%s, loaded=%s" % (saved, reloaded.general.stop_components_on_quit),
    )
    cfg.general.stop_components_on_quit = False
    cfg.save()

    # --- i18n ---
    from app.i18n import STRINGS, set_language, tr

    for lang in ("ru", "en"):
        set_language(lang)
        check(
            "ключи quit/settings заполнены (%s)" % lang,
            bool(tr("quit.confirm_keep_running").strip())
            and bool(tr("settings.stop_on_quit").strip())
            and bool(tr("settings.stop_on_quit_hint").strip()),
            tr("settings.stop_on_quit"),
        )
        check(
            "переводы не равны ключу (%s)" % lang,
            tr("settings.stop_on_quit") != "settings.stop_on_quit"
            and tr("quit.confirm_keep_running") != "quit.confirm_keep_running",
        )
    set_language("ru")
    missing = [
        k
        for k, v in STRINGS.items()
        if (k.startswith("quit.") or k.startswith("settings.stop_on_quit"))
        and not (isinstance(v, dict) and str(v.get("ru", "")).strip() and str(v.get("en", "")).strip())
    ]
    check("оба языка заполнены для новых ключей", not missing, ", ".join(missing))

    print()
    if FAILS:
        print("ПРОВАЛЫ: " + ", ".join(FAILS))
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
