"""64×64 Pixoo render — widgets + light animations for Merlin setups."""

from __future__ import annotations

import math
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from .metrics import Snapshot, format_uptime
from .setups import ScreenDef, Setup

Color = tuple[int, int, int]

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
PIE_FREE = (40, 40, 55)
PIE_USED = (40, 200, 120)
# Upload is usually << download on a shared Y scale — boost visual amplitude
UP_GRAPH_ZOOM = 5.0

# Vertical rhythm (64px canvas)
PAD_X = 2
ROW_TITLE = 9
ROW_TEXT = 10
# Same-row gauges — fixed label column so RAM/CPU/Temp bars share left/right edges
GAUGE_ROW = 11
GAUGE_BAR_H = 6
GAUGE_BAR_ONLY_H = 8
GAUGE_LABEL_COL = 24  # px reserved for label; RAM/CPU/Temp bars share edges


def _draw_pie(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    pct: float,
    color: Color,
) -> None:
    """Used/free pie — pct = % used."""
    pct = max(0.0, min(100.0, pct))
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(bbox, outline=DIM, fill=PIE_FREE)
    if pct >= 99.5:
        draw.ellipse(bbox, fill=color, outline=DIM)
    elif pct > 0.5:
        extent = max(3, int(round(360.0 * pct / 100.0)))
        draw.pieslice(bbox, start=-90, end=-90 + extent, fill=color, outline=color)
    draw.ellipse(bbox, outline=DIM)


def _font() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for path in (
        "/opt/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(path, 10)
        except OSError:
            continue
    return ImageFont.load_default()


def _font_sm() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for path in (
        "/opt/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, 8)
        except OSError:
            continue
    return ImageFont.load_default()


def _bar_color(pct: float) -> Color:
    if pct >= 90:
        return RED
    if pct >= 70:
        return YELLOW
    return GREEN


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _center_x(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, canvas: int = 64) -> int:
    w, _ = _text_size(draw, text, font)
    return max(0, (canvas - w) // 2)


def _short_rate(v: float) -> str:
    if v >= 1000:
        return f"{v / 1000:.1f}M" if v < 10000 else f"{v / 1000:.0f}M"
    return f"{v:.0f}k"


def _short_rate_int(v: float) -> str:
    """Integer-only rate for stats (no decimal point/comma)."""
    if v >= 1000:
        return f"{int(round(v / 1000))}M"
    return f"{int(round(v))}k"


def _draw_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    color: Color,
    anim: float,
) -> None:
    pct = max(0.0, min(100.0, pct))
    sweep = 0.55 + 0.45 * min(1.0, (anim % 1.0) / 0.35) if anim < 1.0 else 1.0
    pulse = 0.92 + 0.08 * abs(math.sin(anim * math.pi * 2))
    draw.rectangle([x, y, x + w, y + h], outline=DIM, fill=BAR_BG)
    fill_w = int(w * (pct / 100.0) * sweep * pulse)
    if fill_w > 0:
        draw.rectangle([x, y, x + max(1, fill_w), y + h], fill=color)


def _draw_gauge(
    draw: ImageDraw.ImageDraw,
    y: int,
    pct: float,
    color: Color,
    anim: float,
    *,
    label: str = "",
    font: ImageFont.ImageFont | None = None,
    label_color: Color | None = None,
) -> int:
    """Bar with optional label; bars share a fixed left/right alignment."""
    if label and font is not None:
        lc = label_color if label_color is not None else FG
        draw.text((PAD_X, y), label, fill=lc, font=font)
        bar_x = PAD_X + GAUGE_LABEL_COL
        bar_h = GAUGE_BAR_H
        bar_y = y + 2
    else:
        bar_x = PAD_X
        bar_h = GAUGE_BAR_ONLY_H
        bar_y = y + 1
    bar_w = max(12, 64 - PAD_X - bar_x)
    _draw_bar(draw, bar_x, bar_y, bar_w, bar_h, pct, color, anim)
    return y + GAUGE_ROW


def _draw_graph(
    draw: ImageDraw.ImageDraw,
    snap: Snapshot,
    x: int,
    y: int,
    w: int,
    h: int,
    anim: float,
    font: ImageFont.ImageFont,
) -> None:
    hist = snap.history
    draw.rectangle([x, y, x + w, y + h], outline=DIM, fill=BAR_BG)
    if len(hist) < 2:
        draw.text((x + 4, y + h // 2 - 4), "sampling", fill=DIM, font=font)
        return

    downs = [s.down_kbps for s in hist]
    ups = [s.up_kbps for s in hist]
    peak = max(max(downs), max(ups), 1.0)

    def series(vals: Sequence[float], color: Color, *, y_zoom: float = 1.0) -> None:
        n = len(vals)
        pts: list[tuple[int, int]] = []
        scroll = int(anim * 2) % max(1, n // 20 + 1)
        for i, v in enumerate(vals):
            px = x + 1 + int((i / max(1, n - 1)) * (w - 2))
            px = min(x + w - 2, px + (1 if (i + scroll) % 7 == 0 else 0))
            frac = min(1.0, (v * y_zoom) / peak)
            py = y + h - 2 - int(frac * (h - 4))
            py = max(y + 1, min(y + h - 2, py))
            pts.append((px, py))
        if len(pts) >= 2:
            draw.line(pts, fill=color, width=1)
        if pts:
            tx, ty = pts[-1]
            draw.point((tx, ty), fill=FG)

    series(downs, GRAPH_DOWN, y_zoom=1.0)
    series(ups, GRAPH_UP, y_zoom=UP_GRAPH_ZOOM)


class FrameRenderer:
    """Renders one screen of a setup for a given animation phase."""

    def __init__(self, setup: Setup, *, marquee_speed: float = 72.0) -> None:
        self.setup = setup
        self.marquee_speed = marquee_speed
        self.font = _font()
        self.font_sm = _font_sm()

    def render(self, screen: ScreenDef, snap: Snapshot, anim: float) -> Image.Image:
        img = Image.new("RGB", (64, 64), BG)
        self._img = img
        draw = ImageDraw.Draw(img)
        accent = int(20 + 40 * abs(math.sin(anim * math.pi)))
        draw.line([(0, 0), (63, 0)], fill=(accent, accent + 30, 80))

        y = 2
        widgets = list(screen.widgets)
        for wid in widgets:
            y = self._draw_widget(draw, wid, snap, anim, y, widgets)
        return img

    def _draw_widget(
        self,
        draw: ImageDraw.ImageDraw,
        wid: str,
        snap: Snapshot,
        anim: float,
        y: int,
        all_widgets: list[str],
    ) -> int:
        title = self.setup.title
        if wid == "title":
            c = tuple(min(255, int(v + 20 * abs(math.sin(anim * math.pi * 2)))) for v in CYAN)
            color: Color = (int(c[0]), int(c[1]), int(c[2]))
            x = _center_x(draw, title, self.font_sm)
            draw.text((x, y), title, fill=color, font=self.font_sm)
            return y + ROW_TITLE

        if wid == "clients":
            # Wired vs Wi‑Fi — UI label « WAN » = WLAN associated
            lan_n = int(snap.clients_lan)
            wan_n = int(snap.clients_wan)
            text = f"{lan_n} LAN - {wan_n} WAN"
            x = _center_x(draw, text, self.font_sm)
            draw.text((x, y + 2), text, fill=FG, font=self.font_sm)
            return y + ROW_TEXT

        if wid == "wan_rate":
            # Space-separated D / U (no slash / tiret)
            d = _short_rate(snap.wan_down_kbps)
            u = _short_rate(snap.wan_up_kbps)
            text = f"Dwn {d}  Up {u}"
            x = _center_x(draw, text, self.font_sm)
            draw.text((x, y), text, fill=ORANGE, font=self.font_sm)
            return y + ROW_TEXT

        if wid == "cpu":
            return _draw_gauge(
                draw,
                y,
                snap.cpu_pct,
                _bar_color(snap.cpu_pct),
                anim,
                label="CPU",
                font=self.font_sm,
                label_color=FG,
            )

        if wid == "temp":
            t = snap.temp_c
            col = RED if t >= 80 else (YELLOW if t >= 65 else CYAN)
            return _draw_gauge(
                draw,
                y,
                min(100.0, t),
                col,
                anim + 0.2,
                label=f"{t:.0f}°C",
                font=self.font_sm,
                label_color=col,
            )

        if wid == "ram":
            return _draw_gauge(
                draw,
                y,
                snap.ram_pct,
                _bar_color(snap.ram_pct),
                anim + 0.4,
                label="RAM",
                font=self.font_sm,
                label_color=FG,
            )

        if wid == "wan_graph":
            # D top-left, U bottom-right; graph in the middle without overlapping text
            d = _short_rate(snap.wan_down_kbps)
            u = _short_rate(snap.wan_up_kbps)
            d_label = f"Dwn {d}"
            u_label = f"Up {u}"
            text_h = 10
            top_y = 2
            bot_y = 64 - text_h - 1
            draw.text((PAD_X, top_y), d_label, fill=GRAPH_DOWN, font=self.font_sm)
            uw, _ = _text_size(draw, u_label, self.font_sm)
            draw.text((64 - PAD_X - uw, bot_y), u_label, fill=GRAPH_UP, font=self.font_sm)

            graph_y = top_y + text_h + 1
            graph_bottom = bot_y - 2
            graph_h = max(16, graph_bottom - graph_y)
            _draw_graph(draw, snap, 1, graph_y, 62, graph_h, anim, self.font_sm)
            return 64

        if wid == "internet":
            # Text only — no check / cross icons
            label = "online" if snap.internet_ok else "offline"
            base = GREEN if snap.internet_ok else RED
            boost = 25 if abs(math.sin(anim * math.pi * 2)) > 0.85 else 0
            col: Color = (
                min(255, base[0] + boost),
                min(255, base[1] + boost),
                min(255, base[2] + boost),
            )
            x = _center_x(draw, label, self.font)
            draw.text((x, y + 2), label, fill=col, font=self.font)
            return y + 14

        if wid == "usb":
            # Same line: "USB2" "USB3" — green if present/mounted, red otherwise
            gap = 4
            x = PAD_X
            for label, ok in (("USB2", snap.usb2), ("USB3", snap.usb3)):
                col = GREEN if ok else RED
                draw.text((x, y), label, fill=col, font=self.font_sm)
                tw, _ = _text_size(draw, label, self.font_sm)
                x += tw + gap
            return y + ROW_TEXT

        if wid == "ethernet":
            # LAN1–LAN4: "LAN" (title cyan) + digits 1234 green=link / red=down
            draw.text((PAD_X, y), "LAN", fill=CYAN, font=self.font_sm)
            x = PAD_X + _text_size(draw, "LAN", self.font_sm)[0] + 2
            ports = snap.lan_ports if len(snap.lan_ports) == 4 else (False, False, False, False)
            for i, up in enumerate(ports, start=1):
                digit = str(i)
                col = GREEN if up else RED
                draw.text((x, y), digit, fill=col, font=self.font_sm)
                x += _text_size(draw, digit, self.font_sm)[0] + 1
            return y + ROW_TEXT

        if wid == "wan_ip":
            # Public WAN IP — continuous marquee right → left
            ip = (snap.wan_ip or "-").strip() or "-"
            msg = f"  WAN IP {ip}   "
            tw, _ = _text_size(draw, msg, self.font_sm)
            band = Image.new("RGB", (64, 12), BG)
            bdraw = ImageDraw.Draw(band)
            period = max(1, tw + 64)
            speed = max(8.0, self.marquee_speed)
            # Scroll right → left (text drifts left continuously)
            x = -(int(anim * speed) % period)
            while x < 64 + tw:
                bdraw.text((x, 1), msg, fill=CYAN, font=self.font_sm)
                x += tw
            img = getattr(self, "_img", None)
            if img is not None:
                img.paste(band, (0, y))
            else:
                draw.text((PAD_X, y), f"WAN IP {ip}"[:15], fill=CYAN, font=self.font_sm)
            return y + ROW_TEXT

        if wid == "top_clients":
            rows = snap.top_clients[:5]
            if not rows:
                draw.text((PAD_X, y), "no data", fill=DIM, font=self.font_sm)
                return y + ROW_TEXT
            yy = y
            for i, tc in enumerate(rows, start=1):
                name = (tc.name or "?").replace("\n", " ")[:12]
                line = f"{i}.{name}"
                draw.text((PAD_X, yy), line, fill=FG if i == 1 else DIM, font=self.font_sm)
                yy += 10
                if yy > 54:
                    break
            return min(64, yy)

        if wid == "hour_stats":
            # Header e.g. « 1h -> min-max » — color-coded min/max rows
            hs = snap.hour_stats
            win = max(1, int(hs.window_s))
            if win % 3600 == 0:
                win_s = f"{win // 3600}h"
            elif win % 60 == 0:
                win_s = f"{win // 60}m"
            else:
                win_s = f"{win}s"
            header = f"{win_s} -> min-max"
            x = _center_x(draw, header, self.font_sm)
            draw.text((x, y), header, fill=CYAN, font=self.font_sm)
            yy = y + 9

            def row(
                label: str,
                lo: float,
                hi: float,
                kind: str,
                accent: Color,
            ) -> None:
                nonlocal yy
                if kind == "rate":
                    lo_s, hi_s = _short_rate_int(lo), _short_rate_int(hi)
                elif kind == "temp":
                    lo_s, hi_s = f"{int(round(lo))}", f"{int(round(hi))}C"
                else:
                    lo_s, hi_s = f"{int(round(lo))}%", f"{int(round(hi))}%"
                draw.text((PAD_X, yy), label, fill=accent, font=self.font_sm)
                draw.text((22, yy), lo_s, fill=DIM, font=self.font_sm)
                draw.text((40, yy), hi_s[:6], fill=accent, font=self.font_sm)
                yy += 9

            t_hi = hs.temp_max
            t_col = RED if t_hi >= 80 else (YELLOW if t_hi >= 65 else CYAN)
            row("Dwn", hs.down_min, hs.down_max, "rate", GRAPH_DOWN)
            row("Up", hs.up_min, hs.up_max, "rate", GRAPH_UP)
            row("CPU", hs.cpu_min, hs.cpu_max, "pct", _bar_color(hs.cpu_max))
            row("T", hs.temp_min, hs.temp_max, "temp", t_col)
            row("RAM", hs.ram_min, hs.ram_max, "pct", _bar_color(hs.ram_max))
            return min(64, yy)

        if wid == "disk_pie":
            # Native storage pie (jffs/opt/root) — used vs free
            pct = snap.disk_pct
            color = _bar_color(pct)
            label = (snap.disk_label or "disk").upper()
            title = f"{label} {pct:.0f}%"
            x = _center_x(draw, title, self.font_sm)
            draw.text((x, y), title, fill=CYAN, font=self.font_sm)
            _draw_pie(draw, 32, 34, 18, pct, color)
            used = snap.disk_used_mb
            total = snap.disk_total_mb
            if total >= 1024:
                foot = f"{used/1024:.1f}/{total/1024:.1f}G"
            else:
                foot = f"{used:.0f}/{total:.0f}M"
            fx = _center_x(draw, foot, self.font_sm)
            draw.text((fx, 54), foot, fill=DIM, font=self.font_sm)
            return 64

        if wid == "uptime":
            up = format_uptime(snap.uptime_s)
            draw.text((PAD_X, y), f"up {up}", fill=DIM, font=self.font_sm)
            return y + ROW_TEXT

        return y


def render_screen(
    setup: Setup,
    screen: ScreenDef,
    snap: Snapshot,
    anim: float = 0.0,
    *,
    marquee_speed: float = 72.0,
) -> Image.Image:
    return FrameRenderer(setup, marquee_speed=marquee_speed).render(screen, snap, anim)
