# 64x64 1-bit display helpers — dashboard style

from lib import fonts
from icons import blit_icon

# Precomputed sin/cos for pie (0..63 → quarter-circle scaled later)
# angle index 0..63 covers 0..360°; values = cos/sin * 256
_COS = bytearray(64)
_SIN = bytearray(64)


def _init_trig():
    # integer approx without importing math at module load cost repeatedly
    import math

    for i in range(64):
        a = i * 2 * math.pi / 64
        _COS[i] = int(math.cos(a) * 127) & 0xFF
        _SIN[i] = int(math.sin(a) * 127) & 0xFF


_init_trig()

_fb = None
_oled = None
_blink = False


def init(i2c=None, width=64, height=64, addr=0x3C):
    """Init SSD1306 or use a software FrameBuffer for host preview."""
    global _fb, _oled
    if i2c is None:
        import framebuf

        buf = bytearray(width * height // 8)
        _fb = framebuf.FrameBuffer(buf, width, height, framebuf.MONO_VLSB)
        _oled = None
        return _fb
    from lib.ssd1306 import SSD1306_I2C

    _oled = SSD1306_I2C(width, height, i2c, addr=addr)
    _fb = _oled
    return _fb


def fb():
    return _fb


def clear():
    _fb.fill(0)


def show():
    """Push buffer to OLED. No-op for host software FB (preview reads _fb)."""
    if _oled is not None:
        _oled.show()


def set_blink(on):
    global _blink
    _blink = bool(on)


def ensure_fb(width=64, height=64):
    """Guarantee a framebuffer exists (host preview / failed I2C)."""
    if _fb is None:
        init(None, width, height)
    return _fb


def draw_header_inverted(title, page_idx, pages=6):
    """Barre blanche 64x10 — titre 3 lettres gauche, dots pagination droite."""
    _fb.fill_rect(0, 0, 64, 10, 1)
    t = (title or "???")[:3].upper()
    fonts.draw_normal(_fb, 2, 2, t, 0)
    # dots ●○○○○○ at right
    dx = 64 - pages * 5 - 2
    for i in range(pages):
        x = dx + i * 5
        if i == page_idx:
            _fb.fill_rect(x, 3, 3, 3, 0)
        else:
            _fb.pixel(x + 1, 4, 0)
            _fb.rect(x, 3, 3, 3, 0)


def draw_big_number(x, y, value_str):
    fonts.draw_big(_fb, x, y, str(value_str), 1)


def draw_tiny_text(x, y, text):
    return fonts.draw_tiny(_fb, x, y, str(text), 1)


def draw_label(x, y, text):
    return fonts.draw_normal(_fb, x, y, str(text), 1)


def draw_icon(x, y, icon):
    blit_icon(_fb, x, y, icon, 1)


def draw_thick_gauge(x, y, w, h, percent, pattern_fill=True):
    """Jauges 4px haut, coins arrondis, w<=38."""
    w = min(38, max(4, w))
    h = max(3, min(6, h))
    pct = max(0, min(100, int(percent)))
    # outline rounded-ish
    _fb.rect(x, y, w, h, 1)
    _fb.pixel(x, y, 0)
    _fb.pixel(x + w - 1, y, 0)
    _fb.pixel(x, y + h - 1, 0)
    _fb.pixel(x + w - 1, y + h - 1, 0)
    fill_w = int((w - 2) * pct / 100)
    if fill_w <= 0:
        return
    for i in range(fill_w):
        for j in range(1, h - 1):
            if pattern_fill and pct <= 50 and ((x + 1 + i + j) & 1):
                continue
            _fb.pixel(x + 1 + i, y + j, 1)
    # % text inverted inside if >50
    if pct > 50:
        s = "%d" % pct
        tw = fonts.text_width_tiny(s)
        tx = x + max(1, (w - tw) // 2)
        ty = y
        # punch hole then draw tiny inverted = draw black then... on white fill use 0
        for i, ch in enumerate(s):
            fonts.draw_tiny(_fb, tx + i * 4, ty, ch, 0)


def draw_vbar(x, y, h, percent):
    """Barre verticale 2px."""
    pct = max(0, min(100, int(percent)))
    fill = int(h * pct / 100)
    _fb.rect(x, y, 2, h, 1)
    if fill > 0:
        _fb.fill_rect(x, y + h - fill, 2, fill, 1)


def draw_toggle(x, y, is_on):
    """ON=[●━] 12x6, OFF=[━○]."""
    _fb.rect(x, y, 12, 6, 1)
    if is_on:
        _fb.fill_rect(x + 1, y + 1, 4, 4, 1)
        _fb.hline(x + 6, y + 2, 4, 1)
        _fb.hline(x + 6, y + 3, 4, 1)
    else:
        _fb.hline(x + 2, y + 2, 4, 1)
        _fb.hline(x + 2, y + 3, 4, 1)
        _fb.rect(x + 7, y + 1, 4, 4, 1)


def draw_dotted_hline(y, x0=0, x1=64, step=2):
    for x in range(x0, x1, step):
        _fb.pixel(x, y, 1)


def draw_dotted_vline(x, y0, y1, step=2):
    for y in range(y0, y1, step):
        _fb.pixel(x, y, 1)


def draw_grid(x, y, w, h, step=8):
    for gx in range(x, x + w, step):
        for gy in range(y, y + h, step):
            _fb.pixel(gx, gy, 1)


def draw_graph_zone(x, y, w, h, data, max_val, is_filled=False, style="solid"):
    """
    Courbe dans zone w×h.
    style: 'solid' (2px), 'dotted' (1px pattern)
    is_filled: hachure sous la courbe
    """
    if not data or max_val <= 0:
        draw_tiny_text(x + 2, y + h // 2 - 2, "NO DATA")
        return
    draw_grid(x, y, w, h, 8)
    n = len(data)
    if n < 2:
        return
    pts = []
    for i, v in enumerate(data):
        px = x + int(i * (w - 1) / (n - 1))
        frac = max(0.0, min(1.0, float(v) / max_val))
        py = y + h - 1 - int(frac * (h - 1))
        pts.append((px, py))
    # fill hatch under curve
    if is_filled:
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            for px in range(x0, x1 + 1):
                if x1 == x0:
                    yy = y0
                else:
                    yy = y0 + (y1 - y0) * (px - x0) // (x1 - x0)
                for py in range(yy, y + h):
                    if ((px + py) & 1) == 0:
                        _fb.pixel(px, py, 1)
    # stroke
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if style == "dotted":
            # dashed line
            steps = max(1, abs(x1 - x0))
            for s in range(steps + 1):
                if (s & 1) == 0:
                    continue
                t = s / steps
                px = int(x0 + (x1 - x0) * t)
                py = int(y0 + (y1 - y0) * t)
                _fb.pixel(px, py, 1)
        else:
            _fb.line(x0, y0, x1, y1, 1)
            # 2px thickness
            if y0 > y:
                _fb.line(x0, y0 - 1, x1, max(y, y1 - 1), 1)


def _cos_sin(idx):
    # signed from stored byte
    c = _COS[idx & 63]
    s = _SIN[idx & 63]
    if c >= 128:
        c -= 256
    if s >= 128:
        s -= 256
    return c, s


def draw_pie_chart(x, y, size, percent, label=None):
    """Camembert size×size (typ. 22) — hachuré, centre 4px pour %."""
    pct = max(0, min(100, int(percent)))
    cx = x + size // 2
    cy = y + size // 2
    radius = size // 2 - 2
    r2 = radius * radius
    hole = 2
    hole2 = hole * hole
    sector = int(64 * pct / 100)  # 0..64 steps of full circle

    # outline
    for i in range(64):
        c, s = _cos_sin(i)
        px = cx + (c * radius) // 127
        py = cy + (s * radius) // 127
        _fb.pixel(px, py, 1)

    # filled sector from angle 0 (east) clockwise-ish via index
    for j in range(size):
        for i in range(size):
            dx = (x + i) - cx
            dy = (y + j) - cy
            d2 = dx * dx + dy * dy
            if d2 > r2 or d2 < hole2:
                continue
            # angle index 0..63
            import math

            ang = math.atan2(dy, dx)
            if ang < 0:
                ang += 2 * math.pi
            idx = int(ang * 64 / (2 * math.pi)) % 64
            if idx <= sector:
                if ((i + j) & 1) == 0:
                    _fb.pixel(x + i, y + j, 1)

    # center percent
    if pct >= 15:
        s = "%d" % pct
        tw = fonts.text_width_tiny(s)
        fonts.draw_tiny(_fb, cx - tw // 2, cy - 2, s, 1)

    if label:
        fonts.draw_tiny(_fb, x, y + size + 1, label, 1)


def draw_progress_ring(x, y, size, percent, thickness=2):
    """Anneau 16x16 typ."""
    pct = max(0, min(100, int(percent)))
    cx = x + size // 2
    cy = y + size // 2
    ro = size // 2 - 1
    ri = max(1, ro - thickness)
    sector = int(64 * pct / 100)
    for i in range(64):
        c, s = _cos_sin(i)
        for r in range(ri, ro + 1):
            px = cx + (c * r) // 127
            py = cy + (s * r) // 127
            if i <= sector:
                _fb.pixel(px, py, 1)
            elif r == ro or r == ri:
                if (i & 1) == 0:
                    _fb.pixel(px, py, 1)


def draw_status_banner(msg="OFFLINE"):
    """Full-screen status — always visible when OLED I2C works.

    Uses NORMAL 5x7 (tiny font is units-only historically). Split long
    messages across two centered lines so letters are never blank gaps.
    """
    ensure_fb()
    clear()
    _fb.fill_rect(0, 0, 64, 10, 1)
    fonts.draw_normal(_fb, 2, 2, "PICO", 0)

    text = (msg or "ERROR").upper().replace("_", " ")
    # Prefer short readable phrases
    if text in ("ROUTER OFFLINE", "OFFLINE", "HTTP FAIL"):
        line1, line2 = "ROUTER", "OFFLINE"
    elif " " in text and len(text) > 9:
        parts = text.split(" ", 1)
        line1, line2 = parts[0][:10], parts[1][:10]
    else:
        line1, line2 = text[:10], ""

    on = not _blink
    _fb.fill_rect(0, 20, 64, 28, 1 if on else 0)
    col = 0 if on else 1
    tw1 = fonts.text_width_normal(line1)
    fonts.draw_normal(_fb, max(1, (64 - tw1) // 2), 24, line1, col)
    if line2:
        tw2 = fonts.text_width_normal(line2)
        fonts.draw_normal(_fb, max(1, (64 - tw2) // 2), 34, line2, col)
    fonts.draw_tiny(_fb, 10, 54, "CHECK WIFI", 1)
    show()


def draw_offline_banner(msg="ROUTER OFFLINE"):
    draw_status_banner(msg)
