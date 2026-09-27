"""Клиент GitHub Releases API."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from . import netutil

API_BASE = "https://api.github.com"


class GitHubError(Exception):
    pass


@dataclass
class Asset:
    name: str
    size: int
    url: str


@dataclass
class Release:
    repo: str
    tag: str
    name: str
    published_at: str
    body: str
    assets: List[Asset] = field(default_factory=list)
    html_url: str = ""

    def find_asset(self, predicate) -> Optional[Asset]:
        for asset in self.assets:
            if predicate(asset.name.lower()):
                return asset
        return None


def _normalize_tag(tag: str) -> str:
    return (tag or "").strip().lstrip("vV")


def version_tuple(version: str):
    parts = []
    for chunk in _normalize_tag(version).replace("-", ".").split("."):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            num = "".join(c for c in chunk if c.isdigit())
            parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    if not current:
        return True
    a, b = version_tuple(candidate), version_tuple(current)
    length = max(len(a), len(b))
    a = a + (0,) * (length - len(a))
    b = b + (0,) * (length - len(b))
    return a > b


class GitHubClient:
    def __init__(self, proxy: str = "", timeout: int = 25):
        self.proxy = proxy
        self.timeout = timeout

    def latest_release(self, repo: str) -> Release:
        url = f"{API_BASE}/repos/{repo}/releases/latest"
        try:
            raw = netutil.http_get(url, proxy=self.proxy, timeout=self.timeout)
        except netutil.NetworkError as exc:
            raise GitHubError(str(exc)) from exc
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            raise GitHubError("Некорректный ответ GitHub") from exc
        if isinstance(data, dict) and data.get("message") and not data.get("tag_name"):
            raise GitHubError(f"GitHub: {data['message']}")
        if not isinstance(data, dict) or not data.get("tag_name"):
            raise GitHubError("GitHub не вернул информацию о релизе")

        assets = [
            Asset(name=a.get("name", ""), size=int(a.get("size") or 0), url=a.get("browser_download_url", ""))
            for a in data.get("assets", [])
            if a.get("browser_download_url")
        ]
        return Release(
            repo=repo,
            tag=str(data.get("tag_name", "")),
            name=str(data.get("name") or data.get("tag_name") or ""),
            published_at=str(data.get("published_at") or ""),
            body=str(data.get("body") or ""),
            assets=assets,
            html_url=str(data.get("html_url") or ""),
        )

    def download(self, url: str, dest, progress_cb=None) -> None:
        netutil.download_to_file(
            url, dest, proxy=self.proxy, progress_cb=progress_cb, timeout=120
        )
