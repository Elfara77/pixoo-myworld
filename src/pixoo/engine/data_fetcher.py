"""Orchestrate parallel plugin fetches with cache and stats."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pixoo.common.models import DataSourceConfig, Project
from pixoo.engine.cache_manager import CacheManager
from pixoo.plugins.base import PluginRegistry, get_registry
from pixoo.utils.secrets import resolve_secrets

logger = logging.getLogger("pixoo.engine.fetcher")


@dataclass
class SourceStats:
    successes: int = 0
    failures: int = 0
    total_ms: float = 0.0
    cache_hits: int = 0
    last_error: str | None = None
    last_success: str | None = None
    last_ms: float | None = None

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return (self.successes / total) if total else 1.0

    @property
    def avg_response_time(self) -> float:
        return (self.total_ms / self.successes / 1000.0) if self.successes else 0.0

    @property
    def cache_hit_rate(self) -> float:
        total = self.successes + self.failures + self.cache_hits
        # approximate: hits vs attempts
        attempts = self.successes + self.failures + self.cache_hits
        return (self.cache_hits / attempts) if attempts else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "success_rate": round(self.success_rate, 3),
            "avg_response_time": round(self.avg_response_time, 3),
            "last_error": self.last_error,
            "last_success": self.last_success,
            "last_ms": self.last_ms,
            "cache_hit_rate": round(self.cache_hit_rate, 3),
            "successes": self.successes,
            "failures": self.failures,
        }


class DataFetcher:
    """Fetch all project sources in parallel with TTL cache."""

    def __init__(
        self,
        registry: PluginRegistry | None = None,
        *,
        max_workers: int = 10,
        persist_cache: bool = True,
    ) -> None:
        self.registry = registry or get_registry()
        cache_path = None
        if persist_cache:
            cache_path = Path.home() / ".cache" / "pixoo" / "cache.json"
        self.cache = CacheManager(persist_path=cache_path)
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pixoo-fetch")
        self.stats: dict[str, SourceStats] = {}
        self._last_values: dict[str, Any] = {}
        self._fetch_log: list[dict[str, Any]] = []

    def close(self) -> None:
        self.thread_pool.shutdown(wait=False, cancel_futures=True)

    def _stats_for(self, source_id: str) -> SourceStats:
        if source_id not in self.stats:
            self.stats[source_id] = SourceStats()
        return self.stats[source_id]

    def _cache_key(self, source: DataSourceConfig) -> str:
        payload = {"plugin": source.plugin, "config": source.config, "id": source.id}
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode()).hexdigest()

    def _log_fetch(self, entry: dict[str, Any]) -> None:
        self._fetch_log.append(entry)
        if len(self._fetch_log) > 300:
            self._fetch_log = self._fetch_log[-300:]
        logger.info(
            "fetch plugin=%s source=%s success=%s cache_hit=%s ms=%s error=%s",
            entry.get("plugin"),
            entry.get("source"),
            entry.get("success"),
            entry.get("cache_hit"),
            entry.get("response_time_ms"),
            entry.get("error"),
        )

    def recent_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._fetch_log[-max(1, limit) :])

    def fetch_single(
        self,
        source: DataSourceConfig,
        *,
        context_values: dict[str, Any] | None = None,
    ) -> Any:
        """Fetch one source with cache / fallback."""
        st = self._stats_for(source.id)
        plugin = self.registry.get(source.plugin)
        fallback = source.config.get("fallback_value", self._last_values.get(source.id))
        if plugin is None:
            st.failures += 1
            st.last_error = f"unknown plugin {source.plugin}"
            return fallback

        config = resolve_secrets(dict(source.config))
        # Allow streaming plugins to return last value without network
        if getattr(plugin, "supports_streaming", False):
            try:
                raw = plugin.fetch_data(config)
                if raw is not None:
                    self._last_values[source.id] = raw
                    st.successes += 1
                    st.last_success = datetime.now(timezone.utc).isoformat()
                    return raw
            except Exception as exc:
                st.failures += 1
                st.last_error = str(exc)
            return self._last_values.get(source.id, fallback)

        if not plugin.validate_config(config):
            st.failures += 1
            st.last_error = "invalid config"
            return self._last_values.get(source.id, fallback)

        ttl = float(config.get("cache_ttl") if config.get("cache_ttl") is not None else 60)
        key = self._cache_key(source)
        cached = self.cache.get(key)
        if cached is not None:
            st.cache_hits += 1
            st.successes += 1
            st.last_success = datetime.now(timezone.utc).isoformat()
            self._last_values[source.id] = cached
            self._log_fetch(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "plugin": source.plugin,
                    "source": source.id,
                    "success": True,
                    "cache_hit": True,
                    "response_time_ms": 0,
                    "fallback_used": False,
                }
            )
            return cached

        t0 = time.perf_counter()
        try:
            raw = plugin.fetch_data(config)
            ms = (time.perf_counter() - t0) * 1000
            value = plugin.extract_value(raw) if hasattr(plugin, "extract_value") else raw
            if value is None and "fallback_value" in config:
                value = config.get("fallback_value")
                used_fb = True
            else:
                used_fb = False
            self.cache.set(key, value, ttl=ttl)
            self._last_values[source.id] = value
            st.successes += 1
            st.total_ms += ms
            st.last_ms = ms
            st.last_success = datetime.now(timezone.utc).isoformat()
            st.last_error = None
            self._log_fetch(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "plugin": source.plugin,
                    "source": source.id,
                    "success": True,
                    "cache_hit": False,
                    "response_time_ms": round(ms, 1),
                    "fallback_used": used_fb,
                }
            )
            return value
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            st.failures += 1
            st.last_error = str(exc)
            st.last_ms = ms
            stale = self.cache.get_stale(key)
            result = stale if stale is not None else self._last_values.get(source.id, fallback)
            self._log_fetch(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "plugin": source.plugin,
                    "source": source.id,
                    "success": False,
                    "cache_hit": False,
                    "response_time_ms": round(ms, 1),
                    "error": str(exc),
                    "fallback_used": result is not None,
                    "fallback_value": result,
                }
            )
            return result

    def fetch_all(self, project: Project) -> dict[str, Any]:
        """Fetch every source in parallel; return id → value."""
        try:
            import psutil

            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        sources = list(project.sources)
        if not sources:
            return {}

        out: dict[str, Any] = {}
        futures = {
            self.thread_pool.submit(self.fetch_single, src): src.id for src in sources
        }
        for fut in as_completed(futures):
            sid = futures[fut]
            try:
                out[sid] = fut.result()
            except Exception as exc:
                logger.error("Source %s failed: %s", sid, exc)
                out[sid] = self._last_values.get(sid)

        # Flatten nested dicts for tag convenience: weather → weather.temperature
        flat = dict(out)
        for sid, val in list(out.items()):
            if isinstance(val, dict):
                for k, v in val.items():
                    flat[f"{sid}.{k}"] = v
        self._last_values.update(flat)
        return flat

    def stats_snapshot(self) -> dict[str, Any]:
        return {k: v.as_dict() for k, v in self.stats.items()}
