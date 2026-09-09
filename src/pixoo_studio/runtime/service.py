"""Runtime — fetch sources, auto-send, backoff, stats, last-known."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..domain.models import Project
from ..plugins.base import FetchContext, PluginLoader, get_loader
from ..render.engine import RenderEngine

logger = logging.getLogger("pixoo_studio.runtime")


@dataclass
class SessionStats:
    sends_ok: int = 0
    sends_fail: int = 0
    started_at: float = field(default_factory=time.time)

    @property
    def uptime_s(self) -> float:
        return max(0.0, time.time() - self.started_at)

    @property
    def error_rate(self) -> float:
        total = self.sends_ok + self.sends_fail
        return (self.sends_fail / total) if total else 0.0


class LastValueCache:
    def __init__(self) -> None:
        self._values: dict[str, float] = {}

    def get(self, sid: str) -> float | None:
        return self._values.get(sid)

    def set(self, sid: str, value: float | None) -> None:
        if value is not None:
            self._values[sid] = float(value)

    def as_dict(self) -> dict[str, float | None]:
        return dict(self._values)


class ConnectionState:
    """LED: ok / degraded / down + backoff exponentiel."""

    def __init__(self, max_backoff: float = 60.0) -> None:
        self.status: str = "unknown"  # ok | degraded | down | unknown
        self.failures: int = 0
        self.max_backoff = max_backoff
        self.next_allowed_at: float = 0.0
        self.last_error: str = ""

    def on_success(self) -> None:
        self.status = "ok"
        self.failures = 0
        self.next_allowed_at = 0.0
        self.last_error = ""

    def on_failure(self, err: str, *, degraded: bool = False) -> None:
        self.failures += 1
        self.last_error = err
        self.status = "degraded" if degraded else "down"
        backoff = min(self.max_backoff, 2 ** min(self.failures, 6))
        self.next_allowed_at = time.time() + backoff

    def can_attempt(self) -> bool:
        return time.time() >= self.next_allowed_at


class DataFetcher:
    """Résout toutes les sources du projet via plugins."""

    def __init__(self, loader: PluginLoader | None = None) -> None:
        self.loader = loader or get_loader()
        self.last = LastValueCache()

    def fetch_all(self, project: Project) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        ctx = FetchContext()
        for src in project.sources:
            plugin = self.loader.get(src.plugin_id)
            if plugin is None:
                logger.warning("Plugin inconnu: %s", src.plugin_id)
                out[src.id] = self.last.get(src.id)
                continue
            if not plugin.validate_config(src.config):
                logger.warning("Config invalide pour %s", src.id)
                out[src.id] = self.last.get(src.id)
                continue
            try:
                ctx.last_value = self.last.get(src.id)
                raw = plugin.fetch_data(src.config, ctx)
                if hasattr(plugin, "extract_numeric"):
                    num = plugin.extract_numeric(raw)
                elif isinstance(raw, (int, float)):
                    num = float(raw)
                else:
                    num = None
                if num is None and isinstance(raw, (int, float)):
                    num = float(raw)
                if num is None:
                    # mode dégradé
                    num = self.last.get(src.id)
                    if num is not None:
                        logger.info("Dégradé %s → last known %s", src.id, num)
                else:
                    self.last.set(src.id, num)
                    hist = project.history_preview.setdefault(src.id, [])
                    hist.append(num)
                    if len(hist) > 200:
                        del hist[:-200]
                out[src.id] = num
            except Exception as exc:
                logger.error("Fetch %s: %s", src.id, exc)
                out[src.id] = self.last.get(src.id)
        return out


class SendService:
    """Envoi périodique vers Pixoo avec backoff."""

    def __init__(self, project: Project, engine: RenderEngine | None = None) -> None:
        self.project = project
        self.engine = engine or RenderEngine()
        self.fetcher = DataFetcher()
        self.stats = SessionStats()
        self.conn = ConnectionState(max_backoff=project.runtime.max_backoff_s)
        self._screen_index = 0
        self._screen_started = time.monotonic()
        self._prev_frame = None
        self._transition_t0: float | None = None

    def current_screen(self):
        if not self.project.screens:
            return None
        return self.project.screens[self._screen_index % len(self.project.screens)]

    def tick_screen_rotation(self) -> None:
        scr = self.current_screen()
        if not scr or len(self.project.screens) < 2:
            return
        if time.monotonic() - self._screen_started >= scr.duration_s:
            self._screen_index = (self._screen_index + 1) % len(self.project.screens)
            self._screen_started = time.monotonic()
            self._transition_t0 = time.monotonic()

    def build_frame(self, values: dict[str, float | None], anim_t: float):
        self.tick_screen_rotation()
        scr = self.current_screen()
        if scr is None:
            from PIL import Image

            return Image.new("RGB", (64, 64), (0, 0, 0))
        frame = self.engine.render_screen(scr, self.project, values, anim_t=anim_t)
        if self._transition_t0 is not None and self._prev_frame is not None:
            dur = max(1, scr.transition_ms) / 1000.0
            p = (time.monotonic() - self._transition_t0) / dur
            if p >= 1:
                self._transition_t0 = None
            else:
                # previous screen frame blended — approx with last pushed
                frame = self.engine.transition(self._prev_frame, frame, p, scr.transition)
        self._prev_frame = frame.copy()
        return frame

    def push_once(self, anim_t: float = 0.0) -> bool:
        if not self.conn.can_attempt():
            return False
        values = self.fetcher.fetch_all(self.project)
        frame = self.build_frame(values, anim_t)
        try:
            from pixoo_monitor.pixoo_client import PixooClient

            client = PixooClient(self.project.meta.pixoo_ip, size=64)
            client.set_brightness(int(self.project.meta.brightness))
            client.push_image(frame)
            self.conn.on_success()
            self.stats.sends_ok += 1
            return True
        except Exception as exc:
            degraded = any(v is not None for v in values.values())
            self.conn.on_failure(str(exc), degraded=degraded)
            self.stats.sends_fail += 1
            logger.error("Push Pixoo: %s", exc)
            return False
