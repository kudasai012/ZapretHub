"""Сборщик IP-адресов заблокированных провайдеров через RIPE Stat.

Берём список автономных систем (ASN), запрашиваем у RIPE Stat все
анонсируемые префиксы, чистим их (только глобальные, без 0.0.0.0/0),
агрегируем и пишем в lists/ipset-all.txt — тот самый файл, который
zapret использует как `--ipset`.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from . import netutil

LOG = logging.getLogger("zapret_hub")

RIPE_URL = "https://stat.ripe.net/data/announced-prefixes/data.json"
TIMEOUT = 20  # секунд на запрос
PAUSE = 1.0  # пауза между запросами, чтобы не долбить API

# ASN, у которых чаще всего обнаруживаются заблокированные адреса
ASN_LIST: Dict[str, str] = {
    "Scaleway": "AS12876",
    "Hetzner": "AS24940",
    "Hetzner 2": "AS213230",
    "Hetzner 3": "AS212317",
    "Hetzner 4": "AS215859",
    "Akamai": "AS20940",
    "Akamai 2": "AS16625",
    "Akamai 3": "AS12222",
    "Akamai 4": "AS33905",
    "Akamai 5": "AS21342",
    "Akamai 6": "AS32787",
    "Akamai 7": "AS35994",
    "Akamai 8": "AS12400",
    "Akamai 9": "AS15802",
    "Akamai 10": "AS18209",
    "Akamai 11": "AS24319",
    "Akamai 12": "AS25019",
    "Akamai 13": "AS26008",
    "Akamai 14": "AS31108",
    "Akamai 15": "AS34164",
    "Akamai 16": "AS49846",
    "Akamai 17": "AS17204",
    "Akamai 18": "AS213120",
    "Akamai 19": "AS393234",
    "Akamai 20": "AS393560",
    "Akamai Cloud (Linode)": "AS63949",
    "DigitalOcean": "AS14061",
    "DigitalOcean 2": "AS46652",
    "DigitalOcean 3": "AS393406",
    "Datacamp, CDN77": "AS60068",
    "Datacamp, CDN77 2": "AS212238",
    "Contabo": "AS51167",
    "Contabo 2": "AS141995",
    "Contabo 3": "AS40021",
    "OVH": "AS16276",
    "OVH 2": "AS35540",
    "Vultr (Constant)": "AS20473",
    "Cloudflare": "AS13335",
    "Cloudflare 2": "AS14789",
    "Cloudflare 3": "AS132892",
    "Cloudflare 4": "AS395747",
    "Cloudflare 5": "AS209242",
    "Clouvider": "AS62240",
    "CreaNova": "AS51765",
    "Oracle Cloud": "AS31898",
    "Oracle 2": "AS1219",
    "Amazon": "AS16509",
    "Amazon 2": "AS14618",
    "Amazon 3": "AS8987",
    "G-Core": "AS199524",
    "G-Core 2": "AS202422",
    "Roblox": "AS22697",
    "Fellowship": "AS46461",
    "Fastly": "AS54113",
    "FranTech": "AS53667",
    "LogicForge": "AS208621",
    "Hostinger": "AS47583",
    "Hostinger 2": "AS204915",
    "Ionos": "AS8560",
    "Ionos 2": "AS15418",
    "DreamHost": "AS29873",
    "GoDaddy": "AS26496",
    "GoDaddy 2": "AS398101",
    "HostGator, BlueHost": "AS46606",
    "Cogent": "AS174",
    "Riot Games, Inc": "AS6507",
    "I3DNET (Discord)": "AS49544",
    "IOMART": "AS20860",
    "IOMART 2": "AS21130",
    "Google Cloud": "AS15169",
    "Microsoft Azure": "AS8075",
    "Melbicom": "AS8849",
    "Melbicom 2": "AS56630",
    "M247 Europe SRL": "AS9009",
    "M247 Europe SRL 2": "AS39675",
    "HostPapa, ColoCrossing": "AS36352",
    "Hurricane Electric": "AS6939",
    "GTT Communications": "AS3257",
    "NTT Global": "AS2914",
    "Telia Carrier": "AS1299",
    "Firstcolo": "AS44066",
    "Hosteur": "AS20773",
    "ITL DC": "AS210403",
    "TELECOM ITALIA SPARKLE S.p.A": "AS6762",
    "Orange (FTRSI)": "AS5511",
    "GlobeNet": "AS52320",
    "Lumen": "AS3356",
    "Tata Communications": "AS6453",
    "Verizon Business": "AS701",
    "Scalaxy": "AS58061",
    "Zenlayer": "AS21859",
    "BunnyCDN": "AS5065",
    "Edgio": "AS15133",
    "Edgio 2": "AS22843",
    "StackPath": "AS33438",
    "StackPath 2": "AS202384",
    "KeyCDN": "AS199653",
    "CacheFly": "AS30081",
    "Imperva_Incapsula": "AS19551",
}


def collapse(networks) -> List:
    """Схлопывает пересекающиеся префиксы в минимальный набор."""
    return list(ipaddress.collapse_addresses(networks))


def sort_key(net):
    return (net.version, int(net.network_address), net.prefixlen)


def fetch_asn_prefixes(asn: str, proxy: str = "") -> List[str]:
    """Все префиксы, которые анонсирует автономная система (по данным RIPE)."""
    url = f"{RIPE_URL}?resource={asn}&min_peers_seeing=1"
    body = netutil.http_get(url, proxy=proxy, timeout=TIMEOUT)
    data = json.loads(body.decode("utf-8", errors="replace"))
    return [
        item.get("prefix", "")
        for item in data.get("data", {}).get("prefixes", [])
        if item.get("prefix")
    ]


def collect(
    asn_items: Optional[List[Tuple[str, str]]] = None,
    proxy: str = "",
    progress: Optional[Callable[[str, int, int], None]] = None,
    log: Optional[Callable[[str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Tuple[List, List]:
    """Обходит все ASN и возвращает (IPv4-сети, IPv6-сети)."""
    items = list(asn_items or ASN_LIST.items())
    total = len(items)
    v4_all, v6_all = set(), set()

    for index, (name, asn) in enumerate(items, start=1):
        if should_stop and should_stop():
            break
        if progress:
            progress(name, index, total)
        try:
            prefixes = fetch_asn_prefixes(asn, proxy=proxy)
            added = 0
            for prefix in prefixes:
                try:
                    net = ipaddress.ip_network(prefix, strict=False)
                except ValueError:
                    continue
                if net.prefixlen == 0 or not net.is_global:
                    continue
                if net.version == 4:
                    v4_all.add(net)
                else:
                    v6_all.add(net)
                added += 1
            if log:
                log(f"{name} ({asn}): +{added}")
        except Exception as exc:  # noqa: BLE001
            if log:
                log(f"{name} ({asn}): ошибка — {exc}")
        time.sleep(PAUSE)

    v4 = sorted(collapse(v4_all), key=sort_key)
    v6 = sorted(collapse(v6_all), key=sort_key)
    return v4, v6


def render(v4: List, v6: List) -> str:
    """Текст файла ipset-all.txt: сначала IPv4, затем IPv6."""
    lines = [str(net) for net in v4] + [str(net) for net in v6]
    return "\n".join(lines) + ("\n" if lines else "")


def write_ipset(path: Path, v4: List, v6: List) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(v4, v6)
    path.write_text(text, encoding="utf-8")
    return len(v4) + len(v6)


class AsnCollector(QObject):
    """Фоновый сборщик IP: ходит по ASN и пишет ipset-all.txt."""

    progress = Signal(str, int, int)      # имя, готово, всего
    finished = Signal(int, int)           # IPv4, IPv6
    failed = Signal(str)
    log_line = Signal(str)
    status = Signal(str)

    def __init__(self, config, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.config = config
        self._stop = False
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        self._stop = True

    def start(self, target: Path) -> None:
        if self.running:
            return
        self._stop = False
        self._thread = threading.Thread(target=self._worker, args=(target,), daemon=True)
        self._thread.start()

    def _worker(self, target: Path) -> None:
        proxy = getattr(self.config.updates, "proxy", "") or ""
        try:
            v4, v6 = collect(
                proxy=proxy,
                progress=lambda name, done, total: self.progress.emit(name, done, total),
                log=lambda line: self.log_line.emit(line),
                should_stop=lambda: self._stop,
            )
            if self._stop:
                self.status.emit("Сбор остановлен")
                return
            count = write_ipset(target, v4, v6)
            self.finished.emit(len(v4), len(v6))
            self.status.emit(f"ipset-all.txt: {count} сетей")
        except Exception as exc:  # noqa: BLE001
            LOG.warning("ASN collect failed: %s", exc)
            self.failed.emit(str(exc))
