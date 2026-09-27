"""Проверка сайтов по HTTP и ping — как тесты в service.bat.

В пакете zapret-discord-youtube тесты (``utils/test zapret.ps1``, пункт 12
«Run Tests» в service.bat) устроены так: для каждой цели из
``utils/targets.txt`` выполняется ``curl.exe -I -s -m 4 --connect-timeout 2
-o NUL -w %{http_code}`` трижды — обычным HTTP/1.1, затем принудительно
TLS 1.2 и TLS 1.3. Для целей вида ``PING:адрес`` делается только ping
(``System.Net.NetworkInformation.Ping.Send(host, 1000)``). Ответ сервера,
ошибка TLS или отсутствие ответа и есть результат теста.

Здесь то же самое, но на стандартной библиотеке: HEAD-запрос через
``http.client`` с нужной версией TLS и ping системной утилитой. Никаких
«просто TCP-соединений»: проверяем именно то, доходит ли запрос до сайта
и что сервер отвечает.
"""
from __future__ import annotations

import http.client
import os
import re
import socket
import ssl
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Tuple

# ---- исход проверки ----
OK = "ok"            # сайт ответил, код ответа получен
SSL = "ssl"          # TLS или сертификат: рукопожатие не сложилось
UNSUP = "unsup"      # версия TLS не поддержана (как UNSUP в test zapret.ps1)
FAIL = "fail"        # нет ответа

PROTO_HTTP11 = "HTTP/1.1"
PROTO_TLS12 = "TLS 1.2"
PROTO_TLS13 = "TLS 1.3"

# в каком порядке и с какими ограничениями TLS проверяем сайт
HTTP_VARIANTS: Tuple[Tuple[str, Optional[str]], ...] = (
    (PROTO_HTTP11, None),
    (PROTO_TLS12, "1.2"),
    (PROTO_TLS13, "1.3"),
)

PING_LABEL = "ping"
PING_TIMEOUT_MS = 1000        # как Ping.Send(host, 1000) в test zapret.ps1
DEFAULT_HTTP_TIMEOUT = 3.0    # как -m 4 в curl из test zapret.ps1
# жёсткий предел одной проверки: ответ дольше уже не считается ответом.
# Браузер пользователя к этому моменту давно показал бы ошибку, поэтому
# такая проверка идёт в отказ как «нет ответа».
MAX_CHECK_MS = 10_000


# ------------------------------------------------------------ исходы

@dataclass
class HttpResult:
    """Исход одного HEAD-запроса к сайту."""

    proto: str
    status: str
    code: int = 0
    ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == OK

    @property
    def text(self) -> str:
        """Короткая подпись для журнала: «200 · 145 мс»."""
        if self.status == OK:
            return f"{self.code} · {self.ms:.0f} мс"
        if self.status == SSL:
            return "ошибка SSL"
        if self.status == UNSUP:
            return "TLS не поддержан"
        return "нет ответа"


# ------------------------------------------------------------ TLS

# текст ошибок OpenSSL, из которых делаем вывод «версия TLS не поддержана»
_UNSUP_MARKERS = (
    "unsupported protocol",
    "protocol version",
    "no protocols available",
    "wrong version number",
    "unknown protocol",
    "sslv3 alert",
    "tlsv1 alert protocol version",
)


def _ssl_status(reason: str) -> str:
    """Ошибку рукопожатия относим либо к версии TLS, либо к сертификату."""
    low = reason.lower()
    if any(marker in low for marker in _UNSUP_MARKERS):
        return UNSUP
    return SSL


def _ssl_context(tls: Optional[str]) -> ssl.SSLContext:
    """Контекст TLS: как у curl по умолчанию, плюс зажатая версия протокола."""
    try:
        ctx = ssl.create_default_context()
    except Exception:  # noqa: BLE001 - нет системных сертификатов
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if tls == "1.2":
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    elif tls == "1.3":
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    return ctx


# ------------------------------------------------------------ HTTP

def http_probe(
    host: str,
    port: int = 443,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    tls: Optional[str] = None,
    secure: bool = True,
) -> HttpResult:
    """HEAD-запрос к сайту: тот же смысл, что у ``curl -I``.

    ``tls`` зажимает версию TLS (``"1.2"`` / ``"1.3"``) — так в тестах
    проверяют, какие протоколы сервер вообще согласен обсуждать.
    ``secure=False`` — обычный HTTP без TLS (адреса ``http://``).
    """
    proto = PROTO_HTTP11
    for name, version in HTTP_VARIANTS:
        if version == tls:
            proto = name
            break
    start = time.perf_counter()
    conn = None
    try:
        if secure:
            conn = http.client.HTTPSConnection(
                host, port, timeout=timeout, context=_ssl_context(tls)
            )
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("HEAD", "/")
        response = conn.getresponse()
        code = int(response.status)
        response.read()
        elapsed = (time.perf_counter() - start) * 1000.0
        if elapsed > MAX_CHECK_MS:
            # ответил, но неприлично долго — считаем, что не ответил
            return HttpResult(proto, FAIL, 0, elapsed)
        return HttpResult(proto, OK, code, elapsed)
    except ssl.SSLError as exc:
        return HttpResult(proto, _ssl_status(str(exc)), 0, _elapsed(start))
    except (socket.timeout, TimeoutError):
        return HttpResult(proto, FAIL, 0, _elapsed(start))
    except OSError:
        return HttpResult(proto, FAIL, 0, _elapsed(start))
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - закрытие не должно шуметь
                pass


def _elapsed(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


# ------------------------------------------------------------ ping

# «time=10ms», «time<1ms», «время=15 мс», «time=13.4 ms»
_TIME_RE = re.compile(r"[=<]\s*<?\s*(\d+(?:[.,]\d+)?)\s*(?:ms|мс)", re.IGNORECASE)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ping_command(host: str, timeout_ms: int) -> list:
    """ping: один пакет, ждём не дольше timeout_ms."""
    if os.name == "nt":
        return ["ping", "-n", "1", "-w", str(timeout_ms), host]
    # на прочих системах -W задаёт таймаут в секундах
    return ["ping", "-c", "1", "-W", str(max(1, round(timeout_ms / 1000))), host]


def ping_probe(host: str, timeout_ms: int = PING_TIMEOUT_MS) -> Optional[float]:
    """Время отклика в миллисекундах или None, если хост не ответил.

    Ответ дольше ``MAX_CHECK_MS`` не считается ответом — возвращаем None.
    """
    timeout_ms = max(100, int(timeout_ms))
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            _ping_command(host, timeout_ms),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_ms / 1000.0 + 3.0,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    match = _TIME_RE.search((proc.stdout or "") + (proc.stderr or ""))
    if match:
        value = float(match.group(1).replace(",", "."))
    else:
        # ответили, но время не распознали — берём общее время вызова
        value = (time.perf_counter() - start) * 1000.0
    return value if value <= MAX_CHECK_MS else None
