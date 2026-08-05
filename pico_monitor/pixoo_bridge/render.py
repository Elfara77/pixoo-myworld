"""64×64 RGB screens from pico_monitor /metrics.json (Merlin exporter)."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFont

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

SCREEN_IDS = ("SYS", "GRP", "TOP", "TMP", "PIE", "SRV")


def _font(size: int = 10):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/opt/share/fonts/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rate(mbps: float) -> str:
    v = float(mbps or 0)
    if v >= 1000:
        return f"{v / 1000:.1f}G"
    if v >= 100:
        return f"{v:.0f}M"
    if v >= 1:
        return f"{v:.1f}M"
    return f"{v * 1000:.0f}K"


def _header(draw: ImageDraw.ImageDraw, title: str, idx: int, font) -> None:
    draw.rectangle([0, 0, 63, 9], fill=CYAN)
    draw.text((2, -1), title[:3], fill=BG, font=font)
    for i in range(6):
        x = 40 + i * 4
        if i == idx:
            draw.rectangle([x, 3, x + 2, 6], fill=BG)
        else:
            draw.rectangle([x, 3, x + 2, 6], outline=BG)


def _gauge(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, pct: float, color) -> None:
    pct = max(0.0, min(100.0, float(pct)))
    draw.rectangle([x, y, x + w - 1, y + 5], outline=DIM, fill=BAR_BG)
    fill = int((w - 2) * pct / 100)
    if fill > 0:
        draw.rectangle([x + 1, y + 1, x + fill, y + 4], fill=color)


def _graph(
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
        draw.text((x + 4, y + h // 2 - 4), "NO DATA", fill=DIM, font=_font(8))
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
        "top_down": [[".45", 125.0], [".12", 42.0]],
        "top_up": [[".22", 18.0], [".33", 7.0]],
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


def render_screen(m: dict[str, Any], idx: int) -> Image.Image:
    idx = idx % len(SCREEN_IDS)
    sid = SCREEN_IDS[idx]
    img = Image.new("RGB", (64, 64), BG)
    d = ImageDraw.Draw(img)
    font = _font(10)
    sm = _font(8)
    _header(d, sid, idx, sm)

    if sid == "SYS":
        d.text((2, 11), str(m.get("uptime_str", "--")), fill=FG, font=sm)
        online = bool(m.get("wan_online"))
        d.ellipse([56, 13, 61, 18], fill=GREEN if online else RED)
        d.text((2, 21), f"CPU {int(m.get('cpu', 0))}%", fill=DIM, font=sm)
        _gauge(d, 2, 30, 60, m.get("cpu", 0), CYAN)
        d.text((2, 38), f"RAM {int(m.get('ram', 0))}%", fill=DIM, font=sm)
        _gauge(d, 2, 47, 60, m.get("ram", 0), ORANGE)
        d.text(
            (2, 56),
            f"D{_rate(m.get('wan_down', 0))} U{_rate(m.get('wan_up', 0))}",
            fill=FG,
            font=sm,
        )

    elif sid == "GRP":
        down = list(m.get("wan_history_down") or [])
        up = list(m.get("wan_history_up") or [])
        d.text((2, 11), f"D {_rate(m.get('wan_down', 0))}", fill=GRAPH_DOWN, font=sm)
        _graph(d, 1, 20, 62, 16, down, GRAPH_DOWN, filled=True)
        d.text((2, 37), f"U {_rate(m.get('wan_up', 0))}", fill=GRAPH_UP, font=sm)
        _graph(d, 1, 46, 62, 16, up, GRAPH_UP, filled=False)

    elif sid == "TOP":
        d.line([(32, 10), (32, 63)], fill=DIM)
        d.text((4, 11), "DL", fill=CYAN, font=sm)
        d.text((36, 11), "UL", fill=ORANGE, font=sm)
        y = 22
        for row in (m.get("top_down") or [])[:2]:
            name, rate = str(row[0])[-3:], float(row[1])
            d.text((2, y), name, fill=FG, font=font)
            d.text((2, y + 10), _rate(rate), fill=DIM, font=sm)
            y += 22
        y = 22
        for row in (m.get("top_up") or [])[:2]:
            name, rate = str(row[0])[-3:], float(row[1])
            d.text((34, y), name, fill=FG, font=font)
            d.text((34, y + 10), _rate(rate), fill=DIM, font=sm)
            y += 22

    elif sid == "TMP":
        cells = [
            (0, 12, "CPU", int(m.get("temp_cpu", 0)), CYAN),
            (32, 12, "2G", int(m.get("temp_2g", 0)), GREEN),
            (0, 38, "5G", int(m.get("temp_5g", 0)), YELLOW),
            (32, 38, "OK", "", GREEN),
        ]
        for x, y, label, val, color in cells:
            d.rectangle([x, y, x + 31, y + 24], outline=DIM)
            d.text((x + 3, y + 2), label, fill=DIM, font=sm)
            if val != "":
                hot = (label == "CPU" and val >= 85) or (label in ("2G", "5G") and val >= 65)
                d.text((x + 6, y + 10), f"{val}", fill=RED if hot else color, font=font)

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

        d.text((6, 11), "JFFS", fill=DIM, font=sm)
        d.text((38, 11), "USB", fill=DIM, font=sm)
        pie(16, 30, 10, jffs.get("used", 0), GREEN)
        pie(48, 30, 10, usb.get("used", 0) if usb.get("present") else 0, ORANGE)
        d.text((2, 46), "CACHE", fill=DIM, font=sm)
        pie(32, 56, 7, cache.get("buffers", 0), CYAN)

    else:  # SRV
        v1 = m.get("vpn1") or {}
        v2 = m.get("vpn2") or {}
        d.text((2, 14), "VPN1", fill=DIM, font=sm)
        d.text((30, 14), "ON" if v1.get("on") else "OFF", fill=GREEN if v1.get("on") else RED, font=sm)
        d.text((48, 14), str(v1.get("type", "?"))[:4], fill=FG, font=sm)
        d.text((2, 26), "VPN2", fill=DIM, font=sm)
        d.text((30, 26), "ON" if v2.get("on") else "OFF", fill=GREEN if v2.get("on") else RED, font=sm)
        d.text((48, 26), str(v2.get("type", "?"))[:4], fill=FG, font=sm)
        jffs = m.get("jffs") or {}
        usb = m.get("usb") or {}
        d.text((2, 40), "JFFS", fill=DIM, font=sm)
        _gauge(d, 28, 42, 34, jffs.get("used", 0), GREEN)
        d.text((2, 52), "USB", fill=DIM, font=sm)
        if usb.get("present"):
            _gauge(d, 28, 54, 34, usb.get("used", 0), ORANGE)
        else:
            d.text((30, 52), "N/A", fill=DIM, font=sm)

    if m.get("_demo") or m.get("_offline"):
        tag = "DEMO" if m.get("_demo") else "OFF"
        d.text((40, 56), tag, fill=YELLOW, font=sm)

    return img


def render_boot_banner(msg: str = "PIXOO OK") -> Image.Image:
    img = Image.new("RGB", (64, 64), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 63, 9], fill=CYAN)
    d.text((4, -1), "PIXOO", fill=BG, font=_font(8))
    d.text((6, 24), msg[:10], fill=ORANGE, font=_font(10))
    d.text((4, 40), "Merlin bridge", fill=FG, font=_font(8))
    for y in range(48, 64):
        for x in range(48, 64):
            if (x + y) & 1:
                img.putpixel((x, y), (255, 255, 255))
    return img
