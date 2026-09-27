"""Сетевые утилиты: запросы к GitHub и скачивание файлов (с опциональным прокси)."""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

USER_AGENT = "ZapretHub/1.0 (+https://github.com/Flowseal)"


class NetworkError(Exception):
    pass


def _ssl_context(relaxed: bool = False) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if relaxed:
        # На части Windows со старыми корневыми сертификатами запросы падают —
        # вторая попытка идёт с ослабленной проверкой.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _build_opener(proxy: str = "", context: Optional[ssl.SSLContext] = None):
    if proxy:
        proxy_map = {"http": proxy, "https": proxy}
        if proxy.startswith("socks"):
            proxy_map = {"http": proxy, "https": proxy, "socks5": proxy}
        handlers = [urllib.request.ProxyHandler(proxy_map)]
    else:
        handlers = [urllib.request.ProxyHandler({})]  # системные переменные игнорируются
    handlers.append(urllib.request.HTTPSHandler(context=context or _ssl_context()))
    return urllib.request.build_opener(*handlers)


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})


def http_get(url: str, proxy: str = "", timeout: int = 25) -> bytes:
    """GET, возвращает тело ответа. Бросает NetworkError с понятным текстом."""
    req = _request(url)
    last_exc: Optional[Exception] = None
    for relaxed in (False, True):
        try:
            opener = _build_opener(proxy, _ssl_context(relaxed))
            with opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise NetworkError(f"HTTP {exc.code} для {url}") from exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    raise NetworkError(f"Не удалось выполнить запрос {url}: {last_exc}")


def download_to_file(
    url: str,
    dest: Path,
    proxy: str = "",
    timeout: int = 120,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    chunk_size: int = 512 * 1024,
) -> Path:
    """Скачивает файл с прогрессом (done_bytes, total_bytes)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = _request(url)
    last_exc: Optional[Exception] = None
    for relaxed in (False, True):
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            opener = _build_opener(proxy, _ssl_context(relaxed))
            with opener.open(req, timeout=timeout) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            try:
                                progress_cb(done, total)
                            except Exception:
                                pass
                tmp.replace(dest)
                return dest
        except urllib.error.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            raise NetworkError(f"HTTP {exc.code} при скачивании {url}") from exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            tmp.unlink(missing_ok=True)
            continue
    raise NetworkError(f"Не удалось скачать {url}: {last_exc}")
