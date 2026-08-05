"""Merlin /metrics.json → Divoom Pixoo 64 HTTP push.

This is the path that lights a Pixoo. pico_monitor/firmware/ is MicroPython
for Pico W + SSD1306 and will NEVER show on a Pixoo.

Usage (from pico_monitor/):
  ../.venv/bin/python -m pixoo_bridge --demo
  ../.venv/bin/python -m pixoo_bridge --pixoo 192.168.52.4
  ../.venv/bin/python -m pixoo_bridge --once   # single boot banner + exit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Allow `python -m pixoo_bridge` from pico_monitor/
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from pixoo_bridge.client import PixooClient
from pixoo_bridge.render import SCREEN_IDS, _demo_metrics, render_boot_banner, render_screen


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def fetch_metrics(url: str, timeout: float = 3.0) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main(argv: list[str] | None = None) -> int:
    root = _HERE.parent
    env = _load_dotenv(root / ".deploy.env")
    env.update({k: v for k, v in os.environ.items() if k.startswith(("PIXOO_", "PICO_"))})

    ap = argparse.ArgumentParser(description="Push Merlin metrics to a Divoom Pixoo 64")
    ap.add_argument(
        "--pixoo",
        default=env.get("PIXOO_IP") or env.get("PICO_PIXOO_IP") or "192.168.52.4",
        help="Pixoo LAN IP (HTTP :80/post)",
    )
    ap.add_argument(
        "--metrics",
        default=env.get("PIXOO_METRICS_URL")
        or f"http://{env.get('PICO_ROUTER_HOST', '192.168.50.1')}:{env.get('PICO_METRICS_PORT', '8088')}/metrics.json",
        help="Merlin /metrics.json URL",
    )
    ap.add_argument("--brightness", type=int, default=int(env.get("PIXOO_BRIGHTNESS", "50")))
    ap.add_argument(
        "--screen-seconds",
        type=float,
        default=float(env.get("PIXOO_SCREEN_SECONDS", "8")),
        help="Seconds per screen (old Pixoo default ~8)",
    )
    ap.add_argument(
        "--frame-interval",
        type=float,
        default=float(env.get("PIXOO_FRAME_INTERVAL", "1.05")),
        help="Min seconds between Pixoo HTTP pushes (rate limit)",
    )
    ap.add_argument("--demo", action="store_true", help="Fake metrics (no Merlin)")
    ap.add_argument("--once", action="store_true", help="Push boot banner once and exit")
    ap.add_argument("--preview", type=Path, default=None, help="Also save PNG frames here")
    args = ap.parse_args(argv)

    client = PixooClient(args.pixoo)
    if not client.ping():
        print(f"ERROR: {args.pixoo} does not answer Pixoo API /post — is it a Pixoo?", flush=True)
        return 2
    print(f"Pixoo OK at {args.pixoo}", flush=True)
    try:
        client.set_brightness(args.brightness)
    except Exception as exc:
        print(f"brightness warn: {exc}", flush=True)

    boot = render_boot_banner("LIVE" if not args.demo else "DEMO")
    client.push_image(boot)
    if args.preview:
        args.preview.mkdir(parents=True, exist_ok=True)
        boot.save(args.preview / "00_boot.png")
    if args.once:
        print("pushed boot banner — exit", flush=True)
        return 0

    screen_i = 0
    screen_t0 = time.monotonic()
    print(
        f"bridge metrics={args.metrics} demo={args.demo} "
        f"screens={len(SCREEN_IDS)} screen_s={args.screen_seconds} frame_s={args.frame_interval}",
        flush=True,
    )

    while True:
        loop_t0 = time.monotonic()
        if args.demo:
            m = _demo_metrics()
        else:
            try:
                m = fetch_metrics(args.metrics)
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                print(f"metrics offline ({exc}) — demo fallback", flush=True)
                m = _demo_metrics()
                m["_offline"] = True

        if time.monotonic() - screen_t0 >= max(1.0, args.screen_seconds):
            screen_i = (screen_i + 1) % len(SCREEN_IDS)
            screen_t0 = time.monotonic()

        frame = render_screen(m, screen_i)
        if args.preview:
            frame.save(args.preview / f"{screen_i:02d}_{SCREEN_IDS[screen_i].lower()}.png")
        try:
            client.push_image(frame)
        except Exception as exc:
            print(f"push error: {exc}", flush=True)

        elapsed = time.monotonic() - loop_t0
        time.sleep(max(0.05, args.frame_interval - elapsed))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
        raise SystemExit(0)
