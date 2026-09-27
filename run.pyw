"""Точка входа Zapret Hub (запускается двойным щелчком, без консоли).

    python run.pyw            — обычный запуск
    python run.pyw --tray     — запуск свёрнутым в трей (автозапуск)
    python run.pyw --minimized
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
