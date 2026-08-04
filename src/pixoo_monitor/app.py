"""Application monitoring → Pixoo."""

from __future__ import annotations

import socket
import time
from typing import Any

from PIL import Image

from .display import Renderer
from .history import HistoryStore, extract_history_values
from .metrics import Collector, Snapshot
from .pixoo_client import PixooClient
from .setups import active_setup_name


def pixoo_reachable(ip: str, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((ip, 80), timeout=timeout):
            return True
    except OSError:
        return False


class PixooDevice:
    """Client HTTP Pixoo (sans lib `pixoo` / tkinter)."""

    def __init__(self, ip: str, size: int = 64, brightness: int = 60) -> None:
        self._client = PixooClient(ip, size)
        try:
            self._client.set_brightness(int(brightness))
        except Exception:
            pass

    def push_image(self, image: Image.Image) -> None:
        self._client.push_image(image)


class MonitorApp:
    def __init__(self, cfg: dict[str, Any], *, dry_run: bool = False) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        pixoo_cfg = cfg.get("pixoo", {})
        self.ip = str(pixoo_cfg.get("ip", "192.168.1.137"))
        self.size = int(pixoo_cfg.get("size", 64))
        self.brightness = int(pixoo_cfg.get("brightness", 60))
        refresh = cfg.get("refresh", {})
        self.interval = float(refresh.get("interval_seconds", 3.0))
        self.page_seconds = float(refresh.get("page_seconds", 8.0))
        self.setup_name = active_setup_name(cfg)
        self.collector = Collector(cfg)
        self.history = HistoryStore(cfg)
        self.renderer = Renderer(cfg, size=self.size)
        self.renderer.history = self.history
        self.device: PixooDevice | None = None
        if not dry_run:
            self.device = PixooDevice(self.ip, self.size, self.brightness)

    def collect(self) -> Snapshot:
        snap = self.collector.collect()
        try:
            self.history.record_snapshot_values(extract_history_values(snap), ts=snap.ts)
        except Exception:
            pass
        return snap

    def pages(self, snap: Snapshot | None = None) -> list[tuple[str, Image.Image]]:
        if snap is None:
            snap = self.collect()
        return self.renderer.build_pages(snap)

    def push(self, image: Image.Image) -> None:
        if self.device is None:
            raise RuntimeError("Mode dry-run: pas de push Pixoo")
        self.device.push_image(image)

    def run_forever(self) -> None:
        page_idx = 0
        page_started = time.monotonic()
        self.collect()
        time.sleep(min(1.0, self.interval))

        while True:
            snap = self.collect()
            pages = self.pages(snap)
            now = time.monotonic()
            if now - page_started >= self.page_seconds:
                page_idx = (page_idx + 1) % max(len(pages), 1)
                page_started = now
            name, image = pages[page_idx % len(pages)]
            if self.device is not None:
                self.push(image)
            time.sleep(self.interval)
