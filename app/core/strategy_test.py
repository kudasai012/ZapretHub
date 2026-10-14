"""Автопроверка стратегий zapret: перебор general*.bat и замер доступа.

Идея: по очереди запускать каждую стратегию нашим же дочерним процессом
winws.exe и проверять, открываются ли сайты. Побеждает стратегия с
наибольшим числом доступных сайтов и наименьшей задержкой.

Сама проверка сделана как в пакете zapret-discord-youtube (``utils/test
zapret.ps1``, пункт 12 «Run Tests» в service.bat): для каждой цели
выполняется HEAD-запрос трижды — обычным HTTP/1.1, затем принудительно
TLS 1.2 и TLS 1.3, — плюс ping. Цели вида ``PING:адрес`` проверяются
только ping. Список целей по умолчанию берётся из ``utils/targets.txt``
самого пакета, поэтому «бонусом» идут все его сайты, а не только Discord
с YouTube.

Сам запуск/остановка процесса делает GUI-поток (QProcess должен жить в том
же потоке, что и виджеты), а этот модуль только измеряет — поэтому он
безопасно работает в отдельном QThread.
"""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QThread, Signal

from .probe import (
    FAIL,
    HTTP_VARIANTS,
    MAX_CHECK_MS,
    OK,
    PING_LABEL,
    PING_TIMEOUT_MS,
    PROTO_HTTP11,
    PROTO_TLS12,
    PROTO_TLS13,
    TCP_FALLBACK_PORTS,
    HttpResult,
    http_probe,
    ping_probe,
    tcp_probe,
)

# на каждый протокол — по одному запросу, ровно как в test zapret.ps1
ATTEMPTS = 1
PROBE_TIMEOUT = 3.0            # как -m 4 в curl из test zapret.ps1
SETTLE_SECONDS = 2.5

# Стратегия не дожила до замера: процесс умер сразу после старта. Это не
# «нет ответа» — цель просто не с чем сравнивать, и в отчёте такая строка
# должна быть видна отдельно, а не выглядеть как плохая стратегия. Значение —
# стабильный токен, а не текст: переводится уже в интерфейсе.
DEAD_PROCESS_ERROR = "winws_not_started"
# сколько сайтов проверяем одновременно внутри одной стратегии: цели
# независимы, а ждать их по очереди — минуты на каждый general*.bat
MAX_WORKERS = 8
# предел на одну цель: молчащая цель не должна подвешивать прогон. Всё,
# что не успело ответить за это время, считается «нет ответа»
TARGET_BUDGET = 10.0
# ответ медленнее этого — «медленный»: в журнале он жёлтый, а не красный
SLOW_MS = 400

# запасной список, если utils/targets.txt пакета ещё нет на диске
DEFAULT_TARGET_LINES: Tuple[str, ...] = (
    "Discord = https://discord.com",
    "DiscordGateway = https://gateway.discord.gg",
    "YouTube = https://www.youtube.com",
    "YouTubeShort = https://youtu.be",
    "GoogleDNS = PING:8.8.8.8",
)


# ------------------------------------------------------------ цели

@dataclass(frozen=True)
class Target:
    """Одна цель проверки: сайт для HTTP/TLS или адрес для ping."""

    host: str
    port: int = 443
    kind: str = "http"          # http | ping
    name: str = ""              # имя из targets.txt, если задано
    scheme: str = "https"       # https | http

    @property
    def key(self) -> str:
        """Стабильный ключ для словарей результатов."""
        if self.name:
            return self.name
        default_port = 443 if self.scheme == "https" else 80
        if self.port and self.port != default_port:
            return f"{self.host}:{self.port}"
        return self.host

    @property
    def label(self) -> str:
        """Что показываем в журнале — всегда проверяемый адрес."""
        return self.host


def _split_host_port(text: str, default_port: int) -> Tuple[str, int]:
    """Разбирает «хост», «хост:порт» и «[IPv6]:порт»."""
    host, port = text.strip(), default_port
    if not host:
        return "", port
    if host.startswith("["):
        end = host.find("]")
        if end > 0:
            host = host[1:end]
            tail = host[end + 1 :]
            if tail.startswith(":") and tail[1:].isdigit():
                port = int(tail[1:])
            return host, port
        return host, port
    if ":" in host:
        head, _, tail = host.rpartition(":")
        if head and ":" not in head and tail.isdigit() and 0 < int(tail) <= 65535:
            return head, int(tail)
    return host, port


def parse_targets(lines: Sequence[str]) -> List[Target]:
    """Разбирает список целей — сайты для проверки и адреса для ping.

    Пустые строки и комментарии (``#``, ``;``, ``###``) пропускаются.
    Поддерживаются все форматы из ``utils/targets.txt`` пакета::

        DiscordMain = "https://discord.com"   -> HTTP/TLS + ping
        CloudflareDNS1111 = "PING:1.1.1.1"     -> только ping

    А также простые записи: ``discord.com``, ``discord.com:8443``,
    ``https://host``, ``PING:1.1.1.1``.
    """
    # Строку разбиваем на строки. ``str`` — это тоже ``Sequence[str]``,
    # только из символов: без разбивки ``for raw in lines`` перебирает
    # текст по буквам, каждая буква становится «целью» с хостом из одного
    # символа, и весь замер честно получает «нет ответа» по всем сайтам.
    if isinstance(lines, str):
        lines = lines.splitlines()

    targets: List[Target] = []
    seen: set = set()
    for raw in lines:
        line = str(raw).strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        name, value = "", line
        if "=" in line:
            head, _, tail = line.partition("=")
            head = head.strip()
            # имя из targets.txt — одно слово, поэтому «хост:порт» с
            # символом «=» в запросе за имя не примем
            if head and " " not in head and ":" not in head:
                name, value = head, tail.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        if not value:
            continue

        low = value.lower()
        if low.startswith("ping:"):
            host, _ = _split_host_port(value[5:], 0)
            target = Target(host=host, port=0, kind="ping", name=name)
        else:
            scheme = "https"
            if low.startswith("http://"):
                scheme, value = "http", value[7:]
            elif low.startswith("https://"):
                value = value[8:]
            # отрезаем путь и параметры: проверяем сам хост
            for sep in ("/", "?"):
                if sep in value:
                    value = value.split(sep, 1)[0]
            host, port = _split_host_port(value, 443 if scheme == "https" else 80)
            target = Target(
                host=host, port=port, kind="http", name=name, scheme=scheme
            )

        if not target.host or target.key in seen:
            continue
        seen.add(target.key)
        targets.append(target)
    return targets


def load_targets_file(path: Path) -> List[str]:
    """Читает utils/targets.txt пакета и возвращает его строки целей.

    Комментарии и заголовки групп (``### Discord``) выбрасываются — в
    нашем редакторе списка они только мешают.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    lines: List[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if "=" not in stripped:
            continue
        lines.append(stripped)
    return lines


def default_target_lines(targets_file: Optional[Path] = None) -> List[str]:
    """Список целей по умолчанию: из пакета, иначе встроенный запасной."""
    if targets_file is not None:
        lines = load_targets_file(Path(targets_file))
        if lines:
            return lines
    return list(DEFAULT_TARGET_LINES)


# ------------------------------------------------------------ результаты

@dataclass
class TargetOutcome:
    """Исход проверки одной цели: ответы по протоколам и ping."""

    target: Target
    http: Dict[str, HttpResult] = field(default_factory=dict)
    ping: Optional[float] = None          # мс ответа ICMP, None — молчит
    # цель молчала дольше TARGET_BUDGET: оставшиеся проверки не делали
    timed_out: bool = False
    # ping молчал, но хост принял TCP-соединение: значит ICMP режут,
    # а сам хост жив. Для целей PING:адрес — это и есть «доступен»
    ping_blocked: bool = False
    # время установки TCP-соединения для ping_blocked: в замер задержки
    # сайтов не идёт — это не время ответа, а только признак живости
    tcp_ms: Optional[float] = None

    @property
    def ok(self) -> bool:
        """Цель доступна, если ответил хотя бы один протокол или ping."""
        return (
            any(result.ok for result in self.http.values())
            or self.ping is not None
            or self.ping_blocked
        )

    @property
    def latency(self) -> Optional[float]:
        """Самая быстрая успешная проверка — для общего замера задержки."""
        values = [
            result.ms for result in self.http.values() if result.ok and result.ms > 0
        ]
        if self.ping is not None and self.ping > 0:
            values.append(self.ping)
        return min(values) if values else None

    def protocols(self) -> List[Tuple[str, Optional[HttpResult]]]:
        """Проверенные протоколы в фиксированном порядке."""
        return [
            (name, self.http.get(name)) for name in (PROTO_HTTP11, PROTO_TLS12, PROTO_TLS13)
        ]

    def summary(self) -> str:
        """Короткая строка вида «HTTP/1.1: 200 · TLS 1.3: нет ответа · ping: 12 мс».

        Для целей ``PING:адрес`` тут только ping. Раньше при молчащем ICMP
        возвращалась пустая строка — в журнаре появлялась строкa «имя — »
        вообще без объяснения, и это выглядело как поломка диагностики.
        """
        parts: List[str] = []
        for name, result in self.protocols():
            if result is not None:
                parts.append(f"{name}: {result.text}")
        if self.ping is not None:
            parts.append(f"{PING_LABEL}: {self.ping:.0f} мс")
        elif self.ping_blocked:
            took = f" за {self.tcp_ms:.0f} мс" if self.tcp_ms is not None else ""
            parts.append(
                f"{PING_LABEL}: ICMP не ответил, порт открыт{took}"
            )
        elif self.target.kind == "ping":
            parts.append(f"{PING_LABEL}: нет ответа")
        return " · ".join(parts)


@dataclass
class StrategyResult:
    """Результат проверки одной стратегии."""

    name: str
    ok: int = 0
    fail: int = 0
    latencies: List[float] = field(default_factory=list)
    error: str = ""
    # сколько успешных проверок пришлось на каждую цель: ключ -> число
    sites: Dict[str, int] = field(default_factory=dict)
    # подробности по каждой цели: протоколы, коды ответа, ping
    details: Dict[str, TargetOutcome] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.ok + self.fail

    @property
    def best(self) -> Optional[float]:
        return min(self.latencies) if self.latencies else None

    @property
    def average(self) -> Optional[float]:
        return statistics.fmean(self.latencies) if self.latencies else None

    @property
    def covered(self) -> int:
        """Сколько разных целей открылись хотя бы одним способом."""
        return sum(1 for hits in self.sites.values() if hits > 0)

    @property
    def site_count(self) -> int:
        return len(self.sites)

    @property
    def score(self) -> Tuple[int, int, float]:
        """Ключ сортировки: больше открытых сайтов — лучше.

        Сначала важнее всего охват: стратегия, которая открыла все сайты из
        списка, всегда выше той, что открыла лишь часть. При равном охвате
        решает число успешных проверок, затем — задержка.
        """
        return (
            self.covered,
            self.ok,
            -(self.average if self.average is not None else 1e9),
        )

    def protocol_summary(self) -> List[Tuple[str, int, int]]:
        """Сколько целей ответило по каждому протоколу: имя -> успех/всего."""
        totals: Dict[str, List[int]] = {}
        for outcome in self.details.values():
            for name, result in outcome.protocols():
                if result is None:
                    continue
                box = totals.setdefault(name, [0, 0])
                box[1] += 1
                if result.ok:
                    box[0] += 1
            box = totals.setdefault(PING_LABEL, [0, 0])
            box[1] += 1
            if outcome.ping is not None:
                box[0] += 1
        # фиксированный порядок: HTTP/1.1, TLS 1.2, TLS 1.3, ping
        return [(name, totals[name][0], totals[name][1]) for name in totals]

    @property
    def checks(self) -> List[str]:
        """Состояние каждой проверки по порядку: ok / slow / fail.

        Из этого списка строится график в строке стратегии — по отрезку на
        каждый ответ: зелёный — быстрый ответ, жёлтый — медленный ответ,
        красный — нет ответа.
        """
        states: List[str] = []
        for outcome in self.details.values():
            for _, result in outcome.protocols():
                if result is None:
                    continue
                if not result.ok:
                    states.append("fail")
                elif result.ms >= SLOW_MS:
                    states.append("slow")
                else:
                    states.append("ok")
            # ICMP мог не ответить, но сайт ответил по HTTPS — цель всё
            # равно доступна, поэтому отрезок графика не красный
            site_ok = any(
                result is not None and result.ok for _, result in outcome.protocols()
            )
            states.append(
                "ok"
                if (outcome.ping is not None or outcome.ping_blocked or site_ok)
                else "fail"
            )
        return states

    @property
    def percent(self) -> int:
        """Доля ответивших проверок в процентах — подпись у графика.

        Медленный ответ — это всё равно ответ, поэтому в процент идут и
        «ok», и «slow»; красный «нет ответа» считается отказом.
        """
        states = self.checks
        if not states:
            return 0
        good = sum(1 for state in states if state != "fail")
        return round(100.0 * good / len(states))

    def summary(self) -> str:
        """Короткая подпись к результату для журнала.

        Раньше при ``ok == 0`` здесь возвращался литерал «нет доступа» —
        ровно та фраза, которую пользователь видел в каждой строке
        диагностики и не понимал, что дело в правах, а не в стратегиях.
        Причина называется в UI (``StrategyRow._failure_reason``), а тут
        остаётся только честное «сайты не ответили».
        """
        if self.error:
            return self.error
        if not self.total:
            return "—"
        if self.ok == 0:
            return "сайты не ответили"
        average = self.average or 0.0
        if self.site_count:
            return (
                f"{average:.0f} мс · сайты {self.covered}/{self.site_count}"
            )
        return f"{average:.0f} мс"


class StrategyTester(QThread):
    """Поток замера: ждёт, пока стратегия разгонится, и тыкает цели."""

    measured = Signal(object)
    log = Signal(str)

    def __init__(
        self,
        name: str,
        targets: Sequence[Target] = (),
        attempts: int = ATTEMPTS,
        settle: float = SETTLE_SECONDS,
        timeout: float = PROBE_TIMEOUT,
        ping_timeout: int = PING_TIMEOUT_MS,
        alive: Optional[Callable[[], bool]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self._targets = tuple(targets)
        self._attempts = max(1, int(attempts))
        self._settle = max(0.0, float(settle))
        self._timeout = max(0.2, float(timeout))
        self._ping_timeout = max(100, int(ping_timeout))
        # проверка, что winws.exe действительно дожил до замера. Без неё
        # стратегия, которая упала сразу после старта (гонка WinDivert при
        # быстрой смене стратегий), выглядела как «нет ответа» у всех целей
        self._alive = alive
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    # ------------------------------------------------------------ замер

    def _probe_target(self, target: Target) -> TargetOutcome:
        """Полный набор проверок одной цели: три протокола и ping.

        На цель отводится ``TARGET_BUDGET`` секунд: если она молчит дольше,
        остальные проверки не выполняются и считаются «нет ответа».
        """
        outcome = TargetOutcome(target=target)
        if target.kind == "ping":
            for _ in range(self._attempts):
                if self._cancelled:
                    break
                if outcome.ping is None:
                    outcome.ping = ping_probe(
                        target.host, min(self._ping_timeout, MAX_CHECK_MS)
                    )
            if outcome.ping is None:
                # ICMP молчит. Это ещё не значит, что хост недоступен:
                # провайдеры и брандмауэры режут ping, а сайт работает.
                # Пробуем TCP — если порт открылся, хост доступен.
                for port in TCP_FALLBACK_PORTS:
                    if self._cancelled:
                        break
                    took = tcp_probe(
                        target.host, port, min(self._timeout, TARGET_BUDGET)
                    )
                    if took is not None:
                        outcome.ping_blocked = True
                        outcome.tcp_ms = took
                        break
            return outcome
        secure = target.scheme == "https"
        variants = HTTP_VARIANTS if secure else ((PROTO_HTTP11, None),)
        deadline = time.monotonic() + TARGET_BUDGET
        for _ in range(self._attempts):
            if self._cancelled:
                break
            for name, version in variants:
                current = outcome.http.get(name)
                if current is not None and current.ok:
                    continue
                left = deadline - time.monotonic()
                if left <= 0.05:
                    # цель молчит дольше 10 секунд — это «нет ответа»
                    outcome.timed_out = True
                    outcome.http[name] = HttpResult(name, FAIL, 0, 0.0)
                    continue
                outcome.http[name] = http_probe(
                    target.host,
                    target.port,
                    min(self._timeout, left),
                    tls=version if secure else None,
                    secure=secure,
                )
            left = deadline - time.monotonic()
            if outcome.ping is None and left > 0.05:
                outcome.ping = ping_probe(
                    target.host, min(self._ping_timeout, int(left * 1000))
                )
        return outcome

    def _measure(self, targets: Sequence[Target]) -> List[TargetOutcome]:
        """Проверяет цели одновременно — как параллельные runspace'ы в .ps1."""
        if not targets:
            return []
        workers = min(MAX_WORKERS, len(targets))
        done: List[TargetOutcome] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._probe_target, t): t for t in targets}
            for future in as_completed(futures):
                if self._cancelled:
                    break
                target = futures[future]
                try:
                    done.append(future.result())
                except Exception as exc:  # noqa: BLE001 - один сбой не рушит прогон
                    self.log.emit(
                        f"[test] {self.name}: {target.label} — сбой проверки: {exc}"
                    )
                    done.append(TargetOutcome(target=target))
        # сохраняем порядок списка целей, а не порядок завершения
        order = {t.key: i for i, t in enumerate(targets)}
        done.sort(key=lambda o: order.get(o.target.key, 0))
        return done

    def run(self) -> None:  # noqa: D102 - поток Qt
        result = StrategyResult(name=self.name)
        deadline = time.monotonic() + self._settle
        while time.monotonic() < deadline:
            if self._cancelled:
                break
            time.sleep(0.05)

        # Стратегия могла не запуститься вовсе: winws.exe умирает при запуске,
        # если предыдущая копия ещё не отпустила фильтр WinDivert (гонка при
        # быстрой смене стратегий) или не смог прочитать свои файлы. Раньше
        # замер шёл всё равно, каждая цель честно получала «нет ответа», и в
        # отчёте это выглядело как плохая стратегия, хотя её просто нет.
        if not self._cancelled and self._alive is not None:
            if not self._alive():
                result.error = DEAD_PROCESS_ERROR
                self.log.emit(
                    f"[{self.name}] процесс не дожил до замера — "
                    "замер пропущен"
                )
                self.measured.emit(result)
                return

        for outcome in self._measure(self._targets):
            if self._cancelled:
                break
            target = outcome.target
            key = target.key
            result.sites.setdefault(key, 0)
            result.details[key] = outcome
            for name, http in outcome.protocols():
                if http is None:
                    continue
                if http.status == OK:
                    result.ok += 1
                    result.sites[key] += 1
                else:
                    result.fail += 1
                # цель молчала дольше 10 секунд — в журнале это видно,
                # иначе непонятно, почему проверка не делалась
                note = ""
                if outcome.timed_out and http.status != OK:
                    note = f" (ждали дольше {TARGET_BUDGET:.0f} с)"
                self.log.emit(
                    f"[test] {self.name}: {target.label} — {name} "
                    f"{http.text}{note}"
                )
            if outcome.ping is not None or outcome.ping_blocked:
                result.ok += 1
                result.sites[key] += 1
                if outcome.ping_blocked:
                    # ICMP не ответил, но порт открылся: хост доступен,
                    # просто пинг режут. Отдельной строкой, чтобы в журнале
                    # было видно — это не «нет ответа», а «жив, но без ping»
                    took = outcome.tcp_ms
                    when = f" за {took:.0f} мс" if took is not None else ""
                    self.log.emit(
                        f"[test] {self.name}: {target.label} — {PING_LABEL} "
                        f"не ответил, порт открыт{when} (ICMP заблокирован, "
                        f"хост доступен)"
                    )
                else:
                    self.log.emit(
                        f"[test] {self.name}: {target.label} — "
                        f"{PING_LABEL} {outcome.ping:.0f} мс"
                    )
            else:
                # ping не ответил. Если сайт и так ответил по HTTPS, это
                # не провал цели — просто ICMP режут. Раньше здесь всегда
                # писалось «нет ответа» и шло в счёт отказов, из-за чего
                # работающая стратегия выглядела сломанной.
                site_answered = any(
                    http is not None and http.status == OK
                    for _, http in outcome.protocols()
                )
                if site_answered:
                    self.log.emit(
                        f"[test] {self.name}: {target.label} — {PING_LABEL} "
                        f"ICMP не ответил (сайт ответил по HTTPS)"
                    )
                else:
                    result.fail += 1
                    self.log.emit(
                        f"[test] {self.name}: {target.label} — "
                        f"{PING_LABEL} нет ответа"
                    )
            # в общий замер задержки идёт самая быстрая успешная проверка
            # цели, иначе ping и HTTP одного сайта считались бы дважды
            latency = outcome.latency
            if latency is not None:
                result.latencies.append(latency)
        self.measured.emit(result)


def rank(results: Sequence[StrategyResult]) -> List[StrategyResult]:
    """Сортирует результаты: рабочие стратегии first, лучшая — в начале."""
    usable = [r for r in results if r.ok > 0]
    broken = [r for r in results if r.ok == 0]
    usable.sort(key=lambda r: r.score, reverse=True)
    return usable + broken
