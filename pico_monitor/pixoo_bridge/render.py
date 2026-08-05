"""64×64 RGB screens from pico_monitor /metrics.json (Merlin exporter).

Pixel fonts (no antialias). PIXOO_COLOR_MODE only affects *text*:
  mono = all text one solid color (white); poly = per-label solid hues.
Gauges, graphs, status dots keep full color + thresholds always.
Critical alerts can blink (PIXOO_ALERT_BLINK) on text and gauge fills.
"""

from __future__ import annotations

from typing import Any, Sequence

from PIL import Image, ImageDraw

from pixoo_bridge import pixel_font as pf

# Full UI palette (graphics always use this)
BG = (6, 8, 14)
FG = (230, 235, 245)
DIM = (90, 100, 120)
CYAN = (40, 210, 230)
ORANGE = (255, 140, 50)
GREEN = (40, 220, 110)
YELLOW = (240, 200, 50)
RED = (255, 70, 70)
BAR_BG = (22, 26, 38)
GRAPH_DOWN = (40, 190, 255)
GRAPH_UP = (255, 130, 60)
HEADER = (40, 210, 230)
HEADER_FG = (6, 8, 14)
# Solid text color in mono mode (no gray nuances)
TEXT_MONO = (255, 255, 255)

ALL_SCREEN_IDS = ("SYS", "GRP", "TOP", "TMP", "PIE", "SRV", "NET", "CLI")
SCREEN_TITLES = {
    "SYS": "System",
    "GRP": "Traffic",
    "TOP": "Top",
    "TMP": "Temps",
    "PIE": "Disk Space",
    "SRV": "Services",
    "NET": "Ports",
    "CLI": "Clients",
}

# Active rotation set (mutable); default = all
_ACTIVE_SCREENS: list[str] = list(ALL_SCREEN_IDS)

# Back-compat alias updated by set_screens / set_render_options
SCREEN_IDS: tuple[str, ...] = tuple(_ACTIVE_SCREENS)

_COLOR_MODE = "mono"
_TEXT_SCROLL = True
_ALERT_BLINK = True
_BLINK_PERIOD_S = 0.55  # half-cycle; full blink ~1.1s (matches frame interval)

# Critical thresholds
CRIT_LOAD = 90.0
CRIT_TEMP_CPU = 85
CRIT_TEMP_RADIO = 65
CRIT_DISK = 90.0


_RATE_STYLE = "short"  # short=K/M/G · long=Kb/s|Mb/s|Gb/s


def get_screen_ids() -> tuple[str, ...]:
    return tuple(_ACTIVE_SCREENS)


def set_screens(spec: str | None) -> tuple[str, ...]:
    """Select active screens. spec='all' or 'SYS,GRP,TMP' (order preserved).

    At least one valid id required; invalid tokens ignored.
    """
    global SCREEN_IDS, _ACTIVE_SCREENS
    if spec is None or not str(spec).strip() or str(spec).strip().lower() in ("all", "*", "default"):
        _ACTIVE_SCREENS = list(ALL_SCREEN_IDS)
        SCREEN_IDS = tuple(_ACTIVE_SCREENS)
        return SCREEN_IDS
    wanted: list[str] = []
    for tok in str(spec).replace(";", ",").replace(" ", ",").split(","):
        sid = tok.strip().upper()
        if not sid:
            continue
        if sid in ALL_SCREEN_IDS and sid not in wanted:
            wanted.append(sid)
    if not wanted:
        _ACTIVE_SCREENS = list(ALL_SCREEN_IDS)
    else:
        _ACTIVE_SCREENS = wanted
    SCREEN_IDS = tuple(_ACTIVE_SCREENS)
    return SCREEN_IDS


def set_render_options(
    *,
    color_mode: str | None = None,
    text_scroll: bool | None = None,
    alert_blink: bool | None = None,
    blink_period_s: float | None = None,
    rate_style: str | None = None,
    screens: str | None = None,
) -> None:
    global _COLOR_MODE, _TEXT_SCROLL, _ALERT_BLINK, _BLINK_PERIOD_S, _RATE_STYLE
    if color_mode is not None:
        mode = color_mode.strip().lower()
        if mode in ("mono", "monochrome", "bw"):
            _COLOR_MODE = "mono"
        elif mode in ("poly", "polychrome", "color", "colour"):
            _COLOR_MODE = "poly"
        else:
            _COLOR_MODE = "mono"
    if text_scroll is not None:
        _TEXT_SCROLL = bool(text_scroll)
    if alert_blink is not None:
        _ALERT_BLINK = bool(alert_blink)
    if blink_period_s is not None:
        _BLINK_PERIOD_S = max(0.2, float(blink_period_s))
    if rate_style is not None:
        rs = rate_style.strip().lower()
        _RATE_STYLE = "long" if rs in ("long", "full", "verbose") else "short"
    if screens is not None:
        set_screens(screens)


def _text_color(color: Sequence[int]) -> tuple[int, int, int]:
    """Mono: flatten all text to one solid white. Poly: keep the solid hue."""
    if _COLOR_MODE == "mono":
        return TEXT_MONO
    return (int(color[0]), int(color[1]), int(color[2]))


def _blink_on() -> bool:
    """True during the visible half of the blink cycle."""
    if not _ALERT_BLINK:
        return True
    import time

    return (int(time.monotonic() / _BLINK_PERIOD_S) % 2) == 0


def _is_crit_load(pct: float) -> bool:
    return float(pct or 0) >= CRIT_LOAD


def _is_crit_disk(pct: float) -> bool:
    return float(pct or 0) >= CRIT_DISK


def _is_crit_temp(label: str, val: int) -> bool:
    if label == "CPU":
        return val >= CRIT_TEMP_CPU
    if label in ("2G", "5G", "AVG", "TMP"):
        return val >= CRIT_TEMP_RADIO
    return False


def _txt(
    img,
    x: int,
    y: int,
    text: str,
    color: Sequence[int],
    *,
    size: str = "normal",
    alert: bool = False,
) -> int:
    """Draw text; if alert and blink off-phase, skip (blink effect)."""
    if alert and _ALERT_BLINK and not _blink_on():
        return x
    col = RED if alert else color
    return pf.draw_text(img, x, y, text, _text_color(col) if not alert else RED, size=size)


def _rate(mbps: float) -> str:
    """Format Mbps — long units when PIXOO_RATE_STYLE=long."""
    v = float(mbps or 0)
    if _RATE_STYLE == "long":
        if v >= 1000:
            return f"{v / 1000:.1f} Gb/s"
        if v >= 100:
            return f"{v:.0f} Mb/s"
        if v >= 1:
            return f"{v:.1f} Mb/s"
        return f"{v * 1000:.0f} Kb/s"
    return _rate_short(v)


def _rate_short(mbps: float) -> str:
    """Compact rate (K/M/G) — used on tight layouts unless long style forced."""
    v = float(mbps or 0)
    if _RATE_STYLE == "long":
        # Still compact-ish but with unit suffix truncated for 64px
        if v >= 1000:
            return f"{v / 1000:.1f}G"
        if v >= 100:
            return f"{v:.0f}M"
        if v >= 1:
            return f"{v:.1f}M"
        return f"{v * 1000:.0f}K"
    if v >= 1000:
        return f"{v / 1000:.1f}G"
    if v >= 100:
        return f"{v:.0f}M"
    if v >= 1:
        return f"{v:.1f}M"
    if v >= 0.001:
        return f"{v * 1000:.0f}K"
    return "0K"


def _scroll(text: str, max_chars: int) -> str:
    return pf.scroll_slice(text, max_chars, enabled=_TEXT_SCROLL)


def _temp_avg(m: dict[str, Any]) -> int:
    vals = [int(m.get(k, 0) or 0) for k in ("temp_cpu", "temp_2g", "temp_5g")]
    vals = [v for v in vals if v > 0]
    if not vals:
        return 0
    return int(round(sum(vals) / len(vals)))


def _temp_hot(label: str, val: int) -> bool:
    if label == "CPU":
        return val >= 85
    if label in ("2G", "5G", "AVG"):
        return val >= 65
    return False


def _gauge_color(pct: float, *, kind: str = "load") -> tuple[int, int, int]:
    """Threshold colors for gauges (always polychrome)."""
    p = float(pct or 0)
    if kind == "temp":
        if p >= 85:
            return RED
        if p >= 65:
            return YELLOW
        return CYAN
    if p >= 90:
        return RED
    if p >= 70:
        return ORANGE
    if kind == "ram":
        return ORANGE
    return CYAN


def _header(img, draw: ImageDraw.ImageDraw, title: str, idx: int) -> None:
    screens = get_screen_ids()
    n = len(screens)
    draw.rectangle([0, 0, 63, 9], fill=HEADER)
    # More title room when few/no page dots
    if n <= 1:
        title_chars = 10
    elif n >= 6:
        title_chars = 5
    else:
        title_chars = 6
    shown = _scroll(title, title_chars)
    _txt(img, 1, 1, shown, HEADER_FG, size="normal")
    if _COLOR_MODE == "mono":
        draw.rectangle([0, 0, 63, 9], fill=HEADER)
        pf.draw_text(img, 1, 1, shown, HEADER_FG, size="normal")
    # Page dots only when 2+ screens are in rotation
    if n <= 1:
        return
    dot0 = 64 - n * 4 - 1
    for i in range(n):
        x = dot0 + i * 4
        if i == idx:
            draw.rectangle([x, 3, x + 2, 6], fill=HEADER_FG)
        else:
            draw.rectangle([x, 3, x + 2, 6], outline=HEADER_FG)


def _gauge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    pct: float,
    color,
    *,
    alert: bool = False,
) -> None:
    pct = max(0.0, min(100.0, float(pct)))
    draw.rectangle([x, y, x + w - 1, y + 5], outline=DIM, fill=BAR_BG)
    fill = int((w - 2) * pct / 100)
    if fill <= 0:
        return
    # Critical: blink fill between RED and empty track
    if alert and _ALERT_BLINK:
        if not _blink_on():
            return
        color = RED
    elif alert:
        color = RED
    draw.rectangle([x + 1, y + 1, x + fill, y + 4], fill=color)


def _gauge_row(
    img,
    draw: ImageDraw.ImageDraw,
    y: int,
    label: str,
    pct: float,
    color,
    *,
    label_w: int = 18,
    alert: bool = False,
) -> None:
    """Label + gauge on the same row; optional critical blink."""
    _txt(img, 2, y, label[:5], DIM if not alert else RED, size="tiny", alert=alert)
    _gauge(draw, 2 + label_w, y, 64 - 4 - label_w, pct, color, alert=alert)


def _graph(
    img,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    data: list[float],
    color,
    filled: bool = False,
) -> None:
    if not data:
        _txt(img, x + 4, y + max(0, h // 2 - 3), "NO DATA", DIM, size="tiny")
        return
    mx = max(max(data), 0.01)
    pts = []
    n = len(data)
    for i, v in enumerate(data):
        px = x + int(i * (w - 1) / max(1, n - 1))
        py = y + h - 1 - int(max(0.0, min(1.0, float(v) / mx)) * (h - 1))
        pts.append((px, py))
    if filled and len(pts) >= 2:
        poly = pts + [(pts[-1][0], y + h - 1), (pts[0][0], y + h - 1)]
        draw.polygon(poly, fill=(color[0] // 3, color[1] // 3, color[2] // 3))
    if len(pts) >= 2:
        draw.line(pts, fill=color, width=1)


def _demo_metrics() -> dict[str, Any]:
    import math
    import time

    t = time.time()
    down = 40 + 30 * abs(math.sin(t / 17))
    up = 8 + 6 * abs(math.sin(t / 23))
    hist_d = [20 + 25 * abs(math.sin((t - i) / 11)) for i in range(32)]
    hist_u = [4 + 5 * abs(math.sin((t - i) / 13)) for i in range(32)]
    return {
        "uptime_str": "12j04h",
        "cpu": int(40 + 35 * abs(math.sin(t / 11))),
        "ram": int(50 + 20 * abs(math.sin(t / 13))),
        "clients": 14,
        "clients_wifi": 10,
        "clients_wired": 4,
        "clients_2g": 6,
        "clients_5g": 4,
        "clients_ssid": [
            {"ssid": "Home", "n": 7},
            {"ssid": "IoT", "n": 3},
        ],
        "wan_online": True,
        "wan_down": round(down, 2),
        "wan_up": round(up, 2),
        "wan_history_down": hist_d,
        "wan_history_up": hist_u,
        "top_down": [["phone45", 125.0], ["living-tv", 42.0], ["idle", 0.0]],
        "top_up": [["nas-box", 18.0], ["cam-front", 7.0], ["zero", 0.0]],
        "temp_cpu": int(55 + 15 * abs(math.sin(t / 19))),
        "temp_2g": 45,
        "temp_5g": 52,
        "vpn1": {"on": True, "type": "OVPN"},
        "vpn2": {"on": False, "type": "WG"},
        "jffs": {"used": 22, "total": 100, "present": True},
        "usb": {"used": 81, "total": 100, "present": True},
        "usb2": {"present": True, "used": 40},
        "usb3": {"present": False, "used": 0},
        "lan_ports": [True, True, False, True],
        "ram_cache": {"buffers": 15, "cached": 25},
        "_demo": True,
    }


def _pick_top(rows: list | None, limit: int = 2) -> list[tuple[str, float]]:
    """Prefer non-zero rates; still show rows so the screen is never empty."""
    parsed: list[tuple[str, float]] = []
    for row in rows or []:
        try:
            name, rate = str(row[0]), float(row[1])
        except (IndexError, TypeError, ValueError):
            continue
        parsed.append((name, max(0.0, rate)))
    if not parsed:
        return []
    nonzero = [p for p in parsed if p[1] > 0]
    pool = nonzero if nonzero else parsed
    return pool[:limit]


def _active_vpns(m: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key, fallback in (("vpn1", "VPN1"), ("vpn2", "VPN2")):
        v = m.get(key) or {}
        if v.get("on"):
            out.append((fallback, str(v.get("type", "?"))[:4]))
    return out


def render_screen(m: dict[str, Any], idx: int) -> Image.Image:
    screens = get_screen_ids()
    if not screens:
        screens = ALL_SCREEN_IDS
    idx = idx % len(screens)
    sid = screens[idx]
    img = Image.new("RGB", (64, 64), BG)
    d = ImageDraw.Draw(img)
    title = SCREEN_TITLES.get(sid, sid)
    _header(img, d, title, idx)

    if sid == "SYS":
        _txt(img, 2, 11, str(m.get("uptime_str", "--"))[:10], FG, size="tiny")
        online = bool(m.get("wan_online"))
        if online or not _ALERT_BLINK or _blink_on():
            d.ellipse([56, 12, 61, 17], fill=GREEN if online else RED)
        cpu = float(m.get("cpu", 0) or 0)
        ram = float(m.get("ram", 0) or 0)
        avg = _temp_avg(m)
        _gauge_row(img, d, 20, "CPU", cpu, _gauge_color(cpu), alert=_is_crit_load(cpu))
        _gauge_row(
            img, d, 30, "RAM", ram, _gauge_color(ram, kind="ram"), alert=_is_crit_load(ram)
        )
        _gauge_row(
            img,
            d,
            40,
            "TMP",
            avg,
            _gauge_color(avg, kind="temp"),
            alert=_is_crit_temp("TMP", avg),
        )
        _txt(img, 2, 52, f"D {_rate_short(m.get('wan_down', 0))}", GRAPH_DOWN, size="tiny")
        _txt(img, 34, 52, f"U {_rate_short(m.get('wan_up', 0))}", GRAPH_UP, size="tiny")

    elif sid == "GRP":
        down = list(m.get("wan_history_down") or [])
        up = list(m.get("wan_history_up") or [])
        d_label = f"D {_rate(m.get('wan_down', 0))}"
        u_label = f"U {_rate(m.get('wan_up', 0))}"
        _txt(img, 2, 11, _scroll(d_label, 15), GRAPH_DOWN, size="tiny")
        _graph(img, d, 1, 17, 62, 21, down, GRAPH_DOWN, filled=True)
        _txt(img, 2, 39, _scroll(u_label, 15), GRAPH_UP, size="tiny")
        _graph(img, d, 1, 45, 62, 18, up, GRAPH_UP, filled=False)

    elif sid == "TOP":
        # Full-width stacked Download / Upload for clarity
        _txt(img, 2, 11, _scroll("Download", 10), CYAN, size="tiny")
        y = 18
        downs = _pick_top(m.get("top_down"))
        if not downs:
            _txt(img, 2, y, "(none)", DIM, size="tiny")
            y += 8
        for name, rate in downs:
            _txt(img, 2, y, _scroll(name, 8), FG, size="tiny")
            _txt(img, 36, y, _rate_short(rate), CYAN, size="tiny")
            y += 8
        y = max(y + 2, 36)
        d.line([(2, y - 2), (61, y - 2)], fill=DIM)
        _txt(img, 2, y, _scroll("Upload", 10), ORANGE, size="tiny")
        y += 7
        ups = _pick_top(m.get("top_up"))
        if not ups:
            _txt(img, 2, y, "(none)", DIM, size="tiny")
        for name, rate in ups:
            _txt(img, 2, y, _scroll(name, 8), FG, size="tiny")
            _txt(img, 36, y, _rate_short(rate), ORANGE, size="tiny")
            y += 8

    elif sid == "TMP":
        avg = _temp_avg(m)
        cells = [
            (0, 12, "CPU", int(m.get("temp_cpu", 0) or 0), CYAN),
            (32, 12, "2G", int(m.get("temp_2g", 0) or 0), GREEN),
            (0, 38, "5G", int(m.get("temp_5g", 0) or 0), YELLOW),
            (32, 38, "AVG", avg, ORANGE),
        ]
        for x, y, label, val, color in cells:
            hot = _temp_hot(label, val) or _is_crit_temp(label, val)
            outline = RED if (hot and (not _ALERT_BLINK or _blink_on())) else DIM
            d.rectangle([x, y, x + 31, y + 24], outline=outline)
            _txt(img, x + 3, y + 2, label, DIM, size="tiny", alert=hot)
            col = RED if hot else color
            _txt(img, x + 3, y + 11, f"{val}C", col, size="normal", alert=hot)

    elif sid == "PIE":
        jffs = m.get("jffs") or {}
        usb = m.get("usb") or {}
        cache = m.get("ram_cache") or {}

        def pie(cx, cy, r, pct, color):
            pct = max(0.0, min(100.0, float(pct)))
            bbox = [cx - r, cy - r, cx + r, cy + r]
            d.ellipse(bbox, outline=DIM, fill=BAR_BG)
            if pct > 0.5:
                extent = max(3, int(round(360.0 * pct / 100.0)))
                d.pieslice(bbox, start=-90, end=-90 + extent, fill=color)

        j_used = int(jffs.get("used", 0) or 0)
        u_used = int(usb.get("used", 0) or 0) if usb.get("present") else 0
        c_used = int(cache.get("buffers", 0) or 0)
        j_alert = _is_crit_disk(j_used)
        u_alert = _is_crit_disk(u_used)
        _txt(img, 2, 11, f"JFFS {j_used}%", DIM, size="tiny", alert=j_alert)
        _txt(img, 34, 11, f"USB {u_used}%", DIM, size="tiny", alert=u_alert)
        j_col = RED if j_alert else _gauge_color(j_used)
        u_col = RED if u_alert else _gauge_color(u_used, kind="ram")
        pie(16, 30, 10, 0 if (j_alert and _ALERT_BLINK and not _blink_on()) else j_used, j_col)
        pie(48, 30, 10, 0 if (u_alert and _ALERT_BLINK and not _blink_on()) else u_used, u_col)
        _txt(img, 2, 44, f"CACHE {c_used}%", DIM, size="tiny")
        pie(40, 54, 7, c_used, CYAN)

    elif sid == "SRV":
        y = 12
        vpns = _active_vpns(m)
        if not vpns:
            _txt(img, 2, y, "VPN none", DIM, size="tiny")
            y += 9
        else:
            for name, typ in vpns:
                _txt(img, 2, y, name, GREEN, size="tiny")
                _txt(img, 28, y, typ, FG, size="tiny")
                y += 8
        y = max(y + 2, 28)
        jffs = m.get("jffs") or {}
        usb2 = m.get("usb2") or {}
        usb3 = m.get("usb3") or {}
        # Fallback to legacy usb blob
        usb = m.get("usb") or {}
        if not usb2 and not usb3 and usb:
            usb2 = {"present": bool(usb.get("present")), "used": usb.get("used", 0)}

        j_used = float(jffs.get("used", 0) or 0)
        _gauge_row(
            img, d, y, "JFFS", j_used, _gauge_color(j_used), alert=_is_crit_disk(j_used)
        )
        y += 10
        u2_on = bool(usb2.get("present"))
        u2_used = float(usb2.get("used", 0) or usb.get("used", 0) or 0)
        _txt(img, 2, y, "USB2", GREEN if u2_on else RED, size="tiny")
        if u2_on:
            _gauge(d, 22, y, 40, u2_used, ORANGE, alert=_is_crit_disk(u2_used))
        else:
            _txt(img, 28, y, "off", DIM, size="tiny")
        y += 10
        u3_on = bool(usb3.get("present"))
        u3_used = float(usb3.get("used", 0) or 0)
        _txt(img, 2, y, "USB3", GREEN if u3_on else RED, size="tiny")
        if u3_on:
            _gauge(d, 22, y, 40, u3_used, ORANGE, alert=_is_crit_disk(u3_used))
        else:
            _txt(img, 28, y, "off", DIM, size="tiny")

    elif sid == "NET":
        # LAN ports + Wi‑Fi + USB presence
        ports = list(m.get("lan_ports") or [False, False, False, False])
        while len(ports) < 4:
            ports.append(False)
        ports = ports[:4]
        _txt(img, 2, 12, "LAN", DIM, size="tiny")
        x = 20
        for i, up in enumerate(ports, start=1):
            _txt(img, x, 12, str(i), GREEN if up else RED, size="normal")
            x += 10
        wifi = int(m.get("clients_wifi", 0) or 0)
        clients = int(m.get("clients", 0) or 0)
        _txt(img, 2, 28, f"WiFi {wifi}", CYAN, size="tiny")
        _txt(img, 34, 28, f"All {clients}", FG, size="tiny")
        usb2 = m.get("usb2") or {}
        usb3 = m.get("usb3") or {}
        u2 = bool(usb2.get("present"))
        u3 = bool(usb3.get("present"))
        _txt(img, 2, 40, "USB2", GREEN if u2 else RED, size="normal")
        _txt(img, 34, 40, "USB3", GREEN if u3 else RED, size="normal")
        online = bool(m.get("wan_online"))
        _txt(img, 2, 54, "WAN", DIM, size="tiny", alert=not online)
        if online or not _ALERT_BLINK or _blink_on():
            d.ellipse([22, 54, 28, 60], fill=GREEN if online else RED)

    elif sid == "CLI":
        # Active clients: totals + band + top SSIDs
        total = int(m.get("clients", 0) or 0)
        wifi = int(m.get("clients_wifi", 0) or 0)
        wired = int(m.get("clients_wired", 0) or max(0, total - wifi))
        n2 = int(m.get("clients_2g", 0) or 0)
        n5 = int(m.get("clients_5g", 0) or 0)
        _txt(img, 2, 11, f"All {total}", FG, size="tiny")
        _txt(img, 2, 19, f"WiFi {wifi}", CYAN, size="tiny")
        _txt(img, 34, 19, f"LAN {wired}", ORANGE, size="tiny")
        _txt(img, 2, 28, f"2G {n2}", GREEN, size="tiny")
        _txt(img, 34, 28, f"5G {n5}", YELLOW, size="tiny")
        d.line([(2, 36), (61, 36)], fill=DIM)
        y = 39
        ssids = list(m.get("clients_ssid") or [])
        if not ssids:
            _txt(img, 2, y, "no SSID", DIM, size="tiny")
        for row in ssids[:3]:
            try:
                name = str(row.get("ssid", "?"))
                n = int(row.get("n", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            _txt(img, 2, y, _scroll(name, 8), FG, size="tiny")
            _txt(img, 50, y, str(n), CYAN, size="tiny")
            y += 8

    else:
        _txt(img, 2, 20, sid[:8], DIM, size="tiny")

    if m.get("_demo") or m.get("_offline"):
        tag = "DEMO" if m.get("_demo") else "OFF"
        _txt(img, 40, 57, tag, YELLOW, size="tiny", alert=bool(m.get("_offline")))

    return img


def render_boot_banner(msg: str = "PIXOO OK") -> Image.Image:
    img = Image.new("RGB", (64, 64), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 63, 9], fill=HEADER)
    pf.draw_text(img, 4, 1, "PIXOO", HEADER_FG, size="normal")
    _txt(img, 6, 22, msg[:10], ORANGE, size="normal")
    _txt(img, 4, 36, "Merlin bridge", FG, size="tiny")
    for y in range(48, 64):
        for x in range(48, 64):
            if (x + y) & 1:
                img.putpixel((x, y), (255, 255, 255))
    return img
