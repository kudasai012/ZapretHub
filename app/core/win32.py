"""Windows-специфичные helpers (на прочих платформах — безопасные заглушки)."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

IS_WINDOWS = sys.platform.startswith("win")

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_RUN_NAME = "ZapretHub"


# ---------------------------------------------------------------- права админа

def is_admin() -> bool:
    if not IS_WINDOWS:
        return True  # вне Windows проверка не имеет смысла
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def relaunch_elevated(args: list[str] | None = None) -> bool:
    """Перезапустить текущий процесс с повышением прав (UAC)."""
    if not IS_WINDOWS:
        return False
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = " ".join(args or sys.argv[1:])
        else:
            exe = sys.executable
            script = str(Path(sys.argv[0]).resolve())
            params = " ".join([f'"{script}"'] + list(args or sys.argv[1:]))
        rc = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", exe, params, None, 1
        )
        return int(rc) > 32
    except Exception:
        return False


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong(0)
                kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                return code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- процессы

def creation_flags() -> int:
    return CREATE_NO_WINDOW if IS_WINDOWS else 0


def descendant_pids(pid: int) -> list[int]:
    """PID процесса и всех его потомков (по снимку таблицы процессов).

    Нужен, чтобы остановить компонент целиком: TgWsProxy_windows.exe —
    PyInstaller-onefile с графической подсистемой, он распаковывает себя в
    %TEMP%\\_MEIxxxxx и запускает второй процесс с тем же именем. Гасить
    только тот процесс, который мы запустили, бесполезно — распакованный
    останется висеть отдельной программой.

    Снимок снимается, пока процесс ещё жив: по его PID потомки и ищутся.
    """
    if pid <= 0:
        return []
    if not IS_WINDOWS:
        return [pid]

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = -1

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_ulong),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_char * 260),
        ]

    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE or snapshot == 0:
            return [pid]
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        children: dict[int, list[int]] = {}
        alive: set[int] = set()
        try:
            ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
            while ok:
                alive.add(int(entry.th32ProcessID))
                children.setdefault(int(entry.th32ParentProcessID), []).append(
                    int(entry.th32ProcessID)
                )
                ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:
        return [pid]

    if pid not in alive:
        return []
    result = [pid]
    queue = [pid]
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in result:
                result.append(child)
                queue.append(child)
    return result


def terminate_pid(pid: int) -> bool:
    """TerminateProcess по одному PID (Windows)."""
    if pid <= 0 or not IS_WINDOWS:
        return False
    PROCESS_TERMINATE = 0x0001
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(kernel32.TerminateProcess(handle, 1))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


# ---------------------------------------------------------------- рабочие столы

# права на создаваемый стол: GENERIC_ALL. Важно, что здесь есть
# DESKTOP_CREATEWINDOW — без него процесс на этом столе не сможет создать
# окно, и tray-программа просто не запустится.
DESKTOP_ACCESS = 0x10000000
_HUB_DESKTOP = "ZapretHub"


def create_desktop(name: str = _HUB_DESKTOP) -> Optional[int]:
    """Создаёт отдельный (скрытый) рабочий стол и возвращает его хэндл.

    Нужен, чтобы сторонняя tray-программа не светилась в трее пользователя:
    её иконка уходит в область уведомлений того стола, на котором она
    запущена, а на нашем столе нет проводника — иконка нигде не видна.
    Сам прокси от этого не меняется: он работает с сетью, а не с окнами.
    """
    if not IS_WINDOWS:
        return None
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.CreateDesktopW.restype = ctypes.c_void_p
        user32.CreateDesktopW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong,
            ctypes.c_ulong, ctypes.c_void_p,
        ]
        handle = user32.CreateDesktopW(name, None, None, 0, DESKTOP_ACCESS, None)
        if not handle:
            # запасной вариант: полный набор прав стола плюс стандартные
            specific = 0x01FF  # все DESKTOP_* права
            standard = 0x001F0000  # стандартные права + SYNCHRONIZE
            handle = user32.CreateDesktopW(
                name, None, None, 0, specific | standard, None
            )
        return int(handle) if handle else None
    except Exception:
        return None


def close_desktop(handle: Optional[int]) -> None:
    """Закрывает хэндл рабочего стола (сам стол живёт, пока есть процессы)."""
    if not handle or not IS_WINDOWS:
        return
    try:
        ctypes.windll.user32.CloseDesktop(ctypes.c_void_p(handle))  # type: ignore[attr-defined]
    except Exception:
        pass


# ---------------------------------------------------------------- область уведомлений

TB_BUTTONCOUNT = 0x0418
TB_GETBUTTON = 0x0417
TB_DELETEBUTTON = 0x0416
PROCESS_VM_RW = 0x0008 | 0x0010 | 0x0020  # OPERATION | READ | WRITE
NIM_DELETE = 0x00000002
# сколько максимум окон процесса тыкаем NIM_DELETE
MAX_ICON_WINDOWS = 24


class _TBBUTTON(ctypes.Structure):
    """Кнопка панели области уведомлений (размер зависит от разрядности)."""

    _fields_ = [
        ("iBitmap", ctypes.c_int),
        ("idCommand", ctypes.c_int),
        ("fsState", ctypes.c_ubyte),
        ("fsStyle", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte * 2),
        ("dwData", ctypes.c_void_p),
        ("iString", ctypes.c_void_p),
    ]


class _TRAYDATA(ctypes.Structure):
    """Данные иконки в области уведомлений: какое окно её показало."""

    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("reserved", ctypes.c_uint * 2),
    ]


class _NOTIFYICONDATA(ctypes.Structure):
    """NOTIFYICONDATAW — размер версии V3, его принимает любой Windows."""

    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_uint),
        ("dwStateMask", ctypes.c_uint),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_uint),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_uint),
        ("guidItem", ctypes.c_ubyte * 16),
    ]


def _declare_user32() -> None:
    """Явные прототипы: без них ctypes режет 64-битные указатели до 32 бит."""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
    ]
    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    user32.SendMessageTimeoutW.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
        ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong),
    ]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.GetWindowThreadProcessId.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong),
    ]
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowExW.restype = ctypes.c_void_p
    user32.FindWindowExW.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
    ]
    user32.EnumWindows.restype = ctypes.c_int
    user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_long]
    user32.Shell_NotifyIconW.restype = ctypes.c_int
    user32.Shell_NotifyIconW.argtypes = [
        ctypes.c_uint, ctypes.POINTER(_NOTIFYICONDATA),
    ]


def _send(toolbar: int, message: int, wparam: int, lparam: int) -> int:
    """SendMessageTimeoutW: чужая панель не должна подвесить нас навсегда."""
    result = ctypes.c_ulong(0)
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    return int(
        user32.SendMessageTimeoutW(
            ctypes.c_void_p(toolbar), message, wparam, lparam, 2, None,
            ctypes.byref(result),
        )
    )


def _tray_toolbars() -> list:
    """Панели области уведомлений (видимые и скрытые иконки)."""
    if not IS_WINDOWS:
        return []
    toolbars: list = []
    try:
        _declare_user32()
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        if not tray:
            return []
        notify = user32.FindWindowExW(tray, 0, "TrayNotifyWnd", None)
        if not notify:
            return []
        # панели лежат прямо в TrayNotifyWnd и внутри SysPager
        roots = [notify]
        pager = user32.FindWindowExW(notify, 0, "SysPager", None)
        if pager:
            roots.append(pager)
        for root in roots:
            child = 0
            while True:
                child = user32.FindWindowExW(root, child, "ToolbarWindow32", None)
                if not child:
                    break
                toolbars.append(child)
    except Exception:
        return []
    return toolbars


def _windows_of_pids(pids: set) -> list:
    """Все top-level окна процессов из `pids`."""
    if not IS_WINDOWS:
        return []
    found: list = []
    try:
        _declare_user32()
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_long
        )

        @callback_type
        def _enum(hwnd, _lparam):  # noqa: ANN001
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and len(found) < MAX_ICON_WINDOWS:
                found.append(int(hwnd))
            return 1

        user32.EnumWindows(_enum, 0)
    except Exception:
        return found
    return found


def _notify_delete(hwnd: int, uid: int) -> bool:
    """Пробует снять иконку через Shell_NotifyIconW(NIM_DELETE)."""
    try:
        _declare_user32()
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        data = _NOTIFYICONDATA()
        data.cbSize = ctypes.sizeof(_NOTIFYICONDATA)
        data.hWnd = ctypes.c_void_p(hwnd)
        data.uID = uid
        data.uFlags = 0
        return bool(user32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data)))
    except Exception:
        return False


def _delete_tray_buttons(pids: set) -> int:
    """Удаляет кнопки иконок наших процессов прямо из панели уведомлений."""
    removed = 0
    try:
        _declare_user32()
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.VirtualAllocEx.restype = ctypes.c_void_p
        kernel32.VirtualAllocEx.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.c_ulong, ctypes.c_ulong,
        ]
        kernel32.VirtualFreeEx.restype = ctypes.c_int
        kernel32.VirtualFreeEx.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong,
        ]
        kernel32.ReadProcessMemory.restype = ctypes.c_int
        kernel32.ReadProcessMemory.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_void_p,
        ]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    except Exception:
        return 0

    for toolbar in _tray_toolbars():
        count = _send(toolbar, TB_BUTTONCOUNT, 0, 0)
        if not count or count < 0 or count > 512:
            continue
        owner = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(
            ctypes.c_void_p(toolbar), ctypes.byref(owner)
        )
        if not owner.value:
            continue
        handle = kernel32.OpenProcess(PROCESS_VM_RW, False, owner.value)
        if not handle:
            continue
        try:
            remote = kernel32.VirtualAllocEx(
                handle, None, ctypes.sizeof(_TBBUTTON),
                0x1000 | 0x2000, 0x40,
            )
            if not remote:
                continue
            try:
                for index in range(count - 1, -1, -1):
                    if not _send(toolbar, TB_GETBUTTON, index, remote):
                        continue
                    local = _TBBUTTON()
                    if not kernel32.ReadProcessMemory(
                        handle, ctypes.c_void_p(remote),
                        ctypes.byref(local), ctypes.sizeof(local), None,
                    ):
                        continue
                    if not local.dwData:
                        continue
                    data = _TRAYDATA()
                    if not kernel32.ReadProcessMemory(
                        handle, ctypes.c_void_p(local.dwData),
                        ctypes.byref(data), ctypes.sizeof(data), None,
                    ):
                        continue
                    if not data.hwnd:
                        continue
                    icon_owner = ctypes.c_ulong(0)
                    user32.GetWindowThreadProcessId(
                        ctypes.c_void_p(data.hwnd), ctypes.byref(icon_owner)
                    )
                    if icon_owner.value in pids:
                        _send(toolbar, TB_DELETEBUTTON, index, 0)
                        removed += 1
            finally:
                kernel32.VirtualFreeEx(handle, ctypes.c_void_p(remote), 0, 0x8000)
        finally:
            kernel32.CloseHandle(handle)
    return removed


def remove_tray_icons(pids) -> int:
    """Убирает из области уведомлений иконки процессов из `pids`.

    Два независимых способа: сначала пробуем снять иконку через
    Shell_NotifyIconW(NIM_DELETE) для окон наших процессов (не требует
    доступа к памяти проводника), затем удаляем кнопку прямо из панели
    уведомлений. Удаляются только свои иконки, чужие не трогаются, любая
    ошибка молча игнорируется — это косметика.
    """
    wanted = {int(pid) for pid in pids if pid and int(pid) > 0}
    if not wanted or not IS_WINDOWS:
        return 0
    removed = 0
    try:
        for hwnd in _windows_of_pids(wanted):
            for uid in (0, 1):
                if _notify_delete(hwnd, uid):
                    removed += 1
    except Exception:
        pass
    try:
        removed += _delete_tray_buttons(wanted)
    except Exception:
        pass
    return removed


def kill_pids(pids) -> int:
    """Убить список процессов: terminate на Windows, signal — на прочих."""
    killed = 0
    for pid in pids:
        if pid <= 0:
            continue
        if IS_WINDOWS:
            if terminate_pid(int(pid)):
                killed += 1
            continue
        try:
            os.kill(int(pid), 15)
            killed += 1
        except OSError:
            pass
    return killed


def kill_process_tree(pid: int) -> bool:
    """Жёстко убить дерево процессов (Windows: taskkill /T /F)."""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            res = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=15,
            )
            return res.returncode == 0
        except Exception:
            return False
    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def run_hidden(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, timeout=timeout, creationflags=creation_flags()
    )


# ------------------------------------------------- вежливая просьба закрыться

#: Установщик Inno Setup закрывает программу, посылая окну WM_CLOSE. Если
#: компоненты запущены, окно спрашивает «Выйди?» — и установка встаёт.
#: Поэтому установщик перед этим создаёт маркерный файл, а программа,
#: увидев его, закрывается без вопросов.
QUIT_REQUEST_DIR = Path(tempfile.gettempdir()) / "ZapretHub"
QUIT_REQUEST_FILE = QUIT_REQUEST_DIR / "quit-request"


def quit_requested() -> bool:
    """True — установщик просит закрыться, спрашивать пользователя не надо."""
    try:
        return QUIT_REQUEST_FILE.exists()
    except OSError:
        return False


def clear_quit_request() -> None:
    """Убирает маркер (вызывается при штатном выходе)."""
    try:
        QUIT_REQUEST_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- автозапуск

def _open_run_key(write: bool = False):
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        _RUN_KEY,
        0,
        winreg.KEY_ALL_ACCESS if write else winreg.KEY_READ,
    )


def build_start_command(extra_args: list[str] | None = None) -> str:
    """Команда для автозапуска: pythonw run.pyw --tray  (или exe при сборке)."""
    args = list(extra_args or [])
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        parts = [f'"{exe}"']
    else:
        pythonw = Path(sys.executable).resolve().parent / "pythonw.exe"
        interpreter = pythonw if pythonw.exists() else Path(sys.executable).resolve()
        script = Path(sys.argv[0]).resolve()
        parts = [f'"{interpreter}"', f'"{script}"']
    if args:
        parts.append(" ".join(args))
    return " ".join(parts)


def autostart_is_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        with _open_run_key() as key:
            winreg.QueryValueEx(key, _APP_RUN_NAME)
        return True
    except Exception:
        return False


def autostart_set(enabled: bool, extra_args: list[str] | None = None) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        with _open_run_key(write=True) as key:
            if enabled:
                winreg.SetValueEx(key, _APP_RUN_NAME, 0, winreg.REG_SZ, build_start_command(extra_args))
            else:
                try:
                    winreg.DeleteValue(key, _APP_RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def autostart_command() -> str:
    if not IS_WINDOWS:
        return ""
    try:
        import winreg

        with _open_run_key() as key:
            value, _ = winreg.QueryValueEx(key, _APP_RUN_NAME)
            return str(value)
    except Exception:
        return ""


# ---------------------------------------------------------------- прочее

def enable_tcp_timestamps() -> bool:
    """netsh interface tcp set global timestamps=enabled (как в service.bat)."""
    if not IS_WINDOWS:
        return False
    try:
        res = subprocess.run(
            ["netsh", "interface", "tcp", "set", "global", "timestamps=enabled"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=20,
        )
        return res.returncode == 0
    except Exception:
        return False


def query_service(name: str) -> str | None:
    """Состояние службы Windows: RUNNING / STOPPED / None (не установлена)."""
    if not IS_WINDOWS:
        return None
    try:
        res = subprocess.run(
            ["sc", "query", name],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=15,
        )
        if res.returncode != 0:
            return None
        text = res.stdout.decode("cp866", errors="replace") + res.stdout.decode(
            "utf-8", errors="replace"
        )
        for line in text.splitlines():
            if "STATE" in line.upper():
                parts = line.split(":", 1)
                if len(parts) == 2:
                    state = parts[1].strip().split()[0] if parts[1].strip() else ""
                    return state.upper() or None
        return "UNKNOWN"
    except Exception:
        return None


def remove_service(name: str) -> bool:
    if not IS_WINDOWS:
        return False
    ok = True
    try:
        subprocess.run(
            ["net", "stop", name],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=30,
        )
    except Exception:
        ok = False
    try:
        res = subprocess.run(
            ["sc", "delete", name],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=30,
        )
        ok = ok and res.returncode == 0
    except Exception:
        ok = False
    return ok


def find_processes_by_image(image: str) -> list[dict]:
    """Все живые процессы с таким именем: [{"pid": int, "name": str}, ...].

    Windows: tasklist /FO CSV. Linux: /proc (для отладки и тестов).
    """
    wanted = image.lower()
    found: list[dict] = []
    if IS_WINDOWS:
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH", "/FO", "CSV"],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=20,
            )
            raw = res.stdout.decode("cp866", errors="replace")
            if not raw.strip():
                raw = res.stdout.decode("utf-8", errors="replace")
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("INFO:"):
                    continue
                parts = [p.strip().strip('"') for p in line.split('","')]
                parts = [p.strip('"') for p in parts]
                if len(parts) < 2:
                    continue
                name = parts[0]
                try:
                    pid = int(parts[1])
                except ValueError:
                    continue
                if name.lower() == wanted:
                    found.append({"pid": pid, "name": name})
        except Exception:
            return []
        return found

    # --- не-Windows: разбор /proc ---
    try:
        import os

        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                comm = Path(f"/proc/{entry}/comm").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if comm.lower() == wanted:
                found.append({"pid": int(entry), "name": comm})
    except Exception:
        return []
    return found


def kill_foreign_processes(image: str, own_pids: Optional[set] = None) -> list[int]:
    """Гасит все процессы `image`, кроме переданных в own_pids.

    Возвращает список PID, которые удалось остановить. Свои дочерние процессы
    (те, что запустил Hub) никогда не трогаются.
    """
    own = {int(p) for p in (own_pids or set())}
    killed: list[int] = []
    for proc in find_processes_by_image(image):
        pid = proc["pid"]
        if pid in own or pid == os.getpid():
            continue
        if kill_process_tree(pid):
            killed.append(pid)
    return killed


def image_path_running(image: str) -> bool:
    """Есть ли живой процесс с таким именем (winws.exe, TgWsProxy_windows.exe)."""
    if not IS_WINDOWS:
        return False
    try:
        res = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=20,
        )
        out = res.stdout.decode("cp866", errors="replace") + res.stdout.decode(
            "utf-8", errors="replace"
        )
        return image.lower() in out.lower()
    except Exception:
        return False
