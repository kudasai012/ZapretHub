"""Управление дочерними процессами компонентов.

ManagedProcess оборачивает subprocess.Popen и:
  * читает stdout/stderr в потоках и отдаёт строки в UI (через сигналы Qt);
  * пишет вывод в лог-файл с простой ротацией по размеру;
  * умеет мягко (terminate) и жёстко (taskkill /T /F на Windows) останавливаться;
  * следит за процессом и эмитит exited.

Процессы компонентов считаются «своими» только пока Hub ими управляет:
TgWsProxy_windows.exe — PyInstaller-onefile с графической подсистемой, он
распаковывает себя во временную папку и запускает второй процесс с тем же
именем. Поэтому ManagedProcess держит не только главный PID, но и всё дерево,
а при остановке подчищает процессы по имени образа — иначе распакованный
остаётся висеть отдельной программой и продолжает работать уже без Hub.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from . import win32

STATUS_STOPPED = "stopped"
STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_STOPPING = "stopping"
STATUS_CRASHED = "crashed"

MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 2

# как часто переснимаем дерево процессов, пока компонент работает
TREE_REFRESH_MS = 500
# сколько ждём, пока процессы по имени образа actually умрут
SWEEP_TIMEOUT = 8.0


class _RotatingWriter:
    """Потокобезопасная запись в файл с ротацией по размеру."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def write(self, line: str) -> None:
        with self._lock:
            try:
                if self.path.exists() and self.path.stat().st_size > MAX_LOG_BYTES:
                    self._rotate()
                with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(line)
            except OSError:
                pass

    def _rotate(self) -> None:
        try:
            for i in range(LOG_BACKUPS, 0, -1):
                src = self.path.with_suffix(self.path.suffix + f".{i}")
                dst = self.path.with_suffix(self.path.suffix + f".{i + 1}")
                if src.exists():
                    if dst.exists():
                        dst.unlink(missing_ok=True)
                    src.replace(dst)
            self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))
        except OSError:
            pass


class ManagedProcess(QObject):
    status_changed = Signal(str)
    log_line = Signal(str)          # готовая строка (без \n)
    exited = Signal(int)
    restart_requested = Signal(float)  # авто-перезапуск: задержка, секунды

    def __init__(
        self,
        key: str,
        exe: Path,
        args: List[str],
        cwd: Path,
        log_file: Path,
        parent: Optional[QObject] = None,
        env_extra: Optional[dict] = None,
        image: Optional[str] = None,
        desktop: Optional[str] = None,
    ):
        super().__init__(parent)
        self.key = key
        self.exe = Path(exe)
        self.args = list(args)
        self.cwd = Path(cwd)
        self._writer = _RotatingWriter(log_file)
        self._env_extra = env_extra or {}
        # имя образа для подчистки «сирот»: процессы с таким именем, которых
        # нет в нашем дереве, после остановки гасятся принудительно
        self.image = (image or self.exe.name).lower()
        # отдельный рабочий стол: сторонняя tray-программа не светится в трее
        self.desktop_name = desktop

        self._proc: Optional[subprocess.Popen] = None
        self._status = STATUS_STOPPED
        self._threads: List[threading.Thread] = []
        self._stopping = False
        self._restarts = 0
        self.started_at: Optional[float] = None
        self.exit_code: Optional[int] = None
        self._tree: List[int] = []
        self._tree_lock = threading.Lock()
        self._tree_stop = threading.Event()
        self._tree_thread: Optional[threading.Thread] = None
        self._desktop_handle: Optional[int] = None
        # авто-перезапуск уходит в поток интерфейса через сигнал
        self.restart_requested.connect(self._schedule_restart)

    # ------------------------------------------------------------ состояние

    @property
    def status(self) -> str:
        return self._status

    @property
    def pid(self) -> int:
        return self._proc.pid if self._proc else -1

    def own_pids(self) -> set:
        """Все PID, которыми управляем: главный процесс и всё его дерево."""
        with self._tree_lock:
            pids = set(self._tree)
        if self._proc is not None:
            try:
                pid = self._proc.pid
                if pid and pid > 0:
                    pids.add(int(pid))
            except Exception:
                pass
        return pids

    def is_running(self) -> bool:
        if self._proc is None:
            return False
        if self._proc.poll() is None:
            return True
        # onefile-обёртка могла передать дело распакованному процессу:
        # если хоть кто-то из дерева жив, компонент ещё работает
        with self._tree_lock:
            tree = list(self._tree)
        return any(win32.process_alive(pid) for pid in tree)

    def uptime(self) -> float:
        if self.started_at and self.is_running():
            return max(0.0, time.time() - self.started_at)
        return 0.0

    def command_line(self) -> str:
        parts = [f'"{self.exe}"'] + [f'"{a}"' if (" " in a or "\t" in a) else a for a in self.args]
        return " ".join(parts)

    # ------------------------------------------------------------ запуск

    def _set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self.status_changed.emit(status)

    def start(self) -> bool:
        if self.is_running():
            return True
        if not self.exe.exists():
            self.log_line.emit(f"[hub] executable not found: {self.exe}")
            self._set_status(STATUS_CRASHED)
            return False

        env = dict(os.environ)
        env.update({k: str(v) for k, v in self._env_extra.items()})
        try:
            self.cwd.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        startupinfo = None
        creationflags = win32.creation_flags()
        if win32.IS_WINDOWS and self.desktop_name:
            # отдельный скрытый рабочий стол: иконка tray-программы
            # уходит на стол без проводника и пользователю не видна
            self._desktop_handle = win32.create_desktop(self.desktop_name)
            if self._desktop_handle:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.lpDesktop = f"WinSta0\\{self.desktop_name}"
                startupinfo.dwFlags |= 0x00000001  # STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE

        try:
            self._proc = subprocess.Popen(
                [str(self.exe)] + self.args,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                startupinfo=startupinfo,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:
            self.log_line.emit(f"[hub] failed to start: {exc}")
            self._proc = None
            self._set_status(STATUS_CRASHED)
            return False

        self._stopping = False
        self.started_at = time.time()
        self.exit_code = None
        self._tree_stop.clear()
        self._tree = [self.pid]
        self._tree_thread = threading.Thread(target=self._watch_tree, daemon=True)
        self._tree_thread.start()
        self._set_status(STATUS_RUNNING)
        self.log_line.emit(f"[hub] started pid={self.pid}: {self.exe.name}")
        if startupinfo is not None:
            self.log_line.emit(
                f"[hub] {self.exe.name} работает на отдельном рабочем столе "
                f"«{self.desktop_name}» — в трее его иконки нет"
            )

        for stream, name in ((self._proc.stdout, "out"),):
            t = threading.Thread(target=self._reader, args=(stream, name), daemon=True)
            t.start()
            self._threads.append(t)
        t = threading.Thread(target=self._monitor, daemon=True)
        t.start()
        self._threads.append(t)
        return True

    def _watch_tree(self) -> None:
        """Переснимает дерево процессов — onefile-ребёнок появляется не сразу.

        Обычный поток, а не QTimer: снимок делается из любого потока, и его
        безопасно остановить из потока-монитора. Поток переснимает дерево,
        пока его не остановят явно: обёртка может умереть раньше ребёнка,
        и последний снимок как раз и покажет, кто остался жив.
        """
        while not self._tree_stop.wait(TREE_REFRESH_MS / 1000.0):
            if self._proc is None:
                return
            try:
                tree = win32.descendant_pids(self._proc.pid)
            except Exception:
                continue
            if not tree:
                continue
            with self._tree_lock:
                self._tree = [pid for pid in tree if pid != os.getpid()]

    def _stop_tree_watch(self) -> None:
        self._tree_stop.set()
        thread = self._tree_thread
        self._tree_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _reader(self, stream, name: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                text = line.rstrip("\r\n")
                if text:
                    self._writer.write(f"{time.strftime('%H:%M:%S')} {text}\n")
                    self.log_line.emit(text)
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _monitor(self) -> None:
        assert self._proc is not None
        while True:
            if not self.is_running():
                break
            time.sleep(0.4)
        self.exit_code = self._proc.poll()
        was_stopping = self._stopping
        self._stop_tree_watch()
        self._set_status(STATUS_STOPPED if was_stopping else STATUS_CRASHED)
        self.log_line.emit(f"[hub] process exited with code {self.exit_code}")
        self.exited.emit(self.exit_code)
        if not was_stopping:
            self._maybe_autorestart()

    def _maybe_autorestart(self) -> None:
        if self._stopping or self._restarts >= 5:
            return
        self._restarts += 1
        delay = min(2.0 * self._restarts, 10.0)
        self.log_line.emit(f"[hub] unexpected exit, restarting in {delay:.0f}s ({self._restarts}/5)")
        # сигнал, а не QTimer.singleShot из чужого потока: QTimer живёт в
        # потоке интерфейса, и создавать его оттуда нельзя
        self.restart_requested.emit(delay)

    def _schedule_restart(self, delay: float) -> None:
        QTimer.singleShot(int(delay * 1000), self._do_autorestart)

    def _do_autorestart(self) -> None:
        if self._stopping or self.is_running():
            return
        self.start()

    def reset_restarts(self) -> None:
        self._restarts = 0

    # ------------------------------------------------------------ останов

    def stop(self, timeout: float = 8.0) -> None:
        """Останавливает компонент целиком: дерево процессов и «сироты».

        Раньше остановка возвращалась сразу, если главный процесс уже умер —
        и распакованный onefile-ребёнок оставался висеть, продолжая работать.
        Теперь подчистка идёт всегда: по снимку дерева, а затем по имени
        образа, поэтому после остановки от компонента не остаётся ничего.
        """
        proc = self._proc
        self._stopping = True
        self._stop_tree_watch()
        if proc is None:
            self._set_status(STATUS_STOPPED)
            return

        self._set_status(STATUS_STOPPING)
        if proc.poll() is None:
            self.log_line.emit("[hub] stopping...")

        # Снимок дерева — пока процесс жив. TgWsProxy_windows.exe (PyInstaller
        # onefile, графическая подсистема) распаковывает себя во временную
        # папку и запускает второй процесс с тем же именем: без этого снимка
        # распакованный оставался висеть отдельной программой после остановки.
        tree = win32.descendant_pids(proc.pid)
        own = self.own_pids() | {os.getpid()}
        try:
            proc.terminate()
        except Exception:
            pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.15)
        if proc.poll() is None:
            self.log_line.emit("[hub] process did not exit, killing the tree")
            win32.kill_process_tree(proc.pid)
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                time.sleep(0.15)

        # Дерево гасим всегда, а не только когда terminate не сработал:
        # родитель умирает первым, а его дети остаются жить.
        leftovers = [pid for pid in tree if pid != proc.pid and win32.process_alive(pid)]
        if leftovers:
            self.log_line.emit(
                "[hub] stopping child processes: " + ", ".join(str(p) for p in leftovers)
            )
            win32.kill_pids(leftovers)
            deadline = time.time() + 3.0
            while time.time() < deadline:
                if not any(win32.process_alive(pid) for pid in leftovers):
                    break
                time.sleep(0.1)
            still = [pid for pid in leftovers if win32.process_alive(pid)]
            if still:
                win32.kill_process_tree(proc.pid)

        # Финальная зачистка по имени образа: onefile-ребёнок мог появиться
        # уже после снимка дерева (или пережить terminate), и тогда он
        # остался бы висеть и работать без Hub. Свои PID не трогаем.
        self._sweep_image(own)

        if proc.poll() is None:
            self.log_line.emit("[hub] process did not exit, killing again")
            try:
                proc.kill()
            except Exception:
                pass
        self._set_status(STATUS_STOPPED)
        self.started_at = None
        with self._tree_lock:
            self._tree = []
        if self._desktop_handle:
            win32.close_desktop(self._desktop_handle)
            self._desktop_handle = None

    def _sweep_image(self, own: set) -> List[int]:
        """Гасит все процессы с нашим именем образа, кроме наших и Hub."""
        if not self.image:
            return []
        killed: List[int] = []
        deadline = time.time() + SWEEP_TIMEOUT
        while True:
            strays = [
                proc["pid"]
                for proc in win32.find_processes_by_image(self.image)
                if proc["pid"] not in own and proc["pid"] != os.getpid()
            ]
            if not strays:
                return killed
            win32.kill_pids(strays)
            killed.extend(strays)
            if time.time() >= deadline:
                self.log_line.emit(
                    "[hub] не удалось остановить "
                    + self.image
                    + " (PID "
                    + ", ".join(str(p) for p in strays)
                    + ")"
                )
                return killed
            time.sleep(0.2)

    def kill(self) -> None:
        proc = self._proc
        self._stopping = True
        self._stop_tree_watch()
        if proc is not None:
            win32.kill_process_tree(proc.pid)
            try:
                proc.kill()
            except Exception:
                pass
        # один в один со stop(): главный процесс мог умереть раньше детей
        self._sweep_image(self.own_pids() | {os.getpid()})
        self._set_status(STATUS_STOPPED)
        self.started_at = None
        with self._tree_lock:
            self._tree = []
        if self._desktop_handle:
            win32.close_desktop(self._desktop_handle)
            self._desktop_handle = None


def format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class TaskThread:
    """Утилита для запуска блокирующей работы в потоке (используется в UI)."""

    def __init__(self, fn: Callable, *args, **kwargs):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.result = None
        self.error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            self.result = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:  # noqa: BLE001
            self.error = exc

    def start(self) -> "TaskThread":
        self._thread.start()
        return self

    def join(self, timeout: float | None = None) -> "TaskThread":
        self._thread.join(timeout)
        return self

    def is_alive(self) -> bool:
        return self._thread.is_alive()
