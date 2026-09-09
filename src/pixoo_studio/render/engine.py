"""Moteur de rendu 64×64 — cache, fonts, marquee, transitions."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..domain.models import Element, Project, Screen

SIZE = 64


def _hex(color: str, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    c = (color or "").strip()
    if c.startswith("#") and len(c) == 7:
        try:
            return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        except ValueError:
            return default
    return default


class FontCache:
    """Pré-génération des polices à l'ouverture du projet."""

    def __init__(self) -> None:
        self._fonts: dict[int, ImageFont.ImageFont | ImageFont.FreeTypeFont] = {}

    def preload(self) -> None:
        for size in (1, 2, 3):
            self.get(size)

    def get(self, size_token: int = 1) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
        size_token = max(1, min(3, int(size_token)))
        if size_token in self._fonts:
            return self._fonts[size_token]
        if size_token <= 1:
            font: ImageFont.ImageFont | ImageFont.FreeTypeFont = ImageFont.load_default()
        else:
            font = ImageFont.load_default()
            for path in (
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "C:/Windows/Fonts/arial.ttf",
            ):
                try:
                    font = ImageFont.truetype(path, 8 if size_token == 2 else 14)
                    break
                except OSError:
                    continue
        self._fonts[size_token] = font
        return font


class FrameCache:
    """Cache LRU simple des frames 64×64."""

    def __init__(self, max_entries: int = 64) -> None:
        self.max_entries = max_entries
        self._store: dict[str, Image.Image] = {}
        self._order: list[str] = []

    def clear(self) -> None:
        self._store.clear()
        self._order.clear()

    def get(self, key: str) -> Image.Image | None:
        img = self._store.get(key)
        if img is not None:
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
        return img

    def put(self, key: str, image: Image.Image) -> None:
        if key in self._store:
            self._order.remove(key)
        self._store[key] = image
        self._order.append(key)
        while len(self._order) > self.max_entries:
            old = self._order.pop(0)
            self._store.pop(old, None)


def _gauge_color(el: Element, pct: float) -> tuple[int, int, int]:
    if pct >= el.crit_at:
        return _hex(el.color_crit, (255, 70, 70))
    if pct >= el.warn_at:
        return _hex(el.color_warn, (240, 200, 40))
    return _hex(el.color, (40, 220, 100))


def _norm(value: float | None, vmin: float, vmax: float) -> float:
    if value is None:
        return 0.0
    span = max(vmax - vmin, 1e-6)
    return max(0.0, min(100.0, (value - vmin) * 100.0 / span))


def _draw_pattern(draw: ImageDraw.ImageDraw, el: Element) -> None:
    x0, y0, x1, y1 = el.x, el.y, el.x + el.w, el.y + el.h
    col = _hex(el.pattern_color, (30, 30, 42))
    kind = (el.pattern or "none").lower()
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
        for y in range(y0, y1):
            for x in range(x0, x1):
                if ((x * 31 + y * 17) ^ (x + y)) % 11 == 0:
                    draw.point((x, y), fill=col)


class RenderEngine:
    """Rendu d'écrans + animations (marquee / transitions)."""

    def __init__(self) -> None:
        self.fonts = FontCache()
        self.cache = FrameCache()
        self.fonts.preload()

    def cache_key(
        self,
        screen: Screen,
        values: dict[str, float | None],
        *,
        anim_t: float,
        transition_progress: float = 0.0,
    ) -> str:
        payload = {
            "sid": screen.id,
            "scr": screen.to_dict(),
            "vals": {k: None if v is None else round(float(v), 3) for k, v in values.items()},
            # bucket anim ~50ms pour limiter invalidations
            "anim": int(anim_t * 20),
            "tr": int(transition_progress * 20),
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode()).hexdigest()

    def render_screen(
        self,
        screen: Screen,
        project: Project,
        values: dict[str, float | None] | None = None,
        *,
        anim_t: float = 0.0,
        use_cache: bool = True,
    ) -> Image.Image:
        values = values or {}
        key = self.cache_key(screen, values, anim_t=anim_t)
        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                return hit.copy()

        img = Image.new("RGB", (SIZE, SIZE), _hex(screen.background, (0, 0, 0)))
        draw = ImageDraw.Draw(img)
        for el in sorted(screen.elements, key=lambda e: (e.z, e.y, e.x)):
            if not el.visible:
                continue
            self._draw_element(draw, img, el, project, values, anim_t)
        if use_cache:
            self.cache.put(key, img.copy())
        return img

    def _draw_element(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        el: Element,
        project: Project,
        values: dict[str, float | None],
        anim_t: float,
    ) -> None:
        src = project.source_by_id(el.source_id) if el.source_id else None
        raw = values.get(el.source_id) if el.source_id else None
        # degraded: last known in history
        if raw is None and el.source_id and project.history_preview.get(el.source_id):
            raw = project.history_preview[el.source_id][-1]
        smin = src.min_value if src else 0.0
        smax = src.max_value if src else 100.0
        unit = src.unit if src else ""
        pct = _norm(raw, smin, smax)
        font = self.fonts.get(el.font_size)

        if el.type == "pattern":
            _draw_pattern(draw, el)
            return
        if el.type == "rect":
            draw.rectangle(
                [el.x, el.y, el.x + max(1, el.w) - 1, el.y + max(1, el.h) - 1],
                fill=_hex(el.color),
            )
            return
        if el.type == "text":
            text = el.text.replace("{title}", "")
            self._draw_text_overflow(draw, img, el, text, font, anim_t)
            return
        if el.type == "value":
            if raw is None:
                label, col = "—", _hex("#78788C")
            else:
                try:
                    label = el.format.format(v=raw, u=unit, pct=pct)
                except Exception:
                    label = f"{raw:.0f}{unit}"
                col = _gauge_color(el, pct)
            # temporary color override via drawing
            old = el.color
            el.color = "#%02x%02x%02x" % col
            self._draw_text_overflow(draw, img, el, label[:16], font, anim_t)
            el.color = old
            return
        if el.type == "bar":
            x, y, w, h = el.x, el.y, max(1, el.w), max(1, el.h)
            draw.rectangle([x, y, x + w - 1, y + h - 1], fill=_hex(el.color_bg))
            fw = max(0, int(round((w - 2) * pct / 100)))
            if fw:
                draw.rectangle([x + 1, y + 1, x + fw, y + h - 2], fill=_gauge_color(el, pct))
            return
        if el.type == "pie":
            box = [el.x, el.y, el.x + max(4, el.w) - 1, el.y + max(4, el.h) - 1]
            draw.ellipse(box, fill=_hex(el.color_secondary))
            if pct > 0.5:
                draw.pieslice(box, start=-90, end=-90 + 360 * pct / 100, fill=_gauge_color(el, pct))
            draw.ellipse(box, outline=_hex("#78788C"))
            return
        if el.type == "status_dot":
            draw.ellipse(
                [el.x, el.y, el.x + max(3, el.w) - 1, el.y + max(3, el.h) - 1],
                fill=_gauge_color(el, pct),
            )
            return
        if el.type == "sparkline":
            self._sparkline(draw, el, project, raw)
            return

    def _draw_text_overflow(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        el: Element,
        text: str,
        font,
        anim_t: float,
    ) -> None:
        color = _hex(el.color)
        if el.overflow != "marquee":
            draw.text((el.x, el.y), text[:20], fill=color, font=font)
            return
        # marquee: render on strip then crop
        try:
            bbox = font.getbbox(text)
            tw = max(1, bbox[2] - bbox[0])
        except Exception:
            tw = max(1, len(text) * 6)
        if tw <= el.w:
            draw.text((el.x, el.y), text, fill=color, font=font)
            return
        # offset loops
        span = tw + el.w
        offset = int((anim_t * el.marquee_speed) % span)
        layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((el.x + el.w - offset, el.y), text, fill=color + (255,), font=font)
        # clip to element box
        clip = layer.crop((el.x, el.y, el.x + el.w, min(SIZE, el.y + max(el.h, 10))))
        img.paste(clip, (el.x, el.y), clip)

    def _sparkline(
        self,
        draw: ImageDraw.ImageDraw,
        el: Element,
        project: Project,
        raw: float | None,
    ) -> None:
        hist = list(project.history_preview.get(el.source_id, []))
        if raw is not None:
            hist = hist + [float(raw)]
        w, h = max(4, el.w), max(4, el.h)
        x0, y0 = el.x, el.y
        draw.rectangle([x0, y0, x0 + w - 1, y0 + h - 2], fill=_hex(el.color_bg))
        if hist:
            pts = hist[-max(4, el.history_points) :]
            vmin, vmax = min(pts), max(pts)
            if abs(vmax - vmin) < 1e-6:
                vmax = vmin + 1
            n = len(pts)
            step = max(1, w // max(n, 1))
            for i, v in enumerate(pts):
                xx = x0 + i * step
                if xx >= x0 + w:
                    break
                norm = (v - vmin) / (vmax - vmin)
                bh = max(1, int(round(norm * (h - 3))))
                draw.rectangle(
                    [xx, y0 + h - 2 - bh, min(x0 + w - 1, xx + max(1, step - 1)), y0 + h - 3],
                    fill=_hex(el.color),
                )
        if el.show_progress:
            fill = min(1.0, len(hist) / max(8, el.history_points))
            pw = int(round(w * fill))
            draw.rectangle([x0, y0 + h - 1, x0 + w - 1, y0 + h - 1], fill=_hex("#282837"))
            if pw:
                draw.rectangle(
                    [x0, y0 + h - 1, x0 + pw - 1, y0 + h - 1],
                    fill=_hex("#3CC8FF") if fill < 1 else _hex("#28DC64"),
                )

    def transition(
        self,
        img_a: Image.Image,
        img_b: Image.Image,
        progress: float,
        mode: str = "fade",
    ) -> Image.Image:
        """Compose une transition entre deux frames (progress 0..1)."""
        p = max(0.0, min(1.0, progress))
        a = img_a.convert("RGBA")
        b = img_b.convert("RGBA")
        if mode == "none" or p <= 0:
            return img_a.copy()
        if p >= 1:
            return img_b.copy()
        if mode == "slide":
            shift = int(SIZE * p)
            out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
            out.paste(a.crop((shift, 0, SIZE, SIZE)), (0, 0))
            out.paste(b.crop((0, 0, shift, SIZE)), (SIZE - shift, 0))
            return out.convert("RGB")
        # fade
        out = Image.blend(a, b, p)
        return out.convert("RGB")

    @staticmethod
    def scale_preview(image: Image.Image, scale: int = 8) -> Image.Image:
        scale = max(1, int(scale))
        return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
