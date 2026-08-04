"""HTTP helpers: URL validation, retries, proxy, timeout caps."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("pixoo.utils.network")

MAX_TIMEOUT_S = 10.0
T = TypeVar("T")


def clamp_timeout(timeout: float | int | None, default: float = 5.0) -> float:
    t = float(timeout if timeout is not None else default)
    if t <= 0:
        t = default
    return min(t, MAX_TIMEOUT_S)


def validate_url(url: str, *, allow_ws: bool = False) -> bool:
    try:
        p = urlparse(str(url or "").strip())
    except Exception:
        return False
    schemes = {"http", "https"}
    if allow_ws:
        schemes |= {"ws", "wss"}
    return p.scheme in schemes and bool(p.netloc)


def proxy_from_env() -> str | None:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = os.environ.get(key)
        if val:
            return val
    return None


def http_client(timeout: float = 5.0) -> httpx.Client:
    kwargs: dict[str, Any] = {
        "timeout": clamp_timeout(timeout),
        "follow_redirects": True,
        "headers": {"User-Agent": "pixoo-engine/2.0"},
    }
    proxy = proxy_from_env()
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def with_retries(
    func: Callable[[], T],
    *,
    retries: int = 3,
    backoff: float = 0.4,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Run func with exponential backoff retries."""
    attempts = max(1, int(retries) + 1)
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return func()
        except exceptions as exc:
            last = exc
            if i >= attempts - 1:
                break
            sleep = backoff * (2**i)
            logger.debug("Retry %s/%s after %.2fs: %s", i + 1, attempts - 1, sleep, exc)
            time.sleep(sleep)
    assert last is not None
    raise last
