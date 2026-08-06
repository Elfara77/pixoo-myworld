"""SUM_GRAPH — graphical 64×64 summary (4×16px blocks) for Pixoo bridge."""

from __future__ import annotations

from typing import Any, Sequence

from PIL import ImageDraw

from pixoo_bridge import pixel_font as pf

# Prompt palette (SUM_GRAPH-local; SUM screen keeps its own colors).
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (80, 80, 80)
GREEN = (0, 200, 0)
YELLOW = (200, 200, 0)
RED = (200, 0, 0)
BLUE = (0, 100, 255)
ORANGE = (255, 150, 0)
CYAN = (0, 200, 200)
BG = (0, 0, 0)

_SPARK_CPU = GREEN
_SPARK_RAM = BLUE
_SPARK_TEMP = RED
_SPARK_WAN = CYAN


def _hist_tail(hist: Any, n: int) -> list[float]:
    try:
        vals = [float(x) for x in (hist or [])]
    except (TypeError, ValueError):
        vals = []
    if not vals:
        return [0.0] * n
    if len(vals) >= n:
        return vals[-n:]
    pad = [vals[0]] * (n - len(vals))
    return pad + vals


def _gauge_threshold_color(pct: float) -> tuple[int, int, int]:
    """<70 green, 70–90 yellow, >90 red."""
    p = float(pct or 0)
    if p > 90:
        return RED
    if p >= 70:
        return YELLOW
    return GREEN


def render_sparkline_15x10(
    draw: ImageDraw.ImageDraw,
    values: Sequence[float],
    x: int,
    y: int,
    color: Sequence[int],
) -> None:
    """15×10 sparkline from last 15 samples (min–max normalized)."""
    vals = list(values[-15:]) if values else []
    while len(vals) < 15:
        vals.insert(0, vals[0] if vals else 0.0)
    vals = vals[-15:]
    lo, hi = min(vals), max(vals)
    span = hi - lo
    pts: list[tuple[int, int]] = []
    for i, v in enumerate(vals):
        if span <= 1e-9:
            py = y + 5
        else:
            py = y + 9 - int(round((float(v) - lo) / span * 9))
        pts.append((x + i, max(y, min(y + 9, py))))
    if len(pts) >= 2:
        draw.line(pts, fill=tuple(color[:3]), width=1)
    elif pts:
        draw.point(pts[0], fill=tuple(color[:3]))


def render_histogram_16x10(
    draw: ImageDraw.ImageDraw,
    values: Sequence[float],
    x: int,
    y: int,
    color: Sequence[int],
) -> None:
    """16×10 bar histogram (WAN peaks) from last 16 samples."""
    vals = list(values[-16:]) if values else []
    while len(vals) < 16:
        vals.insert(0, 0.0)
    vals = vals[-16:]
    hi = max(vals) if vals else 1.0
    if hi <= 1e-9:
        hi = 1.0
    col = tuple(color[:3])
    for i, v in enumerate(vals):
        h = int(round(max(0.0, min(1.0, float(v) / hi)) * 10))
        if h <= 0:
            continue
        bx = x + i
        draw.line([(bx, y + 10 - h), (bx, y + 9)], fill=col, width=1)


def render_horizontal_gauge(
    draw: ImageDraw.ImageDraw,
    value: float,
    x: int,
    y: int,
    width: int,
    height: int,
    color: Sequence[int] | None = None,
) -> None:
    """Horizontal gauge 0–100%; color from thresholds unless overridden."""
    pct = max(0.0, min(100.0, float(value or 0)))
    col = tuple((color or _gauge_threshold_color(pct))[:3])
    x1 = x + max(1, width) - 1
    y1 = y + max(1, height) - 1
    draw.rectangle([x, y, x1, y1], outline=GRAY, fill=BLACK)
    fill_w = int((width - 2) * pct / 100.0)
    if fill_w > 0:
        draw.rectangle([x + 1, y + 1, x + fill_w, y1 - 1], fill=col)


def render_donut_8x8(
    draw: ImageDraw.ImageDraw,
    value: float,
    max_value: float,
    x: int,
    y: int,
    *,
    color: Sequence[int] = GREEN,
) -> None:
    """8×8 donut; arc fill = value/max_value."""
    mx = max(1.0, float(max_value or 1))
    frac = max(0.0, min(1.0, float(value or 0) / mx))
    bbox = [x, y, x + 7, y + 7]
    draw.ellipse(bbox, outline=GRAY, fill=BLACK)
    if frac > 0:
        # Pillow: angles degrees, 0=3 o'clock, counter-clockwise.
        extent = max(1, int(round(360 * frac)))
        draw.pieslice(bbox, start=-90, end=-90 + extent, fill=tuple(color[:3]))
        # Hollow center → donut
        draw.ellipse([x + 2, y + 2, x + 5, y + 5], fill=BLACK, outline=BLACK)


def render_text_3x5(
    img,
    text: str,
    x: int,
    y: int,
    color: Sequence[int],
) -> int:
    """3×5 text (A–Z, 0–9, and font extras). Returns x after glyph."""
    return pf.draw_tiny(img, x, y, str(text), tuple(color[:3]))


def _dot(draw: ImageDraw.ImageDraw, x: int, y: int, on: bool) -> None:
    """2×2 status pixel (●/○ substitute)."""
    if on:
        draw.rectangle([x, y, x + 1, y + 1], fill=GREEN)
    else:
        draw.rectangle([x, y, x + 1, y + 1], outline=RED)


def _ssid_label(name: str) -> str:
    s = "".join(ch for ch in str(name or "?").upper() if ch.isalnum())[:2]
    return s or "?"


def render_sum_graph(img, draw: ImageDraw.ImageDraw, m: dict[str, Any]) -> None:
    """Full-bleed SUM_GRAPH: sparklines → gauges → SSID/ports → top 3."""
    # Lazy import avoids circular import with render.py wiring.
    from pixoo_bridge import render as R

    # ── Bloc 1 (y 0–15): CPU / RAM / TEMP / WAN ──────────────────────────
    cpu = float(m.get("cpu", 0) or 0)
    ram = float(m.get("ram", 0) or 0)
    temp = float(m.get("temp_avg", 0) or R._temp_avg(m))
    wan = float(m.get("wan_down", 0) or 0)

    cells = (
        (0, "CPU", m.get("cpu_history"), _SPARK_CPU, f"{int(round(cpu))}%", False),
        (16, "RAM", m.get("ram_history"), _SPARK_RAM, f"{int(round(ram))}%", False),
        (32, "TEMP", m.get("temp_history"), _SPARK_TEMP, f"{int(round(temp))}C", False),
        (48, "WAN", m.get("wan_history_down"), _SPARK_WAN, None, True),
    )
    for x0, title, hist, col, val, is_wan in cells:
        render_text_3x5(img, title, x0, 0, WHITE)
        vals = _hist_tail(hist, 16 if is_wan else 15)
        if is_wan:
            render_histogram_16x10(draw, vals, x0, 5, col)
            # Compact rate under hist (fits 16px).
            num, unit = R._split_rate(wan)
            render_text_3x5(img, f"{num}{unit}"[:4], x0, 11, CYAN)
        else:
            render_sparkline_15x10(draw, vals[:15], x0, 5, col)
            render_text_3x5(img, str(val)[:5], x0, 11, col)

    # ── Bloc 2 (y 16–31): SYS / NET / CLI / DSK / VPN ─────────────────────
    sys_hp = float(R._system_health_score(m))
    net_sat = float(R._network_saturation(m))
    clients = int(m.get("clients", 0) or 0)
    soft = max(1, int(R._NET_CLIENTS_SOFT))
    cli_pct = min(100.0, 100.0 * clients / soft)
    disk = float(R._disk_used_pct(m))

    # SYS health: high=good → invert for red-high gauge color feel, but fill shows score.
    gauges = (
        (0, 14, "SYS", sys_hp, f"{int(round(sys_hp))}", R._sys_health_color(sys_hp)),
        (15, 14, "NET", net_sat, f"{int(round(net_sat))}", R._net_sat_color(net_sat)),
        (30, 14, "CLI", cli_pct, f"{min(99, clients)}/{int(soft)}", _gauge_threshold_color(cli_pct)),
        (45, 14, "DSK", disk, f"{int(round(disk))}%", R._diagram_color(disk, kind="disk")),
    )
    for x0, w, title, pct, label, col in gauges:
        render_text_3x5(img, title, x0, 16, WHITE)
        render_horizontal_gauge(draw, pct, x0, 22, w, 5, col)
        render_text_3x5(img, label[:5], x0, 28, col)

    # VPN — 4px strip: three status dots
    render_text_3x5(img, "V", 60, 16, WHITE)
    for i, (_n, on, _t) in enumerate(R._vpn_slots(m)[:3]):
        _dot(draw, 61, 22 + i * 3, bool(on))

    # ── Bloc 3 (y 32–47): SSID donuts + LAN + USB + HOT ───────────────────
    ssids = list(m.get("clients_ssid") or [])[:4]
    while len(ssids) < 4:
        ssids.append({"ssid": "-", "n": 0})
    counts = [max(0, int(row.get("n", 0) or 0)) for row in ssids]
    dmax = max(counts) if any(counts) else 1
    for i, row in enumerate(ssids):
        x0 = i * 10
        lab = _ssid_label(str(row.get("ssid", "?")))
        n = counts[i]
        render_text_3x5(img, lab, x0, 32, WHITE)
        col = GREEN if n > 0 else GRAY
        render_donut_8x8(draw, n, dmax, x0 + 1, 37, color=col)
        render_text_3x5(img, str(min(99, n)), x0 + 1, 46, col if n else GRAY)

    # LAN ports 40–47
    render_text_3x5(img, "LAN", 40, 32, WHITE)
    ports = list(m.get("lan_ports") or [False, False, False, False])[:4]
    while len(ports) < 4:
        ports.append(False)
    for i, up in enumerate(ports):
        _dot(draw, 40 + i * 2, 40, bool(up))

    # USB 48–55
    render_text_3x5(img, "USB", 48, 32, WHITE)
    usb2 = m.get("usb2") or {}
    usb3 = m.get("usb3") or {}
    usb = m.get("usb") or {}
    u2 = bool(usb2.get("present") or usb.get("present"))
    u3 = bool(usb3.get("present"))
    _dot(draw, 48, 40, u2)
    _dot(draw, 52, 40, u3)
    render_text_3x5(img, "23", 48, 44, GREEN if (u2 or u3) else GRAY)

    # HOT 56–63 (8px: short label)
    n_hot, hot = R._greedy_clients(m, limit=1)
    n_show = min(9, int(n_hot))
    render_text_3x5(img, "HT", 56, 32, WHITE)
    hot_col = GRAY if n_show == 0 else (YELLOW if n_show < 3 else RED)
    render_text_3x5(img, str(n_show), 56, 38, hot_col)
    if hot:
        _hn, hd, hu, _hu = hot[0]
        tag = R._client_dir_tag(hd, hu)
        render_text_3x5(img, tag, 60, 38, ORANGE if tag == "U" else (BLUE if tag == "D" else RED))
    else:
        render_text_3x5(img, "-", 60, 38, GRAY)

    # ── Bloc 4 (y 48–63): top 3 clients ───────────────────────────────────
    tops = R._rank_clients_by_wan_util(m)[:3]
    rates: list[float] = []
    rows: list[tuple[str, str, float, tuple[int, int, int]]] = []
    for i in range(3):
        if i >= len(tops):
            rows.append(("-", "--------", 0.0, GRAY))
            rates.append(0.0)
            continue
        name, cd, cu, _u = tops[i]
        tag = R._client_dir_tag(cd, cu)
        rate, cap = R._client_dir_rate(cd, cu, tag)
        host_col = R._top_hostname_color(cd, cu)
        # Map host color to SUM_GRAPH palette-ish
        if host_col == R.RED:
            hc = RED
        elif host_col == R.YELLOW:
            hc = YELLOW
        else:
            hc = WHITE
        rows.append((tag, str(name), float(rate), hc))
        rates.append(float(rate))
    peak = max(rates) if rates else 1.0
    if peak <= 1e-9:
        peak = 1.0

    for i, (tag, name, rate, hc) in enumerate(rows):
        y = 48 + i * 5
        if y + 4 > 63:
            break
        tag_col = BLUE if tag == "D" else (ORANGE if tag == "U" else (RED if tag == "B" else GRAY))
        render_text_3x5(img, tag[:1], 0, y, tag_col)
        shown = R._truncate_to_width(name, 28, size="tiny")
        render_text_3x5(img, shown, 5, y, hc)
        # 20px bar at x=36
        bar_col = BLUE if tag == "D" else (ORANGE if tag == "U" else (RED if tag == "B" else GREEN))
        bw = int(round(20 * min(1.0, rate / peak))) if rate > 0 else 0
        draw.rectangle([36, y + 1, 55, y + 3], outline=GRAY, fill=BLACK)
        if bw > 0:
            draw.rectangle([36, y + 1, 35 + bw, y + 3], fill=bar_col)
        num, unit = R._split_rate(rate)
        tok = f"{num}{unit}"
        tw = pf.text_ink_width(tok, size="tiny")
        render_text_3x5(img, tok, max(56, 63 - tw + 1), y, bar_col if rate > 0 else GRAY)
