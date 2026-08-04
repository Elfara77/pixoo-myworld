"""Collecte des métriques AsusWRT-Merlin (shell + /proc) + mode démo."""

from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque


@dataclass
class BandwidthSample:
    ts: float
    down_kbps: float
    up_kbps: float


@dataclass
class TopClient:
    name: str
    down_kbps: float = 0.0
    up_kbps: float = 0.0


@dataclass
class HourStats:
    window_s: int = 3600
    down_min: float = 0.0
    down_max: float = 0.0
    up_min: float = 0.0
    up_max: float = 0.0
    cpu_min: float = 0.0
    cpu_max: float = 0.0
    temp_min: float = 0.0
    temp_max: float = 0.0
    ram_min: float = 0.0
    ram_max: float = 0.0


@dataclass
class Snapshot:
    clients: int = 0
    clients_lan: int = 0
    clients_wan: int = 0  # Wi‑Fi / WLAN (label « WAN » on screen per UI request)
    wan_down_kbps: float = 0.0
    wan_up_kbps: float = 0.0
    cpu_pct: float = 0.0
    temp_c: float = 0.0
    ram_pct: float = 0.0
    disk_pct: float = 0.0
    disk_used_mb: float = 0.0
    disk_total_mb: float = 0.0
    disk_label: str = "disk"
    internet_ok: bool = False
    usb2: bool = False
    usb3: bool = False
    eth_linked: int = 0
    lan_ports: tuple[bool, bool, bool, bool] = (False, False, False, False)
    wan_ip: str = "—"
    uptime_s: float = 0.0
    history: list[BandwidthSample] = field(default_factory=list)
    top_clients: list[TopClient] = field(default_factory=list)
    top_up_clients: list[TopClient] = field(default_factory=list)
    hour_stats: HourStats = field(default_factory=HourStats)
    demo: bool = False


def _run(cmd: str, timeout: float = 4.0) -> str:
    try:
        out = subprocess.check_output(
            cmd,
            shell=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            text=True,
        )
        return (out or "").strip()
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return ""


def _nvram(key: str) -> str:
    return _run(f"nvram get {key} 2>/dev/null")


def _read_text(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def detect_wan_iface(override: str = "") -> str:
    if override:
        return override
    for key in ("wan0_ifname", "wan_ifname", "wan0_gw_ifname"):
        val = _nvram(key)
        if val:
            return val
    # Fallbacks courants Merlin / Linux
    for candidate in ("eth0", "vlan2", "ppp0", "wan", "en0"):
        if Path(f"/sys/class/net/{candidate}").exists():
            return candidate
    return "eth0"


def _iface_bytes(iface: str) -> tuple[int, int] | None:
    """(rx_bytes, tx_bytes) depuis /proc/net/dev."""
    text = _read_text("/proc/net/dev")
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        if name.strip() != iface:
            continue
        parts = rest.split()
        if len(parts) < 10:
            return None
        try:
            rx, tx = int(parts[0]), int(parts[8])
            return rx, tx
        except ValueError:
            return None
    return None


def _cpu_times() -> tuple[int, int] | None:
    """(idle+iowait, total) depuis /proc/stat."""
    for line in _read_text("/proc/stat").splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()
        try:
            vals = [int(x) for x in parts[1:]]
        except ValueError:
            return None
        if len(vals) < 4:
            return None
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        return idle, total
    return None


def _ram_pct() -> float:
    info: dict[str, int] = {}
    for line in _read_text("/proc/meminfo").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        num = v.strip().split()[0]
        try:
            info[k] = int(num)
        except ValueError:
            continue
    total = info.get("MemTotal", 0)
    if total <= 0:
        return 0.0
    avail = info.get("MemAvailable")
    if avail is None:
        free = info.get("MemFree", 0)
        cached = info.get("Cached", 0) + info.get("Buffers", 0)
        avail = free + cached
    used = max(0, total - avail)
    return 100.0 * used / total


def _disk_usage(path: str = "") -> tuple[float, float, float, str]:
    """Native Merlin storage used/free → (pct_used, used_mb, total_mb, label).

    Prefers /jffs (persistent), then /opt (Entware), then /.
    """
    candidates: list[str] = []
    if path.strip():
        candidates.append(path.strip())
    candidates.extend(["/jffs", "/opt", "/"])
    seen: set[str] = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        try:
            st = os.statvfs(p)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total <= 0:
            continue
        used = max(0, total - free)
        pct = 100.0 * used / total
        label = { "/jffs": "jffs", "/opt": "opt", "/": "root" }.get(p, Path(p).name or "disk")
        return pct, used / (1024 * 1024), total / (1024 * 1024), label
    return 0.0, 0.0, 0.0, "disk"


def _temps_c() -> list[float]:
    temps: list[float] = []

    # Thermal zones (milli-°C)
    for path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        raw = _read_text(path).strip()
        try:
            val = float(raw)
            if val > 1000:
                val /= 1000.0
            if 0 < val < 120:
                temps.append(val)
        except ValueError:
            continue

    # Broadcom DMU
    dmu = _read_text("/proc/dmu/temperature").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", dmu)
    if m:
        try:
            t = float(m.group(1))
            if 0 < t < 120:
                temps.append(t)
        except ValueError:
            pass

    # Radios Wi‑Fi (phy_tempsense → raw/2 + 20 approx selon docs community)
    ifaces = _nvram("wl_ifnames") or _nvram("lan_ifnames")
    for iface in (ifaces or "").split():
        out = _run(f"wl -i {iface} phy_tempsense 2>/dev/null")
        m = re.match(r"(\d+)", out)
        if m:
            raw = int(m.group(1))
            t = raw / 2.0 + 20.0
            if 0 < t < 120:
                temps.append(t)

    return temps


_MAC_RE = re.compile(r"(?i)(?:[0-9a-f]{2}:){5}[0-9a-f]{2}")


def _norm_mac(mac: str) -> str:
    return mac.strip().lower()


# Cache radio iface list — nvram storms every sample are expensive on Merlin.
_WL_IFACES_CACHE: list[str] | None = None
_WL_IFACES_CACHE_TS = 0.0
_WL_IFACES_TTL = 60.0

# Hard cap: wl sta_info is heavy; never probe every station every second.
_MAX_STA_INFO_PER_REFRESH = 12


def _wl_client_ifaces() -> list[str]:
    """All wireless interfaces including guest VIFs."""
    global _WL_IFACES_CACHE, _WL_IFACES_CACHE_TS
    now = time.monotonic()
    if _WL_IFACES_CACHE is not None and (now - _WL_IFACES_CACHE_TS) < _WL_IFACES_TTL:
        return _WL_IFACES_CACHE

    found: list[str] = []
    seen: set[str] = set()
    keys = (
        "wl_ifnames",
        "wl0_ifname",
        "wl1_ifname",
        "wl2_ifname",
        "wl0_vifs",
        "wl1_vifs",
        "wl2_vifs",
        "lan_ifnames",
    )
    for key in keys:
        for part in (_nvram(key) or "").split():
            if part and part not in seen:
                # Skip pure LAN switch ports named lan1… — keep wl* and eth used as radio
                if part.startswith(("wl", "eth", "ath")):
                    seen.add(part)
                    found.append(part)
    _WL_IFACES_CACHE = found
    _WL_IFACES_CACHE_TS = now
    return found


def _macs_from_wifi() -> set[str]:
    macs: set[str] = set()
    for iface in _wl_client_ifaces():
        assoc = _run(f"wl -i {iface} assoclist 2>/dev/null")
        for m in _MAC_RE.findall(assoc or ""):
            macs.add(_norm_mac(m))
    return macs


def _macs_from_leases() -> set[str]:
    macs: set[str] = set()
    for path in (
        Path("/var/lib/misc/dnsmasq.leases"),
        Path("/tmp/dnsmasq.leases"),
        Path("/var/lib/dnsmasq/dnsmasq.leases"),
    ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            # dnsmasq: <expiry> <mac> <ip> <hostname> <client-id>
            if len(parts) >= 2 and _MAC_RE.fullmatch(parts[1]):
                macs.add(_norm_mac(parts[1]))
    return macs


def _macs_from_arp() -> set[str]:
    """ARP / neigh entries with a real MAC (wired + Wi‑Fi recently active)."""
    macs: set[str] = set()
    neigh = _run("ip -4 neigh show 2>/dev/null")
    if neigh:
        for line in neigh.splitlines():
            if "lladdr" not in line:
                continue
            # Keep STALE/DELAY — Merlin client list includes recent hosts
            if any(s in line for s in ("FAILED", "INCOMPLETE", "NONE")):
                continue
            m = _MAC_RE.search(line)
            if m:
                macs.add(_norm_mac(m.group(0)))
        return macs

    for line in _read_text("/proc/net/arp").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        flags, mac = parts[2], parts[3]
        if flags == "0x0" or mac in ("00:00:00:00:00:00", "0:0:0:0:0:0"):
            continue
        if _MAC_RE.fullmatch(mac):
            macs.add(_norm_mac(mac))
    return macs


def _bridge_names() -> list[str]:
    names: list[str] = []
    # br0 + guest bridges from nvram
    for key in ("lan_ifname", "lan1_ifname", "lan2_ifname", "lan3_ifname"):
        v = _nvram(key)
        if v and v not in names:
            names.append(v)
    for p in sorted(Path("/sys/class/net").glob("br*")):
        if p.name not in names:
            names.append(p.name)
    if not names:
        names = ["br0"]
    return names


def _macs_from_bridge() -> set[str]:
    macs: set[str] = set()
    for br in _bridge_names():
        out = _run(f"brctl showmacs {br} 2>/dev/null")
        for line in (out or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            mac, islocal = parts[1], parts[2].lower()
            if islocal in ("yes", "1"):
                continue
            if _MAC_RE.fullmatch(mac):
                macs.add(_norm_mac(mac))
    return macs


def _clients_from_nmp() -> tuple[set[str], dict[str, str]] | None:
    """Parse Merlin Network Map client list if present → (macs, mac→name)."""
    macs: set[str] = set()
    names: dict[str, str] = {}
    candidates = (
        Path("/tmp/clientlist.json"),
        Path("/tmp/nmp_client_list"),
        Path("/jffs/nmp_cl_json.js"),
        Path("/tmp/nmp_cl_json.js"),
    )
    raw = ""
    for path in candidates:
        if path.is_file():
            raw = _read_text(path).strip()
            if raw:
                break
    if not raw:
        return None

    # Strip JS assignment wrapper: foo = {...};
    if raw.startswith("var ") or "=" in raw[:40]:
        raw = raw.split("=", 1)[-1].strip().rstrip(";")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    def ingest(mac: str, info: dict) -> None:
        m = _norm_mac(mac)
        if not _MAC_RE.fullmatch(m):
            return
        online = str(info.get("isOnline", info.get("online", info.get("isonline", "1"))))
        if online.lower() in ("0", "false", "no", "off"):
            return
        macs.add(m)
        name = str(info.get("name") or info.get("nickName") or info.get("hostname") or "").strip()
        if name and name not in ("*", "<unknown>"):
            names[m] = name[:20]

    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                ingest(str(v.get("mac", k)), v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        ingest(str(item.get("mac", "")), item)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                ingest(str(item.get("mac", "")), item)

    if not macs:
        return None
    return macs, names


def _names_from_custom_clientlist() -> dict[str, str]:
    """nvram custom_clientlist: <Name>MAC>…"""
    names: dict[str, str] = {}
    raw = _nvram("custom_clientlist")
    if not raw:
        return names
    for chunk in raw.split("<"):
        if not chunk or ">" not in chunk:
            continue
        parts = chunk.split(">")
        if len(parts) < 2:
            continue
        name, mac = parts[0].strip(), _norm_mac(parts[1])
        if name and _MAC_RE.fullmatch(mac):
            names[mac] = name[:20]
    return names


def _names_from_leases() -> dict[str, str]:
    names: dict[str, str] = {}
    for path in (
        Path("/var/lib/misc/dnsmasq.leases"),
        Path("/tmp/dnsmasq.leases"),
    ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 4 and _MAC_RE.fullmatch(parts[1]):
                host = parts[3]
                if host and host not in ("*", ""):
                    names[_norm_mac(parts[1])] = host[:20]
    return names


def _client_directory() -> tuple[set[str], dict[str, str]]:
    """Online client MACs + best-effort names (Merlin client list first)."""
    names: dict[str, str] = {}
    names.update(_names_from_leases())
    names.update(_names_from_custom_clientlist())

    nmp = _clients_from_nmp()
    if nmp is not None:
        macs, nmp_names = nmp
        names.update(nmp_names)
        # Merge wifi/arp in case nmp is slightly stale
        macs |= _macs_from_wifi()
        macs |= _macs_from_arp()
        macs |= _macs_from_bridge()
    else:
        macs = set()
        macs |= _macs_from_wifi()
        macs |= _macs_from_arp()
        macs |= _macs_from_leases()
        macs |= _macs_from_bridge()

    macs = {m for m in macs if not m.startswith(("ff:ff:ff", "01:00:5e", "33:33:"))}
    return macs, names


def _count_clients() -> int:
    return len(_client_directory()[0])


def _client_lan_wan_counts() -> tuple[int, int, int]:
    """Return (total, lan_wired, wifi).

    LAN = online clients not currently Wi‑Fi-associated.
    WAN label on UI = Wi‑Fi associated clients (WLAN).
    """
    all_macs, _names = _client_directory()
    wifi = _macs_from_wifi()
    # Prefer assoclist-only for wifi count (true air clients)
    wifi_n = len(wifi)
    lan_n = len(all_macs - wifi)
    # If NMP/all is empty but wifi has stations, still report wifi
    total = max(len(all_macs), wifi_n + lan_n)
    if not all_macs and wifi:
        total = wifi_n
        lan_n = 0
    return total, lan_n, wifi_n


def _sta_info_traffic(iface: str, mac: str) -> tuple[int, int] | None:
    """Parse wl sta_info → (rx_bytes, tx_bytes).

    Merlin/Broadcom format::
      tx data bytes: 68730715
      rx data bytes: 73557
    """
    mac_u = mac.upper()
    # One attempt with canonical uppercase MAC (wl expects AA:BB:…).
    out = _run(f"wl -i {iface} sta_info {mac_u} 2>/dev/null", timeout=1.5)
    if not out:
        return None

    rx_ucast = rx_data = rx_total = None
    tx_ucast = tx_data = tx_total = None
    for line in out.splitlines():
        ls = line.strip().lower()
        try:
            if ls.startswith("tx ucast bytes:"):
                tx_ucast = int(ls.split(":", 1)[1].strip().split()[0])
            elif ls.startswith("tx data bytes:"):
                tx_data = int(ls.split(":", 1)[1].strip().split()[0])
            elif ls.startswith("tx total bytes:"):
                tx_total = int(ls.split(":", 1)[1].strip().split()[0])
            elif ls.startswith("rx ucast bytes:"):
                rx_ucast = int(ls.split(":", 1)[1].strip().split()[0])
            elif ls.startswith("rx data bytes:"):
                rx_data = int(ls.split(":", 1)[1].strip().split()[0])
            elif ls.startswith("rx total bytes:"):
                rx_total = int(ls.split(":", 1)[1].strip().split()[0])
        except (IndexError, ValueError):
            continue

    def pick(*vals: int | None) -> int | None:
        for v in vals:
            if v is not None:
                return v
        return None

    rx = pick(rx_ucast, rx_data, rx_total)
    tx = pick(tx_ucast, tx_data, tx_total)
    if rx is None and tx is None:
        return None
    return (rx or 0, tx or 0)


def _wifi_assoc_macs() -> dict[str, str]:
    """mac → iface for currently associated Wi‑Fi stations."""
    found: dict[str, str] = {}
    for iface in _wl_client_ifaces():
        assoc = _run(f"wl -i {iface} assoclist 2>/dev/null")
        for m in _MAC_RE.findall(assoc or ""):
            found[_norm_mac(m)] = iface
    return found


def _internet_ok(host: str) -> bool:
    # BusyBox ping: -c count, -W sec (Merlin) ; fallback ping -c1
    out = _run(f"ping -c 1 -W 2 {host} 2>/dev/null")
    if not out:
        out = _run(f"ping -c 1 {host} 2>/dev/null")
    return "1 packets received" in out or "1 received" in out or " bytes from " in out


def _usb_status() -> tuple[bool, bool]:
    """USB2 / USB3 storage mounted (or device present). Green = mounted/connected."""
    usb2 = usb3 = False

    # Merlin: USB shares appear under /tmp/mnt/<label>
    for base in (Path("/tmp/mnt"), Path("/mnt")):
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            # Resolve backing device if possible
            try:
                st = entry.stat()
            except OSError:
                continue
            # Any real mount point counts — prefer /proc/mounts for speed class
            usb2 = True  # at least something mounted; refined below
            break

    # Classify via /proc/mounts + sysfs speed when possible
    mounts = _read_text("/proc/mounts")
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        src, dest = parts[0], parts[1]
        if not dest.startswith(("/tmp/mnt/", "/mnt/")):
            continue
        if not src.startswith("/dev/"):
            continue
        # Find USB speed for this block device
        speed = _usb_speed_for_block(src)
        if speed is None:
            usb2 = True
        elif speed >= 5000:
            usb3 = True
        elif speed > 0:
            usb2 = True

    if usb2 or usb3:
        return usb2, usb3

    # Fallback: any non-hub USB device present
    root = Path("/sys/bus/usb/devices")
    if not root.is_dir():
        return False, False
    for dev in root.iterdir():
        name = dev.name
        if re.fullmatch(r"usb\d+", name) or ":" in name:
            continue
        speed_s = _read_text(dev / "speed").strip()
        try:
            speed = float(speed_s)
        except ValueError:
            continue
        product = _read_text(dev / "product").strip()
        if not product and not (dev / "bDeviceClass").exists():
            continue
        bclass = _read_text(dev / "bDeviceClass").strip()
        if bclass.upper() in ("09", "0X09"):
            continue
        if speed >= 5000:
            usb3 = True
        elif speed > 0:
            usb2 = True
    return usb2, usb3


def _usb_speed_for_block(devnode: str) -> float | None:
    """Best-effort USB speed (Mb/s) for /dev/sdX via sysfs."""
    name = Path(devnode).name
    # strip partition digits: sda1 -> sda
    base = re.sub(r"\d+$", "", name)
    candidates = [
        Path(f"/sys/block/{base}/device"),
        Path(f"/sys/class/block/{base}/device"),
    ]
    for link in candidates:
        try:
            resolved = link.resolve()
        except OSError:
            continue
        # Walk up looking for a usb device with speed
        cur = resolved
        for _ in range(8):
            speed_f = cur / "speed"
            if speed_f.is_file():
                raw = _read_text(speed_f).strip()
                try:
                    return float(raw)
                except ValueError:
                    return None
            cur = cur.parent
            if cur == Path("/"):
                break
    return None


def _lan_port_links() -> tuple[bool, bool, bool, bool]:
    """LAN1–LAN4 link status (True = cable/link up)."""
    ports = [False, False, False, False]
    out = _run("robocfg show 2>/dev/null")
    if out:
        for line in out.splitlines():
            m = re.match(r"Port\s+(\d+):\s+(\S+)", line)
            if not m:
                continue
            port, state = int(m.group(1)), m.group(2).upper()
            if 1 <= port <= 4:
                ports[port - 1] = state not in ("DOWN", "DISABLED", "---", "0")
        return (ports[0], ports[1], ports[2], ports[3])

    # Fallback: lan1..lan4 or eth1..eth4 carrier (skip WAN iface)
    wan = detect_wan_iface()
    for i in range(1, 5):
        for name in (f"lan{i}", f"eth{i}"):
            if name == wan:
                continue
            path = Path(f"/sys/class/net/{name}/carrier")
            if path.is_file() and _read_text(path).strip() == "1":
                ports[i - 1] = True
                break
    return (ports[0], ports[1], ports[2], ports[3])


def _eth_linked_count() -> int:
    return sum(1 for up in _lan_port_links() if up)


def _wan_ip() -> str:
    # Prefer public / real WAN when Merlin exposes it
    for key in ("wan0_realip_ip", "wan0_ipaddr", "wan_ipaddr", "wanx_ipaddr"):
        ip = _nvram(key)
        if ip and ip not in ("0.0.0.0", ""):
            return ip
    out = _run("ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2}' | head -1")
    if "/" in out:
        return out.split("/", 1)[0]
    return out or "-"


def _uptime_s() -> float:
    raw = _read_text("/proc/uptime").split()
    try:
        return float(raw[0])
    except (IndexError, ValueError):
        return 0.0


def format_uptime(seconds: float) -> str:
    s = int(max(0, seconds))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d > 0:
        return f"{d}d{h:02d}h"
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def format_rate_pair(down_kbps: float, up_kbps: float) -> str:
    def one(v: float) -> str:
        if v >= 1000:
            return f"{v / 1000:.0f}" if v >= 10000 else f"{v / 1000:.1f}"
        return f"{v:.0f}"

    # Affiche Mb/s si les deux ≥ 1000, sinon mixte lisible
    if down_kbps >= 1000 or up_kbps >= 1000:
        d = f"{down_kbps / 1000:.0f}" if down_kbps >= 100 else f"{down_kbps / 1000:.1f}"
        u = f"{up_kbps / 1000:.0f}" if up_kbps >= 100 else f"{up_kbps / 1000:.1f}"
        return f"{d}/{u}"
    return f"{one(down_kbps)}/{one(up_kbps)}"


@dataclass
class _SysSample:
    ts: float
    down: float
    up: float
    cpu: float
    temp: float
    ram: float


class MetricsCollector:
    """Échantillonne CPU / WAN, top clients, min/max sur fenêtre configurable."""

    def __init__(
        self,
        *,
        wan_iface: str = "",
        ping_host: str = "1.1.1.1",
        history_seconds: int = 300,
        stats_seconds: int = 3600,
        top_clients: int = 5,
        top_window_seconds: int = 60,
        disk_path: str = "",
        sample_interval: float = 5.0,
        demo: bool = False,
    ) -> None:
        self.wan_iface = detect_wan_iface(wan_iface) if not demo else (wan_iface or "eth0")
        self.ping_host = ping_host
        self.history_seconds = history_seconds
        self.stats_seconds = max(60, stats_seconds)
        self.top_n = max(1, min(8, top_clients))
        self.top_window_seconds = max(5, int(top_window_seconds))
        self.disk_path = disk_path
        self.sample_interval = max(2.0, float(sample_interval))
        # sta_info is the expensive path — never faster than 5s, and backs off on failures.
        self._sta_min_interval = max(5.0, self.sample_interval)
        self._ping_min_interval = 30.0
        self.demo = demo
        self._hist: Deque[BandwidthSample] = deque()
        self._sys: Deque[_SysSample] = deque()
        self._prev_cpu: tuple[int, int] | None = None
        self._prev_net: tuple[float, int, int] | None = None  # ts, rx, tx
        # mac -> rolling (ts, rx, tx) samples for top-client window average
        self._sta_hist: dict[str, Deque[tuple[float, int, int]]] = {}
        self._demo_t0 = time.time()
        self._last_sta_mono = 0.0
        self._cached_top: tuple[list[TopClient], list[TopClient]] = ([], [])
        self._sta_fail_streak = 0
        self._sta_backoff_until = 0.0
        self._last_ping_mono = 0.0
        self._cached_internet = False
        self._last_temp_mono = 0.0
        self._cached_temp = 0.0
        self._last_clients_mono = 0.0
        self._cached_clients = (0, 0, 0)

    def _trim_history(self, now: float) -> None:
        cut = now - self.history_seconds
        while self._hist and self._hist[0].ts < cut:
            self._hist.popleft()
        scut = now - self.stats_seconds
        while self._sys and self._sys[0].ts < scut:
            self._sys.popleft()

    def _hour_stats(self) -> HourStats:
        if not self._sys:
            return HourStats(window_s=self.stats_seconds)
        downs = [s.down for s in self._sys]
        ups = [s.up for s in self._sys]
        cpus = [s.cpu for s in self._sys]
        temps = [s.temp for s in self._sys]
        rams = [s.ram for s in self._sys]
        return HourStats(
            window_s=self.stats_seconds,
            down_min=min(downs),
            down_max=max(downs),
            up_min=min(ups),
            up_max=max(ups),
            cpu_min=min(cpus),
            cpu_max=max(cpus),
            temp_min=min(temps),
            temp_max=max(temps),
            ram_min=min(rams),
            ram_max=max(rams),
        )

    def _top_wifi_clients(self, now: float) -> tuple[list[TopClient], list[TopClient]]:
        """Rank Wi‑Fi clients by avg download/upload over top_window_seconds.

        Rate-limited: ``wl sta_info`` per client can stall radios / CPU on Merlin
        if called every frame for dozens of stations.
        """
        mono = time.monotonic()
        if mono < self._sta_backoff_until:
            return self._cached_top
        if self._last_sta_mono and (mono - self._last_sta_mono) < self._sta_min_interval:
            return self._cached_top

        _macs, names = _client_directory()
        assoc = _wifi_assoc_macs()
        win = float(self.top_window_seconds)
        cut = now - win
        rates: list[tuple[str, float, float]] = []
        failures = 0

        # Prefer previously tracked heavy talkers, then remaining assoc stations.
        preferred = [m for m in self._sta_hist.keys() if m in assoc]
        rest = [m for m in assoc.keys() if m not in self._sta_hist]
        ordered = preferred + rest

        for mac in ordered[:_MAX_STA_INFO_PER_REFRESH]:
            iface = assoc.get(mac)
            if not iface:
                continue
            info = _sta_info_traffic(iface, mac)
            if info is None:
                failures += 1
                continue
            rx_bytes, tx_bytes = info
            hist = self._sta_hist.get(mac)
            if hist is None:
                hist = deque()
                self._sta_hist[mac] = hist
            hist.append((now, rx_bytes, tx_bytes))
            while len(hist) > 1 and hist[0][0] < cut:
                hist.popleft()

            if len(hist) >= 2:
                t0, rx0, tx0 = hist[0]
                t1, rx1, tx1 = hist[-1]
                dt = max(0.001, t1 - t0)
                down_kbps = max(0.0, (tx1 - tx0) * 8.0 / 1000.0 / dt)
                up_kbps = max(0.0, (rx1 - rx0) * 8.0 / 1000.0 / dt)
            else:
                # Warm-up: tiny seed until window has ≥2 samples
                down_kbps = float(tx_bytes) / 1e9
                up_kbps = float(rx_bytes) / 1e9
            rates.append((mac, down_kbps, up_kbps))

        # Drop histories for clients that left
        for mac in list(self._sta_hist.keys()):
            if mac not in assoc:
                del self._sta_hist[mac]

        self._last_sta_mono = mono
        if failures and not rates:
            self._sta_fail_streak += 1
            # Exponential backoff up to 60s when driver/shell probes fail.
            backoff = min(60.0, self._sta_min_interval * (2 ** min(4, self._sta_fail_streak)))
            self._sta_backoff_until = mono + backoff
            return self._cached_top

        self._sta_fail_streak = 0
        self._sta_backoff_until = 0.0

        down_ranked = sorted(rates, key=lambda x: x[1], reverse=True)
        up_ranked = sorted(rates, key=lambda x: x[2], reverse=True)

        def build(ranked: list[tuple[str, float, float]]) -> list[TopClient]:
            out: list[TopClient] = []
            for mac, d_kbps, u_kbps in ranked[: self.top_n]:
                name = names.get(mac) or mac[-8:]
                out.append(TopClient(name=name, down_kbps=max(0.0, d_kbps), up_kbps=max(0.0, u_kbps)))
            return out

        self._cached_top = (build(down_ranked), build(up_ranked))
        return self._cached_top

    def _demo_snapshot(self) -> Snapshot:
        t = time.time() - self._demo_t0
        down = 40 + 60 * abs(math.sin(t / 17)) + random.uniform(0, 15)
        up = 8 + 12 * abs(math.sin(t / 23 + 1)) + random.uniform(0, 4)
        cpu = 25 + 40 * abs(math.sin(t / 11))
        temp = 42 + 8 * abs(math.sin(t / 29))
        ram = 35 + 20 * abs(math.sin(t / 19))
        now = time.time()
        self._hist.append(BandwidthSample(now, down, up))
        self._sys.append(_SysSample(now, down, up, cpu, temp, ram))
        self._trim_history(now)
        tops_down = [
            TopClient("iPhone Anthime", down_kbps=4200 + 200 * math.sin(t / 5), up_kbps=80),
            TopClient("Raph-Phone", down_kbps=1800 + 100 * math.sin(t / 7), up_kbps=40),
            TopClient("Mac", down_kbps=900 + 80 * math.sin(t / 9), up_kbps=200),
            TopClient("Nest-Audio", down_kbps=120 + 20 * math.sin(t / 11), up_kbps=10),
            TopClient("PIXOO 64", down_kbps=40 + 10 * math.sin(t / 13), up_kbps=5),
        ]
        tops_up = [
            TopClient("Mac", down_kbps=900, up_kbps=420 + 40 * math.sin(t / 6)),
            TopClient("iPhone Anthime", down_kbps=4200, up_kbps=180 + 20 * math.sin(t / 8)),
            TopClient("Raph-Phone", down_kbps=1800, up_kbps=90 + 15 * math.sin(t / 10)),
            TopClient("Nest-Audio", down_kbps=120, up_kbps=25),
            TopClient("PIXOO 64", down_kbps=40, up_kbps=8),
        ]
        return Snapshot(
            clients=17,
            clients_lan=4,
            clients_wan=13,
            wan_down_kbps=down,
            wan_up_kbps=up,
            cpu_pct=cpu,
            temp_c=temp,
            ram_pct=ram,
            disk_pct=62.0,
            disk_used_mb=40.0,
            disk_total_mb=64.0,
            disk_label="jffs",
            internet_ok=(int(t) % 40) > 3,
            usb2=True,
            usb3=(int(t) % 60) > 10,
            eth_linked=3,
            lan_ports=(True, True, True, False),
            wan_ip="203.0.113.42",
            uptime_s=86400 * 3 + 3600 * 5 + 60 * 12,
            history=list(self._hist),
            top_clients=tops_down[: self.top_n],
            top_up_clients=tops_up[: self.top_n],
            hour_stats=self._hour_stats(),
            demo=True,
        )

    def sample(self) -> Snapshot:
        if self.demo:
            return self._demo_snapshot()

        now = time.time()
        down_kbps = up_kbps = 0.0
        cur = _iface_bytes(self.wan_iface)
        if cur is None and self.wan_iface:
            self.wan_iface = detect_wan_iface()
            cur = _iface_bytes(self.wan_iface)
        if cur is not None:
            rx, tx = cur
            if self._prev_net is not None:
                pts, prx, ptx = self._prev_net
                dt = max(0.001, now - pts)
                down_kbps = max(0.0, (rx - prx) * 8.0 / 1000.0 / dt)
                up_kbps = max(0.0, (tx - ptx) * 8.0 / 1000.0 / dt)
            self._prev_net = (now, rx, tx)

        self._hist.append(BandwidthSample(now, down_kbps, up_kbps))

        cpu_pct = 0.0
        ct = _cpu_times()
        if ct is not None:
            idle, total = ct
            if self._prev_cpu is not None:
                pidle, ptotal = self._prev_cpu
                didle = idle - pidle
                dtotal = total - ptotal
                if dtotal > 0:
                    cpu_pct = 100.0 * (1.0 - didle / dtotal)
                    cpu_pct = max(0.0, min(100.0, cpu_pct))
            self._prev_cpu = (idle, total)

        mono = time.monotonic()
        if not self._last_temp_mono or (mono - self._last_temp_mono) >= max(5.0, self.sample_interval):
            temps = _temps_c()
            self._cached_temp = sum(temps) / len(temps) if temps else 0.0
            self._last_temp_mono = mono
        temp_c = self._cached_temp
        ram_pct = _ram_pct()
        disk_pct, disk_used, disk_total, disk_label = _disk_usage(self.disk_path)
        lan = _lan_port_links()
        u2, u3 = _usb_status()

        self._sys.append(_SysSample(now, down_kbps, up_kbps, cpu_pct, temp_c, ram_pct))
        self._trim_history(now)

        if not self._last_clients_mono or (mono - self._last_clients_mono) >= self.sample_interval:
            self._cached_clients = _client_lan_wan_counts()
            self._last_clients_mono = mono
        total, lan_n, wifi_n = self._cached_clients
        top_down, top_up = self._top_wifi_clients(now)

        if not self._last_ping_mono or (mono - self._last_ping_mono) >= self._ping_min_interval:
            self._cached_internet = _internet_ok(self.ping_host)
            self._last_ping_mono = mono

        return Snapshot(
            clients=total,
            clients_lan=lan_n,
            clients_wan=wifi_n,
            wan_down_kbps=down_kbps,
            wan_up_kbps=up_kbps,
            cpu_pct=cpu_pct,
            temp_c=temp_c,
            ram_pct=ram_pct,
            disk_pct=disk_pct,
            disk_used_mb=disk_used,
            disk_total_mb=disk_total,
            disk_label=disk_label,
            internet_ok=self._cached_internet,
            usb2=u2,
            usb3=u3,
            eth_linked=sum(1 for up in lan if up),
            lan_ports=lan,
            wan_ip=_wan_ip(),
            uptime_s=_uptime_s(),
            history=list(self._hist),
            top_clients=top_down,
            top_up_clients=top_up,
            hour_stats=self._hour_stats(),
            demo=False,
        )


# Warm-up: deux samples rapprochés pour avoir un premier delta CPU/WAN
def warm_sample(collector: MetricsCollector, pause: float = 0.6) -> Snapshot:
    collector.sample()
    time.sleep(pause)
    return collector.sample()
