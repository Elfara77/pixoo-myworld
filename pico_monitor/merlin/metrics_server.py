#!/usr/bin/env python3
"""Lightweight HTTP /metrics.json for Pico OLED — runs on Asuswrt-Merlin + Entware.

Aligned with asus_merlin/pixoo_merlin metrics semantics (kbps→Mbps, Wi‑Fi temps,
jffs/usb df, top clients best-effort). Avoids hammering wl every request.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST = os.environ.get("PICO_METRICS_HOST", "0.0.0.0")
PORT = int(os.environ.get("PICO_METRICS_PORT", "8088"))
SAMPLE_MIN_S = float(os.environ.get("PICO_SAMPLE_MIN_S", "2.5"))
HISTORY_LEN = int(os.environ.get("PICO_HISTORY_LEN", "64"))

_last = {"ts": 0.0, "payload": {}}
_prev_net = None  # (ts, rx, tx)
_hist_down: list[float] = []
_hist_up: list[float] = []
_prev_sta: dict[str, tuple[float, int, int]] = {}


def _run(cmd: str, timeout: float = 3.0) -> str:
    try:
        out = subprocess.check_output(
            cmd, shell=True, stderr=subprocess.DEVNULL, timeout=timeout, text=True
        )
        return (out or "").strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def _nvram(key: str) -> str:
    return _run(f"nvram get {key} 2>/dev/null")


def _wan_iface() -> str:
    return _nvram("wan0_ifname") or _nvram("wan_ifname") or "eth0"


def _iface_bytes(iface: str) -> tuple[int, int] | None:
    try:
        text = Path(f"/sys/class/net/{iface}/statistics/rx_bytes").read_text()
        rx = int(text.strip())
        text = Path(f"/sys/class/net/{iface}/statistics/tx_bytes").read_text()
        tx = int(text.strip())
        return rx, tx
    except (OSError, ValueError):
        return None


def _cpu_pct() -> float:
    # loadavg * 100 / nproc rough
    try:
        load = float(Path("/proc/loadavg").read_text().split()[0])
        cpus = max(1, os.cpu_count() or 1)
        return max(0.0, min(100.0, load * 100.0 / cpus))
    except (OSError, ValueError):
        return 0.0


def _mem() -> tuple[float, int, int]:
    """Return ram_pct, buffers_mb, cached_mb."""
    info = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal", 1)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        used_pct = max(0.0, min(100.0, (1 - avail / total) * 100))
        buff = info.get("Buffers", 0) // 1024
        cached = info.get("Cached", 0) // 1024
        buff_pct = int(100 * info.get("Buffers", 0) / total)
        return used_pct, buff_pct, int(100 * info.get("Cached", 0) / total)
    except (OSError, ValueError, ZeroDivisionError):
        return 0.0, 0, 0


def _uptime_str() -> str:
    try:
        secs = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError):
        return "--"
    days = int(secs // 86400)
    hours = int((secs % 86400) // 3600)
    if days > 0:
        return f"{days}j{hours:02d}h"
    mins = int((secs % 3600) // 60)
    return f"{hours}h{mins:02d}m"


def _temp_cpu() -> float:
    for p in (
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/hwmon/hwmon0/temp1_input",
    ):
        try:
            v = int(Path(p).read_text().strip())
            return v / 1000.0 if v > 200 else float(v)
        except (OSError, ValueError):
            continue
    # Merlin often uses wl phy_tempsense on radio; fallback nvram/thermal
    out = _run("cat /proc/dmu/temperature 2>/dev/null | awk '{print $NF}'")
    try:
        return float(re.sub(r"[^0-9.]", "", out) or 0)
    except ValueError:
        return 0.0


def _wl_temps() -> tuple[float, float]:
    t2 = t5 = 0.0
    for iface in ("eth1", "eth2", "eth3", "eth4", "eth5", "eth6", "eth7", "wl0", "wl1"):
        out = _run(f"wl -i {iface} phy_tempsense 2>/dev/null")
        if not out:
            continue
        try:
            # "0xXX 0xYY" → first number °C/2 or raw
            num = int(out.split()[0], 0)
            c = num // 2 if num > 100 else float(num)
        except (ValueError, IndexError):
            continue
        if "5" in iface or iface in ("eth2", "eth3", "wl1"):
            if t5 == 0:
                t5 = c
        else:
            if t2 == 0:
                t2 = c
    return t2, t5


def _clients() -> tuple[int, int]:
    wifi = 0
    for iface in ("eth1", "eth2", "eth3", "eth4", "eth5", "eth6", "eth7", "wl0", "wl1"):
        out = _run(f"wl -i {iface} assoclist 2>/dev/null")
        wifi += len(re.findall(r"(?i)assoclist\s+([0-9a-f:]{17})", out))
    # online estimate from arp
    arp = Path("/proc/net/arp").read_text() if Path("/proc/net/arp").is_file() else ""
    total = max(wifi, len(re.findall(r"0x2\s+", arp)))
    return total, wifi


def _df_pct(path: str) -> tuple[int, bool]:
    out = _run(f"df -P {path} 2>/dev/null | awk 'NR==2 {{print $5}}'")
    m = re.search(r"(\d+)", out)
    if not m:
        return 0, False
    return int(m.group(1)), True


def _usb_pct() -> tuple[int, bool]:
    for base in (Path("/tmp/mnt"), Path("/mnt")):
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                return _df_pct(str(entry))
    return 0, False


def _vpn() -> tuple[dict, dict]:
    ovpn = _run("pidof vpnclient1 openvpn 2>/dev/null")
    st1 = _nvram("vpn_client1_state")
    on1 = bool(ovpn) or st1 in ("2", "connected", "1")
    st2 = _nvram("vpn_client2_state")
    on2 = st2 in ("2", "connected", "1")
    return {"on": on1, "type": "OVPN"}, {"on": on2, "type": "WG"}


def _top_clients_wifi(now: float) -> tuple[list, list]:
    """Best-effort top 2 down/up from wl sta_info (capped)."""
    rates = []
    n = 0
    for iface in ("eth1", "eth2", "eth3", "eth4", "eth5", "eth6", "eth7"):
        assoc = _run(f"wl -i {iface} assoclist 2>/dev/null")
        for mac in re.findall(r"(?i)([0-9a-f:]{17})", assoc):
            if n >= 8:
                break
            n += 1
            out = _run(f"wl -i {iface} sta_info {mac} 2>/dev/null", timeout=2.0)
            rx = tx = None
            for line in out.splitlines():
                ls = line.strip().lower()
                try:
                    if ls.startswith("tx ucast bytes:") or ls.startswith("tx data bytes:"):
                        tx = int(ls.split(":", 1)[1].split()[0])
                    elif ls.startswith("rx ucast bytes:") or ls.startswith("rx data bytes:"):
                        rx = int(ls.split(":", 1)[1].split()[0])
                except (ValueError, IndexError):
                    pass
            if rx is None and tx is None:
                continue
            rx = rx or 0
            tx = tx or 0
            prev = _prev_sta.get(mac)
            _prev_sta[mac] = (now, rx, tx)
            if prev:
                pts, prx, ptx = prev
                dt = max(0.001, now - pts)
                down = max(0.0, (tx - ptx) * 8 / 1000 / dt)  # kbps
                up = max(0.0, (rx - prx) * 8 / 1000 / dt)
            else:
                down = up = 0.0
            short = "." + mac.replace(":", "")[-2:]
            rates.append((short, down, up))
    downs = sorted(rates, key=lambda x: x[1], reverse=True)[:2]
    ups = sorted(rates, key=lambda x: x[2], reverse=True)[:2]
    return (
        [(n, round(d / 1000.0, 1)) for n, d, _u in downs],  # Mbps-ish
        [(n, round(u / 1000.0, 1)) for n, _d, u in ups],
    )


def collect() -> dict:
    global _prev_net, _hist_down, _hist_up
    now = time.time()
    if now - _last["ts"] < SAMPLE_MIN_S and _last["payload"]:
        return _last["payload"]

    iface = _wan_iface()
    rx = tx = 0
    cur = _iface_bytes(iface)
    down_mbps = up_mbps = 0.0
    if cur:
        rx, tx = cur
        if _prev_net:
            pts, prx, ptx = _prev_net
            dt = max(0.001, now - pts)
            down_mbps = max(0.0, (rx - prx) * 8 / 1e6 / dt)
            up_mbps = max(0.0, (tx - ptx) * 8 / 1e6 / dt)
            _hist_down.append(down_mbps)
            _hist_up.append(up_mbps)
            _hist_down = _hist_down[-HISTORY_LEN:]
            _hist_up = _hist_up[-HISTORY_LEN:]
        _prev_net = (now, rx, tx)

    ram_pct, buff_pct, cached_pct = _mem()
    t2, t5 = _wl_temps()
    total, wifi = _clients()
    jffs_pct, jffs_ok = _df_pct("/jffs")
    usb_pct, usb_ok = _usb_pct()
    vpn1, vpn2 = _vpn()
    top_d, top_u = _top_clients_wifi(now)
    wan_state = _nvram("wan0_state_t") or _nvram("wan0_state")
    online = wan_state in ("2", "connected") or _run("ping -c 1 -W 1 1.1.1.1 >/dev/null && echo OK") == "OK"

    dur_s = max(1, len(_hist_down) * SAMPLE_MIN_S)
    payload = {
        "uptime_str": _uptime_str(),
        "cpu": int(round(_cpu_pct())),
        "ram": int(round(ram_pct)),
        "clients": total,
        "clients_wifi": wifi,
        "wan_online": online,
        "wan_down": round(down_mbps, 2),
        "wan_up": round(up_mbps, 2),
        "rx_bytes": rx,
        "tx_bytes": tx,
        "wan_history_down": list(_hist_down),
        "wan_history_up": list(_hist_up),
        "wan_history_max_down": max(_hist_down) if _hist_down else 1.0,
        "wan_history_max_up": max(_hist_up) if _hist_up else 1.0,
        "wan_history_duration": f"{int(dur_s)//60}m{int(dur_s)%60:02d}s",
        "top_down": top_d,
        "top_up": top_u,
        "hw_accel": _nvram("ctf_disable") not in ("1",),
        "temp_cpu": int(round(_temp_cpu())),
        "temp_2g": int(round(t2)),
        "temp_5g": int(round(t5)),
        "vpn1": vpn1,
        "vpn2": vpn2,
        "jffs": {"used": jffs_pct, "total": 100, "present": jffs_ok},
        "usb": {"used": usb_pct, "total": 100, "present": usb_ok},
        "ram_cache": {"buffers": buff_pct, "cached": cached_pct},
    }
    _last["ts"] = now
    _last["payload"] = payload
    return payload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/metrics.json", "/metrics", "/"):
            body = json.dumps(collect()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/health":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


def main() -> None:
    httpd = HTTPServer((HOST, PORT), Handler)
    print(f"pico metrics on http://{HOST}:{PORT}/metrics.json", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
