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

# отвязать ребёнка от job-объекта Hub (см. ManagedProcess._spawn)
BREAKAWAY_FROM_JOB = 0x01000000

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
        # «сырой» файл вывода: компонент пишет в него сам, а Hub только
        # читает. Раньше вывод шёл в pipe, и когда Hub убивали, читающий
        # конец исчезал — компонент получал ERROR_BROKEN_PIPE на каждой
        # записи в stdout. Для winws.exe это не страшно, а для TgWsProxy
        # могло обернуться падением. Файл от Hub не зависит вообще.
        self.raw_log: Optional[Path] = None
        self._tail_stop = threading.Event()
        self._tail_thread: Optional[threading.Thread] = None
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

        # отдельный файл вместо pipe: компонент пишет вывод сам и больше
        # никак от Hub не зависит. Hub лишь подглядывает в файл, чтобы
        # показывать строки в интерфейсе.
        raw = Path(self._writer.path).parent / (self.key + ".out.log")
        self.raw_log = raw
        raw_handle = None
        try:
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw_handle = open(raw, "wb")
        except OSError:
            raw_handle = None

        try:
            self._proc = self._spawn(raw_handle, creationflags, startupinfo, env)
        except Exception as exc:  # noqa: BLE001 - файла нет, нет прав, job
            self.log_line.emit(f"[hub] failed to start: {exc}")
            self._proc = None
        if self._proc is None:
            if raw_handle is not None:
                try:
                    raw_handle.close()
                except OSError:
                    pass
            self._set_status(STATUS_CRASHED)
            return False

        # копию дескриптора в родителе закрываем: у ребёнка своя, и файл
        # остаётся открытым у него даже после смерти Hub
        if raw_handle is not None:
            try:
                raw_handle.close()
            except OSError:
                pass

        self._stopping = False
        self.started_at = time.time()
        self.exit_code = None
        self._tree_stop.clear()
        self._tail_stop.clear()
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

        if raw_handle is not None or self._proc.stdout is None:
            t = threading.Thread(target=self._tail, daemon=True)
            t.start()
            self._threads.append(t)
            self._tail_thread = t
        else:
            # файл открыть не удалось — читаем pipe как раньше
            t = threading.Thread(
                target=self._reader, args=(self._proc.stdout, "out"), daemon=True
            )
            t.start()
            self._threads.append(t)
        t = threading.Thread(target=self._monitor, daemon=True)
        t.start()
        self._threads.append(t)
        return True

    def _spawn(self, raw_handle, creationflags, startupinfo, env):
        """Создаёт процесс компонента.

        Вывод идёт в файл (`raw_handle`), а не в pipe: pipe привязывал бы
        компонент к Hub — стоит Hub умереть, и читающий конец исчезает.

        `CREATE_BREAKAWAY_FROM_JOB` отвязывает ребёнка от job-объекта Hub:
        некоторые среды (Citrix, AppLocker, песочницы) кладут процесс в job,
        и тогда вместе с Hub гасли бы и обходы. Флаг требует, чтобы job
        разрешал breakaway, иначе CreateProcess падает — поэтому сначала
        пробуем с флагом, а если не вышло, без него.
        """
        if win32.IS_WINDOWS and raw_handle is not None:
            try:
                return subprocess.Popen(
                    [str(self.exe)] + self.args,
                    cwd=str(self.cwd),
                    stdout=raw_handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags | BREAKAWAY_FROM_JOB,
                    startupinfo=startupinfo,
                    env=env,
                )
            except Exception:
                # job не разрешил breakaway — запускаем как раньше
                pass
        return subprocess.Popen(
            [str(self.exe)] + self.args,
            cwd=str(self.cwd),
            stdout=raw_handle if raw_handle is not None else subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
            env=env,
            text=raw_handle is None,
            encoding="utf-8",
            errors="replace",
        )

    def _tail(self) -> None:
        """Читает «сырой» файл вывода компонента и отдаёт строки в UI.

        Файл открывает и пишет сам компонент, поэтому этот поток ничего не
        держит: если Hub умрёт, компонент продолжит писать в файл, а вместе
        с ним продолжит работать и обход.
        """
        if self.raw_log is None:
            return
        pos = 0
        pending = b""
        while not self._tail_stop.wait(0.25):
            pos, pending = self._drain(pos, pending)
        # финальный добор: процесс уже умер, файл дописан до конца
        self._drain(pos, pending)

    def _drain(self, pos: int, pending: bytes):
        """Читает новые байты из файла вывода. Возвращает (позиция, остаток)."""
        try:
            if not self.raw_log.exists():
                return pos, pending
            size = self.raw_log.stat().st_size
            if size < pos:
                # файл обрезали — начинаем сначала
                pos = 0
                pending = b""
            if size == pos:
                return pos, pending
            with open(self.raw_log, "rb") as f:
                f.seek(pos)
                chunk = f.read(size - pos)
            pos = size
        except OSError:
            return pos, pending
        if not chunk:
            return pos, pending
        pending += chunk
        while b"\n" in pending:
            raw_line, _, pending = pending.partition(b"\n")
            text = raw_line.decode("utf-8", errors="replace").rstrip("\r")
            if text:
                self._writer.write(f"{time.strftime('%H:%M:%S')} {text}\n")
                self.log_line.emit(text)
        return pos, pending

    def _stop_tail(self) -> None:
        self._tail_stop.set()
        thread = self._tail_thread
        self._tail_thread = None
        if thread is not None and thread is not threading.current_thread():
            # поток просыпается каждые 0.25 c, секунды хватает с запасом;
            # дольше ждать нельзя — stop() вызывается из потока интерфейса
            thread.join(timeout=1.0)

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
        self._stop_tail()
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
        self._stop_tail()
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
