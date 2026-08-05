"""64×64 RGB screens from pico_monitor /metrics.json (Merlin exporter).

Pixel fonts (no antialias). Default color mode is mono for LED clarity;
set PIXOO_COLOR_MODE=poly for the polychromatic palette.
"""

from __future__ import annotations

from typing import Any, Sequence

from PIL import Image, ImageDraw

from pixoo_bridge import pixel_font as pf

# --- polychromatic palette ---
_POLY = {
    "BG": (6, 8, 14),
    "FG": (230, 235, 245),
    "DIM": (90, 100, 120),
    "CYAN": (40, 210, 230),
    "ORANGE": (255, 140, 50),
    "GREEN": (40, 220, 110),
    "YELLOW": (240, 200, 50),
    "RED": (255, 70, 70),
    "BAR_BG": (22, 26, 38),
    "GRAPH_DOWN": (40, 190, 255),
    "GRAPH_UP": (255, 130, 60),
    "HEADER": (40, 210, 230),
    "HEADER_FG": (6, 8, 14),
}

# --- monochromatic palette (sharp on LED matrix) ---
_MONO = {
    "BG": (0, 0, 0),
    "FG": (255, 255, 255),
    "DIM": (140, 140, 140),
    "CYAN": (220, 220, 220),
    "ORANGE": (200, 200, 200),
    "GREEN": (230, 230, 230),
    "YELLOW": (180, 180, 180),
    "RED": (255, 255, 255),
    "BAR_BG": (32, 32, 32),
    "GRAPH_DOWN": (255, 255, 255),
    "GRAPH_UP": (180, 180, 180),
    "HEADER": (255, 255, 255),
    "HEADER_FG": (0, 0, 0),
}

SCREEN_IDS = ("SYS", "GRP", "TOP", "TMP", "PIE", "SRV")
SCREEN_TITLES = {
    "SYS": "System",
    "GRP": "Traffic",
    "TOP": "Top",
    "TMP": "Temps",
    "PIE": "Disk Space",
    "SRV": "Services",
}

_COLOR_MODE = "mono"
_TEXT_SCROLL = True


def set_render_options(*, color_mode: str | None = None, text_scroll: bool | None = None) -> None:
    global _COLOR_MODE, _TEXT_SCROLL
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


def _pal() -> dict[str, tuple[int, int, int]]:
    return _MONO if _COLOR_MODE == "mono" else _POLY


def _c(name: str) -> tuple[int, int, int]:
    return _pal()[name]


def _txt(img, x: int, y: int, text: str, color: Sequence[int], *, size: str = "normal") -> int:
    return pf.draw_text(img, x, y, text, color, size=size)


def _rate(mbps: float) -> str:
    """Format Mbps as Kb/s, Mb/s or Gb/s."""
    v = float(mbps or 0)
    if v >= 1000:
        return f"{v / 1000:.1f} Gb/s"
    if v >= 100:
        return f"{v:.0f} Mb/s"
    if v >= 1:
        return f"{v:.1f} Mb/s"
    return f"{v * 1000:.0f} Kb/s"


def _rate_short(mbps: float) -> str:
    """Compact rate for tight layouts (still with unit letter)."""
    v = float(mbps or 0)
    if v >= 1000:
        return f"{v / 1000:.1f}G"
    if v >= 100:
        return f"{v:.0f}M"
    if v >= 1:
        return f"{v:.1f}M"
    return f"{v * 1000:.0f}K"


def _scroll(text: str, max_chars: int) -> str:
    return pf.scroll_slice(text, max_chars, enabled=_TEXT_SCROLL)


def _header(img, draw: ImageDraw.ImageDraw, title: str, idx: int) -> None:
    draw.rectangle([0, 0, 63, 9], fill=_c("HEADER"))
    # Title zone ~x=1..36 (6 chars at 6px); dots on the right
    shown = _scroll(title, 6)
    _txt(img, 1, 1, shown, _c("HEADER_FG"), size="normal")
    for i in range(6):
        x = 40 + i * 4
        if i == idx:
            draw.rectangle([x, 3, x + 2, 6], fill=_c("HEADER_FG"))
        else:
            draw.rectangle([x, 3, x + 2, 6], outline=_c("HEADER_FG"))


def _gauge(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, pct: float, color) -> None:
    pct = max(0.0, min(100.0, float(pct)))
    draw.rectangle([x, y, x + w - 1, y + 5], outline=_c("DIM"), fill=_c("BAR_BG"))
    fill = int((w - 2) * pct / 100)
    if fill > 0:
        draw.rectangle([x + 1, y + 1, x + fill, y + 4], fill=color)


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
        _txt(img, x + 4, y + max(0, h // 2 - 3), "NO DATA", _c("DIM"), size="tiny")
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
        "wan_online": True,
        "wan_down": round(down, 2),
        "wan_up": round(up, 2),
        "wan_history_down": hist_d,
        "wan_history_up": hist_u,
        "top_down": [["phone45", 125.0], ["tv.12", 42.0], ["idle", 0.0]],
        "top_up": [["nas.22", 18.0], ["cam.33", 7.0], ["zero", 0.0]],
        "temp_cpu": int(55 + 15 * abs(math.sin(t / 19))),
        "temp_2g": 45,
        "temp_5g": 52,
        "vpn1": {"on": True, "type": "OVPN"},
        "vpn2": {"on": False, "type": "WG"},
        "jffs": {"used": 22, "total": 100, "present": True},
        "usb": {"used": 81, "total": 100, "present": True},
        "ram_cache": {"buffers": 15, "cached": 25},
        "_demo": True,
    }


def _filter_top(rows: list | None, limit: int = 2) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for row in rows or []:
        try:
            name, rate = str(row[0]), float(row[1])
        except (IndexError, TypeError, ValueError):
            continue
        if rate <= 0.05:
            continue
        out.append((name, rate))
        if len(out) >= limit:
            break
    return out


def render_screen(m: dict[str, Any], idx: int) -> Image.Image:
    idx = idx % len(SCREEN_IDS)
    sid = SCREEN_IDS[idx]
    img = Image.new("RGB", (64, 64), _c("BG"))
    d = ImageDraw.Draw(img)
    title = SCREEN_TITLES.get(sid, sid)
    _header(img, d, title, idx)

    if sid == "SYS":
        # uptime + WAN status
        _txt(img, 2, 12, str(m.get("uptime_str", "--"))[:10], _c("FG"), size="tiny")
        online = bool(m.get("wan_online"))
        d.ellipse([56, 13, 61, 18], fill=_c("GREEN") if online else _c("RED"))
        # labels without numeric (gauge shows level); gap between blocks
        _txt(img, 2, 20, "CPU", _c("DIM"), size="tiny")
        _gauge(d, 2, 28, 60, m.get("cpu", 0), _c("CYAN"))
        _txt(img, 2, 37, "RAM", _c("DIM"), size="tiny")
        _gauge(d, 2, 45, 60, m.get("ram", 0), _c("ORANGE"))
        down_s = _rate_short(m.get("wan_down", 0))
        up_s = _rate_short(m.get("wan_up", 0))
        _txt(img, 2, 55, f"D {down_s}", _c("FG"), size="tiny")
        _txt(img, 34, 55, f"U {up_s}", _c("FG"), size="tiny")

    elif sid == "GRP":
        # Compact labels; two tall graphs (~h=21) with 2px gaps
        down = list(m.get("wan_history_down") or [])
        up = list(m.get("wan_history_up") or [])
        d_label = f"D {_rate(m.get('wan_down', 0))}"
        u_label = f"U {_rate(m.get('wan_up', 0))}"
        _txt(img, 2, 11, _scroll(d_label, 15), _c("GRAPH_DOWN"), size="tiny")
        _graph(img, d, 1, 17, 62, 21, down, _c("GRAPH_DOWN"), filled=True)
        _txt(img, 2, 39, _scroll(u_label, 15), _c("GRAPH_UP"), size="tiny")
        _graph(img, d, 1, 45, 62, 18, up, _c("GRAPH_UP"), filled=False)

    elif sid == "TOP":
        d.line([(32, 10), (32, 63)], fill=_c("DIM"))
        _txt(img, 4, 11, "DL", _c("CYAN"), size="tiny")
        _txt(img, 36, 11, "UL", _c("ORANGE"), size="tiny")
        y = 20
        for name, rate in _filter_top(m.get("top_down")):
            shown = _scroll(name, 4)
            _txt(img, 2, y, shown, _c("FG"), size="normal")
            _txt(img, 2, y + 9, _rate_short(rate), _c("DIM"), size="tiny")
            y += 20
        y = 20
        for name, rate in _filter_top(m.get("top_up")):
            shown = _scroll(name, 4)
            _txt(img, 34, y, shown, _c("FG"), size="normal")
            _txt(img, 34, y + 9, _rate_short(rate), _c("DIM"), size="tiny")
            y += 20

    elif sid == "TMP":
        cells = [
            (0, 12, "CPU", int(m.get("temp_cpu", 0)), _c("CYAN")),
            (32, 12, "2G", int(m.get("temp_2g", 0)), _c("GREEN")),
            (0, 38, "5G", int(m.get("temp_5g", 0)), _c("YELLOW")),
            (32, 38, "OK", None, _c("GREEN")),
        ]
        for x, y, label, val, color in cells:
            d.rectangle([x, y, x + 31, y + 24], outline=_c("DIM"))
            _txt(img, x + 3, y + 2, label, _c("DIM"), size="tiny")
            if val is not None:
                hot = (label == "CPU" and val >= 85) or (label in ("2G", "5G") and val >= 65)
                # Temps keep numeric value + °C unit
                _txt(
                    img,
                    x + 3,
                    y + 11,
                    f"{val}°C",
                    _c("RED") if hot else color,
                    size="normal",
                )

    elif sid == "PIE":
        jffs = m.get("jffs") or {}
        usb = m.get("usb") or {}
        cache = m.get("ram_cache") or {}

        def pie(cx, cy, r, pct, color):
            pct = max(0.0, min(100.0, float(pct)))
            bbox = [cx - r, cy - r, cx + r, cy + r]
            d.ellipse(bbox, outline=_c("DIM"), fill=_c("BAR_BG"))
            if pct > 0.5:
                extent = max(3, int(round(360.0 * pct / 100.0)))
                d.pieslice(bbox, start=-90, end=-90 + extent, fill=color)

        j_used = int(jffs.get("used", 0) or 0)
        u_used = int(usb.get("used", 0) or 0) if usb.get("present") else 0
        c_used = int(cache.get("buffers", 0) or 0)
        _txt(img, 2, 11, f"JFFS {j_used}%", _c("DIM"), size="tiny")
        _txt(img, 34, 11, f"USB {u_used}%", _c("DIM"), size="tiny")
        pie(16, 30, 10, j_used, _c("GREEN"))
        pie(48, 30, 10, u_used, _c("ORANGE"))
        _txt(img, 2, 44, f"CACHE {c_used}%", _c("DIM"), size="tiny")
        pie(40, 54, 7, c_used, _c("CYAN"))

    else:  # SRV
        v1 = m.get("vpn1") or {}
        v2 = m.get("vpn2") or {}
        _txt(img, 2, 12, "VPN1", _c("DIM"), size="tiny")
        _txt(
            img,
            28,
            12,
            "ON" if v1.get("on") else "OFF",
            _c("GREEN") if v1.get("on") else _c("RED"),
            size="tiny",
        )
        _txt(img, 46, 12, str(v1.get("type", "?"))[:4], _c("FG"), size="tiny")
        _txt(img, 2, 22, "VPN2", _c("DIM"), size="tiny")
        _txt(
            img,
            28,
            22,
            "ON" if v2.get("on") else "OFF",
            _c("GREEN") if v2.get("on") else _c("RED"),
            size="tiny",
        )
        _txt(img, 46, 22, str(v2.get("type", "?"))[:4], _c("FG"), size="tiny")
        jffs = m.get("jffs") or {}
        usb = m.get("usb") or {}
        # gauges without duplicate % value
        _txt(img, 2, 34, "JFFS", _c("DIM"), size="tiny")
        _gauge(d, 2, 42, 60, jffs.get("used", 0), _c("GREEN"))
        _txt(img, 2, 50, "USB", _c("DIM"), size="tiny")
        if usb.get("present"):
            _gauge(d, 2, 58, 60, usb.get("used", 0), _c("ORANGE"))
        else:
            _txt(img, 28, 50, "N/A", _c("DIM"), size="tiny")

    if m.get("_demo") or m.get("_offline"):
        tag = "DEMO" if m.get("_demo") else "OFF"
        _txt(img, 40, 57, tag, _c("YELLOW"), size="tiny")

    return img


def render_boot_banner(msg: str = "PIXOO OK") -> Image.Image:
    img = Image.new("RGB", (64, 64), _c("BG"))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 63, 9], fill=_c("HEADER"))
    _txt(img, 4, 1, "PIXOO", _c("HEADER_FG"), size="normal")
    _txt(img, 6, 22, msg[:10], _c("ORANGE"), size="normal")
    _txt(img, 4, 36, "Merlin bridge", _c("FG"), size="tiny")
    for y in range(48, 64):
        for x in range(48, 64):
            if (x + y) & 1:
                img.putpixel((x, y), (255, 255, 255))
    return img
