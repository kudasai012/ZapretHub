"""Конфигурация приложения (data/config.json)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

from . import paths

CONFIG_VERSION = 2


@dataclass
class GeneralSettings:
    language: str = "ru"            # ru | en
    theme: str = "dark"             # dark | light
    minimize_to_tray: bool = True   # крестик -> в трей
    start_minimized: bool = False   # стартовать свёрнутым (без --tray)
    sidebar_collapsed: bool = False # боковое меню свёрнуто в иконки
    check_updates_on_start: bool = True
    # гасить ли обходы при выходе из программы. По умолчанию нет: zapret и
    # TG WS Proxy продолжают работать, пока их не остановят явно — как
    # обычные .bat-файлы. При обновлении через установщик программа
    # останавливает их принудительно, чтобы файлы не были заняты.
    stop_components_on_quit: bool = False


@dataclass
class AutostartSettings:
    enabled: bool = False           # запись в реестре Run
    start_zapret: bool = True
    start_tgws: bool = True
    delay_seconds: int = 0
    # настройки «запускать от имени администратора» нет: права повышаются
    # всегда, иначе zapret (WinDivert) просто не стартует


@dataclass
class UpdateSettings:
    auto_check: bool = True
    interval_hours: int = 12
    proxy: str = ""                 # например http://127.0.0.1:2080 или socks5://127.0.0.1:1080
    last_check: float = 0.0


# чем проверяем стратегии на странице «Диагностика». Формат — как в
# utils/targets.txt пакета zapret: «Имя = https://хост» (проверяем HTTP и
# ping) или «Имя = PING:адрес» (только ping). Просто «хост» и «хост:порт»
# тоже работают. Список по умолчанию дублирует targets.txt пакета, чтобы
# кнопка «Стандартные сайты» работала и без установленного компонента.
DEFAULT_DIAG_TARGETS: tuple[str, ...] = (
    'DiscordMain = "https://discord.com"',
    'DiscordGateway = "https://gateway.discord.gg"',
    'DiscordCDN = "https://cdn.discordapp.com"',
    'DiscordUpdates = "https://updates.discord.com"',
    'YouTubeWeb = "https://www.youtube.com"',
    'YouTubeShort = "https://youtu.be"',
    'YouTubeImage = "https://i.ytimg.com"',
    'YouTubeVideoRedirect = "https://redirector.googlevideo.com"',
    'GoogleMain = "https://www.google.com"',
    'GoogleGstatic = "https://www.gstatic.com"',
    'CloudflareWeb = "https://www.cloudflare.com"',
    'CloudflareCDN = "https://cdnjs.cloudflare.com"',
    'CloudflareDNS1111 = "PING:1.1.1.1"',
    'CloudflareDNS1001 = "PING:1.0.0.1"',
    'GoogleDNS8888 = "PING:8.8.8.8"',
    'GoogleDNS8844 = "PING:8.8.4.4"',
)

# список из ранних версий: если в конфиге лежит он, значит пользователь
# свои сайты не выбирал — показываем список из targets.txt пакета
LEGACY_DIAG_TARGETS: tuple[str, ...] = (
    "discord.com:443",
    "gateway.discord.gg:443",
    "www.youtube.com:443",
)


@dataclass
class ZapretSettings:
    strategy: str = "general.bat"
    game_mode: str = "disabled"     # disabled | tcp | udp | all
    game_tcp_range: str = "1024-65535"
    game_udp_range: str = "1024-65535"
    ipset_mode: str = "loaded"      # loaded | none | any
    diag_targets: list[str] = field(
        default_factory=lambda: list(DEFAULT_DIAG_TARGETS)
    )                                # сайты и адреса для проверки стратегий


@dataclass
class TgwsSettings:
    # конфигурация самого TgWsProxy (портативный config.json)
    host: str = "127.0.0.1"
    port: int = 1443
    secret: str = ""
    dc_ip: list[str] = field(default_factory=lambda: ["2:149.154.167.220", "4:149.154.167.220"])
    buf_kb: int = 256
    pool_size: int = 4
    verbose: bool = False
    cfproxy: bool = True
    force_test_dc: bool = False
    no_secure: bool = False
    check_updates: bool = False     # внутри TgWsProxy (обновления делает Hub)
    log_max_mb: float = 5.0


@dataclass
class AppConfig:
    general: GeneralSettings = field(default_factory=GeneralSettings)
    autostart: AutostartSettings = field(default_factory=AutostartSettings)
    updates: UpdateSettings = field(default_factory=UpdateSettings)
    zapret: ZapretSettings = field(default_factory=ZapretSettings)
    tgws: TgwsSettings = field(default_factory=TgwsSettings)

    # ---------- (де)сериализация ----------

    @staticmethod
    def _merge_dataclass(dc_cls, data: Dict[str, Any]):
        kwargs = {}
        for f in dc_cls.__dataclass_fields__:  # type: ignore[attr-defined]
            if f in data:
                kwargs[f] = data[f]
        return dc_cls(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "general": asdict(self.general),
            "autostart": asdict(self.autostart),
            "updates": asdict(self.updates),
            "zapret": asdict(self.zapret),
            "tgws": asdict(self.tgws),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        cfg = cls()
        for name, dc_cls in (
            ("general", GeneralSettings),
            ("autostart", AutostartSettings),
            ("updates", UpdateSettings),
            ("zapret", ZapretSettings),
            ("tgws", TgwsSettings),
        ):
            section = data.get(name)
            if isinstance(section, dict):
                setattr(cfg, name, cls._merge_dataclass(dc_cls, section))
        cfg._sanitize()
        return cfg

    def _sanitize(self) -> None:
        g = self.general
        if g.language not in ("ru", "en"):
            g.language = "ru"
        if g.theme not in ("dark", "light"):
            g.theme = "dark"

        a = self.autostart
        a.delay_seconds = max(0, min(600, int(a.delay_seconds)))

        u = self.updates
        u.interval_hours = max(1, min(168, int(u.interval_hours)))
        u.proxy = str(u.proxy or "").strip()

        z = self.zapret
        if z.game_mode not in ("disabled", "tcp", "udp", "all"):
            z.game_mode = "disabled"
        if z.ipset_mode not in ("loaded", "none", "any"):
            z.ipset_mode = "loaded"
        z.diag_targets = [
            str(item).strip()
            for item in (z.diag_targets or [])
            if str(item).strip()
        ][:48]

        t = self.tgws
        t.port = max(1, min(65535, int(t.port or 1443)))
        t.buf_kb = max(4, min(4096, int(t.buf_kb or 256)))
        t.pool_size = max(0, min(64, int(t.pool_size or 4)))
        if not t.secret:
            t.secret = os.urandom(16).hex()

    # ---------- файл ----------

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or paths.CONFIG_FILE
        data: Dict[str, Any] = {}
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
        except Exception:
            data = {}
        return cls.from_dict(data)

    def save(self, path: Path | None = None) -> bool:
        path = path or paths.CONFIG_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=str(path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
            return True
        except Exception:
            return False


def load_manifest() -> Dict[str, Any]:
    """Манифест установленных версий компонентов (data/components.json)."""
    try:
        if paths.MANIFEST_FILE.exists():
            with open(paths.MANIFEST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_manifest(data: Dict[str, Any]) -> bool:
    try:
        paths.MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(paths.MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
