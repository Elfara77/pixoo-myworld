#!/usr/bin/env python3
"""Lightweight HTTP /metrics.json for Pico OLED — runs on Asuswrt-Merlin + Entware.

Metrics semantics for Pico OLED (kbps→Mbps, Wi‑Fi temps,
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
_hist_cpu: list[float] = []
_hist_ram: list[float] = []
_hist_temp: list[float] = []
_hist_wifi_down: list[float] = []
_hist_wifi_up: list[float] = []
_hist_lan_down: list[float] = []
_hist_lan_up: list[float] = []
_prev_wifi = None  # (ts, rx, tx)
_prev_lan = None
_prev_br = None
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


def _sum_ifaces_bytes(ifaces: list[str]) -> tuple[int, int]:
    rx = tx = 0
    seen = False
    for iface in ifaces:
        cur = _iface_bytes(iface)
        if not cur:
            continue
        seen = True
        rx += cur[0]
        tx += cur[1]
    return (rx, tx) if seen else (0, 0)


def _wifi_lan_ifaces() -> tuple[list[str], list[str]]:
    """Return (wifi_ifaces wl*, wired_lan physical ports — not br0)."""
    wan = _wan_iface()
    wifi: list[str] = []
    net = Path("/sys/class/net")
    if net.is_dir():
        for p in sorted(net.iterdir()):
            name = p.name
            if name.startswith("wl"):
                wifi.append(name)
    wifi_set = set(wifi)
    wired: list[str] = []
    for iface in ("lan1", "lan2", "lan3", "lan4", "eth1", "eth2", "eth3", "eth4", "eth5", "eth6", "eth7"):
        if iface == wan or iface in wifi_set:
            continue
        if Path(f"/sys/class/net/{iface}").is_dir():
            wired.append(iface)
    return wifi, wired


def _wired_rates(
    now: float,
    wifi_down: float,
    wifi_up: float,
    wired_ifaces: list[str],
) -> tuple[float, float, tuple[float, int, int] | None]:
    """Mbps to/from wired clients; br0 minus WiFi when ports have no counters."""
    global _prev_lan, _prev_br
    if wired_ifaces:
        rx, tx = _sum_ifaces_bytes(wired_ifaces)
        down, up, _prev_lan = _rate_from_prev(_prev_lan, now, rx, tx)
        return down, up, _prev_lan
    if Path("/sys/class/net/br0").is_dir():
        rx, tx = _sum_ifaces_bytes(["br0"])
        br_down, br_up, _prev_br = _rate_from_prev(_prev_br, now, rx, tx)
        return max(0.0, br_down - wifi_down), max(0.0, br_up - wifi_up), _prev_br
    return 0.0, 0.0, _prev_lan


def _rate_from_prev(
    prev: tuple[float, int, int] | None,
    now: float,
    rx: int,
    tx: int,
) -> tuple[float, float, tuple[float, int, int]]:
    """Return (down_mbps, up_mbps, new_prev). down=rx growth, up=tx growth on LAN side."""
    new_prev = (now, rx, tx)
    if not prev:
        return 0.0, 0.0, new_prev
    pts, prx, ptx = prev
    dt = max(0.001, now - pts)
    # On LAN/wifi ifaces: rx = from clients (upload to WAN view), tx = to clients (download)
    # Align with STA convention used elsewhere: down = to clients = tx, up = from clients = rx
    down_mbps = max(0.0, (tx - ptx) * 8 / 1e6 / dt)
    up_mbps = max(0.0, (rx - prx) * 8 / 1e6 / dt)
    return down_mbps, up_mbps, new_prev


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
    total_mins = int(secs // 60)
    days = total_mins // (24 * 60)
    rem_mins = total_mins % (24 * 60)
    hours = rem_mins // 60
    mins = rem_mins % 60
    if days > 0:
        return f"{days}d{hours}h"
    if hours > 0:
        return f"{hours}h{mins:02d}m"
    return f"{mins}m"


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


def _parse_phy_temp(out: str) -> float | None:
    """Parse `wl phy_tempsense` first token → °C."""
    if not out:
        return None
    try:
        num = int(out.split()[0], 0)
        # Broadcom often reports 2×°C when value is large
        return float(num // 2) if num > 100 else float(num)
    except (ValueError, IndexError):
        return None


def _wl_band(iface: str) -> str | None:
    """Return '2g', '5g', or None if iface is not a usable radio.

    Never classify by substring in the iface name (eth5 ≠ 5 GHz).
    Prefer chanspec / status channel; fall back to Merlin nvram wl*_ifname.
    """
    chanspec = _run(f"wl -i {iface} chanspec 2>/dev/null")
    low = chanspec.lower()
    if chanspec:
        if any(tok in low for tok in ("6g", "6ghz", "6/")):
            return "5g"  # treat 6 GHz as high-band cell on TMP
        if any(tok in low for tok in ("5g", "5ghz", "/80", "/160", "he5", "vht")):
            return "5g"
        # channel number: 2.4 GHz is 1–14; 5/6 GHz use higher channels
        m = re.search(r"(?:^|[^0-9])([0-9]{1,3})(?:[^0-9]|$)", chanspec)
        if m:
            ch = int(m.group(1))
            if 1 <= ch <= 14:
                return "2g"
            if ch >= 36:
                return "5g"

    status = _run(f"wl -i {iface} status 2>/dev/null")
    if status:
        sm = re.search(r"Channel\s*[:=]?\s*([0-9]+)", status, re.I)
        if sm:
            ch = int(sm.group(1))
            if 1 <= ch <= 14:
                return "2g"
            if ch >= 36:
                return "5g"
        if re.search(r"5\.?\s*GHz|5GHz|band\s*:\s*5", status, re.I):
            return "5g"
        if re.search(r"2\.4\s*GHz|2GHz|band\s*:\s*2", status, re.I):
            return "2g"

    # Merlin nvram: wl0 ≈ 2.4, wl1 ≈ 5, wl2 ≈ 5/6 on tri-band
    for unit, band in (("0", "2g"), ("1", "5g"), ("2", "5g")):
        ifname = _nvram(f"wl{unit}_ifname")
        if ifname and ifname == iface:
            return band
    return None


def _wl_temps() -> tuple[float, float]:
    """Return (temp_2g, temp_5g) using real band detection per iface."""
    t2 = t5 = 0.0
    mapped: list[str] = []
    ifaces = ("eth1", "eth2", "eth3", "eth4", "eth5", "eth6", "eth7", "wl0", "wl1", "wl2")
    for iface in ifaces:
        out = _run(f"wl -i {iface} phy_tempsense 2>/dev/null")
        c = _parse_phy_temp(out)
        if c is None:
            continue
        band = _wl_band(iface)
        if band is None:
            continue
        mapped.append(f"{iface}={band}:{c:.0f}")
        if band == "5g":
            if t5 == 0:
                t5 = c
        elif band == "2g":
            if t2 == 0:
                t2 = c
    if mapped:
        # One-line debug hint in stderr-less env: stash on last payload via side channel
        _last["wl_temp_map"] = ",".join(mapped)
    return t2, t5


def _clients() -> tuple[int, int]:
    detail = _clients_detail()
    return int(detail["total"]), int(detail["wifi"])


def _iface_ssid_map() -> dict[str, str]:
    """Map wl interface → SSID (including guest virtual ifaces)."""
    out: dict[str, str] = {}
    for unit in range(0, 4):
        ifname = _nvram(f"wl{unit}_ifname")
        ssid = _nvram(f"wl{unit}_ssid") or f"wl{unit}"
        if ifname:
            out[ifname] = ssid[:12]
        for g in range(1, 4):
            gif = _nvram(f"wl{unit}.{g}_ifname")
            gssid = _nvram(f"wl{unit}.{g}_ssid")
            if gif and gssid:
                out[gif] = gssid[:12]
            # Merlin sometimes uses wlX.Y without separate ifname
            virt = f"wl{unit}.{g}"
            if gssid and virt not in out:
                out[virt] = gssid[:12]
    return out


def _clients_detail() -> dict:
    """Active clients: total, wifi, wired, by band (2g/5g), top SSIDs."""
    wifi_macs: set[str] = set()
    wifi_2g = wifi_5g = 0
    by_ssid: dict[str, int] = {}
    ssid_map = _iface_ssid_map()
    ifaces = (
        "eth1", "eth2", "eth3", "eth4", "eth5", "eth6", "eth7",
        "wl0", "wl1", "wl2", "wl0.1", "wl0.2", "wl1.1", "wl1.2", "wl2.1",
    )
    for iface in ifaces:
        assoc = _run(f"wl -i {iface} assoclist 2>/dev/null")
        macs = re.findall(r"(?i)assoclist\s+([0-9a-f:]{17})", assoc)
        if not macs:
            continue
        band = _wl_band(iface)
        if not band:
            parent = iface.split(".")[0]
            if parent != iface:
                band = _wl_band(parent)
        band = band or "2g"
        ssid = ssid_map.get(iface) or ssid_map.get(iface.split(".")[0], iface[:8])
        for mac in macs:
            ml = mac.lower()
            if ml in wifi_macs:
                continue
            wifi_macs.add(ml)
            if band == "5g":
                wifi_5g += 1
            else:
                wifi_2g += 1
            by_ssid[ssid] = by_ssid.get(ssid, 0) + 1

    # Wired ≈ ARP entries that are not Wi‑Fi STAs
    arp_macs: set[str] = set()
    try:
        for line in Path("/proc/net/arp").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "0x2":
                arp_macs.add(parts[3].lower())
    except OSError:
        pass
    wired = max(0, len(arp_macs - wifi_macs))
    # Prefer DHCP lease count for wired if larger signal
    lease_n = 0
    for path in ("/var/lib/misc/dnsmasq.leases", "/tmp/var/lib/misc/dnsmasq.leases"):
        try:
            lease_n = len(Path(path).read_text().splitlines())
            break
        except OSError:
            continue
    if lease_n > 0:
        wired = max(wired, max(0, lease_n - len(wifi_macs)))

    wifi = len(wifi_macs)
    total = wifi + wired
    ssid_list = sorted(by_ssid.items(), key=lambda x: x[1], reverse=True)[:4]
    return {
        "total": total,
        "wifi": wifi,
        "wired": wired,
        "wifi_2g": wifi_2g,
        "wifi_5g": wifi_5g,
        "by_ssid": [{"ssid": s, "n": n} for s, n in ssid_list],
    }


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


def _usb_ports() -> tuple[dict, dict]:
    """Detect USB2 / USB3 device presence and best-effort usage %."""
    u2_on = u3_on = False
    base = Path("/sys/bus/usb/devices")
    if base.is_dir():
        for d in base.iterdir():
            # Skip root hubs without a real device idProduct sibling pattern:
            # count nodes that expose a speed + (idVendor or product).
            speed_p = d / "speed"
            if not speed_p.is_file():
                continue
            if not (d / "idVendor").is_file() and not (d / "product").is_file():
                continue
            # Root hubs are like usb1/usb2 — skip pure hubs named usbN
            if re.fullmatch(r"usb\d+", d.name):
                continue
            try:
                sp = float(speed_p.read_text().strip() or 0)
            except (OSError, ValueError):
                continue
            if sp >= 5000:
                u3_on = True
            elif sp >= 12:
                u2_on = True
    # Mounted storage usage (shared) — attribute to USB3 if present else USB2
    used, present = _usb_pct()
    if present and not (u2_on or u3_on):
        u2_on = True
    u2 = {"present": u2_on, "used": used if u2_on and not u3_on else (used if u2_on else 0)}
    u3 = {"present": u3_on, "used": used if u3_on else 0}
    return u2, u3


def _lan_ports() -> list[bool]:
    """LAN1..LAN4 link up (True) / down (False)."""
    states: list[bool] = []
    # robocfg: "Port 1: ... 1000FD Enabled" / "Down"
    out = _run("robocfg show 2>/dev/null")
    if out:
        for port in range(1, 5):
            m = re.search(
                rf"Port\s+{port}\s*:.*?((?:1000|100|10)\s*\w*|Down|Enabled|Disabled)",
                out,
                re.I | re.S,
            )
            if m:
                tok = m.group(1).lower()
                states.append("down" not in tok and "disabled" not in tok)
            else:
                # line-oriented fallback
                line = ""
                for ln in out.splitlines():
                    if re.match(rf"Port\s+{port}\b", ln, re.I):
                        line = ln.lower()
                        break
                if line:
                    states.append("down" not in line and "disabled" not in line)
                else:
                    states.append(False)
        if len(states) == 4:
            return states

    # sysfs carrier on common LAN ifaces
    for iface in ("lan1", "lan2", "lan3", "lan4", "eth1", "eth2", "eth3", "eth4"):
        try:
            c = Path(f"/sys/class/net/{iface}/carrier").read_text().strip()
            states.append(c == "1")
        except OSError:
            continue
        if len(states) >= 4:
            return states[:4]
    while len(states) < 4:
        states.append(False)
    return states[:4]


def _vpn() -> tuple[dict, dict]:
    ovpn = _run("pidof vpnclient1 openvpn 2>/dev/null")
    st1 = _nvram("vpn_client1_state")
    on1 = bool(ovpn) or st1 in ("2", "connected", "1")
    st2 = _nvram("vpn_client2_state") or _nvram("wgc1_enable")
    # WireGuard client often separate
    wg = _run("pidof wg-quick wireguard 2>/dev/null") or _nvram("wgc1_addr")
    on2 = st2 in ("2", "connected", "1") or bool(wg and _nvram("wgc1_enable") in ("1", "on"))
    t2 = "WG" if (wg or "wg" in (_nvram("vpn_client2_desc") or "").lower()) else "VPN2"
    return {"on": on1, "type": "OVPN"}, {"on": on2, "type": t2}


def _top_clients_wifi(now: float) -> tuple[list, list]:
    """Best-effort top down/up from wl sta_info (capped). Rates in Mbps."""
    rates = []
    n = 0
    for iface in ("eth1", "eth2", "eth3", "eth4", "eth5", "eth6", "eth7", "wl0", "wl1", "wl2"):
        assoc = _run(f"wl -i {iface} assoclist 2>/dev/null")
        for mac in re.findall(r"(?i)([0-9a-f:]{17})", assoc):
            if n >= 12:
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
                # STA tx = download to client; rx = upload from client
                down_kbps = max(0.0, (tx - ptx) * 8 / 1000 / dt)
                up_kbps = max(0.0, (rx - prx) * 8 / 1000 / dt)
            else:
                down_kbps = up_kbps = 0.0
            # Prefer hostname from DHCP lease if available
            short = _lease_name(mac) or ("." + mac.replace(":", "")[-4:])
            rates.append((short, down_kbps, up_kbps))
    downs = sorted(rates, key=lambda x: x[1], reverse=True)[:3]
    ups = sorted(rates, key=lambda x: x[2], reverse=True)[:3]
    return (
        [(n, round(d / 1000.0, 2)) for n, d, _u in downs],
        [(n, round(u / 1000.0, 2)) for n, _d, u in ups],
    )


def _lease_name(mac: str) -> str | None:
    mac_l = mac.lower()
    for path in ("/var/lib/misc/dnsmasq.leases", "/tmp/var/lib/misc/dnsmasq.leases"):
        try:
            text = Path(path).read_text()
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1].lower() == mac_l:
                name = parts[3]
                if name and name != "*":
                    return name[:12]
    return None


def collect() -> dict:
    global _prev_net, _hist_down, _hist_up
    global _hist_cpu, _hist_ram, _hist_temp
    global _hist_wifi_down, _hist_wifi_up, _hist_lan_down, _hist_lan_up
    global _prev_wifi, _prev_lan, _prev_br
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
    cpu_pct = _cpu_pct()
    t2, t5 = _wl_temps()
    t_cpu = _temp_cpu()
    temps = [t for t in (t_cpu, t2, t5) if t and t > 0]
    temp_avg = sum(temps) / len(temps) if temps else 0.0
    _hist_cpu.append(cpu_pct)
    _hist_ram.append(ram_pct)
    _hist_temp.append(temp_avg)
    _hist_cpu = _hist_cpu[-HISTORY_LEN:]
    _hist_ram = _hist_ram[-HISTORY_LEN:]
    _hist_temp = _hist_temp[-HISTORY_LEN:]

    wifi_ifaces, wired_ifaces = _wifi_lan_ifaces()
    wrx, wtx = _sum_ifaces_bytes(wifi_ifaces)
    wifi_down, wifi_up, _prev_wifi = _rate_from_prev(_prev_wifi, now, wrx, wtx)
    lan_down, lan_up, _ = _wired_rates(now, wifi_down, wifi_up, wired_ifaces)
    _hist_wifi_down.append(wifi_down)
    _hist_wifi_up.append(wifi_up)
    _hist_lan_down.append(lan_down)
    _hist_lan_up.append(lan_up)
    _hist_wifi_down = _hist_wifi_down[-HISTORY_LEN:]
    _hist_wifi_up = _hist_wifi_up[-HISTORY_LEN:]
    _hist_lan_down = _hist_lan_down[-HISTORY_LEN:]
    _hist_lan_up = _hist_lan_up[-HISTORY_LEN:]

    cdetail = _clients_detail()
    total, wifi = int(cdetail["total"]), int(cdetail["wifi"])
    jffs_pct, jffs_ok = _df_pct("/jffs")
    usb_pct, usb_ok = _usb_pct()
    usb2, usb3 = _usb_ports()
    lan_ports = _lan_ports()
    vpn1, vpn2 = _vpn()
    top_d, top_u = _top_clients_wifi(now)
    wan_state = _nvram("wan0_state_t") or _nvram("wan0_state")
    online = wan_state in ("2", "connected") or _run("ping -c 1 -W 1 1.1.1.1 >/dev/null && echo OK") == "OK"

    dur_s = max(1, len(_hist_down) * SAMPLE_MIN_S)
    payload = {
        "uptime_str": _uptime_str(),
        "cpu": int(round(cpu_pct)),
        "ram": int(round(ram_pct)),
        "clients": total,
        "clients_wifi": wifi,
        "clients_wired": int(cdetail["wired"]),
        "clients_2g": int(cdetail["wifi_2g"]),
        "clients_5g": int(cdetail["wifi_5g"]),
        "clients_ssid": cdetail["by_ssid"],
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
        "cpu_history": list(_hist_cpu),
        "ram_history": list(_hist_ram),
        "temp_history": list(_hist_temp),
        "temp_avg": int(round(temp_avg)),
        "wifi_down": round(wifi_down, 2),
        "wifi_up": round(wifi_up, 2),
        "lan_down": round(lan_down, 2),
        "lan_up": round(lan_up, 2),
        "wifi_history_down": list(_hist_wifi_down),
        "wifi_history_up": list(_hist_wifi_up),
        "lan_history_down": list(_hist_lan_down),
        "lan_history_up": list(_hist_lan_up),
        "top_down": top_d,
        "top_up": top_u,
        "hw_accel": _nvram("ctf_disable") not in ("1",),
        "temp_cpu": int(round(t_cpu)),
        "temp_2g": int(round(t2)),
        "temp_5g": int(round(t5)),
        "temp_bands": _last.get("wl_temp_map", ""),
        "vpn1": vpn1,
        "vpn2": vpn2,
        "jffs": {"used": jffs_pct, "total": 100, "present": jffs_ok},
        "usb": {"used": usb_pct, "total": 100, "present": usb_ok},
        "usb2": usb2,
        "usb3": usb3,
        "lan_ports": lan_ports,
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
