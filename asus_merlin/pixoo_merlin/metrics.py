"""Collecte des métriques AsusWRT-Merlin (shell + /proc) + mode démo."""

from __future__ import annotations

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
class Snapshot:
    clients: int = 0
    wan_down_kbps: float = 0.0
    wan_up_kbps: float = 0.0
    cpu_pct: float = 0.0
    temp_c: float = 0.0
    ram_pct: float = 0.0
    internet_ok: bool = False
    usb2: bool = False
    usb3: bool = False
    eth_linked: int = 0
    lan_ports: tuple[bool, bool, bool, bool] = (False, False, False, False)
    wan_ip: str = "—"
    uptime_s: float = 0.0
    history: list[BandwidthSample] = field(default_factory=list)
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


def _wl_client_ifaces() -> list[str]:
    """All wireless interfaces including guest VIFs."""
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
    # Prefer ip neigh when available
    neigh = _run("ip -4 neigh show 2>/dev/null")
    if neigh:
        for line in neigh.splitlines():
            # 192.168.50.4 dev br0 lladdr aa:bb:… REACHABLE
            if "lladdr" not in line:
                continue
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
        # IP HW type Flags HW address Mask Device
        flags, mac = parts[2], parts[3]
        if flags == "0x0" or mac in ("00:00:00:00:00:00", "0:0:0:0:0:0"):
            continue
        if _MAC_RE.fullmatch(mac):
            macs.add(_norm_mac(mac))
    return macs


def _macs_from_bridge() -> set[str]:
    macs: set[str] = set()
    out = _run("brctl showmacs br0 2>/dev/null")
    for line in (out or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        # port mac islocal ageing
        mac, islocal = parts[1], parts[2].lower()
        if islocal in ("yes", "1"):
            continue
        if _MAC_RE.fullmatch(mac):
            macs.add(_norm_mac(mac))
    return macs


def _count_clients() -> int:
    """Unique online clients (Wi‑Fi assoc + ARP + leases + bridge) — not ETH port count."""
    macs: set[str] = set()
    macs |= _macs_from_wifi()
    macs |= _macs_from_arp()
    macs |= _macs_from_leases()
    macs |= _macs_from_bridge()
    # Drop broadcast / multicast-ish
    macs = {m for m in macs if not m.startswith(("ff:ff:ff", "01:00:5e", "33:33:"))}
    return len(macs)


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


class MetricsCollector:
    """Échantillonne CPU / WAN et conserve l'historique 5 min."""

    def __init__(
        self,
        *,
        wan_iface: str = "",
        ping_host: str = "1.1.1.1",
        history_seconds: int = 300,
        demo: bool = False,
    ) -> None:
        self.wan_iface = detect_wan_iface(wan_iface) if not demo else (wan_iface or "eth0")
        self.ping_host = ping_host
        self.history_seconds = history_seconds
        self.demo = demo
        self._hist: Deque[BandwidthSample] = deque()
        self._prev_cpu: tuple[int, int] | None = None
        self._prev_net: tuple[float, int, int] | None = None  # ts, rx, tx
        self._demo_t0 = time.time()

    def _trim_history(self, now: float) -> None:
        cut = now - self.history_seconds
        while self._hist and self._hist[0].ts < cut:
            self._hist.popleft()

    def _demo_snapshot(self) -> Snapshot:
        t = time.time() - self._demo_t0
        down = 40 + 60 * abs(__import__("math").sin(t / 17)) + random.uniform(0, 15)
        up = 8 + 12 * abs(__import__("math").sin(t / 23 + 1)) + random.uniform(0, 4)
        self._hist.append(BandwidthSample(time.time(), down, up))
        self._trim_history(time.time())
        return Snapshot(
            clients=12 + int(3 * abs(__import__("math").sin(t / 40))),
            wan_down_kbps=down,
            wan_up_kbps=up,
            cpu_pct=25 + 40 * abs(__import__("math").sin(t / 11)),
            temp_c=42 + 8 * abs(__import__("math").sin(t / 29)),
            ram_pct=35 + 20 * abs(__import__("math").sin(t / 19)),
            internet_ok=(int(t) % 40) > 3,
            usb2=True,
            usb3=(int(t) % 60) > 10,
            eth_linked=3,
            lan_ports=(True, True, True, False),
            wan_ip="203.0.113.42",
            uptime_s=86400 * 3 + 3600 * 5 + 60 * 12,
            history=list(self._hist),
            demo=True,
        )

    def sample(self) -> Snapshot:
        if self.demo:
            return self._demo_snapshot()

        now = time.time()
        # --- WAN rate ---
        down_kbps = up_kbps = 0.0
        cur = _iface_bytes(self.wan_iface)
        if cur is None and self.wan_iface:
            # re-detect
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
        self._trim_history(now)

        # --- CPU ---
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

        temps = _temps_c()
        temp_c = sum(temps) / len(temps) if temps else 0.0
        lan = _lan_port_links()
        u2, u3 = _usb_status()

        return Snapshot(
            clients=_count_clients(),
            wan_down_kbps=down_kbps,
            wan_up_kbps=up_kbps,
            cpu_pct=cpu_pct,
            temp_c=temp_c,
            ram_pct=_ram_pct(),
            internet_ok=_internet_ok(self.ping_host),
            usb2=u2,
            usb3=u3,
            eth_linked=sum(1 for up in lan if up),
            lan_ports=lan,
            wan_ip=_wan_ip(),
            uptime_s=_uptime_s(),
            history=list(self._hist),
            demo=False,
        )


# Warm-up: deux samples rapprochés pour avoir un premier delta CPU/WAN
def warm_sample(collector: MetricsCollector, pause: float = 0.6) -> Snapshot:
    collector.sample()
    time.sleep(pause)
    return collector.sample()
