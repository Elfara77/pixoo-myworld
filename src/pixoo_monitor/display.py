"""Rendu des pages Pixoo 64×64 — modes native (crisp) / scaled (doux)."""

from __future__ import annotations

from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from .metrics import Snapshot
from .metrics.status import Health

Color = tuple[int, int, int]

BG = (0, 0, 0)
FG = (220, 220, 220)
DIM = (120, 120, 140)
GREEN = (40, 220, 100)
YELLOW = (240, 200, 40)
RED = (255, 70, 70)
CYAN = (60, 200, 255)
MAGENTA = (220, 80, 200)
BLUE = (80, 140, 255)
ORANGE = (255, 140, 40)
PIE_FREE = (40, 40, 55)

RENDER_MODES = ("native", "scaled")
DISK_STYLES = ("bar", "pie")


def _font_scaled(size: int = 10) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _font_native() -> ImageFont.ImageFont:
    """Police bitmap PIL — pas d'antialias TrueType."""
    return ImageFont.load_default()


def normalize_render_mode(value: Any) -> str:
    mode = str(value or "scaled").strip().lower()
    aliases = {
        "crisp": "native",
        "pixel": "native",
        "sharp": "native",
        "smooth": "scaled",
        "hires": "scaled",
        "soft": "scaled",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in RENDER_MODES else "scaled"


def normalize_disk_style(value: Any) -> str:
    style = str(value or "bar").strip().lower()
    if style in ("camembert", "piechart", "circle"):
        return "pie"
    if style in ("barre", "horizontal"):
        return "bar"
    # bool legacy
    if value is True:
        return "pie"
    if value is False:
        return "bar"
    return style if style in DISK_STYLES else "bar"


def _bar_color(pct: float, warn: float, crit: float) -> Color:
    if pct >= crit:
        return RED
    if pct >= warn:
        return YELLOW
    return GREEN


def _health_color(h: Health | str) -> Color:
    if h == "ok":
        return GREEN
    if h == "warn":
        return YELLOW
    if h == "down":
        return RED
    return DIM


def _fmt_rate(kbps: float | None) -> str:
    if kbps is None:
        return "…"
    if kbps >= 1000:
        return f"{kbps / 1000:.1f}M"
    return f"{kbps:.0f}k"


def _short_svc(name: str) -> str:
    n = name.lower()
    if "php" in n and "fpm" in n:
        return "fpm"
    if "nginx" in n:
        return "ngx"
    if "apache" in n or "httpd" in n:
        return "apa"
    if "maria" in n or "mysql" in n:
        return "db"
    if "postgres" in n:
        return "pg"
    if "redis" in n:
        return "rds"
    if "cron" in n:
        return "crn"
    return name[:3]


class Renderer:
    def __init__(self, cfg: dict[str, Any], size: int = 64) -> None:
        self.cfg = cfg
        self.size = size
        self.display = cfg.get("display", {})
        self.thr = cfg.get("thresholds", {})
        metrics = cfg.get("_resolved_metrics")
        if not isinstance(metrics, dict):
            metrics = cfg.get("metrics", {})
        self.metrics = metrics

        self.render_mode = normalize_render_mode(self.display.get("render_mode", "scaled"))
        self.native = self.render_mode == "native"
        # disk_style = défaut global (legacy) ; écrans personnalisés ont styles par mesure
        raw_style = self.display.get("disk_style")
        if raw_style is None and self.display.get("disk_pie"):
            raw_style = "pie"
        self.disk_style = normalize_disk_style(raw_style if raw_style is not None else "bar")
        # Styles globaux par métrique (si pas d'écrans custom) : [metric_styles] cpu="pie"
        ms = self.cfg.get("metric_styles") if isinstance(self.cfg.get("metric_styles"), dict) else {}
        self.metric_styles: dict[str, str] = {
            str(k): normalize_disk_style(v) for k, v in ms.items()
        }
        from .screens import parse_screens

        self.screens = parse_screens(self.cfg)
        self.history = None  # injecté par MonitorApp si configuré

        # scaled: canvas 2× puis LANCZOS ; native: 64×64 exact, bitmap
        self.scale = 1 if self.native else 2
        self.canvas = self.size * self.scale

        if self.native:
            bmp = _font_native()
            self.font = bmp
            self.font_sm = bmp
            self.font_lg = bmp
            self.bar_h_sm = 3
            self.bar_h = 3
            self.bar_h_lg = 4
        else:
            s = self.scale
            self.font = _font_scaled(9 * s)
            self.font_sm = _font_scaled(8 * s)
            self.font_lg = _font_scaled(11 * s)
            self.bar_h_sm = 4 * s
            self.bar_h = 5 * s
            self.bar_h_lg = 6 * s

    def _p(self, n: int | float) -> int:
        """Pixel entier sur le canvas (× scale en mode scaled)."""
        return int(round(n)) * self.scale

    def _xy(self, x: int | float, y: int | float) -> tuple[int, int]:
        return self._p(x), self._p(y)

    def _new(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        bg = BG if self.display.get("dark", True) else (20, 20, 30)
        img = Image.new("RGB", (self.canvas, self.canvas), bg)
        return img, ImageDraw.Draw(img)

    def _finalize(self, img: Image.Image) -> Image.Image:
        if img.size == (self.size, self.size):
            return img
        if self.native:
            return img.resize((self.size, self.size), Image.Resampling.NEAREST)
        return img.resize((self.size, self.size), Image.Resampling.LANCZOS)

    def _draw_bar(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        w: int,
        h: int,
        pct: float,
        color: Color,
    ) -> None:
        """x,y,w,h en coordonnées logiques 64×64."""
        if not self.display.get("bars", True):
            return
        pct = max(0.0, min(100.0, pct))
        x0, y0 = self._p(x), self._p(y)
        ww, hh = self._p(w), max(self.scale, self._p(h) if not self.native else h)
        if self.native:
            hh = max(2, int(h))
            ww = int(w)
            x0, y0 = int(x), int(y)
        draw.rectangle([x0, y0, x0 + ww, y0 + hh], outline=DIM, fill=(20, 20, 28))
        fill_w = max(1, int(ww * pct / 100.0)) if pct > 0 else 0
        if fill_w:
            if self.native:
                draw.rectangle([x0, y0, x0 + fill_w, y0 + hh], fill=color)
            else:
                inset = max(1, self.scale // 2)
                draw.rectangle(
                    [x0 + inset, y0 + inset, x0 + fill_w - inset, y0 + hh - inset],
                    fill=color,
                )

    def _draw_pie(
        self,
        draw: ImageDraw.ImageDraw,
        cx: int,
        cy: int,
        radius: int,
        pct: float,
        color: Color,
    ) -> None:
        """Camembert used/free — coordonnées logiques 64×64."""
        pct = max(0.0, min(100.0, pct))
        if self.native:
            # Boîte entière, pas d'antialias
            bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
            draw.ellipse(bbox, outline=DIM, fill=PIE_FREE)
            if pct >= 99.5:
                draw.ellipse(bbox, fill=color, outline=DIM)
            elif pct > 0.5:
                # angles PIL: 0=3h, sens horaire négatif en extents… pieslice start/end en degrés
                extent = max(3, int(round(360.0 * pct / 100.0)))
                # Départ en haut (-90°) pour lecture naturelle
                start = -90
                end = start + extent
                draw.pieslice(bbox, start=start, end=end, fill=color, outline=color)
            # Contour net
            draw.ellipse(bbox, outline=DIM)
        else:
            s = self.scale
            bbox = [
                self._p(cx - radius),
                self._p(cy - radius),
                self._p(cx + radius),
                self._p(cy + radius),
            ]
            draw.ellipse(bbox, outline=DIM, fill=PIE_FREE)
            if pct >= 99.5:
                draw.ellipse(bbox, fill=color, outline=DIM)
            elif pct > 0.5:
                extent = 360.0 * pct / 100.0
                draw.pieslice(bbox, start=-90, end=-90 + extent, fill=color)
            draw.ellipse(bbox, outline=DIM)
            _ = s  # scale déjà appliqué via _p

    def _style_for(self, metric: str, override: str | None = None) -> str:
        if override:
            return normalize_disk_style(override)
        if metric in self.metric_styles:
            return self.metric_styles[metric]
        if metric in ("disk", "nc_disk"):
            return self.disk_style
        return "bar"

    def _disk_gauge(
        self,
        draw: ImageDraw.ImageDraw,
        pct: float,
        color: Color,
        *,
        style: str | None = None,
        metric: str = "disk",
        bar_xywh: tuple[int, int, int, int] | None = None,
        pie_center: tuple[int, int, int] | None = None,
    ) -> None:
        use = self._style_for(metric, style)
        if use == "pie":
            cx, cy, r = pie_center or (48, 40, 14)
            self._draw_pie(draw, cx, cy, r, pct, color)
        else:
            x, y, w, h = bar_xywh or (2, 56, 60, 5)
            self._draw_bar(draw, x, y, w, h, pct, color)

    def page_overview(self, snap: Snapshot) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), snap.hostname[:10], fill=CYAN, font=self.font_sm)
        y = 12
        rows: list[tuple[str, float, float, float]] = []
        if self.metrics.get("cpu") and snap.cpu_percent is not None:
            rows.append(("CPU", snap.cpu_percent, 70, float(self.thr.get("cpu_percent", 90))))
        if self.metrics.get("ram") and snap.ram_percent is not None:
            rows.append(("RAM", snap.ram_percent, 75, float(self.thr.get("ram_percent", 90))))
        if self.metrics.get("swap") and snap.swap_percent is not None:
            rows.append(("SWP", snap.swap_percent, 50, float(self.thr.get("swap_percent", 80))))
        if self.metrics.get("disk") and snap.disk_percent is not None:
            rows.append(("DSK", snap.disk_percent, 80, float(self.thr.get("disk_percent", 90))))
        for label, pct, warn, crit in rows[:4]:
            col = _bar_color(pct, warn, crit)
            d.text(self._xy(2, y), label, fill=DIM, font=self.font_sm)
            d.text(self._xy(22, y), f"{pct:4.0f}%", fill=col, font=self.font_sm)
            metric_key = {"CPU": "cpu", "RAM": "ram", "SWP": "swap", "DSK": "disk"}.get(label, "disk")
            if self._style_for(metric_key) == "pie":
                self._draw_pie(d, 54, y + 5, 5, pct, col)
            else:
                self._draw_bar(d, 2, y + 9, 60, 3 if self.native else 4, pct, col)
            y += 13
        return self._finalize(img)

    def page_n40(self, snap: Snapshot) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), "N40", fill=ORANGE, font=self.font)
        y = 12
        if snap.cpu_percent is not None:
            col = _bar_color(snap.cpu_percent, 70, float(self.thr.get("cpu_percent", 90)))
            d.text(self._xy(2, y), f"CPU {snap.cpu_percent:.0f}%", fill=col, font=self.font_sm)
            self._draw_bar(d, 2, y + 9, 60, 3 if self.native else 4, snap.cpu_percent, col)
            y += 15
        if snap.load_avg:
            l1 = snap.load_avg[0]
            d.text(self._xy(2, y), f"LD {l1:.2f}", fill=FG, font=self.font_sm)
            y += 11
        if snap.temperatures:
            t = snap.temperatures[0][1]
            col = _bar_color(
                t,
                float(self.thr.get("temperature_celsius", 85)) - 15,
                float(self.thr.get("temperature_celsius", 85)),
            )
            d.text(self._xy(2, y), f"TMP {t:.0f}C", fill=col, font=self.font_sm)
            y += 11
        if snap.ram_percent is not None:
            col = _bar_color(snap.ram_percent, 75, float(self.thr.get("ram_percent", 90)))
            d.text(self._xy(2, y), f"RAM {snap.ram_percent:.0f}%", fill=col, font=self.font_sm)
        return self._finalize(img)

    def page_cpu(self, snap: Snapshot, *, title: str | None = None, style: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "CPU")[:10], fill=CYAN, font=self.font)
        pct = snap.cpu_percent if snap.cpu_percent is not None else 0.0
        col = _bar_color(pct, 70, float(self.thr.get("cpu_percent", 90)))
        d.text(self._xy(2, 14), f"{pct:.0f}%", fill=col, font=self.font_lg)
        self._disk_gauge(
            d, pct, col, metric="cpu", style=style,
            bar_xywh=(2, 28, 60, 4 if self.native else 6),
            pie_center=(46, 42, 14),
        )
        if self.metrics.get("load_avg") and snap.load_avg:
            l1, l5, l15 = snap.load_avg
            d.text(self._xy(2, 40), f"L {l1:.2f}", fill=FG, font=self.font_sm)
            d.text(self._xy(2, 50), f"{l5:.1f}/{l15:.1f}", fill=DIM, font=self.font_sm)
        elif snap.cpu_per_core:
            cores = snap.cpu_per_core[:8]
            bw = max(2, 60 // max(len(cores), 1))
            for i, c in enumerate(cores):
                h = max(1, int(18 * c / 100))
                x0 = self._p(2 + i * bw)
                y0 = self._p(60 - h)
                x1 = self._p(2 + i * bw + bw - 2)
                y1 = self._p(60)
                if self.native:
                    x0, y0 = 2 + i * bw, 60 - h
                    x1, y1 = 2 + i * bw + bw - 2, 60
                d.rectangle([x0, y0, x1, y1], fill=_bar_color(c, 70, 90))
        return self._finalize(img)

    def page_mem(
        self,
        snap: Snapshot,
        *,
        title: str | None = None,
        include_ram: bool = True,
        include_swap: bool = True,
        ram_style: str | None = None,
        swap_style: str | None = None,
        force: bool = False,
    ) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "MEM")[:10], fill=CYAN, font=self.font)
        y = 14
        show_ram = include_ram and snap.ram_percent is not None and (
            force or self.metrics.get("ram") or ram_style is not None
        )
        show_swap = include_swap and snap.swap_percent is not None and (
            force or self.metrics.get("swap") or swap_style is not None
        )

        if show_ram and snap.ram_percent is not None:
            col = _bar_color(snap.ram_percent, 75, float(self.thr.get("ram_percent", 90)))
            used = snap.ram_used_gb or 0
            total = snap.ram_total_gb or 0
            d.text(self._xy(2, y), f"RAM {snap.ram_percent:.0f}%", fill=col, font=self.font_sm)
            d.text(self._xy(2, y + 10), f"{used:.1f}/{total:.0f}G", fill=DIM, font=self.font_sm)
            self._disk_gauge(
                d, snap.ram_percent, col, metric="ram", style=ram_style,
                bar_xywh=(2, y + 20, 60, 3 if self.native else 5),
                pie_center=(52, y + 14, 8),
            )
            y += 30
        if show_swap and snap.swap_percent is not None:
            col = _bar_color(snap.swap_percent, 50, float(self.thr.get("swap_percent", 80)))
            d.text(self._xy(2, y), f"SWP {snap.swap_percent:.0f}%", fill=col, font=self.font_sm)
            self._disk_gauge(
                d, snap.swap_percent, col, metric="swap", style=swap_style,
                bar_xywh=(2, y + 10, 60, 3 if self.native else 5),
                pie_center=(52, y + 6, 8),
            )
        return self._finalize(img)

    def page_disk(self, snap: Snapshot, *, title: str | None = None, style: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "DISK")[:10], fill=CYAN, font=self.font)
        pct = snap.disk_percent or 0.0
        col = _bar_color(pct, 80, float(self.thr.get("disk_percent", 90)))
        used = snap.disk_used_gb or 0
        total = snap.disk_total_gb or 0
        path = (snap.disk_path or "/")[-14:]
        use = self._style_for("disk", style)

        if use == "pie":
            d.text(self._xy(2, 12), f"{pct:.0f}%", fill=col, font=self.font_lg)
            d.text(self._xy(2, 28), f"{used:.0f}/{total:.0f}G", fill=FG, font=self.font_sm)
            d.text(self._xy(2, 40), path[:10], fill=DIM, font=self.font_sm)
            self._draw_pie(d, 46, 42, 16 if self.native else 15, pct, col)
        else:
            d.text(self._xy(2, 16), f"{pct:.0f}%", fill=col, font=self.font_lg)
            d.text(self._xy(2, 32), f"{used:.0f}/{total:.0f}G", fill=FG, font=self.font_sm)
            d.text(self._xy(2, 44), path, fill=DIM, font=self.font_sm)
            self._draw_bar(d, 2, 56, 60, 3 if self.native else 5, pct, col)
        return self._finalize(img)

    def page_net(self, snap: Snapshot, *, title: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "NET")[:10], fill=CYAN, font=self.font)
        iface = (snap.net_interface or "?")[:10]
        d.text(self._xy(2, 14), iface, fill=DIM, font=self.font_sm)
        d.text(self._xy(2, 28), f"↓ {_fmt_rate(snap.net_down_kbps)}", fill=GREEN, font=self.font)
        d.text(self._xy(2, 42), f"↑ {_fmt_rate(snap.net_up_kbps)}", fill=YELLOW, font=self.font)
        return self._finalize(img)

    def page_temp(self, snap: Snapshot, *, title: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "TEMP")[:10], fill=CYAN, font=self.font)
        crit = float(self.thr.get("temperature_celsius", 85))
        if not snap.temperatures:
            d.text(self._xy(2, 24), "N/A", fill=DIM, font=self.font_lg)
            d.text(self._xy(2, 42), "no sensor", fill=DIM, font=self.font_sm)
            return self._finalize(img)
        y = 14
        for label, val in snap.temperatures[:4]:
            col = _bar_color(val, crit - 15, crit)
            d.text(self._xy(2, y), f"{label[:6]}", fill=DIM, font=self.font_sm)
            d.text(self._xy(30, y), f"{val:.0f}C", fill=col, font=self.font_sm)
            y += 12
        return self._finalize(img)

    def page_uptime(self, snap: Snapshot, *, title: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "UP")[:10], fill=CYAN, font=self.font)
        hours = snap.uptime_hours or 0.0
        days = int(hours // 24)
        h = int(hours % 24)
        m = int((hours * 60) % 60)
        d.text(self._xy(2, 20), f"{days}d {h}h", fill=FG, font=self.font_lg)
        d.text(self._xy(2, 40), f"{m}m", fill=DIM, font=self.font)
        return self._finalize(img)

    def page_procs(self, snap: Snapshot, *, title: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "TOP")[:10], fill=CYAN, font=self.font)
        y = 14
        for name, cpu in snap.top_processes[:4]:
            d.text(self._xy(2, y), f"{name[:8]}", fill=FG, font=self.font_sm)
            d.text(self._xy(42, y), f"{cpu:.0f}", fill=YELLOW, font=self.font_sm)
            y += 12
        if not snap.top_processes:
            d.text(self._xy(2, 28), "…", fill=DIM, font=self.font)
        return self._finalize(img)

    def page_load(self, snap: Snapshot, *, title: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "LOAD")[:10], fill=CYAN, font=self.font)
        if snap.load_avg:
            l1, l5, l15 = snap.load_avg
            d.text(self._xy(2, 16), f"1m {l1:.2f}", fill=FG, font=self.font)
            d.text(self._xy(2, 32), f"5m {l5:.2f}", fill=DIM, font=self.font)
            d.text(self._xy(2, 48), f"15 {l15:.2f}", fill=DIM, font=self.font)
        else:
            d.text(self._xy(2, 28), "N/A", fill=DIM, font=self.font_lg)
        return self._finalize(img)

    def page_services(self, snap: Snapshot, *, title: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "SVC")[:10], fill=CYAN, font=self.font)
        services = snap.nc.services[:5]
        if not services:
            d.text(self._xy(2, 24), "n/a", fill=DIM, font=self.font)
            d.text(self._xy(2, 40), "no systemd", fill=DIM, font=self.font_sm)
            return self._finalize(img)
        y = 12
        for svc in services:
            short = _short_svc(svc.name)
            if svc.active is True:
                mark, col = "OK", GREEN
            elif svc.active is False:
                mark, col = "KO", RED
            else:
                mark, col = "?", DIM
            d.text(self._xy(2, y), short[:4], fill=DIM, font=self.font_sm)
            d.text(self._xy(28, y), mark, fill=col, font=self.font_sm)
            x0, y0 = self._xy(54, y + 1)
            x1, y1 = self._xy(60, y + 7)
            if self.native:
                x0, y0, x1, y1 = 54, y + 1, 60, y + 7
            d.rectangle([x0, y0, x1, y1], fill=col)
            y += 10
        return self._finalize(img)

    def page_nc_disk(self, snap: Snapshot, *, title: str | None = None, style: str | None = None) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), (title or "NC DSK")[:10], fill=CYAN, font=self.font)
        pct = snap.nc.nc_disk_percent
        if pct is None:
            pct = snap.disk_percent
        pct = pct if pct is not None else 0.0
        col = _bar_color(
            pct, 80, float(self.thr.get("nc_disk_percent", self.thr.get("disk_percent", 90)))
        )
        used = snap.nc.nc_disk_used_gb if snap.nc.nc_disk_used_gb is not None else snap.disk_used_gb
        total = (
            snap.nc.nc_disk_total_gb if snap.nc.nc_disk_total_gb is not None else snap.disk_total_gb
        )
        path = (snap.nc.nc_disk_path or snap.disk_path or "")[-14:]
        use = self._style_for("nc_disk", style)

        if use == "pie":
            d.text(self._xy(2, 12), f"{pct:.0f}%", fill=col, font=self.font_lg)
            if snap.nc.nc_data_size_gb is not None:
                d.text(self._xy(2, 28), f"data {snap.nc.nc_data_size_gb:.0f}G", fill=FG, font=self.font_sm)
            elif used is not None and total is not None:
                d.text(self._xy(2, 28), f"{used:.0f}/{total:.0f}G", fill=DIM, font=self.font_sm)
            d.text(self._xy(2, 40), path[:10], fill=DIM, font=self.font_sm)
            self._draw_pie(d, 46, 42, 16 if self.native else 15, pct, col)
        else:
            d.text(self._xy(2, 14), f"{pct:.0f}%", fill=col, font=self.font_lg)
            if snap.nc.nc_data_size_gb is not None:
                d.text(self._xy(2, 30), f"data {snap.nc.nc_data_size_gb:.0f}G", fill=FG, font=self.font_sm)
            if used is not None and total is not None:
                d.text(self._xy(2, 42), f"{used:.0f}/{total:.0f}G", fill=DIM, font=self.font_sm)
            d.text(self._xy(2, 52), path, fill=DIM, font=self.font_sm)
            self._draw_bar(d, 2, 58, 60, 3 if self.native else 4, pct, col)
        return self._finalize(img)

    def page_nc_http(self, snap: Snapshot) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), "NC HTTP", fill=CYAN, font=self.font)
        ok = snap.nc.nc_http_ok
        if ok is True:
            col, label = GREEN, "OK"
        elif ok is False:
            col, label = RED, "KO"
        else:
            col, label = DIM, "N/A"
        d.text(self._xy(2, 16), label, fill=col, font=self.font_lg)
        code = snap.nc.nc_http_code
        d.text(self._xy(2, 34), f"code {code}" if code else "—", fill=FG, font=self.font_sm)
        d.text(self._xy(2, 46), (snap.nc.nc_http_detail or "")[:12], fill=DIM, font=self.font_sm)
        return self._finalize(img)

    def page_nc_stack(self, snap: Snapshot) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), "NC", fill=CYAN, font=self.font)
        y = 12
        rows = 0

        if self.metrics.get("db_health"):
            ok = snap.nc.db_ok
            col = GREEN if ok else (RED if ok is False else DIM)
            conn = snap.nc.db_connections
            extra = f" {conn}" if conn is not None else ""
            d.text(self._xy(2, y), f"DB{extra}", fill=DIM, font=self.font_sm)
            d.text(self._xy(40, y), "OK" if ok else ("KO" if ok is False else "?"), fill=col, font=self.font_sm)
            y += 10
            rows += 1

        if self.metrics.get("redis"):
            ok = snap.nc.redis_ok
            col = GREEN if ok else (RED if ok is False else DIM)
            mem = snap.nc.redis_memory_mb
            label = f"RDS {mem:.0f}M" if mem is not None else "RDS"
            d.text(self._xy(2, y), label[:10], fill=DIM, font=self.font_sm)
            d.text(self._xy(40, y), "OK" if ok else ("KO" if ok is False else "?"), fill=col, font=self.font_sm)
            y += 10
            rows += 1

        if self.metrics.get("php_fpm_workers"):
            a, t = snap.nc.php_fpm_active, snap.nc.php_fpm_total
            if a is not None and t is not None and t > 0:
                pct = 100.0 * a / t
                col = _bar_color(pct, 70, 90)
                d.text(self._xy(2, y), f"FPM {a}/{t}", fill=col, font=self.font_sm)
            else:
                d.text(
                    self._xy(2, y),
                    f"FPM {snap.nc.php_fpm_detail[:8] or 'n/a'}",
                    fill=DIM,
                    font=self.font_sm,
                )
            y += 10
            rows += 1

        if self.metrics.get("nc_cron"):
            ok = snap.nc.nc_cron_ok
            col = GREEN if ok else (YELLOW if ok is False else DIM)
            age = snap.nc.nc_cron_age_min
            age_s = f"{age:.0f}m" if age is not None else "?"
            d.text(self._xy(2, y), f"CRN {age_s}", fill=DIM, font=self.font_sm)
            d.text(self._xy(40, y), "OK" if ok else ("KO" if ok is False else "?"), fill=col, font=self.font_sm)
            y += 10
            rows += 1

        if self.metrics.get("nc_errors") and rows < 5:
            n = snap.nc.nc_error_count
            col = RED if (n is not None and n > 5) else (YELLOW if (n is not None and n > 0) else DIM)
            d.text(self._xy(2, y), f"ERR {n if n is not None else '?'}", fill=col, font=self.font_sm)
            rows += 1

        if rows == 0:
            d.text(self._xy(2, 28), "n/a", fill=DIM, font=self.font)
        return self._finalize(img)

    def page_status(self, snap: Snapshot) -> Image.Image:
        img, d = self._new()
        st = snap.status
        overall = st.overall if self.metrics.get("status_overall") else (
            st.items[0][1] if st.items else "unknown"
        )
        col = _health_color(overall)
        d.text(self._xy(2, 1), "STATUS", fill=CYAN, font=self.font_sm)
        label = st.overall_label or overall.upper()
        d.text(self._xy(2, 11), label[:10], fill=col, font=self.font)

        items = st.items[:6]
        if not items:
            d.text(self._xy(2, 36), "no checks", fill=DIM, font=self.font_sm)
            return self._finalize(img)

        x = 2
        y = 28
        for name, h in items:
            c = _health_color(h)
            x0, y0 = self._xy(x, y)
            x1, y1 = self._xy(x + 8, y + 8)
            if self.native:
                x0, y0, x1, y1 = x, y, x + 8, y + 8
            d.rectangle([x0, y0, x1, y1], fill=c)
            d.text(self._xy(x, y + 10), name[:3], fill=DIM, font=self.font_sm)
            x += 10
            if x > 54:
                x = 2
                y = 48

        if st.os_label and self.metrics.get("status_host"):
            d.text(
                self._xy(2, 54),
                f"{st.host_name or ''} {st.os_label}".strip()[:14],
                fill=DIM,
                font=self.font_sm,
            )
        return self._finalize(img)

    def page_status_detail(self, snap: Snapshot) -> Image.Image:
        img, d = self._new()
        d.text(self._xy(2, 1), "HEALTH", fill=CYAN, font=self.font_sm)
        st = snap.status
        y = 12
        rows: list[tuple[str, str, Health]] = []
        if self.metrics.get("status_host"):
            rows.append(("HOST", st.os_label or "?", "ok" if st.host_ok else "unknown"))
        if self.metrics.get("status_nc_http"):
            rows.append(("NC", st.nc_http_detail[:6] or st.nc_http, st.nc_http))
        if self.metrics.get("status_services"):
            rows.append(("SVC", f"{st.services_ok}/{st.services_total}", st.services_health))
        if self.metrics.get("status_disk"):
            rows.append(("DSK", st.disk_detail or "?", st.disk_health))
        if self.metrics.get("status_network"):
            rows.append(("NET", st.network_iface or st.network_detail[:6], st.network_health))
        if self.metrics.get("status_thermal"):
            rows.append(("THM", st.thermal_detail[:8] or "?", st.thermal_health))

        for label, val, h in rows[:5]:
            c = _health_color(h)
            d.text(self._xy(2, y), label, fill=DIM, font=self.font_sm)
            d.text(self._xy(26, y), str(val)[:8], fill=c, font=self.font_sm)
            x0, y0 = self._xy(56, y + 1)
            x1, y1 = self._xy(62, y + 7)
            if self.native:
                x0, y0, x1, y1 = 56, y + 1, 62, y + 7
            d.rectangle([x0, y0, x1, y1], fill=c)
            y += 10
        return self._finalize(img)

    def page_custom_screen(self, snap: Snapshot, screen: dict[str, Any]) -> Image.Image:
        """Écran custom : titre + jusqu'à ~4 métriques avec style pie/barre par mesure."""
        from .screens import GAUGE_METRIC_KEYS, metric_style, resolve_screen_title

        metrics = list(screen.get("metrics") or [])
        title = resolve_screen_title(screen)

        # Un seul item → page dédiée riche
        if len(metrics) == 1:
            m = metrics[0]
            st = metric_style(screen, m, self._style_for(m))
            if m in ("cpu", "cpu_per_core"):
                return self.page_cpu(snap, title=title, style=st)
            if m == "ram":
                return self.page_mem(
                    snap, title=title, include_ram=True, include_swap=False,
                    ram_style=st, force=True,
                )
            if m == "swap":
                return self.page_mem(
                    snap, title=title, include_ram=False, include_swap=True,
                    swap_style=st, force=True,
                )
            if m == "disk":
                return self.page_disk(snap, title=title, style=st)
            if m == "nc_disk":
                return self.page_nc_disk(snap, title=title, style=st)
            if m == "network":
                return self.page_net(snap, title=title)
            if m == "temperature":
                return self.page_temp(snap, title=title)
            if m == "load_avg":
                return self.page_load(snap, title=title)
            if m == "uptime":
                return self.page_uptime(snap, title=title)
            if m == "processes":
                return self.page_procs(snap, title=title)
            if m == "services":
                return self.page_services(snap, title=title)
            if m == "nc_http":
                return self.page_nc_http(snap)
            if m in ("db_health", "redis", "php_fpm_workers", "nc_cron", "nc_errors"):
                return self.page_nc_stack(snap)
            if m.startswith("status_"):
                return self.page_status(snap)

        # Composite multi-métriques
        img, d = self._new()
        d.text(self._xy(2, 1), title[:10], fill=CYAN, font=self.font_sm)
        y = 12
        for key in metrics[:4]:
            st = metric_style(screen, key, self._style_for(key))
            label, pct, warn, crit = self._metric_pct_row(snap, key)
            if pct is not None and key in GAUGE_METRIC_KEYS:
                col = _bar_color(pct, warn, crit)
                d.text(self._xy(2, y), label[:4], fill=DIM, font=self.font_sm)
                d.text(self._xy(22, y), f"{pct:4.0f}%", fill=col, font=self.font_sm)
                if st == "pie":
                    self._draw_pie(d, 54, y + 5, 5, pct, col)
                else:
                    self._draw_bar(d, 2, y + 9, 60, 3 if self.native else 4, pct, col)
                y += 13
            else:
                text = self._metric_text_row(snap, key)
                d.text(self._xy(2, y), text[:16], fill=FG, font=self.font_sm)
                y += 12
            if y > 52:
                break
        return self._finalize(img)

    def _metric_pct_row(
        self, snap: Snapshot, key: str
    ) -> tuple[str, float | None, float, float]:
        labels = {
            "cpu": ("CPU", snap.cpu_percent, 70.0, float(self.thr.get("cpu_percent", 90))),
            "ram": ("RAM", snap.ram_percent, 75.0, float(self.thr.get("ram_percent", 90))),
            "swap": ("SWP", snap.swap_percent, 50.0, float(self.thr.get("swap_percent", 80))),
            "disk": ("DSK", snap.disk_percent, 80.0, float(self.thr.get("disk_percent", 90))),
            "nc_disk": (
                "NCD",
                snap.nc.nc_disk_percent if snap.nc.nc_disk_percent is not None else snap.disk_percent,
                80.0,
                float(self.thr.get("nc_disk_percent", 90)),
            ),
            "php_fpm_workers": ("FPM", None, 70.0, 90.0),
        }
        if key == "php_fpm_workers":
            a, t = snap.nc.php_fpm_active, snap.nc.php_fpm_total
            pct = (100.0 * a / t) if a is not None and t else None
            return ("FPM", pct, 70.0, 90.0)
        if key in labels:
            lab, pct, w, c = labels[key]
            return lab, pct, w, c
        return (key[:3].upper(), None, 70.0, 90.0)

    def _metric_text_row(self, snap: Snapshot, key: str) -> str:
        if key == "load_avg" and snap.load_avg:
            return f"LD {snap.load_avg[0]:.2f}"
        if key == "network":
            return f"↓{_fmt_rate(snap.net_down_kbps)} ↑{_fmt_rate(snap.net_up_kbps)}"
        if key == "temperature" and snap.temperatures:
            return f"T {snap.temperatures[0][1]:.0f}C"
        if key == "uptime" and snap.uptime_hours is not None:
            return f"UP {snap.uptime_hours:.0f}h"
        if key == "nc_http":
            ok = snap.nc.nc_http_ok
            return f"NC {'OK' if ok else ('KO' if ok is False else '?')}"
        if key == "services":
            ok = sum(1 for s in snap.nc.services if s.active)
            return f"SVC {ok}/{len(snap.nc.services)}"
        return key[:12]

    def build_pages(self, snap: Snapshot) -> list[tuple[str, Image.Image]]:
        pages: list[tuple[str, Image.Image]] = []
        m = self.metrics

        # Écrans personnalisés (prioritaires si définis)
        if self.screens:
            for scr in self.screens:
                sid = str(scr.get("id") or "scr")
                pages.append((f"scr_{sid}", self.page_custom_screen(snap, scr)))
            # Historique toujours en plus si configuré
            pages.extend(self._history_pages())
            if pages:
                return pages

        status_on = any(
            m.get(k)
            for k in (
                "status_host",
                "status_nc_http",
                "status_services",
                "status_disk",
                "status_network",
                "status_thermal",
                "status_overall",
            )
        )
        if status_on:
            pages.append(("status", self.page_status(snap)))
            if (
                sum(
                    1
                    for k in (
                        "status_host",
                        "status_nc_http",
                        "status_services",
                        "status_disk",
                        "status_network",
                        "status_thermal",
                    )
                    if m.get(k)
                )
                >= 3
            ):
                pages.append(("health", self.page_status_detail(snap)))

        if self.display.get("overview", True) and any(m.get(k) for k in ("cpu", "ram", "swap", "disk")):
            pages.append(("overview", self.page_overview(snap)))

        if self.display.get("n40_thermal") or (
            m.get("temperature")
            and m.get("load_avg")
            and m.get("cpu")
            and not self.display.get("overview", True)
        ):
            if m.get("cpu") or m.get("temperature") or m.get("load_avg"):
                pages.append(("n40", self.page_n40(snap)))

        if m.get("cpu") or m.get("cpu_per_core"):
            pages.append(("cpu", self.page_cpu(snap, style=self._style_for("cpu"))))
        elif m.get("load_avg") and not any(p[0] == "n40" for p in pages):
            pages.append(("load", self.page_load(snap)))

        if m.get("ram") or m.get("swap"):
            pages.append((
                "mem",
                self.page_mem(
                    snap,
                    include_ram=bool(m.get("ram")),
                    include_swap=bool(m.get("swap")),
                    ram_style=self._style_for("ram"),
                    swap_style=self._style_for("swap"),
                ),
            ))

        if m.get("disk"):
            pages.append(("disk", self.page_disk(snap, style=self._style_for("disk"))))

        if m.get("nc_disk"):
            pages.append(("nc_disk", self.page_nc_disk(snap, style=self._style_for("nc_disk"))))

        if m.get("network"):
            pages.append(("net", self.page_net(snap)))

        if m.get("temperature") and not any(p[0] == "n40" for p in pages):
            pages.append(("temp", self.page_temp(snap)))

        if m.get("services"):
            pages.append(("services", self.page_services(snap)))

        if m.get("nc_http"):
            pages.append(("nc_http", self.page_nc_http(snap)))

        if any(m.get(k) for k in ("db_health", "redis", "php_fpm_workers", "nc_cron", "nc_errors")):
            pages.append(("nc_stack", self.page_nc_stack(snap)))

        if m.get("uptime"):
            pages.append(("uptime", self.page_uptime(snap)))

        if m.get("processes"):
            pages.append(("procs", self.page_procs(snap)))

        pages.extend(self._history_pages())

        if not pages:
            img, d = self._new()
            d.text(self._xy(4, 24), "no metrics", fill=DIM, font=self.font)
            pages.append(("empty", self._finalize(img)))

        return pages

    def _history_pages(self) -> list[tuple[str, Image.Image]]:
        store = getattr(self, "history", None)
        if store is None:
            return []
        pages: list[tuple[str, Image.Image]] = []
        short = {
            "cpu": "CPU",
            "ram": "RAM",
            "swap": "SWP",
            "disk": "DSK",
            "network": "NET↓",
            "net_up": "NET↑",
            "temperature": "TMP",
            "load_avg": "LOAD",
            "nc_disk": "NCD",
            "php_fpm_workers": "FPM",
        }
        for metric, conf in store.enabled.items():
            buckets, fill, period = store.buckets(metric)
            img = self.page_history(metric, short.get(metric, metric[:4].upper()), buckets, fill, period)
            pages.append((f"hist_{metric}", img))
        return pages

    def page_history(
        self,
        metric: str,
        title: str,
        buckets: list[float | None],
        fill: float,
        period: str,
    ) -> Image.Image:
        """Sparkline colonnes + barre de progression (fenêtre qui se remplit)."""
        img, d = self._new()
        d.text(self._xy(2, 1), title[:6], fill=CYAN, font=self.font_sm)
        d.text(self._xy(28, 1), period[:8], fill=DIM, font=self.font_sm)

        # Zone graphe : y=12..50, x=2..61
        chart_x, chart_y = 2, 12
        chart_w, chart_h = 60, 38
        vals = [v for v in buckets if v is not None]
        if vals:
            vmin = min(vals)
            vmax = max(vals)
            if abs(vmax - vmin) < 1e-6:
                vmax = vmin + 1.0
            # Pour % metrics, ancrer 0–100 si pertinent
            if metric in ("cpu", "ram", "swap", "disk", "nc_disk", "php_fpm_workers"):
                vmin, vmax = 0.0, max(100.0, vmax)
        else:
            vmin, vmax = 0.0, 1.0

        n = max(len(buckets), 1)
        col_w = max(1, chart_w // n)
        # Recentre si moins de colonnes que la largeur
        usable = min(n, chart_w)
        step = max(1, chart_w // usable) if usable else 1

        for i, v in enumerate(buckets[:usable]):
            x = chart_x + i * step
            if v is None:
                # marqueur bas très sombre = pas encore de donnée
                y0 = chart_y + chart_h - 1
                self._plot_col(d, x, y0, max(1, step - (0 if self.native else 0)), 1, (30, 30, 40))
                continue
            norm = (v - vmin) / (vmax - vmin)
            h = max(1, int(round(norm * (chart_h - 1))))
            y0 = chart_y + chart_h - h
            col = _bar_color(
                (v if metric in ("cpu", "ram", "swap", "disk", "nc_disk", "php_fpm_workers") else norm * 100),
                70,
                90,
            )
            self._plot_col(d, x, y0, max(1, step - (1 if step > 1 and not self.native else 0)), h, col)

        # Dernière valeur
        last = next((v for v in reversed(buckets) if v is not None), None)
        if last is not None:
            if metric in ("network", "net_up"):
                label = f"{last:.0f}"
            elif metric == "load_avg":
                label = f"{last:.2f}"
            else:
                label = f"{last:.0f}"
            d.text(self._xy(2, 52), label[:8], fill=FG, font=self.font_sm)

        # Barre de progression (warming up → pleine fenêtre)
        fill = max(0.0, min(1.0, fill))
        prog_w = 60
        filled = max(0, int(round(prog_w * fill)))
        bx, by = self._xy(2, 60)
        if self.native:
            bx, by = 2, 60
            d.rectangle([bx, by, bx + prog_w, by + 2], fill=(30, 30, 40))
            if filled:
                d.rectangle([bx, by, bx + filled, by + 2], fill=CYAN if fill < 1 else GREEN)
        else:
            d.rectangle(
                [bx, by, bx + self._p(prog_w), by + max(2, self.scale)],
                fill=(30, 30, 40),
            )
            if filled:
                d.rectangle(
                    [bx, by, bx + self._p(filled), by + max(2, self.scale)],
                    fill=CYAN if fill < 1 else GREEN,
                )

        return self._finalize(img)

    def _plot_col(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        w: int,
        h: int,
        color: Color,
    ) -> None:
        """Colonne sparkline en coords logiques."""
        if self.native:
            draw.rectangle([int(x), int(y), int(x + max(1, w) - 1), int(y + max(1, h) - 1)], fill=color)
        else:
            x0, y0 = self._p(x), self._p(y)
            x1 = self._p(x + max(1, w)) - 1
            y1 = self._p(y + max(1, h)) - 1
            draw.rectangle([x0, y0, x1, y1], fill=color)


PageBuilder = Callable[[Snapshot], Image.Image]
