"""64×64 RGB screens from pico_monitor /metrics.json (Merlin exporter).

Pixel fonts (no antialias).
PIXOO_COLOR_MODE: mono = labels/units gray + values solid white;
  poly = colored labels; values always distinct from labels/units.
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

# Default rotation ("all") — SUM is optional and never included by default.
ALL_SCREEN_IDS = ("SYS", "LOD", "TMP", "GRP", "WLC", "TOP", "CLI", "NET", "PIE", "SRV")
OPTIONAL_SCREEN_IDS = ("SUM",)
KNOWN_SCREEN_IDS = ALL_SCREEN_IDS + OPTIONAL_SCREEN_IDS
SCREEN_TITLES = {
    "SYS": "System",
    "LOD": "Load",
    "TMP": "Temps",
    "GRP": "Traffic",
    "WLC": "WiFi/LAN",
    "TOP": "Top",
    "CLI": "Clients",
    "NET": "Ports",
    "PIE": "Disk",
    "SRV": "Services",
    "SUM": "Summary",
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

# Graphs / dense lists: longer rotation dwell (× multiplier on PIXOO_SCREEN_SECONDS).
HEAVY_SCREEN_IDS = frozenset({"LOD", "GRP", "WLC", "TOP", "CLI", "TMP", "SUM"})
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
    """Parse screen list. ``all`` = defaults only (no SUM). ``all,SUM`` or ``SUM`` OK."""
    global SCREEN_IDS, _ACTIVE_SCREENS
    raw = "" if spec is None else str(spec).strip()
    if not raw or raw.lower() in ("*", "default"):
        raw = "all"
    tokens = [t.strip().upper() for t in raw.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
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
) -> None:
    global _COLOR_MODE, _TEXT_SCROLL, _ALERT_BLINK, _BLINK_PERIOD_S, _RATE_STYLE
    global _HEAVY_DWELL, _HEAVY_DWELL_MULT
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


def _blink_on() -> bool:
    if not _ALERT_BLINK:
        return True
    import time

    return (int(time.monotonic() / _BLINK_PERIOD_S) % 2) == 0


def _ink(color: Sequence[int], *, role: str = "value") -> tuple[int, int, int]:
    """role: label|unit|value|status|alert — values stand out from labels/units."""
    if role == "status":
        return (int(color[0]), int(color[1]), int(color[2]))
    if role == "alert":
        return RED
    if _COLOR_MODE == "mono":
        if role in ("label", "unit"):
            return MONO_DIM
        return TEXT_MONO
    if role in ("label", "unit"):
        return LABEL if role == "label" else UNIT
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
) -> int:
    if alert and _ALERT_BLINK and not _blink_on():
        return x
    col = _ink(RED if alert else color, role="alert" if alert else role)
    return pf.draw_text(img, x, y, text, col, size=size)


def _split_rate(mbps: float) -> tuple[str, str]:
    """Return (number, unit) for emphasis."""
    v = float(mbps or 0)
    if _RATE_STYLE == "long":
        if v >= 1000:
            return f"{v / 1000:.1f}", "Gb/s"
        if v >= 100:
            return f"{v:.0f}", "Mb/s"
        if v >= 1:
            return f"{v:.1f}", "Mb/s"
        return f"{v * 1000:.0f}", "Kb/s"
    if v >= 1000:
        return f"{v / 1000:.1f}", "G"
    if v >= 100:
        return f"{v:.0f}", "M"
    if v >= 1:
        return f"{v:.1f}", "M"
    if v >= 0.001:
        return f"{v * 1000:.0f}", "K"
    return "0", "K"


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


def _level_color(pct: float, *, kind: str = "load") -> tuple[int, int, int]:
    """green=ok, yellow=warn, orange=elevated, red=risky."""
    p = float(pct or 0)
    if kind == "temp_cpu":
        if p >= CRIT_TEMP_CPU:
            return RED
        if p >= WARN_TEMP_CPU:
            return ORANGE
        if p >= 55:
            return YELLOW
        return GREEN
    if kind == "temp":
        if p >= CRIT_TEMP_RADIO:
            return RED
        if p >= WARN_TEMP_RADIO:
            return ORANGE
        if p >= 45:
            return YELLOW
        return GREEN
    if kind == "disk":
        if p >= CRIT_DISK:
            return RED
        if p >= WARN_DISK:
            return ORANGE
        if p >= 50:
            return YELLOW
        return GREEN
    # load
    if p >= CRIT_LOAD:
        return RED
    if p >= WARN_LOAD:
        return ORANGE
    if p >= 50:
        return YELLOW
    return GREEN


def _is_crit_load(pct: float) -> bool:
    return float(pct or 0) >= CRIT_LOAD


def _is_crit_disk(pct: float) -> bool:
    return float(pct or 0) >= CRIT_DISK


def _is_crit_temp(label: str, val: int) -> bool:
    if label == "CPU":
        return val >= CRIT_TEMP_CPU
    if label in ("2G", "5G", "AVG", "TMP"):
        return val >= CRIT_TEMP_RADIO
    return False


def _draw_val_unit(
    img,
    x: int,
    y: int,
    num: str,
    unit: str,
    val_color: Sequence[int],
    *,
    size: str = "normal",
    alert: bool = False,
) -> int:
    x = _txt(img, x, y, num, val_color, size=size, role="value", alert=alert)
    if unit:
        x = _txt(img, x + 1, y + (0 if size != "big" else 2), unit, UNIT, size="tiny", role="unit")
    return x


def _header(img, draw: ImageDraw.ImageDraw, title: str, idx: int) -> None:
    screens = get_screen_ids()
    n = len(screens)
    draw.rectangle([0, 0, 63, 9], fill=HEADER)
    badge_w = 0
    if n > 1:
        label = str(idx + 1)
        tw = pf.text_width_tiny(label)
        badge_w = tw + 4
        bx0 = 63 - badge_w + 1
        draw.rectangle([bx0, 1, 63, 8], fill=HEADER_FG, outline=HEADER)
        pf.draw_tiny(img, bx0 + 2, 2, label, HEADER)
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


def _gauge_row(img, draw, y: int, label: str, pct: float, *, kind: str = "load") -> None:
    alert = _is_crit_load(pct) if kind == "load" else _is_crit_disk(pct)
    col = _level_color(pct, kind=kind if kind != "load" else "load")
    _txt(img, 2, y, label[:4], LABEL, size="tiny", role="label", alert=alert)
    _gauge(draw, 20, y, 42, pct, col, alert=alert)


def _graph(img, draw, x, y, w, h, data, color, filled: bool = False) -> None:
    if not data:
        _txt(img, x + 4, y + max(0, h // 2 - 3), "NO DATA", DIM, size="tiny", role="label")
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
        "clients_wired": 4,
        "clients_2g": 6,
        "clients_5g": 4,
        "clients_ssid": [{"ssid": "Home", "n": 7}, {"ssid": "IoT", "n": 3}],
        "wan_online": True,
        "wan_down": round(down, 2),
        "wan_up": round(up, 2),
        "wan_history_down": hist_d,
        "wan_history_up": hist_u,
        "cpu_history": [40 + 30 * abs(math.sin((t - i) / 9)) for i in range(32)],
        "temp_history": [50 + 10 * abs(math.sin((t - i) / 15)) for i in range(32)],
        "temp_avg": 52,
        "wifi_down": round(down * 0.7, 2),
        "wifi_up": round(up * 0.6, 2),
        "lan_down": round(down * 0.3, 2),
        "lan_up": round(up * 0.4, 2),
        "wifi_history_down": [x * 0.7 for x in hist_d],
        "wifi_history_up": [x * 0.6 for x in hist_u],
        "lan_history_down": [x * 0.3 for x in hist_d],
        "lan_history_up": [x * 0.4 for x in hist_u],
        "top_down": [["phone45", 125.0], ["living-tv", 42.0]],
        "top_up": [["nas-box", 18.0], ["cam-front", 7.0]],
        "temp_cpu": int(55 + 15 * abs(math.sin(t / 19))),
        "temp_2g": 45,
        "temp_5g": 52,
        "vpn1": {"on": True, "type": "OVPN"},
        "vpn2": {"on": False, "type": "WG"},
        "jffs": {"used": 22, "total": 100, "present": True},
        "usb": {"used": 81, "total": 100, "present": True},
        "usb2": {"present": True, "used": 40},
        "usb3": {"present": False, "used": 0},
        "lan_ports": [True, True, False, True],
        "ram_cache": {"buffers": 15, "cached": 25},
        "_demo": True,
    }


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
    nonzero = [p for p in parsed if p[1] > 0]
    return (nonzero if nonzero else parsed)[:limit]


def _active_vpns(m: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key, fallback in (("vpn1", "VPN1"), ("vpn2", "VPN2")):
        v = m.get(key) or {}
        if v.get("on"):
            out.append((fallback, str(v.get("type", "?"))[:4]))
    return out


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
    s = float(score or 0)
    if s >= 80:
        return GREEN
    if s >= 60:
        return YELLOW
    if s >= 40:
        return ORANGE
    return RED


def _health_score(m: dict[str, Any]) -> int:
    """Composite router health 0–100 from CPU, RAM, temps, disk, WAN."""
    cpu = float(m.get("cpu", 0) or 0)
    ram = float(m.get("ram", 0) or 0)
    t_cpu = float(m.get("temp_cpu", 0) or 0)
    t_avg = float(m.get("temp_avg", 0) or _temp_avg(m))
    disk = _disk_used_pct(m)
    online = bool(m.get("wan_online"))

    cpu_s = max(0.0, 100.0 - cpu)
    ram_s = max(0.0, 100.0 - ram)
    temp_s = min(_temp_score(t_cpu, kind="temp_cpu"), _temp_score(t_avg, kind="temp"))
    disk_s = max(0.0, 100.0 - disk)
    wan_s = 100.0 if online else 0.0

    score = (
        0.25 * cpu_s
        + 0.20 * ram_s
        + 0.30 * temp_s
        + 0.15 * disk_s
        + 0.10 * wan_s
    )
    return int(round(max(0.0, min(100.0, score))))


def _render_sum(img, d: ImageDraw.ImageDraw, m: dict[str, Any]) -> None:
    """Full-bleed summary (no title banner): health + key live metrics."""
    hp = _health_score(m)
    hp_col = _health_color(hp)
    alert_hp = hp < 40
    _txt(img, 1, 1, "HP", LABEL, size="tiny", role="label", alert=alert_hp)
    _draw_val_unit(img, 12, 0, str(hp), "%", hp_col, size="normal", alert=alert_hp)
    online = bool(m.get("wan_online"))
    if online or not _ALERT_BLINK or _blink_on():
        d.ellipse([57, 1, 62, 6], fill=GREEN if online else RED)
    _gauge(d, 1, 9, 62, hp, hp_col, alert=alert_hp)

    cpu = float(m.get("cpu", 0) or 0)
    ram = float(m.get("ram", 0) or 0)
    tmp = float(m.get("temp_avg", 0) or _temp_avg(m))
    disk = _disk_used_pct(m)

    y = 15
    for label, val, kind, unit in (
        ("CPU", cpu, "load", "%"),
        ("RAM", ram, "load", "%"),
        ("TMP", tmp, "temp_cpu", "°C"),
        ("DSK", disk, "disk", "%"),
    ):
        col = _level_color(val, kind=kind)
        alert = (
            _is_crit_load(val)
            if kind == "load"
            else (_is_crit_disk(val) if kind == "disk" else _is_crit_temp("CPU" if kind == "temp_cpu" else "TMP", int(val)))
        )
        _txt(img, 1, y, label, LABEL, size="tiny", role="label", alert=alert)
        _draw_val_unit(img, 16, y, str(int(val)), unit, col, size="tiny", alert=alert)
        bar_pct = val if kind != "temp_cpu" else min(100.0, (val / max(float(CRIT_TEMP_CPU), 1.0)) * 100.0)
        _gauge(d, 36, y + 1, 27, bar_pct, col, alert=alert)
        y += 6

    _txt(img, 1, y, "Dn", LABEL, size="tiny", role="label")
    dn, du = _split_rate(m.get("wan_down", 0))
    x = _draw_val_unit(img, 12, y, dn, du, GRAPH_DOWN, size="tiny")
    _txt(img, min(x + 2, 34), y, "Up", LABEL, size="tiny", role="label")
    un, uu = _split_rate(m.get("wan_up", 0))
    _draw_val_unit(img, min(x + 12, 44), y, un, uu, GRAPH_UP, size="tiny")
    y += 6

    clients = int(m.get("clients", 0) or 0)
    wifi = int(m.get("clients_wifi", 0) or 0)
    _txt(img, 1, y, "Cli", LABEL, size="tiny", role="label")
    _txt(img, 14, y, str(clients), FG, size="tiny", role="value")
    _txt(img, 28, y, "Wi", LABEL, size="tiny", role="label")
    _txt(img, 38, y, str(wifi), CYAN, size="tiny", role="value")
    vpns = _active_vpns(m)
    if vpns:
        _txt(img, 48, y, "V", GREEN, size="tiny", role="status")
    y += 6

    ports = list(m.get("lan_ports") or [False, False, False, False])[:4]
    while len(ports) < 4:
        ports.append(False)
    _txt(img, 1, y, "L", LABEL, size="tiny", role="label")
    x = 8
    for i, up in enumerate(ports, start=1):
        _txt(img, x, y, str(i), GREEN if up else RED, size="tiny", role="status")
        x += 6
    usb2 = m.get("usb2") or {}
    usb3 = m.get("usb3") or {}
    usb = m.get("usb") or {}
    u2 = bool(usb2.get("present") or usb.get("present"))
    u3 = bool(usb3.get("present"))
    _txt(img, 34, y, "U2", GREEN if u2 else RED, size="tiny", role="status")
    _txt(img, 48, y, "U3", GREEN if u3 else RED, size="tiny", role="status")
    y += 6

    tops = _pick_top(m.get("top_down"), limit=1)
    if tops:
        name, rate = tops[0]
        _txt(img, 1, y, _scroll(name, 7), FG, size="tiny", role="value")
        dn, du = _split_rate(rate)
        _draw_val_unit(img, 38, y, dn, du, GRAPH_DOWN, size="tiny")
    else:
        uptime = str(m.get("uptime_str", "--"))[:8]
        _txt(img, 1, y, "up", LABEL, size="tiny", role="label")
        _txt(img, 12, y, uptime, FG, size="tiny", role="value")


def render_screen(m: dict[str, Any], idx: int) -> Image.Image:
    screens = get_screen_ids() or ALL_SCREEN_IDS
    idx = idx % len(screens)
    sid = screens[idx]
    img = Image.new("RGB", (64, 64), BG)
    d = ImageDraw.Draw(img)
    if sid == "SUM":
        _render_sum(img, d, m)
        if m.get("_offline"):
            _txt(img, 48, 58, "OFF", YELLOW, size="tiny", role="value", alert=True)
        return img

    _header(img, d, SCREEN_TITLES.get(sid, sid), idx)

    if sid == "SYS":
        _txt(img, 2, 11, "up", LABEL, size="tiny", role="label")
        _txt(img, 14, 11, str(m.get("uptime_str", "--"))[:8], FG, size="tiny", role="value")
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
        _txt(img, 2, 46, "Down", LABEL, size="tiny", role="label")
        dn, du = _split_rate(m.get("wan_down", 0))
        _draw_val_unit(img, 22, 46, dn, du, GRAPH_DOWN, size="tiny")
        _txt(img, 2, 54, "Up", LABEL, size="tiny", role="label")
        un, uu = _split_rate(m.get("wan_up", 0))
        _draw_val_unit(img, 22, 54, un, uu, GRAPH_UP, size="tiny")

    elif sid == "LOD":
        cpu_h = list(m.get("cpu_history") or [])
        tmp_h = list(m.get("temp_history") or [])
        cpu_now = int(m.get("cpu", 0) or 0)
        tmp_now = int(m.get("temp_avg", 0) or _temp_avg(m))
        _txt(img, 2, 11, "CPU", LABEL, size="tiny", role="label")
        _draw_val_unit(
            img, 20, 11, str(cpu_now), "%", _level_color(cpu_now), size="tiny", alert=_is_crit_load(cpu_now)
        )
        _graph(img, d, 1, 18, 62, 18, cpu_h, _level_color(cpu_now), filled=True)
        _txt(img, 2, 38, "TMP", LABEL, size="tiny", role="label")
        _draw_val_unit(
            img,
            20,
            38,
            str(tmp_now),
            "°C",
            _level_color(tmp_now, kind="temp"),
            size="tiny",
            alert=_is_crit_temp("TMP", tmp_now),
        )
        _graph(img, d, 1, 45, 62, 17, tmp_h, _level_color(tmp_now, kind="temp"), filled=False)

    elif sid == "TMP":
        # Top: CPU | AVG — Bottom: 2G | 5G
        avg = int(m.get("temp_avg", 0) or _temp_avg(m))
        cells = [
            (0, 11, "CPU", int(m.get("temp_cpu", 0) or 0), "temp_cpu"),
            (32, 11, "AVG", avg, "temp"),
            (0, 37, "2G", int(m.get("temp_2g", 0) or 0), "temp"),
            (32, 37, "5G", int(m.get("temp_5g", 0) or 0), "temp"),
        ]
        for x, y, label, val, kind in cells:
            hot = _is_crit_temp(label if label != "AVG" else "TMP", val)
            col = _level_color(val, kind=kind)
            outline = RED if (hot and (not _ALERT_BLINK or _blink_on())) else DIM
            d.rectangle([x, y, x + 31, y + 24], outline=outline)
            _txt(img, x + 2, y + 2, label, LABEL, size="tiny", role="label", alert=hot)
            _draw_val_unit(img, x + 2, y + 11, str(val), "°C", col, size="normal", alert=hot)

    elif sid == "GRP":
        down = list(m.get("wan_history_down") or [])
        up = list(m.get("wan_history_up") or [])
        _txt(img, 2, 11, "Down", LABEL, size="tiny", role="label")
        dn, du = _split_rate(m.get("wan_down", 0))
        _draw_val_unit(img, 22, 11, dn, du, GRAPH_DOWN, size="tiny")
        _graph(img, d, 1, 18, 62, 18, down, GRAPH_DOWN, filled=True)
        _txt(img, 2, 38, "Up", LABEL, size="tiny", role="label")
        un, uu = _split_rate(m.get("wan_up", 0))
        _draw_val_unit(img, 22, 38, un, uu, GRAPH_UP, size="tiny")
        _graph(img, d, 1, 45, 62, 17, up, GRAPH_UP, filled=False)

    elif sid == "WLC":
        w_down = list(m.get("wifi_history_down") or [])
        l_down = list(m.get("lan_history_down") or [])
        _txt(img, 2, 11, "WiFi", LABEL, size="tiny", role="label")
        dn, du = _split_rate(m.get("wifi_down", 0))
        x = _draw_val_unit(img, 20, 11, dn, du, GRAPH_DOWN, size="tiny")
        _txt(img, min(x + 2, 40), 11, "Up", LABEL, size="tiny", role="label")
        un, uu = _split_rate(m.get("wifi_up", 0))
        _draw_val_unit(img, min(x + 12, 48), 11, un, uu, GRAPH_UP, size="tiny")
        _graph(img, d, 1, 18, 62, 18, w_down, GRAPH_DOWN, filled=True)
        _txt(img, 2, 38, "LAN", LABEL, size="tiny", role="label")
        dn, du = _split_rate(m.get("lan_down", 0))
        x = _draw_val_unit(img, 18, 38, dn, du, GRAPH_UP, size="tiny")
        _txt(img, min(x + 2, 40), 38, "Up", LABEL, size="tiny", role="label")
        un, uu = _split_rate(m.get("lan_up", 0))
        _draw_val_unit(img, min(x + 12, 48), 38, un, uu, ORANGE, size="tiny")
        _graph(img, d, 1, 45, 62, 17, l_down, GRAPH_UP, filled=False)

    elif sid == "TOP":
        _txt(img, 2, 11, "Down", LABEL, size="tiny", role="label")
        y = 18
        downs = _pick_top(m.get("top_down"))
        if not downs:
            _txt(img, 2, y, "(none)", DIM, size="tiny", role="label")
            y += 9
        for name, rate in downs:
            _txt(img, 2, y, _scroll(name, 6), FG, size="normal", role="value")
            dn, du = _split_rate(rate)
            _draw_val_unit(img, 40, y + 1, dn, du, GRAPH_DOWN, size="tiny")
            y += 9
        y = max(y + 1, 37)
        d.line([(2, y - 1), (61, y - 1)], fill=DIM)
        _txt(img, 2, y, "Up", LABEL, size="tiny", role="label")
        y += 7
        ups = _pick_top(m.get("top_up"))
        if not ups:
            _txt(img, 2, y, "(none)", DIM, size="tiny", role="label")
        for name, rate in ups:
            if y > 55:
                break
            _txt(img, 2, y, _scroll(name, 6), FG, size="normal", role="value")
            un, uu = _split_rate(rate)
            _draw_val_unit(img, 40, y + 1, un, uu, GRAPH_UP, size="tiny")
            y += 9

    elif sid == "CLI":
        total = int(m.get("clients", 0) or 0)
        wifi = int(m.get("clients_wifi", 0) or 0)
        wired = int(m.get("clients_wired", 0) or max(0, total - wifi))
        n2 = int(m.get("clients_2g", 0) or 0)
        n5 = int(m.get("clients_5g", 0) or 0)
        _txt(img, 2, 11, "All", LABEL, size="tiny", role="label")
        _txt(img, 18, 11, str(total), FG, size="normal", role="value")
        _txt(img, 2, 22, "WiFi", LABEL, size="tiny", role="label")
        _txt(img, 22, 22, str(wifi), CYAN, size="tiny", role="value")
        _txt(img, 34, 22, "LAN", LABEL, size="tiny", role="label")
        _txt(img, 50, 22, str(wired), ORANGE, size="tiny", role="value")
        _txt(img, 2, 30, "2G", LABEL, size="tiny", role="label")
        _txt(img, 14, 30, str(n2), GREEN, size="tiny", role="value")
        _txt(img, 34, 30, "5G", LABEL, size="tiny", role="label")
        _txt(img, 46, 30, str(n5), YELLOW, size="tiny", role="value")
        d.line([(2, 38), (61, 38)], fill=DIM)
        y = 40
        for row in list(m.get("clients_ssid") or [])[:3]:
            try:
                name, n = str(row.get("ssid", "?")), int(row.get("n", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            _txt(img, 2, y, _scroll(name, 8), FG, size="normal", role="value")
            _txt(img, 52, y + 1, str(n), CYAN, size="tiny", role="value")
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
        _txt(img, 2, 26, "WiFi", LABEL, size="tiny", role="label")
        _txt(img, 22, 26, str(wifi), CYAN, size="tiny", role="value")
        _txt(img, 34, 26, "All", LABEL, size="tiny", role="label")
        _txt(img, 50, 26, str(clients), FG, size="tiny", role="value")
        usb2 = m.get("usb2") or {}
        usb3 = m.get("usb3") or {}
        u2, u3 = bool(usb2.get("present")), bool(usb3.get("present"))
        _txt(img, 2, 38, "USB2", GREEN if u2 else RED, size="normal", role="status")
        _txt(img, 34, 38, "USB3", GREEN if u3 else RED, size="normal", role="status")
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
        _txt(img, 2, 11, "JFFS", LABEL, size="tiny", role="label")
        _draw_val_unit(img, 22, 11, str(j_used), "%", _level_color(j_used, kind="disk"), size="tiny")
        _txt(img, 36, 11, "USB", LABEL, size="tiny", role="label")
        _draw_val_unit(img, 52, 11, str(u_used), "%", _level_color(u_used, kind="disk"), size="tiny")
        j_col = _level_color(j_used, kind="disk")
        u_col = _level_color(u_used, kind="disk")
        show_j = not (_is_crit_disk(j_used) and _ALERT_BLINK and not _blink_on())
        show_u = not (_is_crit_disk(u_used) and _ALERT_BLINK and not _blink_on())
        pie(16, 30, 10, j_used if show_j else 0, j_col)
        pie(48, 30, 10, u_used if show_u else 0, u_col)
        _txt(img, 2, 44, "CACHE", LABEL, size="tiny", role="label")
        _draw_val_unit(img, 28, 44, str(c_used), "%", _level_color(c_used, kind="disk"), size="tiny")
        pie(48, 54, 7, c_used, _level_color(c_used, kind="disk"))

    elif sid == "SRV":
        y = 11
        vpns = _active_vpns(m)
        if not vpns:
            _txt(img, 2, y, "VPN", LABEL, size="tiny", role="label")
            _txt(img, 20, y, "none", DIM, size="tiny", role="value")
            y += 9
        else:
            for name, typ in vpns:
                _txt(img, 2, y, name, GREEN, size="tiny", role="status")
                _txt(img, 28, y, typ, FG, size="tiny", role="value")
                y += 8
        y = max(y + 1, 26)
        jffs = m.get("jffs") or {}
        usb2 = m.get("usb2") or {}
        usb3 = m.get("usb3") or {}
        usb = m.get("usb") or {}
        if not usb2 and not usb3 and usb:
            usb2 = {"present": bool(usb.get("present")), "used": usb.get("used", 0)}
        _gauge_row(img, d, y, "JFFS", float(jffs.get("used", 0) or 0), kind="disk")
        y += 9
        u2_on = bool(usb2.get("present"))
        u2_used = float(usb2.get("used", 0) or usb.get("used", 0) or 0)
        _txt(img, 2, y, "USB2", GREEN if u2_on else RED, size="tiny", role="status")
        if u2_on:
            _gauge(d, 24, y, 38, u2_used, _level_color(u2_used, kind="disk"), alert=_is_crit_disk(u2_used))
        else:
            _txt(img, 28, y, "off", RED, size="tiny", role="status")
        y += 9
        u3_on = bool(usb3.get("present"))
        u3_used = float(usb3.get("used", 0) or 0)
        _txt(img, 2, y, "USB3", GREEN if u3_on else RED, size="tiny", role="status")
        if u3_on:
            _gauge(d, 24, y, 38, u3_used, _level_color(u3_used, kind="disk"), alert=_is_crit_disk(u3_used))
        else:
            _txt(img, 28, y, "off", RED, size="tiny", role="status")

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
