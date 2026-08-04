"""Main loop — sample metrics, rotate setup screens, push to Pixoo."""

from __future__ import annotations

import time
from pathlib import Path

from .client import PixooClient
from .config import Config
from .metrics import MetricsCollector, warm_sample
from .render import render_screen
from .setups import Setup, ensure_default_setup, load_setup


class MerlinApp:
    def __init__(self, config: Config, setup: Setup, root: Path | None = None) -> None:
        self.config = config
        self.setup = setup
        self.root = root
        self.collector = MetricsCollector(
            wan_iface=config.wan_iface,
            ping_host=config.ping_host,
            history_seconds=config.history_seconds,
            stats_seconds=config.stats_seconds,
            top_clients=config.top_clients,
            top_window_seconds=config.top_window_seconds,
            disk_path=config.disk_path,
            demo=config.demo,
        )
        self.client: PixooClient | None = None
        if not config.demo or config.pixoo_ip not in ("", "127.0.0.1"):
            if not config.demo:
                self.client = PixooClient(config.pixoo_ip)
                try:
                    self.client.set_brightness(config.brightness)
                except Exception:
                    pass

    def _push(self, image, preview_dir: Path | None, idx: int) -> None:
        if self.config.save_preview:
            out = Path(self.config.save_preview)
            if out.suffix.lower() in (".png", ".gif", ".bmp"):
                image.save(out)
            else:
                out.mkdir(parents=True, exist_ok=True)
                image.save(out / f"screen_{idx}.png")
        if preview_dir is not None:
            preview_dir.mkdir(parents=True, exist_ok=True)
            image.save(preview_dir / f"screen_{idx}.png")
        if self.client is not None:
            self.client.push_image(image)

    def run_forever(self) -> None:
        screens = self.setup.enabled_screens()
        if not screens:
            raise SystemExit(f"Setup {self.setup.name!r} has no enabled screens/widgets")

        print(
            f"pixoo_merlin setup={self.setup.name} screens={len(screens)} "
            f"demo={self.config.demo} pixoo={self.config.pixoo_ip}",
            flush=True,
        )
        snap = warm_sample(self.collector, pause=0.5)
        screen_i = 0
        screen_t0 = time.monotonic()
        anim = 0.0
        # Per-screen seconds > setup.screen_seconds > config SCREEN_SECONDS
        while True:
            loop_t0 = time.monotonic()
            snap = self.collector.sample()
            screens = self.setup.enabled_screens()
            if not screens:
                time.sleep(self.config.frame_interval)
                continue
            screen_i %= len(screens)
            sc = screens[screen_i]
            if sc.seconds is not None:
                secs = float(sc.seconds)
            elif self.setup.screen_seconds is not None:
                secs = float(self.setup.screen_seconds)
            else:
                secs = float(self.config.screen_seconds)
            secs = max(1.0, secs)
            if time.monotonic() - screen_t0 >= secs:
                screen_i = (screen_i + 1) % len(screens)
                screen_t0 = time.monotonic()
                sc = screens[screen_i]
                anim = 0.0

            frame = render_screen(
                self.setup, sc, snap, anim, marquee_speed=self.config.marquee_speed
            )
            try:
                self._push(frame, None, screen_i)
            except Exception as exc:
                print(f"push error: {exc}", flush=True)

            anim += 0.12
            elapsed = time.monotonic() - loop_t0
            time.sleep(max(0.05, self.config.frame_interval - elapsed))

    def run_once_demo_previews(self, out_dir: Path, cycles: int = 1) -> list[Path]:
        """Render each enabled screen once (or cycles) for smoke tests."""
        screens = self.setup.enabled_screens()
        if not screens:
            raise SystemExit(f"Setup {self.setup.name!r} has no enabled screens")
        snap = warm_sample(self.collector, pause=0.4)
        # build some history for graphs
        for _ in range(12):
            snap = self.collector.sample()
            time.sleep(0.05)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for c in range(cycles):
            for i, sc in enumerate(screens):
                img = render_screen(
                    self.setup, sc, snap, anim=0.3 + c * 0.2, marquee_speed=self.config.marquee_speed
                )
                path = out_dir / f"{self.setup.name}_{sc.id}_{i}.png"
                img.save(path)
                paths.append(path)
                if self.client is not None:
                    try:
                        self.client.push_image(img)
                        time.sleep(self.config.frame_interval)
                    except Exception as exc:
                        print(f"push error: {exc}", flush=True)
        return paths


def build_app(config: Config, setup_name: str | None = None, root: Path | None = None) -> MerlinApp:
    root = root or Path(__file__).resolve().parent.parent
    ensure_default_setup(root)
    name = setup_name or config.setup_name
    setup = load_setup(name, root)
    return MerlinApp(config, setup, root=root)
