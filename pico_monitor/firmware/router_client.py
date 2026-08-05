# Fetch Merlin metrics (HTTP JSON) + history buffers for graphs

import time

try:
    import config
except ImportError:
    config = None


class HistoryBuffer:
    def __init__(self, maxlen=64):
        self.maxlen = maxlen
        self.data = [0.0] * maxlen
        self.idx = 0
        self.count = 0

    def append(self, value):
        self.data[self.idx] = float(value)
        self.idx = (self.idx + 1) % self.maxlen
        if self.count < self.maxlen:
            self.count += 1

    def get_all(self):
        if self.count == 0:
            return []
        if self.count < self.maxlen:
            return self.data[: self.count]
        return self.data[self.idx :] + self.data[: self.idx]

    def get_max(self):
        vals = self.get_all()
        return max(vals) if vals else 1.0


class TrafficMonitor:
    def __init__(self, history_len=64):
        self.down_history = HistoryBuffer(history_len)
        self.up_history = HistoryBuffer(history_len)
        self.last_rx = 0
        self.last_tx = 0
        self.last_time = 0
        self.down_bps = 0.0
        self.up_bps = 0.0

    def update(self, rx_bytes, tx_bytes, current_time):
        if self.last_time > 0 and current_time > self.last_time:
            dt = current_time - self.last_time
            if dt > 0 and rx_bytes >= self.last_rx and tx_bytes >= self.last_tx:
                self.down_bps = (rx_bytes - self.last_rx) * 8.0 / dt
                self.up_bps = (tx_bytes - self.last_tx) * 8.0 / dt
                self.down_history.append(self.down_bps)
                self.up_history.append(self.up_bps)
        self.last_rx = rx_bytes
        self.last_tx = tx_bytes
        self.last_time = current_time


_traffic = None
_fail_streak = 0
_last_good = None


def init():
    global _traffic
    n = getattr(config, "HISTORY_LEN", 64) if config else 64
    _traffic = TrafficMonitor(n)


def _fmt_duration(seconds):
    seconds = int(seconds)
    m = seconds // 60
    s = seconds % 60
    return "%dm%02ds" % (m, s)


def _demo_metrics(t):
    import math

    down = 40e6 + 30e6 * abs(math.sin(t / 17))
    up = 8e6 + 6e6 * abs(math.sin(t / 23))
    _traffic.update(int(t * down / 8), int(t * up / 8), t)
    # fake cumulative via synthetic bytes
    return {
        "uptime_str": "12j04h",
        "cpu": int(40 + 35 * abs(math.sin(t / 11))),
        "ram": int(50 + 20 * abs(math.sin(t / 13))),
        "clients": 14,
        "clients_wifi": 10,
        "wan_online": True,
        "wan_down": _traffic.down_bps / 1e6,
        "wan_up": _traffic.up_bps / 1e6,
        "wan_history_down": list(_traffic.down_history.get_all()),
        "wan_history_up": list(_traffic.up_history.get_all()),
        "wan_history_max_down": _traffic.down_history.get_max(),
        "wan_history_max_up": _traffic.up_history.get_max(),
        "wan_history_duration": _fmt_duration(
            max(1, _traffic.down_history.count * getattr(config, "FETCH_INTERVAL_S", 3))
        ),
        "top_down": [(".45", 125.0), (".12", 42.0)],
        "top_up": [(".22", 87.0), (".33", 12.0)],
        "hw_accel": False,
        "temp_cpu": int(55 + 20 * abs(math.sin(t / 19))),
        "temp_2g": 45,
        "temp_5g": 52,
        "vpn1": {"on": True, "type": "OVPN"},
        "vpn2": {"on": False, "type": "WG"},
        "jffs": {"used": 22, "total": 100, "present": True},
        "usb": {"used": 81, "total": 100, "present": True},
        "ram_cache": {"buffers": 15, "cached": 25},
    }


def _http_get_json(url, timeout=4):
    try:
        import urequests

        r = urequests.get(url, timeout=timeout)
        try:
            data = r.json()
        finally:
            r.close()
        return data
    except Exception:
        # usocket fallback minimal GET
        try:
            import usocket
            import ujson

            # parse http://host:port/path
            if not url.startswith("http://"):
                return None
            rest = url[7:]
            hostpath = rest.split("/", 1)
            hostport = hostpath[0]
            path = "/" + (hostpath[1] if len(hostpath) > 1 else "")
            if ":" in hostport:
                host, port_s = hostport.split(":", 1)
                port = int(port_s)
            else:
                host, port = hostport, 80
            ai = usocket.getaddrinfo(host, port, 0, usocket.SOCK_STREAM)[0]
            s = usocket.socket(ai[0], ai[1], ai[2])
            s.settimeout(timeout)
            s.connect(ai[-1])
            req = "GET %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n" % (
                path,
                host,
            )
            s.send(req.encode())
            buf = b""
            while True:
                chunk = s.recv(512)
                if not chunk:
                    break
                buf += chunk
            s.close()
            body = buf.split(b"\r\n\r\n", 1)[-1]
            return ujson.loads(body)
        except Exception:
            return None


def fetch_all_metrics():
    """Return metrics dict for screens; degrade after 3 failures."""
    global _fail_streak, _last_good
    if _traffic is None:
        init()

    demo = getattr(config, "DEMO", 0) if config else 0
    if demo:
        m = _demo_metrics(time.time())
        _last_good = m
        _fail_streak = 0
        return m

    host = getattr(config, "ROUTER_HOST", "192.168.50.1")
    port = getattr(config, "ROUTER_PORT", 8088)
    path = getattr(config, "METRICS_PATH", "/metrics.json")
    url = "http://%s:%d%s" % (host, port, path)
    data = _http_get_json(url)
    if not data:
        _fail_streak += 1
        if _last_good and _fail_streak < 3:
            d = dict(_last_good)
            d["wan_online"] = False
            return d
        if _last_good:
            d = dict(_last_good)
            d["wan_online"] = False
            d["_degraded"] = True
            return d
        return {"wan_online": False, "_offline": True}

    _fail_streak = 0
    # Prefer server-provided history; else derive from counters
    if "rx_bytes" in data and "tx_bytes" in data:
        _traffic.update(int(data["rx_bytes"]), int(data["tx_bytes"]), time.time())
        data.setdefault("wan_down", _traffic.down_bps / 1e6)
        data.setdefault("wan_up", _traffic.up_bps / 1e6)
        data["wan_history_down"] = list(_traffic.down_history.get_all())
        data["wan_history_up"] = list(_traffic.up_history.get_all())
        data["wan_history_max_down"] = _traffic.down_history.get_max()
        data["wan_history_max_up"] = _traffic.up_history.get_max()
        data["wan_history_duration"] = _fmt_duration(
            max(1, _traffic.down_history.count * getattr(config, "FETCH_INTERVAL_S", 3))
        )
    _last_good = data
    return data
