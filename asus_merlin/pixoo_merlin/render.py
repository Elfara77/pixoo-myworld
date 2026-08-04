"""64×64 Pixoo render — widgets + light animations for Merlin setups."""

from __future__ import annotations

import math
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from .metrics import Snapshot, format_rate_pair, format_uptime  # noqa: F401 — format_uptime used below
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
    # Sweep-in animation on first part of cycle
    sweep = 0.55 + 0.45 * min(1.0, (anim % 1.0) / 0.35) if anim < 1.0 else 1.0
    # Soft pulse on fill
    pulse = 0.92 + 0.08 * abs(math.sin(anim * math.pi * 2))
    draw.rectangle([x, y, x + w, y + h], outline=DIM, fill=BAR_BG)
    fill_w = int(w * (pct / 100.0) * sweep * pulse)
    if fill_w > 0:
        draw.rectangle([x, y, x + max(1, fill_w), y + h], fill=color)


def _draw_check(draw: ImageDraw.ImageDraw, cx: int, cy: int, ok: bool, anim: float) -> None:
    r = 8 + int(1.5 * abs(math.sin(anim * math.pi * 2)))
    color = GREEN if ok else RED
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, fill=(12, 16, 22))
    if ok:
        # check mark
        draw.line([(cx - 4, cy), (cx - 1, cy + 4), (cx + 5, cy - 4)], fill=color, width=2)
    else:
        draw.line([(cx - 4, cy - 4), (cx + 4, cy + 4)], fill=color, width=2)
        draw.line([(cx + 4, cy - 4), (cx - 4, cy + 4)], fill=color, width=2)


def _draw_graph(
    draw: ImageDraw.ImageDraw,
    snap: Snapshot,
    x: int,
    y: int,
    w: int,
    h: int,
    anim: float,
) -> None:
    hist = snap.history
    draw.rectangle([x, y, x + w, y + h], outline=DIM, fill=BAR_BG)
    if len(hist) < 2:
        font = _font_sm()
        draw.text((x + 4, y + h // 2 - 4), "sampling…", fill=DIM, font=font)
        return

    downs = [s.down_kbps for s in hist]
    ups = [s.up_kbps for s in hist]
    peak = max(max(downs), max(ups), 1.0)

    def series(vals: Sequence[float], color: Color, phase: float) -> None:
        n = len(vals)
        pts: list[tuple[int, int]] = []
        scroll = int(anim * 2) % max(1, n // 20 + 1)
        for i, v in enumerate(vals):
            px = x + 1 + int((i / max(1, n - 1)) * (w - 2))
            # slight horizontal shimmer
            px = min(x + w - 2, px + (1 if (i + scroll) % 7 == 0 else 0))
            py = y + h - 2 - int((v / peak) * (h - 4))
            py = max(y + 1, min(y + h - 2, py))
            pts.append((px, py))
        if len(pts) >= 2:
            draw.line(pts, fill=color, width=1)
        # tip glow
        if pts:
            tx, ty = pts[-1]
            draw.point((tx, ty), fill=FG)

    series(downs, GRAPH_DOWN, 0)
    series(ups, GRAPH_UP, 1)

    font = _font_sm()

    def short(v: float) -> str:
        if v >= 1000:
            return f"{v / 1000:.1f}M"
        return f"{v:.0f}k"

    draw.text((x + 2, y + 1), f"D{short(snap.wan_down_kbps)}", fill=GRAPH_DOWN, font=font)
    ul = f"U{short(snap.wan_up_kbps)}"
    uw, _ = _text_size(draw, ul, font)
    draw.text((x + w - uw - 2, y + 1), ul, fill=GRAPH_UP, font=font)
    draw.text((x + 2, y + h - 9), "5min", fill=DIM, font=font)


class FrameRenderer:
    """Renders one screen of a setup for a given animation phase."""

    def __init__(self, setup: Setup) -> None:
        self.setup = setup
        self.font = _font()
        self.font_sm = _font_sm()

    def render(self, screen: ScreenDef, snap: Snapshot, anim: float) -> Image.Image:
        img = Image.new("RGB", (64, 64), BG)
        draw = ImageDraw.Draw(img)
        # subtle top accent line (animated)
        accent = int(20 + 40 * abs(math.sin(anim * math.pi)))
        draw.line([(0, 0), (63, 0)], fill=(accent, accent + 30, 80))

        y = 2
        widgets = list(screen.widgets)
        # Compact layout: pack known widgets in a sensible vertical order
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
            # pulse brightness
            c = tuple(min(255, int(v + 20 * abs(math.sin(anim * math.pi * 2)))) for v in CYAN)
            # type as Color
            color: Color = (int(c[0]), int(c[1]), int(c[2]))
            x = _center_x(draw, title, self.font_sm)
            draw.text((x, y), title, fill=color, font=self.font_sm)
            return y + 10

        if wid == "clients":
            text = f"=> {snap.clients} clients <="
            x = _center_x(draw, text, self.font_sm)
            draw.text((x, y), text, fill=FG, font=self.font_sm)
            return y + 10

        if wid == "wan_rate":
            pair = format_rate_pair(snap.wan_down_kbps, snap.wan_up_kbps)
            text = f"Wan {pair}"
            x = _center_x(draw, text, self.font)
            draw.text((x, y), text, fill=ORANGE, font=self.font)
            return y + 11

        if wid == "cpu":
            pct = snap.cpu_pct
            draw.text((2, y), f"CPU {pct:.0f}%", fill=FG, font=self.font_sm)
            _draw_bar(draw, 2, y + 9, 60, 4, pct, _bar_color(pct), anim)
            return y + 16

        if wid == "temp":
            t = snap.temp_c
            col = RED if t >= 80 else (YELLOW if t >= 65 else CYAN)
            draw.text((2, y), f"Temp {t:.0f}C", fill=col, font=self.font_sm)
            # mini gauge
            _draw_bar(draw, 2, y + 9, 60, 3, min(100.0, t), col, anim + 0.2)
            return y + 15

        if wid == "ram":
            pct = snap.ram_pct
            draw.text((2, y), f"RAM {pct:.0f}%", fill=FG, font=self.font_sm)
            _draw_bar(draw, 2, y + 9, 60, 4, pct, _bar_color(pct), anim + 0.4)
            return y + 16

        if wid == "wan_graph":
            _draw_graph(draw, snap, 1, y, 62, 48 if "title" in all_widgets else 56, anim)
            return 64

        if wid == "internet":
            _draw_check(draw, 16, y + 10, snap.internet_ok, anim)
            label = "Online" if snap.internet_ok else "Offline"
            draw.text((28, y + 6), label, fill=GREEN if snap.internet_ok else RED, font=self.font_sm)
            return y + 22

        if wid == "usb":
            u2 = "OK" if snap.usb2 else "--"
            u3 = "OK" if snap.usb3 else "--"
            c2 = GREEN if snap.usb2 else DIM
            c3 = GREEN if snap.usb3 else DIM
            draw.text((2, y), "USB2", fill=DIM, font=self.font_sm)
            draw.text((28, y), u2, fill=c2, font=self.font_sm)
            draw.text((2, y + 9), "USB3", fill=DIM, font=self.font_sm)
            draw.text((28, y + 9), u3, fill=c3, font=self.font_sm)
            return y + 20

        if wid == "ethernet":
            text = f"ETH {snap.eth_linked}"
            draw.text((2, y), text, fill=FG, font=self.font_sm)
            # dots for linked ports
            for i in range(min(8, max(0, snap.eth_linked))):
                draw.rectangle([36 + i * 3, y + 2, 37 + i * 3, y + 5], fill=GREEN)
            return y + 11

        if wid == "wan_ip":
            ip = snap.wan_ip or "—"
            if len(ip) > 15:
                ip = ip[:15]
            draw.text((2, y), ip, fill=CYAN, font=self.font_sm)
            return y + 10

        if wid == "uptime":
            up = format_uptime(snap.uptime_s)
            draw.text((2, y), f"up {up}", fill=DIM, font=self.font_sm)
            return y + 10

        return y


def render_screen(setup: Setup, screen: ScreenDef, snap: Snapshot, anim: float = 0.0) -> Image.Image:
    return FrameRenderer(setup).render(screen, snap, anim)
