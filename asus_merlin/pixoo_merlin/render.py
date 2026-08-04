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

# Vertical rhythm (64px canvas)
PAD_X = 2
ROW_TITLE = 9
ROW_TEXT = 10
# Same-row gauges: "CPU 25%" + bar — regular gap, no vertical crush
GAUGE_ROW = 11
GAUGE_BAR_H = 5


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
    label: str,
    pct: float,
    color: Color,
    anim: float,
    font: ImageFont.ImageFont,
) -> int:
    """Label left, bar right on one row — fixed rhythm, text never overlaps bar."""
    label_color: Color = color if "Temp" in label else FG
    draw.text((PAD_X, y), label, fill=label_color, font=font)
    lw, _ = _text_size(draw, label, font)
    gap = 3
    bar_x = min(40, PAD_X + lw + gap)
    bar_w = max(12, 64 - PAD_X - bar_x)
    bar_y = y + 2
    _draw_bar(draw, bar_x, bar_y, bar_w, GAUGE_BAR_H, pct, color, anim)
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

    def series(vals: Sequence[float], color: Color) -> None:
        n = len(vals)
        pts: list[tuple[int, int]] = []
        scroll = int(anim * 2) % max(1, n // 20 + 1)
        for i, v in enumerate(vals):
            px = x + 1 + int((i / max(1, n - 1)) * (w - 2))
            px = min(x + w - 2, px + (1 if (i + scroll) % 7 == 0 else 0))
            py = y + h - 2 - int((v / peak) * (h - 4))
            py = max(y + 1, min(y + h - 2, py))
            pts.append((px, py))
        if len(pts) >= 2:
            draw.line(pts, fill=color, width=1)
        if pts:
            tx, ty = pts[-1]
            draw.point((tx, ty), fill=FG)

    series(downs, GRAPH_DOWN)
    series(ups, GRAPH_UP)


class FrameRenderer:
    """Renders one screen of a setup for a given animation phase."""

    def __init__(self, setup: Setup) -> None:
        self.setup = setup
        self.font = _font()
        self.font_sm = _font_sm()

    def render(self, screen: ScreenDef, snap: Snapshot, anim: float) -> Image.Image:
        img = Image.new("RGB", (64, 64), BG)
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
            text = f"=> {snap.clients} clients <="
            x = _center_x(draw, text, self.font_sm)
            draw.text((x, y), text, fill=FG, font=self.font_sm)
            return y + ROW_TEXT

        if wid == "wan_rate":
            # Space-separated D / U (no slash / tiret)
            d = _short_rate(snap.wan_down_kbps)
            u = _short_rate(snap.wan_up_kbps)
            text = f"D {d}  U {u}"
            x = _center_x(draw, text, self.font_sm)
            draw.text((x, y), text, fill=ORANGE, font=self.font_sm)
            return y + ROW_TEXT

        if wid == "cpu":
            return _draw_gauge(
                draw, y, f"CPU {snap.cpu_pct:.0f}%", snap.cpu_pct, _bar_color(snap.cpu_pct), anim, self.font_sm
            )

        if wid == "temp":
            t = snap.temp_c
            col = RED if t >= 80 else (YELLOW if t >= 65 else CYAN)
            return _draw_gauge(draw, y, f"Temp {t:.0f}C", min(100.0, t), col, anim + 0.2, self.font_sm)

        if wid == "ram":
            return _draw_gauge(
                draw,
                y,
                f"RAM {snap.ram_pct:.0f}%",
                snap.ram_pct,
                _bar_color(snap.ram_pct),
                anim + 0.4,
                self.font_sm,
            )

        if wid == "wan_graph":
            # Header = live D / U values (no "Asus Merlin", no slash)
            d = _short_rate(snap.wan_down_kbps)
            u = _short_rate(snap.wan_up_kbps)
            left = f"D {d}"
            right = f"U {u}"
            draw.text((PAD_X, y), left, fill=GRAPH_DOWN, font=self.font_sm)
            rw, _ = _text_size(draw, right, self.font_sm)
            draw.text((64 - PAD_X - rw, y), right, fill=GRAPH_UP, font=self.font_sm)
            graph_y = y + ROW_TITLE + 1
            graph_h = max(20, 62 - graph_y)
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
            # Physical LAN ports with link (not capped) — prefer "clients" for total hosts
            n = max(0, int(snap.eth_linked))
            text = f"ETH {n}"
            x = _center_x(draw, text, self.font_sm)
            draw.text((x, y), text, fill=FG, font=self.font_sm)
            return y + ROW_TEXT

        if wid == "wan_ip":
            ip = (snap.wan_ip or "-").strip()
            if len(ip) > 15:
                ip = ip[:15]
            x = _center_x(draw, ip, self.font_sm)
            draw.text((x, y), ip, fill=CYAN, font=self.font_sm)
            return y + ROW_TEXT

        if wid == "uptime":
            up = format_uptime(snap.uptime_s)
            draw.text((PAD_X, y), f"up {up}", fill=DIM, font=self.font_sm)
            return y + ROW_TEXT

        return y


def render_screen(setup: Setup, screen: ScreenDef, snap: Snapshot, anim: float = 0.0) -> Image.Image:
    return FrameRenderer(setup).render(screen, snap, anim)
