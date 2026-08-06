"""SUM_GRAPH — full-bleed WAN down/up history (64 samples) for Pixoo 64×64."""

from __future__ import annotations

from typing import Any

from PIL import ImageDraw

from pixoo_bridge import pixel_font as pf

# Local accents (down / up)
COL_DN = (40, 190, 255)  # cyan-blue — download
COL_UP = (255, 140, 50)  # orange — upload
WHITE = (255, 255, 255)
DIM = (100, 108, 122)


def _tail64(hist: Any) -> list[float]:
    try:
        vals = [float(x) for x in (hist or [])]
    except (TypeError, ValueError):
        vals = []
    if not vals:
        return [0.0] * 64
    if len(vals) >= 64:
        return vals[-64:]
    return [0.0] * (64 - len(vals)) + vals


def render_sum_graph(img, draw: ImageDraw.ImageDraw, m: dict[str, Any]) -> None:
    """Replace prior multi-block SUM_GRAPH with a pure WAN D/U history screen."""
    from pixoo_bridge import render as R

    down_h = _tail64(m.get("wan_history_down"))
    up_h = _tail64(m.get("wan_history_up"))
    down_now = float(m.get("wan_down", 0) or 0)
    up_now = float(m.get("wan_up", 0) or 0)
    online = bool(m.get("wan_online"))

    # Header strip (tiny): Dn rate | Up rate | WAN status
    pf.draw_tiny(img, 0, 0, "DN", WHITE)
    dn_col = R._wan_link_color(down_now, R._WAN_MAX_DOWN_MBPS)
    R._draw_rate(img, 10, 0, down_now, color=dn_col)

    up_lab = "UP"
    up_x = 34
    pf.draw_tiny(img, up_x, 0, up_lab, WHITE)
    up_col = R._wan_link_color(up_now, R._WAN_MAX_UP_MBPS)
    R._draw_rate(img, up_x + 10, 0, up_now, color=up_col)

    if online:
        pf.draw_tiny(img, 56, 0, "OK", (40, 220, 110))
    else:
        # Blink handled by caller OFF badge; still mark WAN
        pf.draw_tiny(img, 52, 0, "WAN", (255, 70, 70))

    # Main dual graph: full width, samples map 1:1 to x when n==64
    # y=6..56 → 51px tall; footer legend y=58..63
    R._graph_up_down(
        img,
        draw,
        0,
        6,
        64,
        51,
        down_h,
        up_h,
        COL_DN,
        COL_UP,
        fill_down=True,
    )

    # Legend / peaks
    peak_d = max(down_h) if down_h else 0.0
    peak_u = max(up_h) if up_h else 0.0
    pf.draw_tiny(img, 0, 59, "DN", COL_DN)
    R._draw_rate(img, 10, 59, peak_d, color=COL_DN)
    pf.draw_tiny(img, 34, 59, "UP", COL_UP)
    R._draw_rate(img, 44, 59, peak_u, color=COL_UP)
