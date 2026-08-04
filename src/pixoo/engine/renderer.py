"""Pillow-only 64x64 renderer (no GUI dependencies)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from PIL import Image, ImageDraw

from pixoo.common.models import Project, Screen
from pixoo.utils.fonts import get_font, preload_fonts

SIZE = 64


def _hex(color: str, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    c = (color or "").strip()
    if c.startswith("#") and len(c) == 7:
        try:
            return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        except ValueError:
            return default
    return default


def substitute_placeholders(text: str, values: dict[str, Any]) -> str:
    """Replace tags via shared data_binding resolver."""
    from pixoo.studio.data_binding import resolve_tags

    return resolve_tags(text, values)

class FrameCache:
    def __init__(self, max_entries: int = 48) -> None:
        self.max_entries = max_entries
        self._store: dict[str, Image.Image] = {}
        self._order: list[str] = []

    def clear(self) -> None:
        self._store.clear()
        self._order.clear()

    def get(self, key: str) -> Image.Image | None:
        img = self._store.get(key)
        if img is not None and key in self._order:
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


class Renderer:
    """Render project screens to 64x64 RGB images."""

    def __init__(self) -> None:
        self.cache = FrameCache()
        preload_fonts()

    def cache_key(self, screen: Screen, values: dict[str, Any], anim_t: float) -> str:
        def _norm(v: Any) -> Any:
            if isinstance(v, float):
                return round(v, 2)
            return v

        payload = {
            "id": screen.id,
            "els": screen.elements,
            "bg": screen.background,
            "vals": {k: _norm(v) for k, v in values.items()},
            "anim": int(anim_t * 15),
        }
        return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def render(
        self,
        screen: Screen,
        project: Project,
        values: dict[str, Any],
        *,
        anim_t: float = 0.0,
        use_cache: bool = True,
    ) -> Image.Image:
        key = self.cache_key(screen, values, anim_t)
        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                return hit.copy()

        img = Image.new("RGB", (SIZE, SIZE), _hex(screen.background, (0, 0, 0)))
        draw = ImageDraw.Draw(img)
        elements = sorted(screen.elements, key=lambda e: int(e.get("z") or 0))
        for el in elements:
            if not el.get("visible", True):
                continue
            self._draw_element(draw, img, el, project, values, anim_t)
        if use_cache:
            self.cache.put(key, img.copy())
        return img

    def _draw_element(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        el: dict[str, Any],
        project: Project,
        values: dict[str, Any],
        anim_t: float,
    ) -> None:
        etype = str(el.get("type") or "text")
        if etype == "text":
            self._draw_text(draw, img, el, values, anim_t)
        elif etype == "gauge":
            self._draw_gauge(draw, el, project, values)
        elif etype == "graph":
            self._draw_graph(draw, el, project, values)
        elif etype == "image":
            self._draw_image(img, el)
        elif etype == "rect":
            x, y, w, h = int(el["x"]), int(el["y"]), int(el.get("w", 8)), int(el.get("h", 8))
            draw.rectangle([x, y, x + w - 1, y + h - 1], fill=_hex(str(el.get("color") or "#1E1E2A")))
        elif etype == "pattern":
            self._draw_pattern(draw, el)

    def _source_value(
        self, source: str, project: Project, values: dict[str, Any]
    ) -> tuple[float | None, float, float]:
        raw = values.get(source)
        val: float | None
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            val = float(raw)
        elif isinstance(raw, str):
            try:
                val = float(raw.strip().rstrip("%"))
            except ValueError:
                val = None
        elif isinstance(raw, dict):
            val = None
            for key in ("value", "price", "temperature"):
                if key in raw:
                    try:
                        val = float(raw[key])
                        break
                    except (TypeError, ValueError):
                        pass
        else:
            val = None
        vmin, vmax = 0.0, 100.0
        for s in project.sources:
            if s.id == source:
                vmin, vmax = s.min_value, s.max_value
                break
        if val is None and project.history.get(source):
            val = project.history[source][-1]
        return val, vmin, vmax
    def _pct(self, val: float | None, vmin: float, vmax: float) -> float:
        if val is None:
            return 0.0
        span = max(vmax - vmin, 1e-6)
        return max(0.0, min(100.0, (val - vmin) * 100.0 / span))

    def _draw_text(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        el: dict[str, Any],
        values: dict[str, Any],
        anim_t: float,
    ) -> None:
        content = substitute_placeholders(str(el.get("content") or ""), values)
        color = _hex(str(el.get("color") or "#FFFFFF"))
        font = get_font(1)
        x, y = int(el.get("x", 0)), int(el.get("y", 0))
        w = int(el.get("w") or 60)
        anim = str(el.get("animation") or "none")
        if anim != "marquee":
            draw.text((x, y), content[:24], fill=color, font=font)
            return
        try:
            bbox = font.getbbox(content)
            tw = max(1, bbox[2] - bbox[0])
        except Exception:
            tw = max(1, len(content) * 6)
        if tw <= w:
            draw.text((x, y), content, fill=color, font=font)
            return
        speed = float(el.get("speed") or 20)
        offset = int((anim_t * speed) % (tw + w))
        layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((x + w - offset, y), content, fill=color + (255,), font=font)
        h = int(el.get("h") or 10)
        clip = layer.crop((x, y, x + w, min(SIZE, y + h)))
        img.paste(clip, (x, y), clip)

    def _draw_gauge(
        self,
        draw: ImageDraw.ImageDraw,
        el: dict[str, Any],
        project: Project,
        values: dict[str, Any],
    ) -> None:
        source = str(el.get("source") or "system.cpu")
        val, vmin, vmax = self._source_value(source, project, values)
        pct = self._pct(val, vmin, vmax)
        warn, crit = float(el.get("warn_at") or 70), float(el.get("crit_at") or 90)
        if pct >= crit:
            col = _hex(str(el.get("color_crit") or "#FF4646"))
        elif pct >= warn:
            col = _hex(str(el.get("color_warn") or "#F0C828"))
        else:
            col = _hex(str(el.get("color") or "#28DC64"))
        style = str(el.get("style") or "bar")
        x, y = int(el["x"]), int(el["y"])
        w, h = int(el.get("w") or 60), int(el.get("h") or 6)
        if style == "pie":
            box = [x, y, x + max(4, w) - 1, y + max(4, h) - 1]
            draw.ellipse(box, fill=_hex(str(el.get("color_bg") or "#282837")))
            if pct > 0.5:
                draw.pieslice(box, start=-90, end=-90 + 360 * pct / 100, fill=col)
            draw.ellipse(box, outline=_hex("#78788C"))
        else:
            draw.rectangle([x, y, x + w - 1, y + h - 1], fill=_hex(str(el.get("color_bg") or "#14141C")))
            fw = max(0, int(round((w - 2) * pct / 100)))
            if fw:
                draw.rectangle([x + 1, y + 1, x + fw, y + h - 2], fill=col)

    def _draw_graph(
        self,
        draw: ImageDraw.ImageDraw,
        el: dict[str, Any],
        project: Project,
        values: dict[str, Any],
    ) -> None:
        source = str(el.get("source") or "system.cpu")
        hist = list(project.history.get(source) or [])
        val, _, _ = self._source_value(source, project, values)
        if val is not None:
            hist = hist + [float(val)]
        x, y = int(el["x"]), int(el["y"])
        w, h = int(el.get("w") or 60), int(el.get("h") or 14)
        draw.rectangle([x, y, x + w - 1, y + h - 2], fill=_hex(str(el.get("color_bg") or "#14141C")))
        if hist:
            pts = hist[-int(el.get("history_points") or 56) :]
            vmin, vmax = min(pts), max(pts)
            if abs(vmax - vmin) < 1e-6:
                vmax = vmin + 1
            step = max(1, w // max(len(pts), 1))
            col = _hex(str(el.get("color") or "#3CC8FF"))
            for i, v in enumerate(pts):
                xx = x + i * step
                if xx >= x + w:
                    break
                bh = max(1, int(round((v - vmin) / (vmax - vmin) * (h - 3))))
                draw.rectangle([xx, y + h - 2 - bh, min(x + w - 1, xx + step - 1), y + h - 3], fill=col)
        if el.get("show_progress", True):
            fill = min(1.0, len(hist) / max(8, int(el.get("history_points") or 56)))
            pw = int(round(w * fill))
            draw.rectangle([x, y + h - 1, x + w - 1, y + h - 1], fill=_hex("#282837"))
            if pw:
                draw.rectangle([x, y + h - 1, x + pw - 1, y + h - 1], fill=_hex("#3CC8FF"))

    def _draw_image(self, img: Image.Image, el: dict[str, Any]) -> None:
        path = str(el.get("path") or "")
        if not path:
            return
        try:
            src = Image.open(path).convert("RGBA")
            w, h = int(el.get("w") or 64), int(el.get("h") or 64)
            src = src.resize((w, h), Image.Resampling.NEAREST)
            img.paste(src, (int(el["x"]), int(el["y"])), src)
        except OSError:
            return

    def _draw_pattern(self, draw: ImageDraw.ImageDraw, el: dict[str, Any]) -> None:
        x0, y0 = int(el.get("x", 0)), int(el.get("y", 0))
        x1, y1 = x0 + int(el.get("w", 64)), y0 + int(el.get("h", 64))
        col = _hex(str(el.get("pattern_color") or el.get("color") or "#12121A"))
        for x in range(x0, x1, 4):
            draw.line([(x, y0), (x, y1 - 1)], fill=col)
        for y in range(y0, y1, 4):
            draw.line([(x0, y), (x1 - 1, y)], fill=col)

    @staticmethod
    def to_png_bytes(image: Image.Image) -> bytes:
        import io

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
