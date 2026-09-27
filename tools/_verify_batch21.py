"""Проверка оставшихся пунктов 21-й партии."""
import os
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

ROOT = Path("/home/user/Zapret_hub")
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

app = QApplication(sys.argv[:1])
tmp = Path(tempfile.mkdtemp(prefix="zhub-"))

import app.paths as paths  # noqa: E402

for k, v in dict(
    DATA_DIR=tmp / "data",
    CONFIG_FILE=tmp / "data" / "config.json",
    MANIFEST_FILE=tmp / "data" / "components.json",
    LOGS_DIR=tmp / "data" / "logs",
    BACKUPS_DIR=tmp / "data" / "backups",
    TEMP_DIR=tmp / "data" / "tmp",
    LOCK_FILE=tmp / "data" / "hub.lock",
    HUB_LOG_FILE=tmp / "data" / "logs" / "hub.log",
).items():
    setattr(paths, k, v)
paths.ensure_dirs()
paths.ZAPRET_DIR = paths.COMPONENTS_DIR / "zapret-discord-youtube"
paths.TGWS_DIR = paths.COMPONENTS_DIR / "tg-ws-proxy"

from app.config import AppConfig  # noqa: E402
from app.context import AppContext  # noqa: E402
from app.core.probe import (  # noqa: E402
    FAIL,
    OK,
    PROTO_HTTP11,
    PROTO_TLS12,
    PROTO_TLS13,
    HttpResult,
)
from app.core.strategy_test import (  # noqa: E402
    StrategyResult,
    TargetOutcome,
    load_targets_file,
    parse_targets,
)
from app.i18n import set_language, tr  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

cfg = AppConfig.load()
cfg.general.language = "ru"
cfg.general.theme = "dark"
cfg.save()
set_language("ru")
app.setStyleSheet(theme.stylesheet())

window = MainWindow(AppContext())
window.resize(1180, 820)
window.show()
window.goto_page(2, animate=False)
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)

diag = window.diagnostics_page
tray = window.tray
targets = parse_targets(
    load_targets_file(ROOT / "components/zapret-discord-youtube/utils/targets.txt")
)


def mk(i, quality=1.0):
    d = {}
    for idx, t in enumerate(targets):
        http = {}
        if t.kind == "http":
            for n in (PROTO_HTTP11, PROTO_TLS12, PROTO_TLS13):
                if quality >= 1.0:
                    http[n] = HttpResult(n, OK, 200, 60.0 + 12.0 * idx)
                else:
                    http[n] = HttpResult(n, FAIL, 0, 0.0)
        d[t.key] = TargetOutcome(
            target=t,
            http=http,
            ping=None if quality < 1.0 else 11.0 + 3.0 * idx,
        )
    ok = sum(1 for o in d.values() for _, r in o.protocols() if r and r.ok)
    ok += sum(1 for o in d.values() if o.ping is not None)
    total = sum(1 for o in d.values() for _, r in o.protocols() if r) + len(d)
    return StrategyResult(
        name=diag._order[i],
        ok=ok,
        fail=total - ok,
        latencies=[60.0],
        sites={k: 4 for k in d},
        details=d,
    )


results_ok = []


def check(name, cond, extra=""):
    results_ok.append(bool(cond))
    print(("  OK   " if cond else "  BAD  ") + name + (f"  [{extra}]" if extra else ""))


print("\n=== 4. button / tray ===")
check("button 'Test · 22'", "22" in diag.start_button.text(),
      diag.start_button.text())
check("tray 'Start all'", tray.toggle_all_action.text() == "Запустить всё",
      tray.toggle_all_action.text())

diag._running = True
diag._update_buttons()
check("button became 'Stop'", diag.start_button.text() == "Остановить",
      diag.start_button.text())
# во время перебора zapret реально запущен — притворимся, что это так
window.ctx.zapret.is_running = lambda: True
tray.refresh()
check("tray became 'Stop all'", tray.toggle_all_action.text() == "Остановить всё",
      tray.toggle_all_action.text())
window.ctx.zapret.is_running = lambda: False
tray.refresh()
check("tray back to 'Start all'", tray.toggle_all_action.text() == "Запустить всё",
      tray.toggle_all_action.text())
diag._running = False
diag._update_buttons()
check("button back to 'Test'", diag.start_button.text().startswith("Протестировать"),
      diag.start_button.text())

print("\n=== 2. picking ===")
names = diag._order
diag._picked.clear()
for n in names[:4]:
    diag._picked.add(n)
for n, row in diag._rows.items():
    row.set_picked(n in diag._picked)
diag._update_buttons()
check("4 of 22 picked", len(diag._picked_names()) == 4, str(len(diag._picked_names())))
check("button 'Test · 4'", "· 4" in diag.start_button.text(), diag.start_button.text())
check("header '4/22'", "4/22" in diag.results_text.text(), diag.results_text.text())

diag._set_all_picked(True)
check("'pick all' -> 22/22", len(diag._picked_names()) == 22, diag.start_button.text())
diag._set_all_picked(False)
check("'pick none' -> empty", len(diag._picked_names()) == 0, diag.start_button.text())
check("nothing picked -> toast on click", tr("diag.nothing_picked").startswith("Не отмечено"))
diag._set_all_picked(True)

print("\n=== 1. filtering ===")
results = [mk(i) for i in range(9)]
results = [results[8], results[0], results[3], results[1], results[2],
           results[4], results[5], results[6], results[7]]
best = diag.apply_results(results)
check("best found", best is not None and best.ok > 0, best.name if best else "-")
order_in_layout = [
    diag.rows_layout.itemAt(i).widget().strategy for i in range(diag.rows_layout.count())
]
top9 = order_in_layout[:9]
check("best first in list", top9[0] == best.name,
      " | ".join(n.replace("general (", "").replace(").bat", "") for n in top9[:4]))
check("rank 1 on best", diag._rows[best.name].rank_label.text() == "1",
      diag._rows[best.name].rank_label.text())
check("rank 2 on second", diag._rows[top9[1]].rank_label.text() == "2")
check("best marked selected", diag._rows[best.name].property("selected") == "yes")
check("card mode best", diag.live_card.property("mode") == "best")

print("\n=== 3. auto-apply ===")
window.ctx.config.zapret.strategy = "general (ALT9).bat"
diag._was_running = False
diag._original = "general (ALT9).bat"
diag._apply_best_after_run(best)
check("current = best", window.ctx.config.zapret.strategy == best.name,
      window.ctx.config.zapret.strategy)
window.grab().save("/home/user/shots/verify_final.png")

print("\n=== 3b. stop without result ===")
window.ctx.config.zapret.strategy = "general (ALT5).bat"
diag._original = "general (ALT5).bat"
diag._was_running = False
diag._apply_best_after_run(None)
check("original restored",
      window.ctx.config.zapret.strategy == "general (ALT5).bat",
      window.ctx.config.zapret.strategy)

print(f"\nTOTAL: {sum(results_ok)}/{len(results_ok)}")
sys.exit(0 if all(results_ok) else 1)
