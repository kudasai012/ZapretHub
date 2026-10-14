"""Проверка: компонент переживает смерть Hub и не зависит от его пайпов.

Главный смысл — процесс компонента должен продолжать работать, когда Hub
убивают (End Task, TerminateProcess). Раньше вывод компонента шёл в pipe,
читающий конец которого держал Hub: после смерти Hub компонент получал
ERROR_BROKEN_PIPE на каждой записи в stdout. Теперь компонент пишет в
свой файл, а Hub только подглядывает в него.

Запуск:  QT_QPA_PLATFORM=offscreen python tools/procman_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("[OK ] " if ok else "[FAIL] ") + label + (" - " + detail if detail else ""))
    if not ok:
        FAILS.append(label)


# скрипт-«компонент»: пишет строки в stdout и живёт, пока его не убьут.
# Главное — он продолжает писать в stdout ВЕСЬ срок жизни. Если вывод идёт
# в pipe, читающий конец которого держал Hub, то после смерти Hub запись
# даёт EPIPE/SIGPIPE и процесс умирает. С файлом этого не происходит.
CHILD = r'''
import sys, time
n = 0
while True:
    print("tick %d" % n, flush=True)
    n += 1
    time.sleep(0.1)
'''


def main():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    tmp = Path(tempfile.mkdtemp(prefix="zh-proc-"))
    child_py = tmp / "child.py"
    child_py.write_text(CHILD, encoding="utf-8")

    from app.core import win32
    from app.core.procman import ManagedProcess, STATUS_RUNNING

    seen = []
    proc = ManagedProcess(
        key="testchild",
        exe=Path(sys.executable),
        args=[str(child_py)],
        cwd=tmp,
        log_file=tmp / "testchild.log",
        image="python",
    )
    proc.log_line.connect(lambda line: seen.append(line))

    check("start()", proc.start() is True)
    check("статус RUNNING", proc.status == STATUS_RUNNING, proc.status)
    pid = proc.pid
    check("pid валиден", pid > 0, str(pid))

    # ждём, пока tailer прочитает строки
    deadline = time.time() + 8
    while time.time() < deadline and len(seen) < 4:
        app.processEvents()
        time.sleep(0.05)
    check("строки из stdout дошли до UI", len(seen) >= 4, "%d строк: %r" % (len(seen), seen[:5]))
    check(
        "файл вывода создан",
        proc.raw_log is not None and Path(proc.raw_log).exists(),
        str(proc.raw_log),
    )
    raw = Path(proc.raw_log)
    check("в файле вывода есть строки", raw.exists() and "tick 0" in raw.read_text(encoding="utf-8", errors="replace"))

    # ---- имитируем смерть Hub: потоки tailer просто исчезают, как и все
    # ---- потоки программы при TerminateProcess. Stop НЕ вызываем.
    proc._stop_tail()
    proc._stop_tree_watch()
    # смерть Hub закрывает все его дескрипторы — в том числе читающий
    # конец pipe. При выводе в pipe это единственное, что убивает компонент.
    stream = getattr(proc._proc, "stdout", None)
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass
    time.sleep(0.6)
    app.processEvents()

    check(
        "компонент жив после смерти Hub",
        win32.process_alive(pid),
        "pid=%d" % pid,
    )
    # вывод должен продолжаться: если бы он шёл в pipe Hub, запись после
    # смерти Hub дала бы EPIPE и процесс бы умер
    before = raw.stat().st_size
    time.sleep(0.8)
    after = raw.stat().st_size
    check(
        "компонент продолжает писать вывод после смерти Hub",
        after > before,
        "было %d байт, стало %d" % (before, after),
    )
    check(
        "и всё ещё жив",
        win32.process_alive(pid),
        "pid=%d" % pid,
    )

    # ---- штатная остановка гасит и дерево ----
    proc.stop()
    deadline = time.time() + 10
    while time.time() < deadline and win32.process_alive(pid):
        time.sleep(0.1)
    check("stop() гасит компонент", not win32.process_alive(pid), "pid=%d" % pid)

    # ---- негативный контроль: тот же компонент, но вывод в pipe ----
    # Ровно так было устроено раньше, и ровно поэтому обходы умирали
    # вместе с Hub. Если бы эта проверка прошла, исправление было бы
    # бессмысленным.
    class PipeProcess(ManagedProcess):
        """Принудительно старый способ: вывод в pipe от Hub."""

        def _spawn(self, raw_handle, creationflags, startupinfo, env):
            import subprocess

            return subprocess.Popen(
                [str(self.exe)] + self.args,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                env=env,
            )

    pipe_proc = PipeProcess(
        key="pipechild",
        exe=Path(sys.executable),
        args=[str(child_py)],
        cwd=tmp,
        log_file=tmp / "pipechild.log",
        image="python",
    )
    check("pipe-вариант запускается", pipe_proc.start() is True)
    pipe_pid = pipe_proc.pid
    time.sleep(1.0)
    app.processEvents()
    pipe_proc._stop_tail()
    pipe_proc._stop_tree_watch()
    stream = getattr(pipe_proc._proc, "stdout", None)
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass
    time.sleep(1.0)
    check(
        "а вот с pipe компонент умирает (подтверждает смысл правки)",
        not win32.process_alive(pipe_pid),
        "pid=%d" % pipe_pid,
    )
    if win32.process_alive(pipe_pid):
        pipe_proc.stop()

    print()
    if FAILS:
        print("ПРОВАЛЫ: " + ", ".join(FAILS))
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
