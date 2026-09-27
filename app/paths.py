r"""Пути приложения Zapret Hub.

Программа работает в двух режимах.

**Установленная** (exe лежит в ``C:\\Program Files\\Zapret Hub``):

    C:/Program Files/Zapret Hub/       <- BASE_DIR: только чтение
        ZapretHub.exe
        assets\icon.ico
    %LOCALAPPDATA%\Zapret Hub\        <- DATA_ROOT: сюда пишем
        data\         конфиг, манифест версий, логи, бэкапы, блокировка
        components\   скачанные zapret-discord-youtube и tg-ws-proxy

В ``Program Files`` писать нельзя без прав администратора, поэтому всё
изменяемое уезжает в профиль пользователя. Портабельный режим включается
файлом ``portable.txt`` рядом с exe — тогда данные снова лежат в папке
программы (поведение прежних сборок).

**Из исходников** (``python run.pyw``): данные остаются в папке проекта,
чтобы ничего не разъезжалось при разработке.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

#: имя папки данных в профиле пользователя
APP_DIR_NAME = "Zapret Hub"


def _base_dir() -> Path:
    """Корень программы: папка exe (если собрано) или папка исходников."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # app/paths.py -> app/ -> корень проекта
    return Path(__file__).resolve().parent.parent


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _user_data_dir() -> Path:
    """Папка изменяемых данных в профиле пользователя."""
    if sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / APP_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    root = os.environ.get("XDG_DATA_HOME")
    if root:
        return Path(root) / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def _data_root() -> Path:
    """Корень для всего изменяемого: конфиг, логи, компоненты, бэкапы."""
    if not _is_frozen():
        # из исходников — всё в проекте
        return BASE_DIR
    if (BASE_DIR / "portable.txt").exists():
        # портабельный режим просили явно
        return BASE_DIR
    return _user_data_dir()


BASE_DIR: Path = _base_dir()

#: куда писать: рядом с программой (портабельно) или в профиль пользователя
DATA_ROOT: Path = _data_root()

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


def is_portable() -> bool:
    """True — данные лежат рядом с программой, False — в профиле."""
    return DATA_ROOT == BASE_DIR


def migrate_portable_data() -> bool:
    """Переносит данные из папки программы в профиль (один раз).

    Нужно тем, кто запускал прежние сборки из ``dist\\``: их ``data\\``
    осталась рядом с exe. Копируем только если в профиле ещё пусто —
    иначе свежие настройки затрём старыми.
    """
    if DATA_ROOT == BASE_DIR:
        return False
    old = BASE_DIR / "data"
    new = DATA_DIR
    try:
        if not old.is_dir() or new.exists():
            return False
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(old, new)
        return True
    except OSError:
        return False


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги (идемпотентно)."""
    for d in (COMPONENTS_DIR, DATA_DIR, LOGS_DIR, BACKUPS_DIR, TEMP_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def is_windows() -> bool:
    return sys.platform.startswith("win")


def open_in_file_manager(path: Path) -> None:
    """Открыть проводник/файловый менеджер на нужном пути."""
    path = Path(path)
