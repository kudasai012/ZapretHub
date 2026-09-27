"""Установка и обновление компонентов через GitHub Releases.

Zapret публикуется архивом (.zip), TG WS Proxy — одним .exe.
При обновлении zapret пользовательские списки и настройки (game filter,
ipset) сохраняются, а предыдущая версия уезжает в data/backups/.
"""
from __future__ import annotations

import platform
import shutil
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from .. import paths
from ..config import AppConfig, load_manifest, save_manifest
from . import github
from .github import GitHubClient, Release

ZAPRET_REPO = "Flowseal/zapret-discord-youtube"
TGWS_REPO = "Flowseal/tg-ws-proxy"

# файлы zapret, которые переживают обновление
PRESERVE_ZAPRET = [
    "lists/list-general-user.txt",
    "lists/list-exclude-user.txt",
    "lists/ipset-exclude-user.txt",
    "lists/ipset-all.txt",
    "lists/ipset-all.txt.backup",
    "utils/game_filter.enabled",
]


@dataclass
class UpdateInfo:
    component: str                      # "zapret" | "tgws"
    installed: Optional[str]
    latest: str
    release: Optional[Release] = None
    update_available: bool = False
    not_installed: bool = False
    asset_name: str = ""
    error: str = ""

    @property
    def display_name(self) -> str:
        return "zapret-discord-youtube" if self.component == "zapret" else "TG WS Proxy"


def tgws_asset_name() -> str:
    """Выбор сборки TgWsProxy под архитектуру и версию Windows."""
    machine = (platform.machine() or "").lower()
    is_arm = "arm" in machine or "aarch" in machine
    is_64 = machine.endswith("64") or "amd64" in machine or "x86_64" in machine
    win_ver = getattr(sys, "getwindowsversion", lambda: None)()
    is_win7 = bool(win_ver) and (win_ver.major, win_ver.minor) == (6, 1)
    if is_arm:
        return "TgWsProxy_windows_arm64.exe"
    if is_win7:
        return "TgWsProxy_windows_7_64bit.exe" if is_64 else "TgWsProxy_windows_7_32bit.exe"
    return "TgWsProxy_windows.exe"


def _strip_v(version: str) -> str:
    return (version or "").strip().lstrip("vV")


def _write_version_marker(directory: Path, version: str) -> None:
    """Пишет .version рядом с компонентом — переживает удаление data/."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".version").write_text(version.strip(), encoding="utf-8")
    except OSError:
        pass


def read_version_marker(directory: Path) -> Optional[str]:
    try:
        text = (Path(directory) / ".version").read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


class Updater(QObject):
    check_started = Signal()
    check_finished = Signal(list)          # List[UpdateInfo]
    check_failed = Signal(str)
    progress = Signal(str, int, int)       # component, done, total
    status = Signal(str)                   # сообщение для UI
    installed = Signal(str, str)           # component, version
    failed = Signal(str, str)              # component, message
    log_line = Signal(str)

    def __init__(self, config: AppConfig, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.config = config
        self._threads: List[threading.Thread] = []

    # ------------------------------------------------------------ версии

    def installed_versions(self) -> Dict[str, Optional[str]]:
        manifest = load_manifest()
        zapret_ver = None
        service_bat = paths.ZAPRET_DIR / "service.bat"
        if service_bat.exists():
            try:
                import re

                text = service_bat.read_text(encoding="utf-8", errors="replace")
                m = re.search(r'set\s+"LOCAL_VERSION=([^"]+)"', text, re.IGNORECASE)
                if m:
                    zapret_ver = m.group(1).strip()
            except OSError:
                pass
        if not zapret_ver:
            zapret_ver = (manifest.get("zapret") or {}).get("version")
        tgws_ver = (manifest.get("tgws") or {}).get("version") or read_version_marker(
            paths.TGWS_DIR
        )
        return {"zapret": zapret_ver, "tgws": tgws_ver}

    def is_installed(self, component: str) -> bool:
        if component == "zapret":
            return (paths.ZAPRET_DIR / "bin" / "winws.exe").exists()
        return (paths.TGWS_DIR / "TgWsProxy_windows.exe").exists()

    # ------------------------------------------------------------ проверка

    def check_all(self) -> None:
        t = threading.Thread(target=self._check_all_worker, daemon=True)
        t.start()
        self._threads.append(t)

    def _check_all_worker(self) -> None:
        self.check_started.emit()
        client = GitHubClient(proxy=self.config.updates.proxy)
        infos: List[UpdateInfo] = []
        try:
            versions = self.installed_versions()
            for component, repo in (("zapret", ZAPRET_REPO), ("tgws", TGWS_REPO)):
                installed = versions.get(component)
                info = UpdateInfo(component=component, installed=installed, latest=installed or "")
                info.not_installed = not self.is_installed(component)
                try:
                    release = client.latest_release(repo)
                    info.release = release
                    info.latest = _strip_v(release.tag)
                    info.update_available = github.is_newer(release.tag, installed or "")
                    if component == "tgws":
                        asset = self._pick_tgws_asset(release)
                        info.asset_name = asset.name if asset else ""
                    else:
                        asset = release.find_asset(lambda n: n.endswith(".zip"))
                        info.asset_name = asset.name if asset else ""
                except github.GitHubError as exc:
                    info.error = str(exc)
                    info.latest = installed or ""
                infos.append(info)
            self.check_finished.emit(infos)
        except Exception as exc:  # noqa: BLE001
            self.check_failed.emit(str(exc))

    def _pick_tgws_asset(self, release: Release):
        preferred = tgws_asset_name().lower()
        asset = release.find_asset(lambda n: n == preferred)
        if asset:
            return asset
        return release.find_asset(lambda n: n.startswith("tgwsproxy_windows") and n.endswith(".exe"))

    # ------------------------------------------------------------ установка

    def install(self, component: str, info: UpdateInfo, on_done: Optional[Callable] = None) -> None:
        t = threading.Thread(target=self._install_worker, args=(component, info, on_done), daemon=True)
        t.start()
        self._threads.append(t)

    def _install_worker(self, component: str, info: UpdateInfo, on_done) -> None:
        try:
            version = self._do_install(component, info)
            self.installed.emit(component, version)
            if on_done:
                on_done(True, version)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            self.failed.emit(component, message)
            if on_done:
                on_done(False, message)

    def _do_install(self, component: str, info: UpdateInfo) -> str:
        if not info.release:
            raise RuntimeError("Нет информации о релизе — сначала выполните проверку")
        if component == "zapret":
            asset = info.release.find_asset(lambda n: n.endswith(".zip"))
            if not asset:
                raise RuntimeError("В релизе нет .zip-архива")
            return self._install_zapret(asset.url, info.release.tag)
        asset = self._pick_tgws_asset(info.release)
        if not asset:
            raise RuntimeError("В релизе нет подходящей сборки TgWsProxy")
        return self._install_tgws(asset.url, info.release.tag)

    # ---- zapret ----

    def _install_zapret(self, url: str, tag: str) -> str:
        paths.ensure_dirs()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tmp_zip = paths.TEMP_DIR / f"zapret-{_strip_v(tag)}-{stamp}.zip"
        extract_dir = paths.TEMP_DIR / f"zapret-extract-{stamp}"

        self.status.emit("zapret: скачивание...")
        client = GitHubClient(proxy=self.config.updates.proxy)
        client.download(url, tmp_zip, progress_cb=lambda d, t: self.progress.emit("zapret", d, t))

        self.status.emit("zapret: распаковка...")
        try:
            with zipfile.ZipFile(tmp_zip) as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile as exc:
            raise RuntimeError("Архив повреждён") from exc

        root = self._single_root(extract_dir)
        if not (root / "bin" / "winws.exe").exists() and not (root / "winws.exe").exists():
            raise RuntimeError("В архиве не найден winws.exe")

        backup_dir: Optional[Path] = None
        if paths.ZAPRET_DIR.exists():
            backup_dir = paths.BACKUPS_DIR / f"zapret-{stamp}"
            try:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
                shutil.move(str(paths.ZAPRET_DIR), str(backup_dir))
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Не удалось создать резервную копию: {exc}") from exc

        try:
            shutil.move(str(root), str(paths.ZAPRET_DIR))
        except Exception as exc:  # noqa: BLE001
            if backup_dir and backup_dir.exists():
                shutil.move(str(backup_dir), str(paths.ZAPRET_DIR))
            raise RuntimeError(f"Не удалось установить новую версию: {exc}") from exc

        # сохраняем пользовательские настройки: список + все *-user.txt,
        # которые могли появиться в новой версии или быть добавлены вручную
        relatives = set(PRESERVE_ZAPRET)
        backup_lists = backup_dir / "lists" if backup_dir else None
        if backup_lists and backup_lists.exists():
            for extra in backup_lists.glob("*-user.txt"):
                relatives.add(f"lists/{extra.name}")
        if backup_dir and backup_dir.exists():
            for rel in sorted(relatives):
                src = backup_dir / rel
                dst = paths.ZAPRET_DIR / rel
                if src.exists():
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(src), str(dst))
                    except OSError:
                        pass

        version = _strip_v(tag)
        actual = self._zapret_version_from_disk()
        manifest = load_manifest()
        _write_version_marker(paths.ZAPRET_DIR, actual or version)
        manifest["zapret"] = {
            "version": actual or version,
            "release": version,
            "installed_at": stamp,
            "backup": str(backup_dir) if backup_dir else "",
        }
        save_manifest(manifest)

        self._cleanup_backups("zapret-", keep=3)
        try:
            tmp_zip.unlink(missing_ok=True)
            shutil.rmtree(extract_dir, ignore_errors=True)
        except OSError:
            pass
        return actual or version

    @staticmethod
    def _single_root(folder: Path) -> Path:
        entries = [p for p in folder.iterdir() if p.name not in ("__MACOSX",)]
        dirs = [p for p in entries if p.is_dir()]
        if len(entries) == 1 and dirs:
            return dirs[0]
        return folder

    def _zapret_version_from_disk(self) -> Optional[str]:
        import re

        service_bat = paths.ZAPRET_DIR / "service.bat"
        try:
            text = service_bat.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'set\s+"LOCAL_VERSION=([^"]+)"', text, re.IGNORECASE)
            return m.group(1).strip() if m else None
        except OSError:
            return None

    # ---- tgws ----

    def _install_tgws(self, url: str, tag: str) -> str:
        paths.ensure_dirs()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tmp_exe = paths.TEMP_DIR / f"TgWsProxy-{_strip_v(tag)}-{stamp}.exe"

        self.status.emit("tgws: скачивание...")
        client = GitHubClient(proxy=self.config.updates.proxy)
        client.download(url, tmp_exe, progress_cb=lambda d, t: self.progress.emit("tgws", d, t))

        if tmp_exe.stat().st_size < 1024 * 512:
            tmp_exe.unlink(missing_ok=True)
            raise RuntimeError("Скачанный файл подозрительно мал — загрузка прервана")

        paths.TGWS_DIR.mkdir(parents=True, exist_ok=True)
        target = paths.TGWS_DIR / "TgWsProxy_windows.exe"
        backup: Optional[Path] = None
        if target.exists():
            backup = paths.BACKUPS_DIR / f"tgws-{stamp}" / "TgWsProxy_windows.exe"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(target), str(backup))

        try:
            shutil.move(str(tmp_exe), str(target))
        except Exception as exc:  # noqa: BLE001
            if backup and backup.exists():
                shutil.copy2(str(backup), str(target))
            raise RuntimeError(f"Не удалось заменить exe (возможно, процесс ещё запущен): {exc}") from exc

        version = _strip_v(tag)
        manifest = load_manifest()
        _write_version_marker(paths.TGWS_DIR, version)
        manifest["tgws"] = {
            "version": version,
            "release": version,
            "installed_at": stamp,
            "backup": str(backup) if backup else "",
        }
        save_manifest(manifest)
        self._cleanup_backups("tgws-", keep=2)
        return version

    # ---- обслуживание ----

    def _cleanup_backups(self, prefix: str, keep: int) -> None:
        try:
            dirs = sorted(
                [p for p in paths.BACKUPS_DIR.iterdir() if p.is_dir() and p.name.startswith(prefix)],
                key=lambda p: p.name,
                reverse=True,
            )
            for old in dirs[keep:]:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
