r"""Пути приложения Zapret Hub.

Программа живёт **там, куда её поставили**: папка exe — это и есть корень
программы, и данные лежат там же.

    C:/Program Files/Zapret Hub/     <- BASE_DIR, всё здесь
        ZapretHub.exe
        assets/
        data/            конфиг, манифест версий, логи, бэкапы, блокировка
        components/      скачанные zapret-discord-youtube и tg-ws-proxy
        unins000.exe     деинсталлятор (если ставили через установщик)

Никакого профиля пользователя и никакого портабельного режима: папка одна,
поэтому «Открыть папку компонентов» и «Открыть папку логов» ведут в одно
предсказуемое место. Запись в ``Program Files`` требует прав администратора,
а они zapret'у нужны и так — программа сама перезапускается с повышением.

**Из исходников** (``python run.pyw``): корень — папка проекта, данные
рядом с ней. Логика та же, отличается только путь.
"""
from __future__ import annotations

import subprocess
import sys
import webbrowser
from pathlib import Path

#: имя папки данных внутри папки программы
APP_DIR_NAME = "Zapret Hub"


def _base_dir() -> Path:
    """Корень программы: папка exe (если собрано) или папка исходников."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # app/paths.py -> app/ -> корень проекта
    return Path(__file__).resolve().parent.parent


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


BASE_DIR: Path = _base_dir()

#: куда писать. Всегда рядом с программой: портабельного режима и профиля
#: пользователя больше нет — иначе «Открыть папку» вела бы не туда, куда
#: человек думает.
DATA_ROOT: Path = BASE_DIR

COMPONENTS_DIR: Path = DATA_ROOT / "components"
DATA_DIR: Path = DATA_ROOT / "data"
LOGS_DIR: Path = DATA_DIR / "logs"
BACKUPS_DIR: Path = DATA_DIR / "backups"
TEMP_DIR: Path = DATA_DIR / "tmp"

CONFIG_FILE: Path = DATA_DIR / "config.json"
MANIFEST_FILE: Path = DATA_DIR / "components.json"
LOCK_FILE: Path = DATA_DIR / "hub.lock"
HUB_LOG_FILE: Path = LOGS_DIR / "hub.log"

# Компоненты
ZAPRET_DIR: Path = COMPONENTS_DIR / "zapret-discord-youtube"
TGWS_DIR: Path = COMPONENTS_DIR / "tg-ws-proxy"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги (идемпотентно).

    Заодно выдаёт группе «Пользователи» полный доступ к каждой папке.
    Программа работает с повышением прав (winws.exe требует WinDivert), а
    проводник — всегда без него, и без этого шага кнопки «Папка логов» и
    «Папка компонентов» молча ничего не открывали: папка есть, но открыть
    её нечем. Особенно это заметно при установке в ``AppData\\Local``:
    установщик тоже повышенный, и владельцем папки становится «Администраторы».
    """
    for d in (
        COMPONENTS_DIR,
        DATA_DIR,
        LOGS_DIR,
        BACKUPS_DIR,
        TEMP_DIR,
        ZAPRET_DIR,
        TGWS_DIR,
    ):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        _grant_users_access(d)


def uninstaller_path() -> Path | None:
    """Путь к ``unins000.exe`` рядом с программой, если он есть.

    Inno Setup кладёт деинсталлятор в папку установки, поэтому кнопка
    «Удалить программу» работает только для установленной копии.
    """
    if not _is_frozen():
        return None
    candidate = BASE_DIR / "unins000.exe"
    return candidate if candidate.is_file() else None


#: SID группы «Пользователи» (BUILTIN\\Users). Берём именно SID, а не имя:
#: на локализованной Windows имя группы другое, а SID всегда один.
_USERS_SID = "*S-1-5-32-545"


def _grant_users_access(path: Path) -> None:
    """Выдаёт группе «Пользователи» полный доступ к папке.

    Зачем: программа **всегда** работает с повышением прав — winws.exe
    требует WinDivert, а без администратора он не стартует. Проводник же в
    Windows всегда запущен **без** повышения. Папки, которые создал
    повышенный процесс, наследуют права от родителя, и если владелец
    родителя — «Администраторы» (так бывает при установке в AppData\\Local:
    установщик тоже повышенный), проводник не может открыть такую папку и
    молча ничего не показывает. Право выдаём явно и с наследованием, чтобы
    новые файлы внутри тоже открывались.

    Ошибки молча игнорируются: если не получилось, открытие всё равно
    пытаемся — вдруг права и так в порядке.
    """
    if not is_windows():
        return
    try:
        subprocess.run(
            [
                "icacls",
                str(path),
                "/grant",
                f"{_USERS_SID}:(OI)(CI)F",
                "/C",
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except Exception:  # noqa: BLE001 - права не критичны для открытия
        pass


def _open_windows(path: Path) -> None:
    """Открыть папку в проводнике Windows.

    ``os.startfile`` — это ``ShellExecute`` на самой папке, и из процесса
    с повышением прав он не всегда срабатывает: проводник работает без
    повышения, и UIPI (User Interface Privilege Isolation) не даёт ему
    принять команду от повышенного процесса. Поэтому есть запасные
    способы, и первый из них — запустить ``explorer.exe`` с путём
    аргументом: так запрос уходит напрямую, а не через существующий
    экземпляр проводника.
    """
    import os

    # 1. Прямой запуск explorer.exe с путём. Работает из повышенного
    #    процесса, когда os.startfile молчит.
    try:
        subprocess.Popen(
            ["explorer", str(path)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    except Exception:  # noqa: BLE001 - пробуем следующий способ
        pass

    # 2. Обычный ассоциативный запуск.
    try:
        os.startfile(str(path))  # noqa: S606 - путь из нашей же конфигурации
        return
    except Exception:  # noqa: BLE001
        pass

    # 3. Последнее средство — через командную строку.
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", str(path)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            shell=False,
        )
    except Exception:  # noqa: BLE001 - зовущий покажет причину
        raise


def open_in_file_manager(path: Path) -> bool:
    """Открыть проводник на нужном пути. True — получилось.

    Именно эта функция раньше была пустой заготовкой, из-за чего кнопки
    «Открыть папку компонентов» и «Открыть папку логов» молча ничего не
    делали. Папку создаём перед открытием: иначе проводник ругается,
    что пути не существует.
    """
    path = Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    # Права выдаём до открытия: иначе проводник откроет папку пустой или
    # не откроет вовсе, и причина будет невидимой.
    _grant_users_access(path)
    try:
        if sys.platform.startswith("win"):
            _open_windows(path)
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return True
        subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:  # noqa: BLE001 - нечего показывать, зовущий сам решит
        return False


def open_url(url: str) -> bool:
    """Открыть ссылку в браузере по умолчанию. True — получилось."""
    try:
        webbrowser.open(str(url))
        return True
    except Exception:  # noqa: BLE001
        return False
