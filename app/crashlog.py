"""Сбор аварийных завершений в файл.

Программу из исходников запускают двойным щелчком по `run.bat`, а он зовёт
`pythonw.exe` — **оконный интерпретатор без консоли**. Любая необработанная
ошибка на старте в этом случае невидима: окно мелькает и исчезает, текста
нет никакого. Именно на это и была жалоба («в панели задач мелькает python»).

Модуль ставит `sys.excepthook` (плюс `threading.excepthook` и `faulthandler`)
так, чтобы любой сбой писал полный traceback в

    <папка программы>\\crash.log
    %TEMP%\\ZapretHub-crash.log

и, если Qt уже поднят, показывал окно с текстом ошибки.
"""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path
from typing import Optional

#: не ставить хуки повторно
_installed = False


def _log_paths() -> list:
    """Куда писать: папка программы и временная папка."""
    paths = []
    try:
        from . import paths as app_paths

        paths.append(Path(app_paths.BASE_DIR) / "crash.log")
    except Exception:
        pass
    try:
        import tempfile

        paths.append(Path(tempfile.gettempdir()) / "ZapretHub-crash.log")
    except Exception:
        pass
    if not paths:
        paths.append(Path.cwd() / "crash.log")
    return paths


def _append(text: str) -> None:
    block = "\n" + "=" * 62 + "\n" + time_stamp() + "\n" + text + "\n"
    for path in _log_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(block)
        except Exception:
            pass


def time_stamp() -> str:
    try:
        import datetime

        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return ""


def _format(exc_type, exc_value, exc_tb) -> str:
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip()
    extra = ["Python " + sys.version.split()[0], "argv: " + repr(sys.argv)]
    if getattr(sys, "frozen", False):
        extra.append("frozen exe: " + str(sys.executable))
    return text + "\n\n" + "\n".join(extra)


def _show_dialog(title: str, body: str) -> None:
    """Показывает ошибку окном — при pythonw это единственный шанс её увидеть."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        created = False
        if app is None:
            app = QApplication(sys.argv[:1] if sys.argv else ["zapret-hub"])
            created = True
        box = QMessageBox(QMessageBox.Critical, title, body)
        box.exec()
        if created:
            app.quit()
    except Exception:
        # даже если окно не показывать — текст хотя бы уйдёт в stderr
        try:
            sys.stderr.write(body + "\n")
        except Exception:
            pass


def _hook(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return
    text = _format(exc_type, exc_value, exc_tb)
    _append(text)
    lines = text.splitlines()
    head = "\n".join(lines[:14])
    if len(lines) > 14:
        head = head + "\n... ещё " + str(len(lines) - 14) + " строк"
    head = head + "\n\nПодробности записаны в crash.log (рядом с программой)."
    _show_dialog("Zapret Hub — ошибка запуска", head)
    try:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    except Exception:
        pass


def _safe_hook(exc_type, exc_value, exc_tb) -> None:
    """Обёртка над `_hook`: перехватчик не имеет права упасть сам.

    При `pythonw.exe` у `sys.__excepthook__` нет и stderr, поэтому прямой
    вызов штатного обработчика даёт `AttributeError: 'NoneType' object has
    no attribute 'write'` — и пользователь снова не увидит причину.
    """
    try:
        _hook(exc_type, exc_value, exc_tb)
    except Exception:  # noqa: BLE001
        try:
            _append(_format(exc_type, exc_value, exc_tb))
        except Exception:
            pass


def _thread_hook(args) -> None:
    text = _format(args.exc_type, args.exc_value, args.exc_traceback)
    _append("(поток) " + text)


class _NullStream:
    def write(self, *args):
        return 0

    def flush(self):
        pass


def _fix_streams() -> None:
    """При `pythonw.exe` `sys.stdout`/`sys.stderr` равны None.

    Любой `print()` из чужой библиотеки после этого падает с AttributeError,
    то есть программа умирает по причине, которая выглядит совсем не там,
    где случилась. Подставляем файл из crash.log.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(_log_paths()[0], "a", encoding="utf-8"))
            except Exception:
                setattr(sys, name, _NullStream())


def install() -> None:
    """Ставит перехватчики. Вызывать как можно раньше, до импорта Qt."""
    global _installed
    if _installed:
        return
    _installed = True

    _fix_streams()
    sys.excepthook = _safe_hook
    try:
        threading.excepthook = _thread_hook  # type: ignore[assignment]
    except Exception:
        pass

    # segfault/abort в нативных библиотеках Qt тоже должны оставлять след
    try:
        import faulthandler

        for path in _log_paths():
            try:
                handle = open(path, "a", encoding="utf-8", errors="replace")
                faulthandler.enable(file=handle, all_threads=True)
                break
            except Exception:
                continue
    except Exception:
        pass

    # выход по SystemExit с кодом ошибки — тоже стоит зафиксировать
    def _at_exit() -> None:
        code = getattr(sys, "last_value", None)
        if isinstance(code, SystemExit) and code.code not in (0, None):
            _append("SystemExit(" + repr(code.code) + ")")

    import atexit

    atexit.register(_at_exit)


def report(message: str, exc: Optional[BaseException] = None) -> None:
    """Пишет произвольное сообщение в тот же crash.log."""
    text = message
    if exc is not None:
        text = text + "\n\n" + "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).rstrip()
    _append(text)


def log_path() -> Path:
    return _log_paths()[0]
