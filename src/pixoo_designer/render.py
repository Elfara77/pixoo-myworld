"""Rendu Pillow 64×64 d'un Screen designer."""

from __future__ import annotations

import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .model import Element, Project, Screen

SIZE = 64


def _hex(color: str, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    c = (color or "").strip()
    if c.startswith("#") and len(c) == 7:
        try:
            return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        except ValueError:
            return default
    return default


def _font(size_token: int = 1) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    # Prefer bitmap default for crisp native look
    if size_token <= 1:
        return ImageFont.load_default()
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, 8 if size_token == 2 else 14)
        except OSError:
            continue
    return ImageFont.load_default()


def _gauge_color(el: Element, pct: float) -> tuple[int, int, int]:
    if pct >= el.crit_at:
        return _hex(el.color_crit, (255, 70, 70))
    if pct >= el.warn_at:
        return _hex(el.color_warn, (240, 200, 40))
    return _hex(el.color, (40, 220, 100))


def _draw_pattern(draw: ImageDraw.ImageDraw, el: Element) -> None:
    x0, y0, x1, y1 = el.x, el.y, el.x + el.w, el.y + el.h
    col = _hex(el.pattern_color, (30, 30, 42))
    kind = (el.pattern or "none").lower()
    if kind == "none":
        return
    if kind == "grid":
        for x in range(x0, x1, 4):
            draw.line([(x, y0), (x, y1 - 1)], fill=col)
        for y in range(y0, y1, 4):
            draw.line([(x0, y), (x1 - 1, y)], fill=col)
    elif kind == "dots":
        for y in range(y0 + 1, y1, 3):
            for x in range(x0 + 1, x1, 3):
                draw.point((x, y), fill=col)
    elif kind == "scanlines":
        for y in range(y0, y1, 2):
            draw.line([(x0, y), (x1 - 1, y)], fill=col)
    elif kind == "diagonal":
        for i in range(-el.h, el.w, 3):
            draw.line([(x0 + i, y0), (x0 + i + el.h, y1 - 1)], fill=col)
    elif kind == "noise":
        # pseudo noise déterministe
        for y in range(y0, y1):
            for x in range(x0, x1):
                if ((x * 31 + y * 17) ^ (x + y)) % 11 == 0:
                    draw.point((x, y), fill=col)


def _norm(value: float | None, source_min: float, source_max: float) -> float:
    if value is None:
        return 0.0
    span = max(source_max - source_min, 1e-6)
    return max(0.0, min(100.0, (value - source_min) * 100.0 / span))


def render_screen(
    screen: Screen,
    project: Project,
    values: dict[str, float | None] | None = None,
    *,
    size: int = SIZE,
) -> Image.Image:
    values = values or {}
    img = Image.new("RGB", (size, size), _hex(screen.background, (0, 0, 0)))
    draw = ImageDraw.Draw(img)

    elements = sorted(screen.elements, key=lambda e: (e.z, e.y, e.x))
    for el in elements:
        if not el.visible:
            continue
        src = project.source_by_id(el.source_id) if el.source_id else None
        raw = values.get(el.source_id) if el.source_id else None
        smin = src.min_value if src else 0.0
        smax = src.max_value if src else 100.0
        unit = src.unit if src else ""
        pct = _norm(raw, smin, smax)

        if el.type == "pattern":
            _draw_pattern(draw, el)
            continue

        if el.type == "rect":
            draw.rectangle(
                [el.x, el.y, el.x + max(1, el.w) - 1, el.y + max(1, el.h) - 1],
                fill=_hex(el.color, (30, 30, 42)),
            )
            continue

        if el.type == "text":
            text = el.text
            if screen.title_mode != "hidden" and "{title}" in text:
                text = text.replace("{title}", screen.title)
            draw.text((el.x, el.y), text[:20], fill=_hex(el.color), font=_font(el.font_size))
            continue

        if el.type == "value":
            if raw is None:
                label = "—"
                col = _hex("#78788C")
            else:
                try:
                    label = el.format.format(v=raw, u=unit, pct=pct)
                except Exception:
                    label = f"{raw:.0f}{unit}"
                col = _gauge_color(el, pct)
            draw.text((el.x, el.y), label[:12], fill=col, font=_font(el.font_size))
            continue

        if el.type == "bar":
            x, y, w, h = el.x, el.y, max(1, el.w), max(1, el.h)
            draw.rectangle([x, y, x + w - 1, y + h - 1], fill=_hex(el.color_bg, (20, 20, 28)))
            fill_w = max(0, int(round((w - 2) * pct / 100.0)))
            if fill_w > 0:
                draw.rectangle([x + 1, y + 1, x + fill_w, y + h - 2], fill=_gauge_color(el, pct))
            continue

        if el.type == "pie":
            # utilise w/h comme bbox
            x0, y0 = el.x, el.y
            x1, y1 = el.x + max(4, el.w) - 1, el.y + max(4, el.h) - 1
            draw.ellipse([x0, y0, x1, y1], fill=_hex(el.color_secondary, (40, 40, 55)))
            if pct > 0.5:
                # start at 12 o'clock
                extent = 360.0 * pct / 100.0
                draw.pieslice([x0, y0, x1, y1], start=-90, end=-90 + extent, fill=_gauge_color(el, pct))
            draw.ellipse([x0, y0, x1, y1], outline=_hex("#78788C"))
            continue

        if el.type == "status_dot":
            col = _gauge_color(el, pct)
            x0, y0 = el.x, el.y
            x1, y1 = el.x + max(3, el.w) - 1, el.y + max(3, el.h) - 1
            draw.ellipse([x0, y0, x1, y1], fill=col)
            continue

        if el.type == "sparkline":
            hist = list(project.history_preview.get(el.source_id, []))
            # append current
            if raw is not None:
                hist = hist + [float(raw)]
            # downsample to width
            w, h = max(4, el.w), max(4, el.h)
            x0, y0 = el.x, el.y
            draw.rectangle([x0, y0, x0 + w - 1, y0 + h - 2], fill=_hex(el.color_bg, (16, 16, 24)))
            if hist:
                # take last N
                pts = hist[-max(4, el.history_points) :]
                vmin, vmax = min(pts), max(pts)
                if abs(vmax - vmin) < 1e-6:
                    vmax = vmin + 1.0
                if src and src.max_value > src.min_value and src.unit == "%":
                    vmin, vmax = src.min_value, max(src.max_value, vmax)
                n = len(pts)
                col_w = max(1, w // n)
                for i, v in enumerate(pts[: w]):
                    norm = (v - vmin) / (vmax - vmin)
                    bh = max(1, int(round(norm * (h - 3))))
                    xx = x0 + i * col_w
                    if xx >= x0 + w:
                        break
                    yy = y0 + (h - 2) - bh
                    draw.rectangle(
                        [xx, yy, min(x0 + w - 1, xx + max(1, col_w - 1)), y0 + h - 3],
                        fill=_hex(el.color, (60, 200, 255)),
                    )
            if el.show_progress:
                # barre basse = période « remplie » (simulée: min(1, len/points))
                fill = min(1.0, len(hist) / max(8, el.history_points))
                pw = max(0, int(round(w * fill)))
                draw.rectangle([x0, y0 + h - 1, x0 + w - 1, y0 + h - 1], fill=_hex("#282837"))
                if pw:
                    draw.rectangle(
                        [x0, y0 + h - 1, x0 + pw - 1, y0 + h - 1],
                        fill=_hex("#3CC8FF") if fill < 1 else _hex("#28DC64"),
                    )
            # period label tiny
            draw.text((x0 + w - 14, y0), (el.period or "")[:4], fill=_hex("#585868"), font=_font(1))
            continue

    # titre auto si mode default et aucun text title
    if screen.title_mode == "default":
        has_title = any(e.type == "text" and e.text for e in screen.elements)
        if not has_title:
            draw.text((2, 1), screen.title[:10], fill=(60, 200, 255), font=_font(1))

    return img


def scale_preview(image: Image.Image, scale: int = 8) -> Image.Image:
    """Aperçu net (nearest-neighbor)."""
    scale = max(1, int(scale))
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
