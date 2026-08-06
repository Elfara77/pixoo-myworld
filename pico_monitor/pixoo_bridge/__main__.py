"""Merlin /metrics.json → Divoom Pixoo 64 HTTP push.

This is the path that lights a Pixoo. pico_monitor/firmware/ is MicroPython
for Pico W + SSD1306 and will NEVER show on a Pixoo.

Usage (from pico_monitor/ on Mac):
  ../.venv/bin/python -m pixoo_bridge --demo
  ../.venv/bin/python -m pixoo_bridge --pixoo 192.168.52.4

On Merlin (Entware), watchdog runs:
  python3 -m pixoo_bridge --log /jffs/addons/pico_monitor/logs/pixoo_bridge.log
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

# Allow `python -m pixoo_bridge` from pico_monitor/ (Mac) or addon root (Merlin)
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from pixoo_bridge.client import PixooClient
from pixoo_bridge.render import (
    get_screen_ids,
    render_boot_banner,
    render_screen,
    screen_dwell_seconds,
    set_render_options,
    set_sum_dwell,
    _demo_metrics,
)

LOG = logging.getLogger("pixoo_bridge")


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


def _setup_logging(log_path: str | None) -> None:
    """Stdout always (watchdog/nohup captures it). Optional extra FileHandler."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_path:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
        except OSError as exc:
            print(f"log file warn: {exc}", flush=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


_SNAPSHOT_HIST_MAX = 10
_LAST_HIST_MONO = 0.0
_LAST_HIST_SID = ""


def _resolve_snapshot_path(explicit: str | None, log_path: str | None) -> Path | None:
    """PNG path for last pushed frame. Pixoo API cannot read the LED matrix back."""
    if explicit:
        return Path(explicit)
    if log_path:
        # …/logs/pixoo_bridge.log → …/run/pixoo_last.png
        return Path(log_path).resolve().parent.parent / "run" / "pixoo_last.png"
    # Watchdog starts without --log (stdout→nohup); cwd is addon root.
    return Path.cwd() / "run" / "pixoo_last.png"


def _prune_snapshot_hist(hist_dir: Path, *, keep: int = _SNAPSHOT_HIST_MAX) -> None:
    files = sorted(hist_dir.glob("*.png"), key=lambda p: p.name)
    for old in files[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
        try:
            old.with_suffix(".txt").unlink()
        except OSError:
            pass


def _save_snapshot(
    frame,
    path: Path,
    *,
    screen_id: str = "",
    hist_max: int = _SNAPSHOT_HIST_MAX,
    hist_every_s: float = 2.0,
) -> None:
    """Atomically write last 64×64 PNG + rolling hist/ (max `hist_max` frames)."""
    global _LAST_HIST_MONO, _LAST_HIST_SID
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        frame.save(tmp, format="PNG")
        tmp.replace(path)
        if screen_id:
            path.with_suffix(".txt").write_text(f"{screen_id}\n", encoding="utf-8")

        # Rolling history: on screen change or every hist_every_s (≤ hist_max PNGs).
        now = time.monotonic()
        sid = str(screen_id or "UNK")
        sid_changed = sid != _LAST_HIST_SID
        due = (now - _LAST_HIST_MONO) >= max(0.5, float(hist_every_s))
        if sid_changed or due or _LAST_HIST_MONO <= 0:
            hist_dir = path.parent / "hist"
            hist_dir.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)[:16] or "UNK"
            stamp = time.strftime("%Y%m%d_%H%M%S")
            hist_png = hist_dir / f"{stamp}_{safe}.png"
            n = 0
            while hist_png.exists() and n < 99:
                n += 1
                hist_png = hist_dir / f"{stamp}_{safe}_{n}.png"
            frame.save(hist_png, format="PNG")
            hist_png.with_suffix(".txt").write_text(f"{sid}\n", encoding="utf-8")
            _prune_snapshot_hist(hist_dir, keep=max(1, int(hist_max)))
            _LAST_HIST_MONO = now
            _LAST_HIST_SID = sid
    except OSError as exc:
        LOG.warning("snapshot save warn: %s", exc)


def fetch_metrics(url: str, timeout: float = 3.0) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main(argv: list[str] | None = None) -> int:
    root = _HERE.parent
    env = _load_dotenv(root / ".deploy.env")
    env.update(_load_dotenv(root / "config.env"))
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
        or f"http://{env.get('PICO_ROUTER_HOST', '127.0.0.1')}:{env.get('PICO_METRICS_PORT', '8088')}/metrics.json",
        help="Merlin /metrics.json URL",
    )
    ap.add_argument("--brightness", type=int, default=int(env.get("PIXOO_BRIGHTNESS", "50")))
    ap.add_argument(
        "--screen-seconds",
        type=float,
        default=float(env.get("PIXOO_SCREEN_SECONDS", "8")),
        help="Base seconds per screen (heavy screens use × multiplier when enabled)",
    )
    ap.add_argument(
        "--heavy-screen-dwell",
        default=env.get("PIXOO_HEAVY_SCREEN_DWELL", "1"),
        help="1=longer dwell on graph/dense screens (default), 0=same as --screen-seconds for all",
    )
    ap.add_argument(
        "--heavy-screen-multiplier",
        type=float,
        default=float(env.get("PIXOO_HEAVY_SCREEN_MULTIPLIER", "2")),
        help="Dwell multiplier for heavy screens (default 2)",
    )
    ap.add_argument(
        "--wlc-graph-mode",
        default=env.get("PIXOO_WLC_GRAPH_MODE") or env.get("PIXOO_GRAPH_MODE", "overlay"),
        choices=("overlay", "split"),
        help="WLC screen: overlay=down+up same graph; split=down left, up right",
    )
    ap.add_argument(
        "--wan-max-down",
        type=float,
        default=float(env.get("PIXOO_WAN_MAX_DOWN_MBPS", "190")),
        help="WAN download saturation cap Mbps (SUM Net health / Top ranking)",
    )
    ap.add_argument(
        "--wan-max-up",
        type=float,
        default=float(env.get("PIXOO_WAN_MAX_UP_MBPS", "12")),
        help="WAN upload saturation cap Mbps (SUM Net health / Top ranking)",
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
    ap.add_argument(
        "--color-mode",
        default=env.get("PIXOO_COLOR_MODE", "mono"),
        choices=("mono", "poly"),
        help="mono = all text one solid color; poly = colored labels (gauges stay colored)",
    )
    ap.add_argument(
        "--text-scroll",
        default=env.get("PIXOO_TEXT_SCROLL", "1"),
        help="1/0 — scroll titles and long labels that exceed the 64px width",
    )
    ap.add_argument(
        "--alert-blink",
        default=env.get("PIXOO_ALERT_BLINK", "1"),
        help="1/0 — blink critical text/gauges (CPU/RAM≥90, temps, disk≥90, WAN off)",
    )
    ap.add_argument(
        "--blink-period",
        type=float,
        default=float(env.get("PIXOO_BLINK_PERIOD", "0.55")),
        help="Half-cycle seconds for alert blink (default 0.55 ≈ 1 Hz full cycle)",
    )
    ap.add_argument(
        "--rate-style",
        default=env.get("PIXOO_RATE_STYLE", "short"),
        choices=("short", "long"),
        help="short=K/M/G · long=Kb/s|Mb/s|Gb/s",
    )
    ap.add_argument(
        "--screens",
        default=env.get("PIXOO_SCREENS", "all"),
        help="Active screens: all (no SUM), all,SUM, SUM alone, or SYS,LOD,...",
    )
    ap.add_argument(
        "--log",
        default=env.get("PIXOO_LOG") or None,
        help="Also write log file (e.g. /jffs/addons/pico_monitor/logs/pixoo_bridge.log)",
    )
    ap.add_argument(
        "--snapshot-path",
        default=env.get("PIXOO_SNAPSHOT_PATH") or None,
        help="Write last pushed 64×64 PNG here (default: <addon>/run/pixoo_last.png when --log set)",
    )
    args = ap.parse_args(argv)

    scroll_on = str(args.text_scroll).strip().lower() in ("1", "true", "yes", "on")
    blink_on = str(args.alert_blink).strip().lower() in ("1", "true", "yes", "on")
    heavy_dwell = str(args.heavy_screen_dwell).strip().lower() in ("1", "true", "yes", "on")
    set_render_options(
        color_mode=args.color_mode,
        text_scroll=scroll_on,
        alert_blink=blink_on,
        blink_period_s=args.blink_period,
        rate_style=args.rate_style,
        screens=args.screens,
        heavy_screen_dwell=heavy_dwell,
        heavy_screen_multiplier=args.heavy_screen_multiplier,
        wlc_graph_mode=args.wlc_graph_mode,
        wan_max_down_mbps=args.wan_max_down,
        wan_max_up_mbps=args.wan_max_up,
    )
    screens = get_screen_ids()

    _setup_logging(args.log)
    snapshot_path = _resolve_snapshot_path(args.snapshot_path, args.log)
    LOG.info(
        "start pixoo=%s metrics=%s demo=%s brightness=%s screen_s=%s heavy_dwell=%s heavy_x=%s wlc_graph=%s wan_max=%.0f/%.0f frame_s=%s color=%s scroll=%s blink=%s rate=%s screens=%s snapshot=%s",
        args.pixoo,
        args.metrics,
        args.demo,
        args.brightness,
        args.screen_seconds,
        heavy_dwell,
        args.heavy_screen_multiplier,
        args.wlc_graph_mode,
        args.wan_max_down,
        args.wan_max_up,
        args.frame_interval,
        args.color_mode,
        scroll_on,
        blink_on,
        args.rate_style,
        ",".join(screens),
        str(snapshot_path) if snapshot_path else "-",
    )

    client = PixooClient(args.pixoo)
    if not client.ping():
        LOG.error("%s does not answer Pixoo API /post — is it a Pixoo?", args.pixoo)
        return 2
    LOG.info("Pixoo OK at %s", args.pixoo)
    try:
        client.set_brightness(args.brightness)
        LOG.info("brightness set to %s", args.brightness)
    except Exception as exc:
        LOG.warning("brightness warn: %s", exc)

    boot = render_boot_banner("LIVE" if not args.demo else "DEMO")
    client.push_image(boot)
    if snapshot_path is not None:
        _save_snapshot(boot, snapshot_path, screen_id="BOOT")
    LOG.info("pushed boot banner (%s)", "DEMO" if args.demo else "LIVE")
    if args.preview:
        args.preview.mkdir(parents=True, exist_ok=True)
        boot.save(args.preview / "00_boot.png")
    if args.once:
        LOG.info("pushed boot banner — exit (--once)")
        return 0

    screen_i = 0
    screen_t0 = time.monotonic()
    metrics_ok = 0
    metrics_fail = 0
    screens = get_screen_ids()
    LOG.info("loop screens=%s ids=%s", len(screens), ",".join(screens))

    while True:
        loop_t0 = time.monotonic()
        offline = False
        screens = get_screen_ids()
        if not screens:
            screens = ("SYS",)
        if args.demo:
            m = _demo_metrics()
        else:
            try:
                m = fetch_metrics(args.metrics)
                metrics_ok += 1
                if metrics_ok == 1 or metrics_ok % 60 == 0:
                    LOG.info("metrics OK (%s fetches) from %s", metrics_ok, args.metrics)
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                metrics_fail += 1
                if metrics_fail == 1 or metrics_fail % 30 == 0:
                    LOG.warning(
                        "metrics offline (%s) — demo fallback (fails=%s)",
                        exc,
                        metrics_fail,
                    )
                m = _demo_metrics()
                m["_offline"] = True
                offline = True

        screen_i = screen_i % len(screens)
        cur_sid = screens[screen_i]
        dwell = screen_dwell_seconds(cur_sid, args.screen_seconds)
        if time.monotonic() - screen_t0 >= dwell:
            screen_i = (screen_i + 1) % len(screens)
            screen_t0 = time.monotonic()
            LOG.info(
                "screen → %s (%d/%d) dwell=%.1fs%s",
                screens[screen_i],
                screen_i + 1,
                len(screens),
                screen_dwell_seconds(screens[screen_i], args.screen_seconds),
                " [offline-demo]" if offline else "",
            )

        screen_i = screen_i % len(screens)
        cur_sid = screens[screen_i]
        dwell = screen_dwell_seconds(cur_sid, args.screen_seconds)
        if cur_sid == "SUM":
            set_sum_dwell(screen_t0, dwell)
        frame = render_screen(m, screen_i)
        if args.preview:
            frame.save(args.preview / f"{screen_i:02d}_{screens[screen_i].lower()}.png")
        try:
            client.push_image(frame)
            if snapshot_path is not None:
                _save_snapshot(frame, snapshot_path, screen_id=screens[screen_i])
        except Exception as exc:
            LOG.error("push error: %s\n%s", exc, traceback.format_exc())

        elapsed = time.monotonic() - loop_t0
        time.sleep(max(0.05, args.frame_interval - elapsed))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        LOG.info("stopped (KeyboardInterrupt)")
        raise SystemExit(0)
    except Exception:
        LOG.error("fatal:\n%s", traceback.format_exc())
        raise
