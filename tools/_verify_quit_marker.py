"""Маркер «установщик просит закрыться»: диалог «Выйти?» не показывается."""
import os, sys
sys.path.insert(0, "/home/user/Zapret_hub")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

tmp = Path(tempfile.mkdtemp(prefix="qr-"))
import app.paths as paths  # noqa: E402

paths.DATA_DIR = tmp / "data"
paths.CONFIG_FILE = tmp / "data" / "config.json"
paths.LOCK_FILE = tmp / "data" / "hub.lock"
paths.HUB_LOG_FILE = tmp / "data" / "hub.log"
paths.ensure_dirs()

from app.config import AppConfig  # noqa: E402
from app.context import AppContext  # noqa: E402
from app.core import win32  # noqa: E402
from app.i18n import set_language  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv[:1])
cfg = AppConfig.load()
cfg.general.language = "ru"
cfg.general.theme = "dark"
cfg.save()
set_language("ru")
app.setStyleSheet(theme.stylesheet())

w = MainWindow(AppContext())
w.resize(1180, 820)
w.show()

# притворяемся, что компоненты запущены — именно тогда раньше был вопрос
w.ctx.any_running = lambda: True

asked = []


def fake_question(*args, **kwargs):
    asked.append(True)
    return QMessageBox.Yes


QMessageBox.question = staticmethod(fake_question)

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("  OK   " if cond else "  BAD  ") + name + (f" [{extra}]" if extra else ""))


print("=== без маркера: программа спрашивает ===")
ev = QCloseEvent()
w._confirm_quit(ev)
check("диалог «Выйти?» показан", asked)
check("событие закрытия принято (пользователь согласился)", ev.isAccepted())

asked.clear()
print("\n=== маркер установлен: установщик закрывает программу ===")
win32.QUIT_REQUEST_FILE.parent.mkdir(parents=True, exist_ok=True)
win32.QUIT_REQUEST_FILE.write_text("quit", encoding="utf-8")
check("маркер виден программе", win32.quit_requested())
ev2 = QCloseEvent()
w._confirm_quit(ev2)
check("диалог НЕ показан", not asked)
check("окно закрылось молча", ev2.isAccepted())

print("\n=== маркер убран ===")
win32.clear_quit_request()
check("маркера нет", not win32.quit_requested())

print(f"\nTOTAL: {sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
