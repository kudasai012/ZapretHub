"""Точка входа Zapret Hub (запускается двойным щелчком, без консоли).

    python run.pyw            — обычный запуск
    python run.pyw --tray     — запуск свёрнутым в трей (автозапуск)
    python run.pyw --minimized
    python run.pyw --console  — запуск с консолью (отладка)

Важно: `run.bat` запускает этот файл через `pythonw.exe` — интерпретатор
**без консоли**. Если программа упадёт на старте, пользователь не увидит
ничего: окно мелькнёт и исчезнет. Поэтому перехватчик аварий ставится
**до** импорта Qt и всего остального (см. app/crashlog.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- первым делом: ловим падения, иначе они невидимы при pythonw ---
try:
    from app import crashlog

    crashlog.install()
except Exception:  # noqa: BLE001 - если и это не встало, просто запускаемся
    pass


def _run() -> int:
    from app.main import main

    return main()


if __name__ == "__main__":
    try:
        raise SystemExit(_run())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - показать хоть как-то
        try:
            from app import crashlog

            crashlog.report("Необработанная ошибка при запуске", exc)
        except Exception:
            pass
        raise
