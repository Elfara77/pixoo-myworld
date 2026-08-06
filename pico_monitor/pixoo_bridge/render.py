"""64×64 RGB screens from pico_monitor /metrics.json (Merlin exporter).

Pixel fonts (no antialias).
PIXOO_COLOR_MODE: mono = values solid white; labels cyan banner tone (or dim/red);
  poly = same label rules; values colored per metric.
Status (LAN/USB/WAN) always green/red. Gauges/pies: green→yellow→orange→red.
"""

from __future__ import annotations

from typing import Any, Sequence

from PIL import Image, ImageDraw

from pixoo_bridge import pixel_font as pf

BG = (6, 8, 14)
FG = (240, 244, 250)
DIM = (100, 108, 122)
LABEL = (110, 118, 132)
UNIT = (95, 105, 120)
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
TEXT_MONO = (255, 255, 255)
MONO_DIM = (130, 130, 130)

# Wi‑Fi band labels (tiny font width on 64px layout)
LABEL_BAND_24 = "2.4GHz"
LABEL_BAND_5 = "5GHz"

# Default rotation ("all") — SUM is optional and never included by default.
ALL_SCREEN_IDS = ("SYS", "LOD", "TMP", "GRP", "WLC", "TOP", "CLI", "NET", "PIE", "SRV")
OPTIONAL_SCREEN_IDS = ("SUM", "SUM_GRAPH")
KNOWN_SCREEN_IDS = ALL_SCREEN_IDS + OPTIONAL_SCREEN_IDS
SCREEN_TITLES = {
    "SYS": "System",
    "LOD": "Load",
    "TMP": "Temps",
    "GRP": "Traffic",
    "WLC": "WiFi/Eth",
    "TOP": "Top",
    "CLI": "Clients",
    "NET": "Ports",
    "PIE": "Disks",
    "SRV": "Services",
    "SUM": "Summary",
    "SUM_GRAPH": "WAN hist",
}

_ACTIVE_SCREENS: list[str] = list(ALL_SCREEN_IDS)
SCREEN_IDS: tuple[str, ...] = tuple(_ACTIVE_SCREENS)

_COLOR_MODE = "mono"
_TEXT_SCROLL = True
_ALERT_BLINK = True
_BLINK_PERIOD_S = 0.55

CRIT_LOAD = 90.0
WARN_LOAD = 70.0
CRIT_TEMP_CPU = 85
WARN_TEMP_CPU = 70
CRIT_TEMP_RADIO = 65
WARN_TEMP_RADIO = 55
CRIT_DISK = 90.0
WARN_DISK = 70.0

_RATE_STYLE = "short"
# WLC WiFi/Eth + GRP WAN graphs: overlay = down+up same panel; split = down left, up right.
_WLC_GRAPH_MODE = "overlay"

# WAN saturation caps (Mbps) for SUM Net health / Top relative ranking.
_WAN_MAX_DOWN_MBPS = 190.0
_WAN_MAX_UP_MBPS = 12.0
# Soft client count at which Net client-load factor reaches 100% raw occupancy.
_NET_CLIENTS_SOFT = 24.0
# Client is "greedy" if down or up util vs WAN max is ≥ this fraction.
_GREEDY_UTIL = 0.40
# NET hybrid: ignore util below this fraction of WAN cap; EMA previous weight.
_NET_SIGNIF_UTIL = 0.05
_NET_SMOOTH_PREV = 0.6
_NET_SMOOTH_RAW = 0.4
_NET_SAT_SMOOTH: float | None = None
# Short histories for SUM SYS/NET gauge trend arrows (last samples).
_SYS_HP_HIST: list[float] = []
_NET_SAT_HIST: list[float] = []
# SUM dwell D split into 8 equal slots (Σ=D):
# 0–3 clients (4/8); 4–7 WAN graph (4/8) with DOWN|UP legend above the plot.
_SUM_DWELL_T0 = 0.0
_SUM_DWELL_D = 1.0


def set_sum_dwell(t0: float, dwell_s: float) -> None:
    """Bind SUM phase clock to the current rotator dwell (call each SUM frame)."""
    global _SUM_DWELL_T0, _SUM_DWELL_D
    _SUM_DWELL_T0 = float(t0)
    _SUM_DWELL_D = max(0.08, float(dwell_s))


def sum_phase() -> int:
    """0–7 within current SUM dwell (equal eighths of D, integer ms — no float edge flicker)."""
    import time

    elapsed_ms = max(0, int((time.monotonic() - _SUM_DWELL_T0) * 1000.0))
    dwell_ms = max(80, int(round(_SUM_DWELL_D * 1000.0)))
    return min(7, (elapsed_ms * 8) // dwell_ms)


def sum_show_wan_graph() -> bool:
    """True for the last 4/8 of the SUM dwell (graph window)."""
    return sum_phase() >= 4


# Graphs / dense lists: longer rotation dwell (× multiplier on PIXOO_SCREEN_SECONDS).
HEAVY_SCREEN_IDS = frozenset({"LOD", "GRP", "WLC", "TOP", "CLI", "TMP", "SUM", "SUM_GRAPH"})
_HEAVY_DWELL = True
_HEAVY_DWELL_MULT = 2.0


def screen_dwell_seconds(screen_id: str, base_seconds: float) -> float:
    """Seconds to show `screen_id`; heavy screens use base × multiplier when enabled."""
    base = max(1.0, float(base_seconds))
    if _HEAVY_DWELL and screen_id in HEAVY_SCREEN_IDS:
        return max(1.0, base * _HEAVY_DWELL_MULT)
    return base


def get_screen_ids() -> tuple[str, ...]:
    return tuple(_ACTIVE_SCREENS)


def set_screens(spec: str | None) -> tuple[str, ...]:
    """Parse screen list. ``all`` = defaults only (no SUM/SUM_GRAPH). ``all,SUM`` OK."""
    global SCREEN_IDS, _ACTIVE_SCREENS
    raw = "" if spec is None else str(spec).strip()
    if not raw or raw.lower() in ("*", "default"):
        raw = "all"
    tokens = [t.strip().upper() for t in raw.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
    # Allow SUMGRAPH as alias for SUM_GRAPH
    tokens = ["SUM_GRAPH" if t in ("SUMGRAPH", "GRAPH") else t for t in tokens]
    wanted: list[str] = []
    if any(t in ("ALL", "DEFAULT") for t in tokens):
        wanted = list(ALL_SCREEN_IDS)
        for sid in tokens:
            if sid in ("ALL", "DEFAULT"):
                continue
            if sid in KNOWN_SCREEN_IDS and sid not in wanted:
                wanted.append(sid)
    else:
        for sid in tokens:
            if sid in KNOWN_SCREEN_IDS and sid not in wanted:
                wanted.append(sid)
    _ACTIVE_SCREENS = wanted if wanted else list(ALL_SCREEN_IDS)
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
    heavy_screen_dwell: bool | None = None,
    heavy_screen_multiplier: float | None = None,
    wlc_graph_mode: str | None = None,
    wan_max_down_mbps: float | None = None,
    wan_max_up_mbps: float | None = None,
) -> None:
    global _COLOR_MODE, _TEXT_SCROLL, _ALERT_BLINK, _BLINK_PERIOD_S, _RATE_STYLE
    global _HEAVY_DWELL, _HEAVY_DWELL_MULT, _WLC_GRAPH_MODE
    global _WAN_MAX_DOWN_MBPS, _WAN_MAX_UP_MBPS
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
    if heavy_screen_dwell is not None:
        _HEAVY_DWELL = bool(heavy_screen_dwell)
    if heavy_screen_multiplier is not None:
        _HEAVY_DWELL_MULT = max(1.0, float(heavy_screen_multiplier))
    if wlc_graph_mode is not None:
        m = str(wlc_graph_mode).strip().lower()
        if m in ("split", "lr", "left-right", "left", "side", "dual"):
            _WLC_GRAPH_MODE = "split"
        else:
            _WLC_GRAPH_MODE = "overlay"
    if wan_max_down_mbps is not None:
        _WAN_MAX_DOWN_MBPS = max(0.1, float(wan_max_down_mbps))
    if wan_max_up_mbps is not None:
        _WAN_MAX_UP_MBPS = max(0.1, float(wan_max_up_mbps))


def _blink_on() -> bool:
    if not _ALERT_BLINK:
        return True
    import time

    return (int(time.monotonic() / _BLINK_PERIOD_S) % 2) == 0


def _resolve_label_color(color: Sequence[int], *, negligible: bool = False) -> tuple[int, int, int]:
    """Banner cyan for labels; never grey (negligible applies to values only)."""
    del negligible  # labels stay banner-colored
    if tuple(int(c) for c in color) == LABEL:
        return HEADER
    return (int(color[0]), int(color[1]), int(color[2]))


def _rate_is_negligible(mbps: float) -> bool:
    num, unit = _split_rate(float(mbps or 0))
    return _rate_display_color(float(mbps or 0), num, unit) == DIM


def _txt_label(
    img,
    x: int,
    y: int,
    text: str,
    *,
    alert: bool = False,
    negligible: bool = False,
    mbps: float | None = None,
) -> int:
    del negligible, mbps  # labels never grey
    return _txt(img, x, y, text, LABEL, size="tiny", role="label", alert=alert)


def _ink(color: Sequence[int], *, role: str = "value") -> tuple[int, int, int]:
    """role: label|unit|value|status|alert — values stand out from labels/units."""
    if role in ("status", "label"):
        return (int(color[0]), int(color[1]), int(color[2]))
    if role == "alert":
        return RED
    if _COLOR_MODE == "mono":
        if role == "unit":
            return MONO_DIM
        return TEXT_MONO
    if role == "unit":
        return UNIT
    return (int(color[0]), int(color[1]), int(color[2]))


def _txt(
    img,
    x: int,
    y: int,
    text: str,
    color: Sequence[int],
    *,
    size: str = "normal",
    role: str = "value",
    alert: bool = False,
    label_negligible: bool = False,
) -> int:
    if alert and _ALERT_BLINK and not _blink_on():
        return x
    if role == "label":
        color = _resolve_label_color(color, negligible=label_negligible)
    col = _ink(RED if alert else color, role="alert" if alert else role)
    return pf.draw_text(img, x, y, text, col, size=size)


def _split_rate(mbps: float) -> tuple[str, str]:
    """Return (number, unit). Promote when >999: K→M→G→T (integer, no '.')."""
    v = float(mbps or 0)
    if v <= 0:
        return ("0", "Kb/s" if _RATE_STYLE == "long" else "K")

    if _RATE_STYLE == "long":
        # Work in Kb/s then promote at >999
        kb = v * 1000.0
        if kb <= 999:
            return f"{int(round(kb))}", "Kb/s"
        mb = v
        if mb <= 999:
            return f"{int(round(mb))}", "Mb/s"
        gb = v / 1000.0
        if gb <= 999:
            return f"{int(round(gb))}", "Gb/s"
        tb = gb / 1000.0
        return f"{max(1, int(round(tb)))}", "Tb/s"

    # Short: K / M / G / T from Mbps
    kb = v * 1000.0
    if kb <= 999:
        return f"{int(round(kb))}", "K"
    if v <= 999:
        return f"{int(round(v))}", "M"
    g = v / 1000.0
    if g <= 999:
        return f"{int(round(g))}", "G"
    t = g / 1000.0
    return f"{max(1, int(round(t)))}", "T"


def _compact_uptime_str(raw: str) -> str:
    """Normalize uptime token for SUM footer (same rules as metrics_server)."""
    s = str(raw or "--").strip()
    if not s or s == "--" or s == "WAN":
        return s or "--"
    # Already compact forms
    if s.endswith("d") and "h" not in s and "m" not in s:
        return s
    days = hours = mins = 0
    try:
        if "d" in s:
            dpart, rest = s.split("d", 1)
            days = int(dpart or 0)
            if rest.endswith("h"):
                hours = int(rest[:-1] or 0)
        elif "h" in s:
            hpart, rest = s.split("h", 1)
            hours = int(hpart or 0)
            if rest.endswith("m"):
                mins = int(rest[:-1] or 0)
        elif s.endswith("m"):
            mins = int(s[:-1] or 0)
        else:
            return s[:6]
    except ValueError:
        return s[:6]
    if days > 9:
        return f"{days}d"
    if days > 0:
        return f"{days}d{hours}h"
    if hours > 9:
        return f"0d{hours}h"
    if hours > 0:
        return f"{hours}h{mins:02d}m"
    return f"{mins}m"


def _rate_short(mbps: float) -> str:
    n, u = _split_rate(mbps)
    return f"{n}{u}"


def _rate(mbps: float) -> str:
    n, u = _split_rate(mbps)
    if _RATE_STYLE == "long":
        return f"{n} {u}"
    return f"{n}{u}"


def _scroll(text: str, max_chars: int) -> str:
    return pf.scroll_slice(text, max_chars, enabled=_TEXT_SCROLL)


def _temp_avg(m: dict[str, Any]) -> int:
    vals = [int(m.get(k, 0) or 0) for k in ("temp_cpu", "temp_2g", "temp_5g")]
    vals = [v for v in vals if v > 0]
    return int(round(sum(vals) / len(vals))) if vals else 0


def _temp_tile_color(celsius: float) -> tuple[int, int, int]:
    """Temp value color: green <70°C, yellow 70–80°C, red >80°C."""
    t = float(celsius or 0)
    if t <= 0:
        return DIM
    if t > 80:
        return RED
    if t >= 70:
        return YELLOW
    return GREEN


def _disk_tile_color(used_pct: float) -> tuple[int, int, int]:
    """Disk % used for pies/labels: green low, yellow medium, red high."""
    p = float(used_pct or 0)
    if p >= CRIT_DISK:
        return RED
    if p >= WARN_DISK:
        return YELLOW
    return GREEN


def _diagram_color(pct: float, *, kind: str = "load") -> tuple[int, int, int]:
    """Gauges, pies, bars: green / yellow / red from current value (matches fill color)."""
    p = float(pct or 0)
    if kind in ("disk", "disk_tile"):
        return _disk_tile_color(p)
    if kind in ("temp", "temp_cpu", "temp_tile"):
        return _temp_tile_color(p)
    if p >= CRIT_LOAD:
        return RED
    if p >= WARN_LOAD:
        return YELLOW
    return GREEN


def _level_color(pct: float, *, kind: str = "load") -> tuple[int, int, int]:
    """Alias for gauges/graphs; diagram metrics use green/yellow/red only."""
    if kind in ("load", "disk", "disk_tile", "temp", "temp_cpu", "temp_tile"):
        return _diagram_color(pct, kind=kind)
    return _diagram_color(pct, kind="load")


def _is_crit_load(pct: float) -> bool:
    return float(pct or 0) >= CRIT_LOAD


def _is_crit_disk(pct: float) -> bool:
    return float(pct or 0) >= CRIT_DISK


def _is_crit_temp_tile(val: int) -> bool:
    return int(val) > 80


def _is_crit_disk_tile(pct: float) -> bool:
    return float(pct or 0) >= CRIT_DISK


def _is_crit_temp(label: str, val: int) -> bool:
    if label == "CPU":
        return val >= CRIT_TEMP_CPU
    if label in ("2G", "5G", "AVG", "TMP"):
        return val >= CRIT_TEMP_RADIO
    return False


def _rate_display_color(mbps: float, num: str, unit: str) -> tuple[int, int, int]:
    """Throughput: 0K inactive gray; K>0 green; M/G yellow (no red)."""
    blob = f"{num}{unit}".lower().replace(" ", "")
    if blob.startswith("0k") or (num.strip() in ("0", "0.0") and unit.upper().startswith("K")):
        return DIM
    u = unit.strip().upper()
    if u.startswith("G") or u.startswith("M"):
        return YELLOW
    if u.startswith("K"):
        return GREEN
    return FG


def _wan_link_color(mbps: float, max_mbps: float) -> tuple[int, int, int]:
    """Color vs WAN cap: gray idle, green <40%, yellow 40–70%, red ≥70%."""
    v = float(mbps or 0)
    cap = max(0.1, float(max_mbps))
    if v <= 0 or _rate_is_negligible(v):
        return DIM
    util = v / cap
    if util < 0.40:
        return GREEN
    if util < 0.70:
        return YELLOW
    return RED


def _draw_rate(
    img,
    x: int,
    y: int,
    mbps: float,
    *,
    size: str = "tiny",
    alert: bool = False,
    color: Sequence[int] | None = None,
) -> int:
    num, unit = _split_rate(mbps)
    col = color if color is not None else _rate_display_color(mbps, num, unit)
    return _draw_val_unit(
        img, x, y, num, unit, col, size=size, value_role="status", alert=alert
    )


def _rate_pixel_width(mbps: float, *, size: str = "tiny") -> int:
    """Advance width of a rate (includes trailing tiny spacer after unit)."""
    num, unit = _split_rate(mbps)
    w = pf.text_width(num, size=size)
    if unit:
        w += 1 + pf.text_width(unit, size=size)
    return w


def _rate_ink_width(mbps: float, *, size: str = "tiny") -> int:
    """Width through last lit pixel of a rate (flush-right)."""
    num, unit = _split_rate(mbps)
    if not unit:
        return pf.text_ink_width(num, size=size)
    # num advance + 1px gap + unit ink (same structure as _draw_val_unit)
    return pf.text_width(num, size=size) + 1 + pf.text_ink_width(unit, size=size)


def _draw_rate_right(
    img,
    right: int,
    y: int,
    mbps: float,
    *,
    size: str = "tiny",
    color: Sequence[int] | None = None,
) -> int:
    """Draw rate with last ink on `right` (inclusive). Returns start x."""
    w = _rate_ink_width(mbps, size=size)
    x = max(0, right - w + 1)
    _draw_rate(img, x, y, mbps, size=size, color=color)
    return x


def _rate_dir_tag_ink_width(mbps: float, tag: str, *, size: str = "tiny") -> int:
    """Width through last ink of rate + 1px gap + direction tag."""
    return _rate_ink_width(mbps, size=size) + 1 + pf.text_ink_width(tag, size=size)


def _draw_rate_dir_tag_right(
    img,
    right: int,
    y: int,
    mbps: float,
    tag: str,
    tag_color: Sequence[int],
    *,
    size: str = "tiny",
    rate_color: Sequence[int] | None = None,
) -> int:
    """Draw rate then direction tag (U/D) flush-right. Returns rate start x."""
    tag_ink = pf.text_ink_width(tag, size=size)
    tag_x = max(0, right - tag_ink + 1)
    rate_right = tag_x - 2  # 1px gap before tag
    rx = _draw_rate_right(img, rate_right, y, mbps, size=size, color=rate_color)
    _txt(img, tag_x, y, tag, tag_color, size=size, role="status")
    return rx


def _draw_val_unit_right(
    img,
    right: int,
    y: int,
    num: str,
    unit: str,
    val_color: Sequence[int],
    *,
    size: str = "tiny",
    value_role: str = "status",
    alert: bool = False,
) -> int:
    """Draw num+unit with last ink on `right`. Returns start x."""
    w = pf.text_width(num, size=size)
    if unit:
        w += 1 + pf.text_ink_width(unit, size=size)
    else:
        w = pf.text_ink_width(num, size=size)
    x = max(0, right - w + 1)
    _draw_val_unit(
        img, x, y, num, unit, val_color, size=size, value_role=value_role, alert=alert
    )
    return x


def _truncate_to_width(text: str, max_w: int, *, size: str = "tiny") -> str:
    if max_w <= 0:
        return ""
    out = ""
    for ch in text:
        trial = out + ch
        if pf.text_width(trial, size=size) > max_w:
            break
        out = trial
    return out


def _draw_val_unit(
    img,
    x: int,
    y: int,
    num: str,
    unit: str,
    val_color: Sequence[int],
    *,
    size: str = "normal",
    unit_size: str | None = None,
    value_role: str = "value",
    alert: bool = False,
) -> int:
    x = _txt(img, x, y, num, val_color, size=size, role=value_role, alert=alert)
    if unit:
        us = unit_size or ("tiny" if size not in ("big", "normal") else "normal")
        y_off = 0 if size != "big" else 2
        if us == "tiny" and size == "normal":
            y_off = 1
        u_role = "status" if value_role == "status" else "unit"
        u_col = val_color if u_role == "status" else UNIT
        x = _txt(img, x + 1, y + y_off, unit, u_col, size=us, role=u_role)
    return x


def _cli_count_color(n: int) -> tuple[int, int, int]:
    return DIM if int(n or 0) == 0 else GREEN


def _draw_cli_count(img, x: int, y: int, n: int, *, size: str = "tiny") -> int:
    n = int(n or 0)
    return _txt(img, x, y, str(n), _cli_count_color(n), size=size, role="status")


def _draw_client_count(img, x: int, y: int, n: int, *, size: str = "tiny") -> int:
    """Client totals: green if >0, red + optional blink if 0."""
    n = int(n or 0)
    if n == 0:
        return _txt(img, x, y, str(n), RED, size=size, role="status", alert=True)
    return _txt(img, x, y, str(n), GREEN, size=size, role="status")


def _header(img, draw: ImageDraw.ImageDraw, title: str, idx: int) -> None:
    screens = get_screen_ids()
    n = len(screens)
    draw.rectangle([0, 0, 63, 9], fill=HEADER)
    badge_w = 0
    if n > 1:
        label = str(idx + 1)
        tw = pf.text_width_tiny(label)
        # Full-height black strip on the right (not a tight box around the digit).
        badge_w = max(10, tw + 6)
        bx0 = 64 - badge_w
        draw.rectangle([bx0, 0, 63, 9], fill=HEADER_FG)
        draw.line([(bx0, 0), (bx0, 9)], fill=HEADER)
        text_x = bx0 + max(1, (badge_w - tw) // 2)
        pf.draw_tiny(img, text_x, 2, label, HEADER)
    title_chars = max(3, (63 - badge_w) // 6)
    shown = _scroll(title, title_chars)
    pf.draw_text(img, 1, 1, shown, HEADER_FG, size="normal")


def _gauge(draw, x: int, y: int, w: int, pct: float, color, *, alert: bool = False) -> None:
    pct = max(0.0, min(100.0, float(pct)))
    draw.rectangle([x, y, x + w - 1, y + 4], outline=DIM, fill=BAR_BG)
    fill = int((w - 2) * pct / 100)
    if fill <= 0:
        return
    if alert and _ALERT_BLINK:
        if not _blink_on():
            return
        color = RED
    elif alert:
        color = RED
    draw.rectangle([x + 1, y + 1, x + fill, y + 3], fill=color)


def _wifi_wired_split_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    wifi_mbps: float,
    wired_mbps: float,
    *,
    h: int = 5,
) -> None:
    """Full solid bar: WiFi orange (left) + Wired green (right) by rate ratio."""
    if w <= 0 or h <= 0:
        return
    wifi = max(0.0, float(wifi_mbps or 0))
    wired = max(0.0, float(wired_mbps or 0))
    total = wifi + wired
    x1 = x + w - 1
    y1 = y + h - 1
    if total <= 0:
        draw.rectangle([x, y, x1, y1], fill=BAR_BG)
        return
    # wifi_ratio = wifi/total → left width; remainder = wired (right).
    # Floor (not round) reduces 0.5-boundary left/right flicker.
    wifi_w = int(w * (wifi / total))
    wifi_w = max(0, min(w, wifi_w))
    if wifi_w >= w:
        draw.rectangle([x, y, x1, y1], fill=ORANGE)
        return
    if wifi_w <= 0:
        draw.rectangle([x, y, x1, y1], fill=GREEN)
        return
    draw.rectangle([x, y, x + wifi_w - 1, y1], fill=ORANGE)
    draw.rectangle([x + wifi_w, y, x1, y1], fill=GREEN)


def _draw_sum_down_up_split_gauges(
    img,
    draw: ImageDraw.ImageDraw,
    m: dict[str, Any],
    *,
    x0: int,
    x1: int,
    y: int,
    step: int,
) -> int:
    """Two full-width DOWN/UP WiFi|Wired bars; returns y after both rows."""
    # Align both gauges to the wider "DOWN" label.
    lab_w = pf.text_width("DOWN", size="tiny")
    gap = 1
    gx = x0 + lab_w + gap
    gw = max(4, x1 - gx + 1)
    bar_h = 5

    _txt(img, x0, y, "DOWN", LABEL, size="tiny", role="label")
    _wifi_wired_split_bar(
        draw,
        gx,
        y,
        gw,
        float(m.get("wifi_down", 0) or 0),
        float(m.get("lan_down", 0) or 0),
        h=bar_h,
    )
    y += step

    _txt(img, x0, y, "UP", LABEL, size="tiny", role="label")
    _wifi_wired_split_bar(
        draw,
        gx,
        y,
        gw,
        float(m.get("wifi_up", 0) or 0),
        float(m.get("lan_up", 0) or 0),
        h=bar_h,
    )
    return y + step


def _gauge_row(img, draw, y: int, label: str, pct: float, *, kind: str = "load") -> None:
    alert = _is_crit_load(pct) if kind == "load" else _is_crit_disk(pct)
    col = _diagram_color(pct, kind=kind if kind != "load" else "load")
    _txt(img, 2, y, label[:4], LABEL, size="tiny", role="label", alert=alert)
    _gauge(draw, 20, y, 42, pct, col, alert=alert)


def _graph_fill_color(color: Sequence[int], *, scale: float = 0.38) -> tuple[int, int, int]:
    """Solid area-under-curve tint — same hue, weaker than the stroke."""
    s = max(0.05, min(1.0, float(scale)))
    return (
        max(0, min(255, int(color[0] * s))),
        max(0, min(255, int(color[1] * s))),
        max(0, min(255, int(color[2] * s))),
    )


# Peak-hold Y scales so rolling history max changes don't yank the whole plot.
_GRAPH_Y_HOLD: dict[str, float] = {}


def _held_ymax(key: str, raw: float, *, decay: float = 0.94) -> float:
    """Instant rise, slow decay — kills temporal rescale jumps."""
    raw = max(0.01, float(raw or 0))
    prev = _GRAPH_Y_HOLD.get(key)
    if prev is None or raw > prev:
        held = raw
    else:
        held = max(raw, prev * decay)
    _GRAPH_Y_HOLD[key] = held
    return held


def _pad_series_right(series: list[float], n: int) -> list[float]:
    """Right-align samples in a fixed slot count (stable X map as history grows)."""
    n = max(2, int(n))
    if len(series) >= n:
        return [float(v) for v in series[-n:]]
    pad = n - len(series)
    return [0.0] * pad + [float(v) for v in series]


def _series_to_pts(
    series: list[float],
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    ymax: float,
) -> list[tuple[int, int]]:
    if not series or w <= 0 or h <= 0:
        return []
    mx = max(0.01, float(ymax))
    n = len(series)
    out: list[tuple[int, int]] = []
    for i, v in enumerate(series):
        px = x + int(i * (w - 1) / max(1, n - 1))
        py = y + h - 1 - int(max(0.0, min(1.0, float(v) / mx)) * (h - 1))
        out.append((px, py))
    return out


def _graph(img, draw, x, y, w, h, data, color, filled: bool = False, *, scale_key: str = "g") -> None:
    if not data:
        _txt(img, x + 4, y + max(0, h // 2 - 3), "NO DATA", DIM, size="tiny", role="label")
        return
    # Prefer width-aligned slots so X doesn't reshuffle while history fills.
    slots = max(2, min(int(w), max(len(data), 2)))
    series = _pad_series_right([float(v) for v in data], slots)
    ymax = _held_ymax(scale_key, max(series))
    pts = _series_to_pts(series, x=x, y=y, w=w, h=h, ymax=ymax)
    if filled and len(pts) >= 2:
        poly = pts + [(pts[-1][0], y + h - 1), (pts[0][0], y + h - 1)]
        draw.polygon(poly, fill=_graph_fill_color(color))
    if len(pts) >= 2:
        draw.line(pts, fill=color, width=1)


def _graph_up_down(
    img,
    draw,
    x,
    y,
    w,
    h,
    down,
    up,
    col_down,
    col_up,
    *,
    fill_down: bool = True,
    fill_up: bool | None = None,
    scale_key: str = "du",
) -> None:
    """Down + up on one panel with shared held Y scale; optional area fills."""
    down_r = [float(v) for v in (down or [])]
    up_r = [float(v) for v in (up or [])]
    if fill_up is None:
        fill_up = fill_down
    if not down_r and not up_r:
        _txt(img, x + 4, y + max(0, h // 2 - 3), "NO DATA", DIM, size="tiny", role="label")
        return

    slots = max(2, min(int(w), max(len(down_r), len(up_r), 2)))
    down_s = _pad_series_right(down_r, slots)
    up_s = _pad_series_right(up_r, slots)
    raw_max = max(max(down_s), max(up_s), 0.01)
    ymax = _held_ymax(scale_key, raw_max)

    d_pts = _series_to_pts(down_s, x=x, y=y, w=w, h=h, ymax=ymax)
    u_pts = _series_to_pts(up_s, x=x, y=y, w=w, h=h, ymax=ymax)
    # Fills under curves first (weaker than stroke), then strokes on top.
    if fill_down and len(d_pts) >= 2:
        poly = d_pts + [(d_pts[-1][0], y + h - 1), (d_pts[0][0], y + h - 1)]
        draw.polygon(poly, fill=_graph_fill_color(col_down))
    if fill_up and len(u_pts) >= 2:
        poly = u_pts + [(u_pts[-1][0], y + h - 1), (u_pts[0][0], y + h - 1)]
        draw.polygon(poly, fill=_graph_fill_color(col_up))
    if len(d_pts) >= 2:
        draw.line(d_pts, fill=col_down, width=1)
    if len(u_pts) >= 2:
        draw.line(u_pts, fill=col_up, width=1)


def _wlc_graph_panel(
    img,
    draw,
    x: int,
    y: int,
    w: int,
    h: int,
    down,
    up,
    col_down,
    col_up,
    *,
    fill_down: bool = True,
    scale_key: str = "wlc",
) -> None:
    """WiFi/Eth traffic mini-graphs (overlay or split per PIXOO_WLC_GRAPH_MODE)."""
    if _WLC_GRAPH_MODE == "split":
        gap = 1
        lw = max(8, (w - gap) // 2)
        rw = max(8, w - lw - gap)
        _graph(img, draw, x, y, lw, h, list(down or []), col_down, filled=fill_down, scale_key=f"{scale_key}:d")
        _graph(img, draw, x + lw + gap, y, rw, h, list(up or []), col_up, filled=False, scale_key=f"{scale_key}:u")
        return
    _graph_up_down(
        img, draw, x, y, w, h, down, up, col_down, col_up, fill_down=fill_down, scale_key=scale_key
    )


def _demo_metrics() -> dict[str, Any]:
    import math
    import time

    t = time.time()
    down = 40 + 30 * abs(math.sin(t / 17))
    up = 8 + 6 * abs(math.sin(t / 23))
    hist_d = [20 + 25 * abs(math.sin((t - i) / 11)) for i in range(32)]
    hist_u = [4 + 5 * abs(math.sin((t - i) / 13)) for i in range(32)]
    return {
        "uptime_str": "12d04h",
        "cpu": int(40 + 35 * abs(math.sin(t / 11))),
        "ram": int(50 + 20 * abs(math.sin(t / 13))),
        "clients": 14,
        "clients_wifi": 10,
        "clients_wired": 4,
        "clients_2g": 6,
        "clients_5g": 4,
        "clients_ssid": [
            {"ssid": "T2G", "n": 10},
            {"ssid": "CAM", "n": 4},
            {"ssid": "Main", "n": 2},
            {"ssid": "Bis", "n": 1},
        ],
        "wan_online": True,
        "wan_down": round(down, 2),
        "wan_up": round(up, 2),
        "wan_history_down": hist_d,
        "wan_history_up": hist_u,
        "wan_history_max_down": max(hist_d) if hist_d else 1.0,
        "wan_history_max_up": max(hist_u) if hist_u else 1.0,
        "cpu_history": [40 + 30 * abs(math.sin((t - i) / 9)) for i in range(32)],
        "ram_history": [50 + 20 * abs(math.sin((t - i) / 11)) for i in range(32)],
        "temp_history": [50 + 10 * abs(math.sin((t - i) / 15)) for i in range(32)],
        "temp_avg": 52,
        "wifi_down": round(down * 0.7, 2),
        "wifi_up": round(up * 0.6, 2),
        "lan_down": round(down * 0.25, 2),
        "lan_up": round(up * 0.35, 2),
        "wifi_history_down": [x * 0.7 + 2 * abs(math.sin((t - i) / 7)) for i, x in enumerate(hist_d)],
        "wifi_history_up": [x * 0.6 for x in hist_u],
        "lan_history_down": [x * 0.2 + 5 * abs(math.sin((t - i) / 5)) for i, x in enumerate(hist_d)],
        "lan_history_up": [x * 0.35 for x in hist_u],
        "top_down": [["phone45", 125.0], ["living-tv", 42.0], ["ipad-lab", 28.0], ["cam-yard", 15.0]],
        "top_up": [["nas-box", 18.0], ["cam-front", 7.0], ["laptop", 5.0], ["phone45", 3.0]],
        "temp_cpu": int(55 + 15 * abs(math.sin(t / 19))),
        "temp_2g": 45,
        "temp_5g": 52,
        "vpn1": {"on": True, "type": "OVPN"},
        "vpn2": {"on": False, "type": "WG"},
        "vpn3": {"on": False, "type": "VPN"},
        "jffs": {"used": 22, "total": 100, "present": True},
        "usb": {"used": 81, "total": 100, "present": True},
        "usb2": {"present": True, "used": 40},
        "usb3": {"present": False, "used": 0},
        "lan_ports": [True, True, False, True],
        "ram_cache": {"buffers": 15, "cached": 25},
        "_demo": True,
    }


def _first_top(rows: list | None) -> tuple[str, float] | None:
    """Literal first metrics top entry (name, Mbps), or None."""
    if not rows:
        return None
    try:
        row = rows[0]
        return str(row[0]), max(0.0, float(row[1]))
    except (IndexError, TypeError, ValueError):
        return None


def _pick_top(rows: list | None, limit: int = 2) -> list[tuple[str, float]]:
    parsed: list[tuple[str, float]] = []
    for row in rows or []:
        try:
            name, rate = str(row[0]), float(row[1])
        except (IndexError, TypeError, ValueError):
            continue
        parsed.append((name, max(0.0, rate)))
    if not parsed:
        return []
    ordered = sorted(parsed, key=lambda x: x[1], reverse=True)
    active = [p for p in ordered if p[1] > 0]
    if len(active) >= limit:
        return active[:limit]
    rest = [p for p in ordered if p not in active]
    return (active + rest)[:limit]


def _active_vpns(m: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key, fallback in (("vpn1", "VPN1"), ("vpn2", "VPN2")):
        v = m.get(key) or {}
        if v.get("on"):
            out.append((fallback, str(v.get("type", "?"))[:4]))
    return out


def _vpn_slots(m: dict[str, Any]) -> list[tuple[str, bool, str]]:
    slots: list[tuple[str, bool, str]] = []
    defaults = ("OVPN", "WG", "VPN")
    for i, (key, fallback) in enumerate(
        (("vpn1", "VPN1"), ("vpn2", "VPN2"), ("vpn3", "VPN3"))
    ):
        v = m.get(key) or {}
        on = bool(v.get("on"))
        typ = str(v.get("type", defaults[i]))[:4]
        slots.append((fallback, on, typ))
    return slots


def _disk_used_pct(m: dict[str, Any]) -> float:
    """Worst disk fill among JFFS / USB mounts present."""
    vals: list[float] = []
    jffs = m.get("jffs") or {}
    if jffs.get("present", True) or jffs.get("used") is not None:
        vals.append(float(jffs.get("used", 0) or 0))
    for key in ("usb", "usb2", "usb3"):
        u = m.get(key) or {}
        if u.get("present"):
            vals.append(float(u.get("used", 0) or 0))
    return max(vals) if vals else 0.0


def _temp_score(temp: float, *, kind: str = "temp_cpu") -> float:
    """0–100 health from temperature (high temp → low score)."""
    t = float(temp or 0)
    if kind == "temp_cpu":
        warn, crit = float(WARN_TEMP_CPU), float(CRIT_TEMP_CPU)
        cool = 45.0
    else:
        warn, crit = float(WARN_TEMP_RADIO), float(CRIT_TEMP_RADIO)
        cool = 40.0
    if t <= 0:
        return 100.0
    if t <= cool:
        return 100.0
    if t >= crit:
        return 0.0
    if t >= warn:
        return max(0.0, 40.0 * (crit - t) / max(1.0, crit - warn))
    return 100.0 - 40.0 * (t - cool) / max(1.0, warn - cool)


def _health_color(score: float) -> tuple[int, int, int]:
    """Generic health: green high, yellow mid, red low."""
    s = float(score or 0)
    if s >= 70:
        return GREEN
    if s >= 40:
        return YELLOW
    return RED


def _sys_health_color(score: float) -> tuple[int, int, int]:
    """SYS health: green good, yellow mid, red if <30%."""
    s = float(score or 0)
    if s < 30:
        return RED
    if s < 70:
        return YELLOW
    return GREEN


def _net_sat_color(sat: float) -> tuple[int, int, int]:
    """Net saturation fill/value color: green <40, yellow 40–70, red ≥70."""
    s = float(sat or 0)
    if s < 40:
        return GREEN
    if s < 70:
        return YELLOW
    return RED


def _system_health_score(m: dict[str, Any]) -> int:
    """0–100 router health via progressive penalties (100 = healthy).

    CPU only after 50%, RAM after 60%, temp_cpu after 65°C, disk after 80%.
    """
    cpu = float(m.get("cpu", 0) or 0)
    ram = float(m.get("ram", 0) or 0)
    t_cpu = float(m.get("temp_cpu", 0) or 0)
    disk = _disk_used_pct(m)

    cpu_penalty = max(0.0, (cpu - 50.0) / 50.0) * 40.0
    ram_penalty = max(0.0, (ram - 60.0) / 40.0) * 30.0
    if t_cpu > 65.0:
        temp_penalty = min((t_cpu - 65.0) / 20.0, 1.0) * 20.0
    else:
        temp_penalty = 0.0
    if disk > 80.0:
        disk_penalty = min((disk - 80.0) / 20.0, 1.0) * 10.0
    else:
        disk_penalty = 0.0

    score_cpu = 100.0 - cpu_penalty
    score_ram = 100.0 - ram_penalty
    score_temp = 100.0 - temp_penalty
    score_disk = 100.0 - disk_penalty

    score = (
        score_cpu * 0.35
        + score_ram * 0.30
        + score_temp * 0.25
        + score_disk * 0.10
    )
    return int(round(max(0.0, min(100.0, score))))


def _network_saturation(m: dict[str, Any]) -> float:
    """0–100 effective network load (100 = saturated).

    Hybrid: max(down×1.5, up×1.5, clients×0.4) after ignoring micro-util
    (<5% of WAN cap), then EMA smooth 60/40 vs previous frame.
    """
    global _NET_SAT_SMOOTH
    if not bool(m.get("wan_online")):
        _NET_SAT_SMOOTH = 100.0
        return 100.0

    wan_down = float(m.get("wan_down", 0) or 0)
    wan_up = float(m.get("wan_up", 0) or 0)
    clients = int(m.get("clients", 0) or 0)

    instant_down = min(1.0, wan_down / _WAN_MAX_DOWN_MBPS)
    instant_up = min(1.0, wan_up / _WAN_MAX_UP_MBPS)
    instant_clients = min(1.0, clients / max(1.0, _NET_CLIENTS_SOFT))

    signif_down = instant_down if instant_down > _NET_SIGNIF_UTIL else 0.0
    signif_up = instant_up if instant_up > _NET_SIGNIF_UTIL else 0.0

    raw = max(signif_down * 1.5, signif_up * 1.5, instant_clients * 0.4)
    raw = min(1.0, raw)
    raw_pct = 100.0 * raw

    if _NET_SAT_SMOOTH is None:
        _NET_SAT_SMOOTH = raw_pct
    else:
        _NET_SAT_SMOOTH = (
            _NET_SAT_SMOOTH * _NET_SMOOTH_PREV + raw_pct * _NET_SMOOTH_RAW
        )
    return float(max(0.0, min(100.0, _NET_SAT_SMOOTH)))


def _network_health_score(m: dict[str, Any]) -> int:
    """0–100 network health (100 = healthy = low saturation)."""
    sat = _network_saturation(m)
    return int(round(max(0.0, min(100.0, 100.0 - sat))))


def _health_score(m: dict[str, Any]) -> int:
    """Legacy composite (average of system + network health)."""
    return int(round((_system_health_score(m) + _network_health_score(m)) / 2.0))


def _pick_top_by_wan_util(m: dict[str, Any]) -> tuple[str, float] | None:
    """Client with highest util vs WAN max down/up (not WiFi PHY max)."""
    ranked = _rank_clients_by_wan_util(m)
    if not ranked:
        return None
    name, down, up, _util = ranked[0]
    # Show the rate of the direction that dominates util.
    d_u = down / _WAN_MAX_DOWN_MBPS
    u_u = up / _WAN_MAX_UP_MBPS
    return name, down if d_u >= u_u else up


def _rank_clients_by_wan_util(m: dict[str, Any]) -> list[tuple[str, float, float, float]]:
    """Merge top_down/top_up by hostname → (name, down, up, max_util)."""
    by_name: dict[str, list[float]] = {}
    for name, rate in _pick_top(m.get("top_down"), limit=12):
        ent = by_name.setdefault(name, [0.0, 0.0])
        ent[0] = max(ent[0], float(rate))
    for name, rate in _pick_top(m.get("top_up"), limit=12):
        ent = by_name.setdefault(name, [0.0, 0.0])
        ent[1] = max(ent[1], float(rate))
    ranked: list[tuple[str, float, float, float]] = []
    for name, (down, up) in by_name.items():
        util = max(down / _WAN_MAX_DOWN_MBPS, up / _WAN_MAX_UP_MBPS)
        ranked.append((name, down, up, util))
    ranked.sort(key=lambda x: x[3], reverse=True)
    return ranked


def _greedy_clients(
    m: dict[str, Any], *, limit: int = 3
) -> tuple[int, list[tuple[str, float, float, float]]]:
    """Count clients ≥ greedy util; return top `limit` by util (down and/or up)."""
    ranked = _rank_clients_by_wan_util(m)
    greedy = [row for row in ranked if row[3] >= _GREEDY_UTIL]
    return len(greedy), greedy[:limit]


def _top_hostname_color(down_mbps: float, up_mbps: float) -> tuple[int, int, int]:
    """White idle; yellow if greedy on one side; red if greedy down and up (streaming)."""
    greedy_dn = (float(down_mbps) / _WAN_MAX_DOWN_MBPS) >= _GREEDY_UTIL
    greedy_up = (float(up_mbps) / _WAN_MAX_UP_MBPS) >= _GREEDY_UTIL
    if greedy_dn and greedy_up:
        return RED
    if greedy_dn or greedy_up:
        return YELLOW
    return FG


def _client_dir_tag(down_mbps: float, up_mbps: float) -> str:
    """D=down, U=up, B=both greedy — why this client ranks as top."""
    d_u = float(down_mbps) / _WAN_MAX_DOWN_MBPS
    u_u = float(up_mbps) / _WAN_MAX_UP_MBPS
    greedy_dn = d_u >= _GREEDY_UTIL
    greedy_up = u_u >= _GREEDY_UTIL
    if greedy_dn and greedy_up:
        return "B"
    if greedy_up and not greedy_dn:
        return "U"
    if greedy_dn and not greedy_up:
        return "D"
    return "U" if u_u > d_u else "D"


def _client_dir_rate(down_mbps: float, up_mbps: float, tag: str) -> tuple[float, float]:
    """Rate to show + WAN cap for coloring, from D/U/B tag."""
    if tag == "U":
        return float(up_mbps), _WAN_MAX_UP_MBPS
    if tag == "B":
        # Show the hotter side's rate when both are greedy.
        if (float(up_mbps) / _WAN_MAX_UP_MBPS) >= (float(down_mbps) / _WAN_MAX_DOWN_MBPS):
            return float(up_mbps), _WAN_MAX_UP_MBPS
        return float(down_mbps), _WAN_MAX_DOWN_MBPS
    return float(down_mbps), _WAN_MAX_DOWN_MBPS


def _trend_from_history(
    hist: Any,
    *,
    eps_abs: float = 0.05,
    eps_ratio: float = 0.05,
    allow_equal: bool = True,
) -> str:
    """Compare recent history → ↑ / ↓ / = / empty if unknown.

    Uses a 2-sample mean vs prior 2-sample mean when possible to avoid
    single-tick flicker at float thresholds.
    """
    try:
        vals = [float(x) for x in (hist or [])]
    except (TypeError, ValueError):
        return ""
    if len(vals) < 2:
        return ""
    if len(vals) >= 4:
        prev = (vals[-4] + vals[-3]) / 2.0
        cur = (vals[-2] + vals[-1]) / 2.0
    else:
        prev, cur = vals[-2], vals[-1]
    thr = max(float(eps_abs), float(eps_ratio) * max(abs(prev), abs(cur), 1e-9))
    if cur > prev + thr:
        return "↑"
    if cur < prev - thr:
        return "↓"
    return "=" if allow_equal else ""


def _trend_color(mark: str) -> tuple[int, int, int]:
    """↑ orange (rise), ↓ green (fall), = gray (stable)."""
    if mark == "↑":
        return ORANGE
    if mark == "↓":
        return GREEN
    if mark == "=":
        return DIM
    return LABEL


def _draw_trend(img, x: int, y: int, mark: str) -> int:
    """Draw trend mark; returns x after glyph (or unchanged if empty)."""
    if not mark:
        return x
    return _txt(img, x, y, mark, _trend_color(mark), size="tiny", role="status")


def _score_hist_push(buf: list[float], val: float, *, keep: int = 4, min_delta: float = 0.5) -> None:
    """Append only when the value moved enough — stops per-frame arrow flicker."""
    v = float(val)
    if buf and abs(buf[-1] - v) < min_delta:
        return
    buf.append(v)
    del buf[:-keep]


def _draw_sum_footer(img, draw: ImageDraw.ImageDraw, m: dict[str, Any]) -> None:
    """Bottom 7px band (1+5+1): continuous accent fill, black 3×5 with 1px margins."""
    from datetime import datetime

    band_h = 7  # 1px top + 5px glyph + 1px bottom
    band_y0 = 64 - band_h  # 57 — flush to bottom edge
    text_y = band_y0 + 1
    margin = 1
    x_right = 63

    now = datetime.now()
    time_s = now.strftime("%H:%M")
    date_s = now.strftime("%d/%m")
    online = bool(m.get("wan_online"))
    mid = "WAN" if not online else _compact_uptime_str(str(m.get("uptime_str", "--") or "--"))

    time_ink = max(1, pf.text_ink_width(time_s, size="tiny"))
    date_ink = max(1, pf.text_ink_width(date_s, size="tiny"))
    time_x = margin
    # Date last ink on x=62 → 1px right margin on column 63
    date_x = x_right - margin - date_ink + 1

    # Continuous band: white full width, then mid accent over the center span.
    draw.rectangle([0, band_y0, x_right, 63], fill=FG, outline=FG)
    # 1px white pad after time ink, 1px white pad before date ink; mid fills the rest.
    mid_x0 = time_x + time_ink + 1
    mid_x1 = date_x - 2
    mid_col = GREEN if online else RED
    if mid_x1 >= mid_x0:
        draw.rectangle([mid_x0, band_y0, mid_x1, 63], fill=mid_col, outline=mid_col)

    # Mid text: 1px into the mid accent (glyph bordered by accent on all sides).
    mid_text_x = mid_x0 + 1
    avail = max(0, (date_x - 1) - mid_text_x)
    while mid and pf.text_width(mid, size="tiny") > avail:
        mid = mid[:-1]

    black = (0, 0, 0)
    pf.draw_tiny(img, time_x, text_y, time_s, black)
    show_mid = bool(mid) and (online or not _ALERT_BLINK or _blink_on())
    if show_mid:
        pf.draw_tiny(img, mid_text_x, text_y, mid, black)
    pf.draw_tiny(img, date_x, text_y, date_s, black)


def _draw_sum_vpn_usb_row(
    img,
    draw: ImageDraw.ImageDraw,
    m: dict[str, Any],
    *,
    x0: int,
    x1: int,
    y: int,
) -> None:
    """VPN123 … [5G]n … USB23 — 5G badge fixed mid (black on orange like Wi)."""
    x = x0
    x = _txt(img, x, y, "VPN", LABEL, size="tiny", role="label")
    for i, (_name, on, _typ) in enumerate(_vpn_slots(m)[:3], start=1):
        x = _txt(img, x, y, str(i), GREEN if on else RED, size="tiny", role="status")

    n5 = max(0, int(m.get("clients_5g", 0) or 0))
    cnt = str(min(99, n5))
    five_bw = max(1, pf.text_ink_width("5G", size="tiny")) + 2
    mid_w = five_bw + 1 + pf.text_ink_width(cnt, size="tiny")
    # Fixed screen-centered cluster so it does not shift with VPN/USB widths.
    mx = max(x0, (x0 + x1 - mid_w + 1) // 2)
    mx = _draw_sum_inv_lab(img, draw, mx, y, "5G", ORANGE)
    _txt(img, mx + 1, y, cnt, DIM if n5 == 0 else FG, size="tiny", role="status")

    usb2 = m.get("usb2") or {}
    usb3 = m.get("usb3") or {}
    usb = m.get("usb") or {}
    u2 = bool(usb2.get("present") or usb.get("present"))
    u3 = bool(usb3.get("present"))
    usb_ink = pf.text_ink_width("USB23", size="tiny")
    ux = x1 - usb_ink + 1
    ux = _txt(img, ux, y, "USB", LABEL, size="tiny", role="label")
    ux = _txt(img, ux, y, "2", GREEN if u2 else RED, size="tiny", role="status")
    _txt(img, ux, y, "3", GREEN if u3 else RED, size="tiny", role="status")


def _draw_sum_down_up_legend_row(
    img,
    draw: ImageDraw.ImageDraw,
    *,
    x0: int,
    x1: int,
    y: int,
) -> None:
    """DOWN (left) + UP (right) inverted badges — legend for the WAN graph below."""
    _draw_sum_inv_lab(img, draw, x0, y, "DOWN", GRAPH_DOWN)
    up_bw = max(1, pf.text_ink_width("UP", size="tiny")) + 2
    _draw_sum_inv_lab(img, draw, x1 - up_bw + 1, y, "UP", GRAPH_UP)


def _draw_sum_inv_lab(
    img,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    fill: Sequence[int],
) -> int:
    """Inverted tiny label (black on `fill`, 1px pad all sides). Returns x after badge."""
    pad = 1
    ink = max(1, pf.text_ink_width(text, size="tiny"))
    bw = ink + pad * 2
    # 1px above + 5px glyph + 1px below → taller color band on Wi/LAN only.
    draw.rectangle([x, y - pad, x + bw - 1, y + 4 + pad], fill=fill, outline=fill)
    pf.draw_tiny(img, x + pad, y, text, (0, 0, 0))
    return x + bw


def _draw_sum_wi_lan_row(
    img,
    draw: ImageDraw.ImageDraw,
    m: dict[str, Any],
    *,
    x0: int,
    x1: int,
    y: int,
) -> None:
    """Wi wifi/total …… LAN1234 — Wi on orange, LAN on green (black text)."""
    clients = int(m.get("clients", 0) or 0)
    wifi = int(m.get("clients_wifi", 0) or 0)
    ports = list(m.get("lan_ports") or [False, False, False, False])[:4]
    while len(ports) < 4:
        ports.append(False)

    x = _draw_sum_inv_lab(img, draw, x0, y, "Wi", ORANGE)
    x += 1
    x = _txt(img, x, y, str(wifi), DIM if wifi == 0 else FG, size="tiny", role="status")
    x = _txt(img, x, y, "/", HEADER, size="tiny", role="status")
    _txt(img, x, y, str(clients), DIM if clients == 0 else FG, size="tiny", role="status")

    lan_bw = max(1, pf.text_ink_width("LAN", size="tiny")) + 2
    dig_span = pf.text_width("123", size="tiny") + pf.text_ink_width("4", size="tiny")
    lx = x1 - (lan_bw + dig_span) + 1
    lx = _draw_sum_inv_lab(img, draw, lx, y, "LAN", GREEN)
    for i, up in enumerate(ports, start=1):
        lx = _txt(img, lx, y, str(i), GREEN if up else RED, size="tiny", role="status")


def _render_sum(img, d: ImageDraw.ImageDraw, m: dict[str, Any]) -> None:
    """Full-bleed summary: DWN first; 2 top hosts; footer time/uptime/date inverted."""
    sys_hp = _system_health_score(m)
    net_sat = _network_saturation(m)
    sys_col = _sys_health_color(sys_hp)
    net_col = _net_sat_color(net_sat)
    _score_hist_push(_SYS_HP_HIST, sys_hp)
    _score_hist_push(_NET_SAT_HIST, net_sat)

    # Full width — no side gutter (pixels 0 and 63 used).
    x0, x1 = 0, 63
    # Shared columns. Right labels (NET/RAM/TMP) share one X so they line up.
    # Reserve: LABEL + trend slot + gap + max "100°C" (empty slot when no arrow).
    lab_w = pf.text_width("SYS", size="tiny")
    lab_l = x0
    trend_w = pf.text_width("↑", size="tiny")
    tmp_val_max = (
        pf.text_width("100", size="tiny") + 1 + pf.text_ink_width("°C", size="tiny")
    )
    lab_r = x1 - (lab_w + trend_w + 2 + tmp_val_max) + 1
    # Gauges start after label + reserved trend slot (SYS/NET/CPU/RAM).
    content_l = lab_l + lab_w + trend_w
    content_r = lab_r + lab_w + trend_w
    g_l = content_l
    g_w_l = max(4, lab_r - g_l - 1)
    g_r = content_r
    g_w_r = max(4, x1 - g_r + 1)
    step = 6  # 5px tiny glyph + 1px row gap
    y = 0

    def _right_x(text: str) -> int:
        # Flush last ink to x1 (tiny advance width leaves a dead trailing px).
        return x1 - pf.text_ink_width(text, size="tiny") + 1

    # 1) DWN↑ rate | UP↑ rate — trend glued to label
    down = float(m.get("wan_down", 0) or 0)
    up = float(m.get("wan_up", 0) or 0)
    down_col = _wan_link_color(down, _WAN_MAX_DOWN_MBPS)
    up_col = _wan_link_color(up, _WAN_MAX_UP_MBPS)
    tr_dn = _trend_from_history(m.get("wan_history_down"), eps_abs=0.05)
    tr_up = _trend_from_history(m.get("wan_history_up"), eps_abs=0.02)
    x = _txt(img, x0, y, "DWN", LABEL, size="tiny", role="label")
    x = _draw_trend(img, x, y, tr_dn)  # glued to label
    x += 1
    _draw_rate(img, x, y, down, color=down_col)
    up_rate_w = _rate_ink_width(up)
    tr_up_w = pf.text_width(tr_up, size="tiny") if tr_up else 0
    up_lab_w = pf.text_width("UP", size="tiny")
    block = up_lab_w + tr_up_w + 1 + up_rate_w
    ux = x1 - block + 1
    ux = _txt(img, ux, y, "UP", LABEL, size="tiny", role="label")
    ux = _draw_trend(img, ux, y, tr_up)
    ux += 1
    _draw_rate(img, ux, y, up, color=up_col)
    y += step

    # 2) Wi wifi/total …… LAN1234 (moved up; inverted Wi/LAN labels)
    _draw_sum_wi_lan_row(img, d, m, x0=x0, x1=x1, y=y)
    y += step

    # 3–4) slots 0–3: SYS/NET+CPU/RAM — slots 4–7 (graph): DOWN/UP WiFi|Wired bars
    show_wan_graph = sum_show_wan_graph()
    cpu = float(m.get("cpu", 0) or 0)
    ram = float(m.get("ram", 0) or 0)
    tmp = float(m.get("temp_avg", 0) or _temp_avg(m))
    disk = _disk_used_pct(m)

    if show_wan_graph:
        y = _draw_sum_down_up_split_gauges(img, d, m, x0=x0, x1=x1, y=y, step=step)
    else:
        tr_sys = _trend_from_history(_SYS_HP_HIST, eps_abs=1.0, eps_ratio=0.02)
        tr_net = _trend_from_history(_NET_SAT_HIST, eps_abs=1.0, eps_ratio=0.02)

        def _label_trend_gauge(
            lab_x: int,
            lab: str,
            mark: str,
            pct: float,
            col,
            *,
            alert: bool,
            g_x0: int,
            g_w0: int,
        ) -> None:
            _txt(img, lab_x, y, lab, LABEL, size="tiny", role="label", alert=alert)
            if mark:
                _draw_trend(img, lab_x + lab_w, y, mark)
            _gauge(d, g_x0, y, g_w0, pct, col, alert=alert)

        _label_trend_gauge(lab_l, "SYS", tr_sys, sys_hp, sys_col, alert=False, g_x0=g_l, g_w0=g_w_l)
        _label_trend_gauge(lab_r, "NET", tr_net, net_sat, net_col, alert=False, g_x0=g_r, g_w0=g_w_r)
        y += step

        cpu_col = _diagram_color(cpu, kind="load")
        ram_col = _diagram_color(ram, kind="load")
        cpu_alert = _is_crit_load(cpu)
        ram_alert = _is_crit_load(ram)
        tr_cpu = _trend_from_history(m.get("cpu_history"), eps_abs=1.0, eps_ratio=0.02)
        tr_ram = _trend_from_history(m.get("ram_history"), eps_abs=1.0, eps_ratio=0.02)
        _label_trend_gauge(lab_l, "CPU", tr_cpu, cpu, cpu_col, alert=cpu_alert, g_x0=g_l, g_w0=g_w_l)
        _label_trend_gauge(lab_r, "RAM", tr_ram, ram, ram_col, alert=ram_alert, g_x0=g_r, g_w0=g_w_r)
        y += step

    # 5) DSK % …… TMP↑ °C — TMP label at same lab_r as NET/RAM
    dsk_col = _diagram_color(disk, kind="disk")
    tmp_i = int(round(tmp))
    tmp_hot = _is_crit_temp_tile(tmp_i)
    tmp_col = RED if tmp_hot else _temp_tile_color(tmp_i)
    _txt(img, lab_l, y, "DSK", LABEL, size="tiny", role="label", alert=_is_crit_disk_tile(disk))
    _draw_val_unit(
        img,
        lab_l + lab_w + 2,
        y,
        str(int(round(disk))),
        "%",
        dsk_col,
        size="tiny",
        value_role="status",
        alert=_is_crit_disk_tile(disk),
    )
    tr_tmp = _trend_from_history(m.get("temp_history"), eps_abs=0.5, eps_ratio=0.01)
    tmp_num = str(tmp_i)
    bx = _txt(
        img,
        lab_r,
        y,
        "TMP",
        RED if tmp_hot else LABEL,
        size="tiny",
        role="status" if tmp_hot else "label",
    )
    bx = _draw_trend(img, bx, y, tr_tmp)
    bx = max(bx, content_r)  # keep value column aligned with NET/RAM gauges
    bx += 2
    _draw_val_unit(img, bx, y, tmp_num, "°C", tmp_col, size="tiny", value_role="status")
    y += step

    # 6) Graph: DOWN……UP legend | Clients: VPN … 5Gn … USB
    if show_wan_graph:
        _draw_sum_down_up_legend_row(img, d, x0=x0, x1=x1, y=y)
    else:
        _draw_sum_vpn_usb_row(img, d, m, x0=x0, x1=x1, y=y)
    y += step

    # 7–8) Hot Wifi + tops  XOR  WAN graph — graph = last 4/8 of dwell D.
    block_y0 = y
    block_h = step * 3 - 1  # 17px — three tiny rows
    if show_wan_graph:
        down_h = list(m.get("wan_history_down") or [])[-64:]
        up_h = list(m.get("wan_history_up") or [])[-64:]
        _graph_up_down(
            img,
            d,
            x0,
            block_y0,
            64,
            block_h,
            down_h,
            up_h,
            GRAPH_DOWN,
            GRAPH_UP,
            fill_down=True,
            scale_key="sum_wan",
        )
        y = block_y0 + step * 3
    else:
        # Hot Wifi n …… down_rate up_rate (hottest Wi‑Fi STA)
        n_hot, hot = _greedy_clients(m, limit=3)
        n_show = min(9, int(n_hot))
        hot_col = DIM if n_show == 0 else FG
        hot_lab = "Hot Wifi"
        _txt(img, x0, y, hot_lab, LABEL, size="tiny", role="label")
        _txt(
            img,
            x0 + pf.text_width(hot_lab, size="tiny") + 2,
            y,
            str(n_show),
            hot_col,
            size="tiny",
            role="status",
        )
        if hot:
            _hn, hd, hu, _hutil = hot[0]
            up_w = _rate_ink_width(hu)
            _draw_rate_right(img, x1, y, hu, color=_wan_link_color(hu, _WAN_MAX_UP_MBPS))
            _draw_rate_right(
                img,
                x1 - up_w - 2,
                y,
                hd,
                color=_wan_link_color(hd, _WAN_MAX_DOWN_MBPS),
            )
        else:
            _txt(img, _right_x("--"), y, "--", DIM, size="tiny", role="status")
        y += step

        # Line 1 = #1 top_up + unit + orange U; line 2 = #1 top_down + unit + green D
        footer_y0 = 64 - 7
        for entry, tag, tag_col in (
            (_first_top(m.get("top_up")), "U", ORANGE),
            (_first_top(m.get("top_down")), "D", GREEN),
        ):
            if y + 4 >= footer_y0:
                break
            if not entry:
                _txt(img, x0, y, "-", DIM, size="tiny", role="status")
                y += step
                continue
            name, rate = entry
            trail_w = _rate_dir_tag_ink_width(rate, tag)
            max_name_w = max(0, x1 - trail_w - 2 - x0 + 1)
            shown = _truncate_to_width(str(name), max_name_w)
            _txt(img, x0, y, shown, FG if rate > 0 else DIM, size="tiny", role="status")
            # Rate (num+K/M/G) in white; only U/D carries direction color.
            _draw_rate_dir_tag_right(
                img,
                x1,
                y,
                rate,
                tag,
                tag_col,
                rate_color=FG if rate > 0 else DIM,
            )
            y += step

    # 9) Footer pinned to bottom: continuous 7px inverted band
    _draw_sum_footer(img, d, m)


def render_screen(m: dict[str, Any], idx: int) -> Image.Image:
    screens = get_screen_ids() or ALL_SCREEN_IDS
    idx = idx % len(screens)
    sid = screens[idx]
    img = Image.new("RGB", (64, 64), BG)
    d = ImageDraw.Draw(img)
    if sid == "SUM":
        _render_sum(img, d, m)
        if m.get("_offline"):
            _txt(img, 51, 0, "OFF", YELLOW, size="tiny", role="value", alert=True)
        return img
    if sid == "SUM_GRAPH":
        from pixoo_bridge.sum_graph import render_sum_graph

        render_sum_graph(img, d, m)
        if m.get("_offline"):
            _txt(img, 51, 0, "OFF", YELLOW, size="tiny", role="value", alert=True)
        return img

    _header(img, d, SCREEN_TITLES.get(sid, sid), idx)

    if sid == "SYS":
        uptime = str(m.get("uptime_str", "--"))[:7]
        _txt(img, 2, 11, "Uptime", LABEL, size="tiny", role="label", label_negligible=uptime in ("--", ""))
        _txt(img, 26, 11, uptime, FG, size="tiny", role="value")
        online = bool(m.get("wan_online"))
        if online or not _ALERT_BLINK or _blink_on():
            d.ellipse([56, 11, 61, 16], fill=GREEN if online else RED)
        cpu = float(m.get("cpu", 0) or 0)
        ram = float(m.get("ram", 0) or 0)
        avg = float(m.get("temp_avg", 0) or _temp_avg(m))
        _gauge_row(img, d, 20, "CPU", cpu, kind="load")
        _gauge_row(img, d, 28, "RAM", ram, kind="load")
        _gauge_row(img, d, 36, "TMP", avg, kind="temp_cpu")
        # Down / Up with distinct value colors
        _txt_label(img, 2, 46, "Down", mbps=m.get("wan_down", 0))
        _draw_rate(img, 22, 46, m.get("wan_down", 0))
        _txt_label(img, 2, 54, "Up", mbps=m.get("wan_up", 0))
        _draw_rate(img, 22, 54, m.get("wan_up", 0))

    elif sid == "LOD":
        cpu_h = list(m.get("cpu_history") or [])
        ram_h = list(m.get("ram_history") or [])
        cpu_now = int(m.get("cpu", 0) or 0)
        ram_now = int(m.get("ram", 0) or 0)
        _txt(img, 2, 11, "CPU", LABEL, size="tiny", role="label")
        _draw_val_unit(
            img, 20, 11, str(cpu_now), "%", _diagram_color(cpu_now, kind="load"), size="tiny",
            value_role="status", alert=_is_crit_load(cpu_now),
        )
        _graph(img, d, 1, 18, 62, 18, cpu_h, _diagram_color(cpu_now, kind="load"), filled=True, scale_key="lod_cpu")
        _txt(img, 2, 38, "RAM", LABEL, size="tiny", role="label")
        _draw_val_unit(
            img,
            20,
            38,
            str(ram_now),
            "%",
            _diagram_color(ram_now, kind="load"),
            size="tiny",
            value_role="status",
            alert=_is_crit_load(ram_now),
        )
        _graph(img, d, 1, 45, 62, 17, ram_h, _diagram_color(ram_now, kind="load"), filled=False, scale_key="lod_ram")

    elif sid == "TMP":
        # Top: CPU | AVG — Bottom: 2.4GHz | 5GHz
        avg = int(m.get("temp_avg", 0) or _temp_avg(m))
        cells = [
            (0, 11, "CPU", int(m.get("temp_cpu", 0) or 0)),
            (32, 11, "AVG", avg),
            (0, 37, LABEL_BAND_24, int(m.get("temp_2g", 0) or 0)),
            (32, 37, LABEL_BAND_5, int(m.get("temp_5g", 0) or 0)),
        ]
        for x, y, label, val in cells:
            hot = _is_crit_temp_tile(val)
            col = RED if hot else _temp_tile_color(val)
            outline = RED if hot else DIM
            d.rectangle([x, y, x + 31, y + 24], outline=outline)
            _txt(
                img,
                x + 2,
                y + 2,
                label,
                RED if hot else LABEL,
                size="tiny",
                role="status" if hot else "label",
                label_negligible=(not hot and val <= 0),
            )
            _draw_val_unit(
                img,
                x + 2,
                y + 10,
                str(val),
                "°C",
                col,
                size="normal",
                unit_size="normal",
                value_role="status",
            )

    elif sid == "GRP":
        down = list(m.get("wan_history_down") or [])
        up = list(m.get("wan_history_up") or [])
        if _WLC_GRAPH_MODE == "split":
            _txt_label(img, 2, 11, "Dn", mbps=m.get("wan_down", 0))
            _draw_rate(img, 14, 11, m.get("wan_down", 0))
            _txt_label(img, 34, 11, "Up", mbps=m.get("wan_up", 0))
            _draw_rate(img, 44, 11, m.get("wan_up", 0))
            _wlc_graph_panel(img, d, 1, 18, 62, 44, down, up, GRAPH_DOWN, GRAPH_UP, fill_down=True, scale_key="grp")
        else:
            _txt_label(img, 2, 11, "Dn", mbps=m.get("wan_down", 0))
            x = _draw_rate(img, 14, 11, m.get("wan_down", 0))
            _txt_label(img, min(x + 2, 34), 11, "Up", mbps=m.get("wan_up", 0))
            _draw_rate(img, min(x + 12, 44), 11, m.get("wan_up", 0))
            _wlc_graph_panel(img, d, 1, 18, 62, 44, down, up, GRAPH_DOWN, GRAPH_UP, fill_down=True, scale_key="grp")

    elif sid == "WLC":
        w_down = list(m.get("wifi_history_down") or [])
        w_up = list(m.get("wifi_history_up") or [])
        eth_down = list(m.get("lan_history_down") or [])
        eth_up = list(m.get("lan_history_up") or [])
        _txt(img, 2, 11, "WiFi", LABEL, size="tiny", role="label")
        x = _draw_rate(img, 20, 11, m.get("wifi_down", 0))
        _txt_label(img, min(x + 2, 40), 11, "Up", mbps=m.get("wifi_up", 0))
        _draw_rate(img, min(x + 12, 48), 11, m.get("wifi_up", 0))
        _wlc_graph_panel(img, d, 1, 18, 62, 17, w_down, w_up, GRAPH_DOWN, GRAPH_UP, fill_down=True, scale_key="wlc_wifi")
        _txt(img, 2, 38, "Eth", LABEL, size="tiny", role="label")
        x = _draw_rate(img, 18, 38, m.get("lan_down", 0))
        _txt_label(img, min(x + 2, 40), 38, "Up", mbps=m.get("lan_up", 0))
        _draw_rate(img, min(x + 12, 48), 38, m.get("lan_up", 0))
        _wlc_graph_panel(img, d, 1, 45, 62, 16, eth_down, eth_up, ORANGE, GRAPH_UP, fill_down=False, scale_key="wlc_eth")

    elif sid == "TOP":
        downs = _pick_top(m.get("top_down"), limit=2)
        _txt(img, 2, 11, "Down", LABEL, size="tiny", role="label", label_negligible=not downs)
        if not downs:
            _txt(img, 2, 18, "(none)", DIM, size="tiny", role="label")
        else:
            for i, (name, rate) in enumerate(downs[:2]):
                row_y = 18 + i * 8
                _txt(img, 2, row_y, _scroll(name, 8), FG, size="tiny", role="value")
                _draw_rate(img, 42, row_y, rate)
        d.line([(2, 33), (61, 33)], fill=DIM)
        ups = _pick_top(m.get("top_up"), limit=2)
        _txt(img, 2, 35, "Up", LABEL, size="tiny", role="label", label_negligible=not ups)
        if not ups:
            _txt(img, 2, 44, "(none)", DIM, size="tiny", role="label")
        else:
            for i, (name, rate) in enumerate(ups[:2]):
                row_y = 44 + i * 8
                _txt(img, 2, row_y, _scroll(name, 8), FG, size="tiny", role="value")
                _draw_rate(img, 42, row_y, rate)

    elif sid == "CLI":
        total = int(m.get("clients", 0) or 0)
        wifi = int(m.get("clients_wifi", 0) or 0)
        wired = int(m.get("clients_wired", 0) or max(0, total - wifi))
        n2 = int(m.get("clients_2g", 0) or 0)
        n5 = int(m.get("clients_5g", 0) or 0)
        _txt(img, 2, 10, "All", LABEL, size="normal", role="label")
        _draw_cli_count(img, 2 + pf.text_width("All", size="normal") + 3, 10, total, size="normal")
        _txt(img, 2, 22, "WiFi", LABEL, size="tiny", role="label")
        _draw_cli_count(img, 24, 22, wifi)
        _txt(img, 34, 22, "Eth", LABEL, size="tiny", role="label")
        _draw_cli_count(img, 48, 22, wired)
        _txt(img, 2, 29, LABEL_BAND_24, LABEL, size="tiny", role="label")
        _draw_cli_count(img, 22, 29, n2)
        _txt(img, 34, 29, LABEL_BAND_5, LABEL, size="tiny", role="label")
        _draw_cli_count(img, 50, 29, n5)
        d.line([(2, 38), (61, 38)], fill=DIM)
        y = 40
        for row in list(m.get("clients_ssid") or [])[:3]:
            try:
                name, n = str(row.get("ssid", "?")), int(row.get("n", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            _txt(img, 2, y, _scroll(name, 8), LABEL, size="tiny", role="label")
            _draw_cli_count(img, 50, y, n)
            y += 8

    elif sid == "NET":
        ports = list(m.get("lan_ports") or [False, False, False, False])[:4]
        while len(ports) < 4:
            ports.append(False)
        _txt(img, 2, 12, "LAN", LABEL, size="tiny", role="label")
        x = 20
        for i, up in enumerate(ports, start=1):
            _txt(img, x, 11, str(i), GREEN if up else RED, size="normal", role="status")
            x += 10
        wifi = int(m.get("clients_wifi", 0) or 0)
        clients = int(m.get("clients", 0) or 0)
        wired = int(m.get("clients_wired", 0) or max(0, clients - wifi))
        _txt(img, 2, 24, "WiFi", LABEL, size="tiny", role="label")
        _draw_client_count(img, 22, 24, wifi)
        _txt(img, 34, 24, "Eth", LABEL, size="tiny", role="label")
        _draw_client_count(img, 48, 24, wired)
        _txt(img, 2, 33, "All", LABEL, size="tiny", role="label")
        _draw_client_count(img, 18, 33, clients)
        usb2 = m.get("usb2") or {}
        usb3 = m.get("usb3") or {}
        u2, u3 = bool(usb2.get("present")), bool(usb3.get("present"))
        _txt(img, 2, 42, "USB2", GREEN if u2 else RED, size="normal", role="status")
        _txt(img, 34, 42, "USB3", GREEN if u3 else RED, size="normal", role="status")
        online = bool(m.get("wan_online"))
        _txt(img, 2, 52, "WAN", LABEL, size="tiny", role="label", alert=not online)
        if online or not _ALERT_BLINK or _blink_on():
            d.ellipse([22, 52, 28, 58], fill=GREEN if online else RED)

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
        j_col = _diagram_color(j_used, kind="disk")
        u_col = _diagram_color(u_used, kind="disk")
        c_col = _diagram_color(c_used, kind="disk")
        _txt(img, 2, 11, "JFFS", j_col, size="tiny", role="status")
        _draw_val_unit(img, 22, 11, str(j_used), "%", j_col, size="tiny", value_role="status")
        _txt(img, 36, 11, "USB", u_col, size="tiny", role="status")
        _draw_val_unit(img, 52, 11, str(u_used), "%", u_col, size="tiny", value_role="status")
        show_j = not (_is_crit_disk_tile(j_used) and _ALERT_BLINK and not _blink_on())
        show_u = not (_is_crit_disk_tile(u_used) and _ALERT_BLINK and not _blink_on())
        pie(16, 30, 10, j_used if show_j else 0, j_col)
        pie(48, 30, 10, u_used if show_u else 0, u_col)
        _txt(img, 2, 44, "CACHE", c_col, size="tiny", role="status")
        _draw_val_unit(img, 28, 44, str(c_used), "%", c_col, size="tiny", value_role="status")
        pie(48, 54, 7, c_used, c_col)

    elif sid == "SRV":
        y = 11
        slots = _vpn_slots(m)
        any_vpn = any(on for _, on, _ in slots)
        _txt(img, 2, y, "VPN", LABEL, size="tiny", role="label")
        if any_vpn:
            _txt(img, 20, y, "ON", GREEN, size="tiny", role="status")
        else:
            _txt(img, 20, y, "off", RED, size="tiny", role="status")
        y += 8
        for name, on, typ in slots:
            _txt(img, 2, y, name, GREEN if on else RED, size="tiny", role="status")
            if on:
                _txt(img, 28, y, typ, GREEN, size="tiny", role="value")
            else:
                _txt(img, 28, y, "off", RED, size="tiny", role="status")
            y += 8
        y += 1
        jffs = m.get("jffs") or {}
        usb2 = m.get("usb2") or {}
        usb3 = m.get("usb3") or {}
        usb = m.get("usb") or {}
        if not usb2 and not usb3 and usb:
            usb2 = {"present": bool(usb.get("present")), "used": usb.get("used", 0)}
        _gauge_row(img, d, y, "JFFS", float(jffs.get("used", 0) or 0), kind="disk")
        y += 9
        u2_on = bool(usb2.get("present"))
        u2_used = float(usb2.get("used", 0) or usb.get("used", 0) or 0) if u2_on else 0.0
        _txt(img, 2, y, "USB2", GREEN if u2_on else RED, size="tiny", role="status")
        if u2_on:
            _gauge(
                d, 20, y, 42, u2_used, _diagram_color(u2_used, kind="disk"), alert=_is_crit_disk(u2_used)
            )
        else:
            _gauge(d, 20, y, 42, 0, BAR_BG)
            _txt(img, 24, y, "off", RED, size="tiny", role="status")
        y += 9
        u3_on = bool(usb3.get("present"))
        u3_used = float(usb3.get("used", 0) or 0) if u3_on else 0.0
        _txt(img, 2, y, "USB3", GREEN if u3_on else RED, size="tiny", role="status")
        if u3_on:
            _gauge(
                d, 20, y, 42, u3_used, _diagram_color(u3_used, kind="disk"), alert=_is_crit_disk(u3_used)
            )
        else:
            _gauge(d, 20, y, 42, 0, BAR_BG)
            _txt(img, 24, y, "off", RED, size="tiny", role="status")

    else:
        _txt(img, 2, 20, sid[:8], DIM, size="tiny", role="label")

    if m.get("_demo") or m.get("_offline"):
        tag = "DEMO" if m.get("_demo") else "OFF"
        _txt(img, 40, 57, tag, YELLOW, size="tiny", role="value", alert=bool(m.get("_offline")))

    return img


def render_boot_banner(msg: str = "PIXOO OK") -> Image.Image:
    img = Image.new("RGB", (64, 64), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 63, 9], fill=HEADER)
    pf.draw_text(img, 4, 1, "PIXOO", HEADER_FG, size="normal")
    _txt(img, 6, 22, msg[:10], ORANGE, size="normal", role="value")
    _txt(img, 4, 36, "Merlin bridge", FG, size="tiny", role="value")
    for y in range(48, 64):
        for x in range(48, 64):
            if (x + y) & 1:
                img.putpixel((x, y), (255, 255, 255))
    return img
