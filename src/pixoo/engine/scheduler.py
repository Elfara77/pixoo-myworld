"""Fetch plugins, render, rate-limit, push to Pixoo."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from PIL import Image

from pixoo.common.models import Project
from pixoo.engine.renderer import Renderer
from pixoo.plugins.base import PluginRegistry, get_registry

logger = logging.getLogger("pixoo.engine.scheduler")


@dataclass
class EngineStats:
    started_at: float = field(default_factory=time.time)
    sends_ok: int = 0
    error_count: int = 0
    last_send: str | None = None
    status: str = "starting"

    @property
    def uptime(self) -> float:
        return max(0.0, time.time() - self.started_at)


class Scheduler:
    """Main engine loop helpers (thread-safe enough for daemon + API)."""

    def __init__(self, project: Project, registry: PluginRegistry | None = None) -> None:
        self.project = project
        self.registry = registry or get_registry()
        self.renderer = Renderer()
        self.stats = EngineStats()
        self._values: dict[str, float | None] = {}
        self._last_hash: str | None = None
        self._last_frame: Image.Image | None = None
        self._screen_index = 0
        self._screen_started = time.monotonic()
        self._last_push_mono = 0.0
        self._anim_t0 = time.monotonic()
        self._failures = 0

    def fetch_values(self) -> dict[str, float | None]:
        try:
            import psutil

            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        out: dict[str, float | None] = {}
        for src in self.project.sources:
            plugin = self.registry.get(src.plugin)
            if plugin is None or not plugin.validate_config(src.config):
                out[src.id] = self._values.get(src.id)
                continue
            try:
                raw = plugin.fetch_data(src.config)
                num = plugin.extract_numeric(raw)
                if num is None and isinstance(raw, (int, float)):
                    num = float(raw)
                if num is None:
                    num = self._values.get(src.id)
                else:
                    hist = self.project.history.setdefault(src.id, [])
                    hist.append(num)
                    if len(hist) > 200:
                        del hist[:-200]
                out[src.id] = num
            except Exception as exc:
                logger.error("Source %s failed: %s", src.id, exc)
                out[src.id] = self._values.get(src.id)
        self._values = out
        return out

    def current_screen(self):
        if not self.project.screens:
            return None
        return self.project.screens[self._screen_index % len(self.project.screens)]

    def rotate_screens(self) -> None:
        scr = self.current_screen()
        if not scr or len(self.project.screens) < 2:
            return
        if time.monotonic() - self._screen_started >= scr.duration_s:
            self._screen_index = (self._screen_index + 1) % len(self.project.screens)
            self._screen_started = time.monotonic()

    def build_frame(self) -> Image.Image:
        self.rotate_screens()
        scr = self.current_screen()
        values = self._values or self.fetch_values()
        anim_t = time.monotonic() - self._anim_t0
        if scr is None:
            frame = Image.new("RGB", (64, 64), (0, 0, 0))
        else:
            frame = self.renderer.render(scr, self.project, values, anim_t=anim_t)
        self._last_frame = frame
        return frame

    def frame_hash(self, image: Image.Image) -> str:
        return hashlib.sha1(image.tobytes()).hexdigest()

    def should_push(self, image: Image.Image) -> bool:
        interval = max(1.0, float(self.project.runtime.send_interval_s))
        if time.monotonic() - self._last_push_mono < interval:
            return False
        h = self.frame_hash(image)
        # Always allow push when animating (hash changes) or first frame
        if self._last_hash is None or h != self._last_hash:
            return True
        return False

    def push_frame(self, image: Image.Image, *, force: bool = False) -> bool:
        interval = max(1.0, float(self.project.runtime.send_interval_s))
        if not force and time.monotonic() - self._last_push_mono < interval:
            return False
        if not force and not self.should_push(image):
            return False
        try:
            from pixoo_monitor.pixoo_client import PixooClient

            client = PixooClient(self.project.meta.pixoo_ip, size=64)
            client.set_brightness(int(self.project.meta.brightness))
            client.push_image(image)
            self._last_push_mono = time.monotonic()
            self._last_hash = self.frame_hash(image)
            self.stats.sends_ok += 1
            self.stats.last_send = datetime.now(timezone.utc).isoformat()
            self.stats.status = "running"
            self._failures = 0
            return True
        except Exception as exc:
            self.stats.error_count += 1
            self._failures += 1
            self.stats.status = "error"
            logger.error("Pixoo push failed: %s", exc)
            return False

    def tick(self) -> Image.Image:
        self.fetch_values()
        frame = self.build_frame()
        if self.project.runtime.auto_send:
            self.push_frame(frame)
        return frame

    def reload_project(self, project: Project) -> None:
        self.project = project
        self.renderer.cache.clear()
        self._last_hash = None
        logger.info("Project reloaded: %s", project.meta.name)
