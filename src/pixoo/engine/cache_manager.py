"""TTL cache with optional JSON persistence and stale fallback."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger("pixoo.engine.cache")

T = TypeVar("T")


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    stored_at: float


class CacheManager:
    """In-memory TTL cache with optional disk persistence."""

    def __init__(self, persist_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, CacheEntry] = {}
        self.hits = 0
        self.misses = 0
        self.persist_path = Path(persist_path) if persist_path else None
        if self.persist_path:
            self._load_persistent()

    def _load_persistent(self) -> None:
        assert self.persist_path is not None
        if not self.persist_path.is_file():
            return
        try:
            raw = json.loads(self.persist_path.read_text(encoding="utf-8"))
            now = time.time()
            for key, item in (raw or {}).items():
                self._store[key] = CacheEntry(
                    value=item.get("value"),
                    expires_at=float(item.get("expires_at") or 0),
                    stored_at=float(item.get("stored_at") or now),
                )
        except Exception as exc:
            logger.warning("Could not load cache file: %s", exc)

    def _save_persistent(self) -> None:
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                k: {"value": e.value, "expires_at": e.expires_at, "stored_at": e.stored_at}
                for k, e in self._store.items()
            }
            self.persist_path.write_text(json.dumps(payload, default=str), encoding="utf-8")
        except Exception as exc:
            logger.debug("Cache persist failed: %s", exc)

    def get(self, key: str, ttl: int | float | None = None) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            if time.time() > entry.expires_at:
                self.misses += 1
                return None
            self.hits += 1
            return entry.value

    def get_stale(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            return None if entry is None else entry.value

    def set(self, key: str, value: Any, ttl: int | float = 60) -> None:
        ttl_f = max(0.0, float(ttl))
        now = time.time()
        with self._lock:
            self._store[key] = CacheEntry(value=value, expires_at=now + ttl_f, stored_at=now)
            self._save_persistent()

    def get_or_fetch(self, key: str, fetch_func: Callable[[], T], ttl: int | float = 60) -> T:
        hit = self.get(key)
        if hit is not None:
            return hit  # type: ignore[return-value]
        try:
            value = fetch_func()
            self.set(key, value, ttl=ttl)
            return value
        except Exception:
            stale = self.get_stale(key)
            if stale is not None:
                logger.info("Using stale cache for %s", key)
                return stale  # type: ignore[return-value]
            raise

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)
            self._save_persistent()

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._save_persistent()

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0
