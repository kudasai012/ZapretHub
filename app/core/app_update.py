"""Обновление самой программы Zapret Hub через GitHub Releases.

Компоненты (zapret-discord-youtube, tg-ws-proxy) тянет ``core.updater`` —
а этот модуль смотрит на релизы **самого Hub**: берёт последний релиз
репозитория ``kudasai012/ZapretHub``, сравнивает его тег с версией
программы и, если версия свежее, отдаёт описание изменений (markdown из
тела релиза) и ссылку на установщик.

Установка идёт через ``ZapretHub-Setup-*.exe``: программа скачивает его,
запускает и закрывается — дальше работает установщик, он же заменит
файлы. Так не нужно угадывать, какие файлы подменять, и не ломается
деинсталлятор.
"""
from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal

from .. import __version__
from . import github

#: установщик, который кладём в Release. Ищем по началу имени.
SETUP_PREFIX = "zaprethub-setup-"
#: портативный exe — на случай, если установщика почему-то нет
PORTABLE_NAME = "zaprethub.exe"


@dataclass
class AppRelease:
    """Информация о последнем релизе программы."""

    tag: str
    name: str
    body: str
    html_url: str
    published_at: str
    assets: List[github.Asset] = field(default_factory=list)
    #: текущая версия программы на момент проверки
    current: str = __version__

    @property
    def version(self) -> str:
        """Версия релиза без буквы «v» — для сравнения с нашей."""
        return github._normalize_tag(self.tag)

    @property
    def update_available(self) -> bool:
        return github.is_newer(self.version, self.current)

    def setup_asset(self) -> Optional[github.Asset]:
        """Установщик из релиза, если он там есть."""
        return self.find_asset(
            lambda name: name.startswith(SETUP_PREFIX) and name.endswith(".exe")
        )

    def portable_asset(self) -> Optional[github.Asset]:
        return self.find_asset(lambda name: name == PORTABLE_NAME)

    def find_asset(self, predicate) -> Optional[github.Asset]:
        for asset in self.assets:
            if predicate(asset.name.lower()):
                return asset
        return None


class AppUpdater(QObject):
    """Проверка и установка обновлений самой программы."""

    check_started = Signal()
    check_finished = Signal(object)        # AppRelease
    check_failed = Signal(str)
    progress = Signal(str, int, int)       # сообщение, скачано, всего
    downloaded = Signal(str)               # путь к файлу
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._threads: List[threading.Thread] = []

    # ------------------------------------------------------------ проверка

    def check(self, proxy: str = "") -> None:
        """Запрашивает последний релиз в отдельном потоке."""
        thread = threading.Thread(
            target=self._check_worker, args=(proxy,), daemon=True
        )
        self._threads.append(thread)
        thread.start()

    def _check_worker(self, proxy: str) -> None:
        self.check_started.emit()
        try:
            client = github.GitHubClient(proxy=proxy)
            release = client.latest_release(github_repo())
        except github.GitHubError as exc:
            self.check_failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - сети бывают любыми
            self.check_failed.emit(str(exc))
            return
        self.check_finished.emit(
            AppRelease(
                tag=release.tag,
                name=release.name,
                body=release.body,
                html_url=release.html_url,
                published_at=release.published_at,
                assets=list(release.assets),
            )
        )

    # ------------------------------------------------------------ скачивание

    def download(self, asset: github.Asset, dest_dir: Optional[Path] = None) -> None:
        """Качает установщик во временную папку."""
        thread = threading.Thread(
            target=self._download_worker, args=(asset, dest_dir), daemon=True
        )
        self._threads.append(thread)
        thread.start()

    def _download_worker(
        self, asset: github.Asset, dest_dir: Optional[Path]
    ) -> None:
        target_dir = Path(dest_dir) if dest_dir else Path(tempfile.gettempdir())
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        dest = target_dir / asset.name

        def on_progress(done: int, total: int) -> None:
            self.progress.emit(asset.name, done, total)

        try:
            client = github.GitHubClient()
            client.download(asset.url, dest, progress_cb=on_progress)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.downloaded.emit(str(dest))

    # ------------------------------------------------------------ установка

    @staticmethod
    def launch(path: Path) -> bool:
        """Запускает установщик. True — получилось."""
        import subprocess
        import sys

        try:
            if sys.platform.startswith("win"):
                # ShellExecute: установщик сам попросит повышение прав
                import ctypes

                result = ctypes.windll.shell32.ShellExecuteW(
                    None, "open", str(path), None, str(path.parent), 1
                )
                return int(result) > 32
            subprocess.Popen([str(path)])
            return True
        except Exception:  # noqa: BLE001
            return False


def github_repo() -> str:
    """Репозиторий программы — из ``app/__init__.py``."""
    from .. import GITHUB_REPO

    return GITHUB_REPO


def check_now(proxy: str = "") -> Optional[AppRelease]:
    """Синхронная проверка (для фоновой проверки при старте)."""
    try:
        client = github.GitHubClient(proxy=proxy)
        release = client.latest_release(github_repo())
    except Exception:  # noqa: BLE001
        return None
    info = AppRelease(
        tag=release.tag,
        name=release.name,
        body=release.body,
        html_url=release.html_url,
        published_at=release.published_at,
        assets=list(release.assets),
    )
    return info if info.update_available else None
