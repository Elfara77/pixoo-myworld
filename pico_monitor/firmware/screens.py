# Six dashboard screens for 64x64 OLED

import display as d
import icons


def _rate_str(mbps):
    """Format Mbps float → tiny/bold friendly string + unit."""
    v = float(mbps or 0)
    if v >= 1000:
        return "%.1f" % (v / 1000.0), "G"
    if v >= 1:
        if v >= 100:
            return "%.0f" % v, "M"
        return "%.1f" % v, "M"
    kb = v * 1000
    return "%.0f" % kb, "K"


def _scale_max(data_max):
    m = float(data_max or 1)
    return max(m * 1.2, 1.0)


class DisplayManager:
    def __init__(self):
        self.data = {}
        self.error = None
        self._tick = 0

    def update_data(self, data):
        self.data = data or {}
        self.error = None

    def set_error(self, msg):
        self.error = msg

    def _m(self):
        return self.data


_mgr = DisplayManager()


def manager():
    return _mgr


def draw_screen_sys():
    m = _mgr._m()
    d.clear()
    d.draw_header_inverted("SYS", 0)
    # uptime + online
    d.draw_icon(1, 11, icons.ICON_CLOCK)
    d.draw_label(11, 12, m.get("uptime_str", "--"))
    online = m.get("wan_online", False)
    if online:
        d.fb().fill_rect(58, 13, 4, 4, 1)
    else:
        d.fb().rect(58, 13, 4, 4, 1)
    # CPU / RAM gauges
    d.draw_icon(1, 19, icons.ICON_CPU)
    d.draw_thick_gauge(12, 21, 38, 4, m.get("cpu", 0))
    d.draw_tiny_text(52, 21, "%d" % int(m.get("cpu", 0)))
    d.draw_icon(1, 28, icons.ICON_RAM)
    d.draw_thick_gauge(12, 30, 38, 4, m.get("ram", 0))
    d.draw_tiny_text(52, 30, "%d" % int(m.get("ram", 0)))
    # clients
    d.draw_icon(1, 38, icons.ICON_USER)
    d.draw_label(12, 39, "%d" % int(m.get("clients", 0)))
    d.draw_tiny_text(28, 40, "W:%d" % int(m.get("clients_wifi", 0)))
    # rates
    dn, du = _rate_str(m.get("wan_down", 0))
    un, uu = _rate_str(m.get("wan_up", 0))
    d.draw_icon(1, 47, icons.ICON_DOWN)
    d.draw_tiny_text(11, 49, dn + du)
    d.draw_icon(34, 47, icons.ICON_UP)
    d.draw_tiny_text(44, 49, un + uu)
    d.show()


def draw_screen_graph():
    m = _mgr._m()
    d.clear()
    d.draw_header_inverted("GRP", 1)
    down = m.get("wan_history_down") or []
    up = m.get("wan_history_up") or []
    max_d = _scale_max(m.get("wan_history_max_down") or (max(down) if down else 1))
    max_u = _scale_max(m.get("wan_history_max_up") or (max(up) if up else 1))
    # DOWN zone y10-32
    d.draw_icon(0, 10, icons.ICON_DOWN)
    cur_d, u_d = _rate_str(m.get("wan_down", 0))
    d.draw_big_number(10, 10, cur_d[:4])
    mx_d, mu_d = _rate_str(max_d / 1e6 if max_d > 1000 else max_d / 1e6)
    # max_d is in bps from history
    mx_val = max_d / 1e6
    mx_s, mx_u = _rate_str(mx_val)
    d.draw_tiny_text(48, 10, "m" + mx_s + mx_u)
    hist_d = [v / 1e6 for v in down] if down and down[0] > 1000 else list(down)
    # normalize: server may send Mbps already
    if down and max(down) > 10000:
        plot_d = [v / 1e6 for v in down]
        plot_max_d = max_d / 1e6
    else:
        plot_d = list(down)
        plot_max_d = max(max_d / 1e6 if max_d > 500 else max_d, 0.1)
    d.draw_graph_zone(0, 12, 64, 20, plot_d, max(plot_max_d * 1.2, 0.1), True, "solid")
    d.draw_dotted_hline(33)
    # UP zone
    d.draw_icon(0, 34, icons.ICON_UP)
    cur_u, u_u = _rate_str(m.get("wan_up", 0))
    d.draw_big_number(10, 34, cur_u[:4])
    if up and max(up) > 10000:
        plot_u = [v / 1e6 for v in up]
        plot_max_u = max_u / 1e6
    else:
        plot_u = list(up)
        plot_max_u = max(max_u / 1e6 if max_u > 500 else max_u, 0.1)
    mx_s2, mx_u2 = _rate_str(plot_max_u)
    d.draw_tiny_text(48, 34, "m" + mx_s2 + mx_u2)
    d.draw_graph_zone(0, 36, 64, 22, plot_u, max(plot_max_u * 1.2, 0.1), False, "dotted")
    n = len(plot_d) if plot_d else 0
    d.draw_tiny_text(1, 59, "%dpts %s" % (n, m.get("wan_history_duration", "--")))
    d.show()


def draw_screen_top():
    m = _mgr._m()
    d.clear()
    from lib import fonts

    # split header DL : UL
    d.fb().fill_rect(0, 0, 64, 10, 1)
    fonts.draw_normal(d.fb(), 4, 2, "DL", 0)
    fonts.draw_normal(d.fb(), 28, 2, ":", 0)
    fonts.draw_normal(d.fb(), 40, 2, "UL", 0)
    d.draw_dotted_vline(32, 10, 64, 2)
    downs = m.get("top_down") or []
    ups = m.get("top_up") or []
    y = 12
    for row in downs[:2]:
        name, rate = row[0], float(row[1])
        fonts.draw_big(d.fb(), 1, y, str(name)[-3:][:3], 1)
        rs, ru = _rate_str(rate)
        fonts.draw_tiny(d.fb(), 1, y + 14, rs + ru, 1)
        d.draw_vbar(28, y, 16, min(100, int(rate / 2)))
        y += 22
    y = 12
    for row in ups[:2]:
        name, rate = row[0], float(row[1])
        fonts.draw_big(d.fb(), 34, y, str(name)[-3:][:3], 1)
        rs, ru = _rate_str(rate)
        fonts.draw_tiny(d.fb(), 34, y + 14, rs + ru, 1)
        d.draw_vbar(60, y, 16, min(100, int(rate / 2)))
        y += 22
    d.show()


def draw_screen_tmp():
    m = _mgr._m()
    d.clear()
    d.draw_header_inverted("TMP", 3)
    tc = int(m.get("temp_cpu", 0))
    t2 = int(m.get("temp_2g", 0))
    t5 = int(m.get("temp_5g", 0))
    try:
        import config as _cfg

        cpu_lim = getattr(_cfg, "TEMP_CPU_ALERT", 85)
        wifi_lim = getattr(_cfg, "TEMP_WIFI_ALERT", 65)
    except ImportError:
        cpu_lim, wifi_lim = 85, 65
    alert_c = tc >= cpu_lim
    alert_w = max(t2, t5) >= wifi_lim
    # 2x2 cells
    cells = [
        (0, 12, icons.ICON_CHIP, "%d" % tc, "C", alert_c and (_mgr._tick & 1)),
        (32, 12, icons.ICON_WIFI, "%d" % t2, "2", alert_w and (_mgr._tick & 1)),
        (0, 34, icons.ICON_WIFI, "%d" % t5, "5", alert_w and (_mgr._tick & 1)),
        (32, 34, icons.ICON_OK, "OK", "", False),
    ]
    from lib import fonts

    for x, y, icon, val, tag, inv in cells:
        if inv:
            d.fb().fill_rect(x, y, 32, 18, 1)
            col = 0
        else:
            d.fb().rect(x, y, 32, 18, 1)
            col = 1
        blit = icons.blit_icon
        # draw icon manually with color
        for row in range(8):
            bits = icon[row]
            for col_i in range(8):
                if bits & (0x80 >> col_i):
                    d.fb().pixel(x + 2 + col_i, y + 2 + row, col)
        fonts.draw_big(d.fb(), x + 12, y + 2, val[:3], col)
        if tag:
            fonts.draw_tiny(d.fb(), x + 26, y + 12, tag, col)
    # footer ports hint
    d.draw_tiny_text(2, 56, "[C][2][5][F]")
    _mgr._tick += 1
    d.show()


def draw_screen_pie():
    m = _mgr._m()
    d.clear()
    d.draw_header_inverted("PIE", 4)
    jffs = m.get("jffs") or {}
    usb = m.get("usb") or {}
    cache = m.get("ram_cache") or {}
    d.draw_tiny_text(8, 11, "JFFS")
    d.draw_tiny_text(40, 11, "USB")
    if jffs.get("present", True):
        d.draw_pie_chart(5, 14, 22, int(jffs.get("used", 0)))
        d.draw_tiny_text(5, 38, "%d%%" % int(jffs.get("used", 0)))
    else:
        d.draw_tiny_text(8, 22, "N/A")
    if usb.get("present", False):
        d.draw_pie_chart(37, 14, 22, int(usb.get("used", 0)))
        d.draw_tiny_text(37, 38, "%d%%" % int(usb.get("used", 0)))
    else:
        d.draw_tiny_text(40, 22, "N/A")
    d.draw_tiny_text(2, 43, "RAM Cache")
    buff = int(cache.get("buffers", 0))
    d.draw_pie_chart(21, 47, 16, buff)
    d.draw_tiny_text(40, 52, "%d%%" % buff)
    d.show()


def draw_screen_srv():
    m = _mgr._m()
    d.clear()
    d.draw_header_inverted("SRV", 5)
    v1 = m.get("vpn1") or {}
    v2 = m.get("vpn2") or {}
    d.draw_tiny_text(1, 12, "VPN1")
    d.draw_toggle(22, 11, bool(v1.get("on")))
    d.draw_tiny_text(38, 12, str(v1.get("type", "OVPN"))[:4])
    d.draw_tiny_text(1, 22, "VPN2")
    d.draw_toggle(22, 21, bool(v2.get("on")))
    d.draw_tiny_text(38, 22, str(v2.get("type", "WG"))[:4])
    jffs = m.get("jffs") or {}
    usb = m.get("usb") or {}
    d.draw_tiny_text(1, 32, "JFFS")
    d.draw_thick_gauge(20, 33, 38, 4, int(jffs.get("used", 0)))
    d.draw_tiny_text(1, 42, "USB")
    if usb.get("present", False):
        d.draw_thick_gauge(20, 43, 38, 4, int(usb.get("used", 0)))
    else:
        d.draw_tiny_text(22, 43, "N/A")
    d.show()


SCREENS = (
    draw_screen_sys,
    draw_screen_graph,
    draw_screen_top,
    draw_screen_tmp,
    draw_screen_pie,
    draw_screen_srv,
)
