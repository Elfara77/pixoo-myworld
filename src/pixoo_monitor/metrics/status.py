"""Collecteur « status » — santé globale best-effort pour Pixoo."""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Any, Literal

Health = Literal["ok", "warn", "down", "unknown"]


@dataclass
class StatusSnapshot:
    host_ok: bool | None = None
    host_name: str = ""
    os_label: str = ""
    os_detail: str = ""
    nc_http: Health = "unknown"
    nc_http_detail: str = ""
    services_ok: int = 0
    services_total: int = 0
    services_unknown: int = 0
    services_health: Health = "unknown"
    disk_health: Health = "unknown"
    disk_percent: float | None = None
    disk_detail: str = ""
    network_health: Health = "unknown"
    network_iface: str = ""
    network_detail: str = ""
    thermal_health: Health = "unknown"
    thermal_temp: float | None = None
    thermal_load: float | None = None
    thermal_detail: str = ""
    overall: Health = "unknown"
    overall_label: str = ""
    items: list[tuple[str, Health]] = field(default_factory=list)


def _run(cmd: list[str], *, timeout: float = 2.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def detect_os_label() -> tuple[str, str]:
    """Retourne (label court, détail) ex. ('Debian', 'Debian 13…')."""
    system = platform.system()
    if system == "Linux":
        try:
            from pathlib import Path

            p = Path("/etc/os-release")
            if p.is_file():
                data: dict[str, str] = {}
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        data[k] = v.strip().strip('"')
                pretty = data.get("PRETTY_NAME") or data.get("NAME") or "Linux"
                name = data.get("NAME") or "Linux"
                short = "Debian" if "debian" in name.lower() else name.split()[0][:8]
                return short[:10], pretty[:40]
        except OSError:
            pass
        return "Linux", platform.release()[:20]
    if system == "Darwin":
        ver = platform.mac_ver()[0] or ""
        return "macOS", f"macOS {ver}".strip()[:40]
    return system[:8] or "?", platform.platform()[:40]


def check_iface_up(iface: str | None) -> tuple[bool | None, str]:
    if not iface:
        return None, "no-iface"
    try:
        import psutil

        stats = psutil.net_if_stats()
        st = stats.get(iface)
        if st is None:
            return None, "missing"
        return bool(st.isup), "up" if st.isup else "down"
    except Exception:
        return None, "error"


def check_connectivity(target: str, *, enabled: bool = True) -> tuple[Health, str]:
    """Ping gateway ou cible externe — best-effort, sans root."""
    if not enabled:
        return "unknown", "disabled"
    host = (target or "").strip()
    if not host:
        host = _default_gateway() or "1.1.1.1"
    if not shutil.which("ping"):
        # TCP fallback : DNS 53 ou HTTPS
        try:
            with socket.create_connection((host if host[0].isdigit() else "1.1.1.1", 53), timeout=1.5):
                return "ok", f"tcp/{host}"
        except OSError:
            try:
                with socket.create_connection(("1.1.1.1", 443), timeout=1.5):
                    return "ok", "tcp/1.1.1.1"
            except OSError:
                return "down", "no-ping"
    # -c 1 -W 1 (Linux) ; macOS -c 1 -W 1000 (ms) — try Linux first
    for args in (
        ["ping", "-c", "1", "-W", "1", host],
        ["ping", "-c", "1", "-W", "1000", host],
        ["ping", "-c", "1", host],
    ):
        proc = _run(args, timeout=3.0)
        if proc is None:
            continue
        if proc.returncode == 0:
            return "ok", f"ping {host}"
        # continue trying other flag variants only if command failed oddly
        if "invalid" not in (proc.stderr or "").lower() and "illegal" not in (proc.stderr or "").lower():
            return "down", f"ping {host}"
    return "down", f"ping {host}"


def _default_gateway() -> str | None:
    system = platform.system()
    if system == "Linux":
        proc = _run(["ip", "route", "show", "default"], timeout=1.5)
        if proc and proc.returncode == 0:
            parts = (proc.stdout or "").split()
            if "via" in parts:
                i = parts.index("via")
                if i + 1 < len(parts):
                    return parts[i + 1]
    if system == "Darwin":
        proc = _run(["route", "-n", "get", "default"], timeout=1.5)
        if proc and proc.returncode == 0:
            for line in (proc.stdout or "").splitlines():
                if "gateway:" in line.lower():
                    return line.split(":", 1)[-1].strip() or None
    return None


def worst(*states: Health) -> Health:
    order = {"down": 3, "warn": 2, "unknown": 1, "ok": 0}
    best = "ok"
    rank = -1
    any_known = False
    for s in states:
        if s == "unknown":
            continue
        any_known = True
        if order[s] > rank:
            rank = order[s]
            best = s
    return best if any_known else "unknown"


def health_from_bool(ok: bool | None, *, warn_as_down: bool = False) -> Health:
    if ok is True:
        return "ok"
    if ok is False:
        return "down" if warn_as_down else "down"
    return "unknown"


def disk_health(pct: float | None, warn: float = 80.0, crit: float = 90.0) -> Health:
    if pct is None:
        return "unknown"
    if pct >= crit:
        return "down"
    if pct >= warn:
        return "warn"
    return "ok"


def thermal_health(
    temp: float | None,
    load1: float | None,
    *,
    temp_warn: float = 70.0,
    temp_crit: float = 85.0,
    load_warn: float = 4.0,
    load_crit: float = 8.0,
) -> Health:
    states: list[Health] = []
    if temp is not None:
        if temp >= temp_crit:
            states.append("down")
        elif temp >= temp_warn:
            states.append("warn")
        else:
            states.append("ok")
    if load1 is not None:
        if load1 >= load_crit:
            states.append("down")
        elif load1 >= load_warn:
            states.append("warn")
        else:
            states.append("ok")
    return worst(*states) if states else "unknown"


class StatusCollector:
    """Agrège un StatusSnapshot à partir du Snapshot système + NC + checks réseau."""

    def __init__(self, cfg: dict[str, Any], want: dict[str, bool]) -> None:
        self.cfg = cfg
        self.want = want
        st = cfg.get("status") if isinstance(cfg.get("status"), dict) else {}
        self.status_cfg = dict(st or {})

    def build(
        self,
        *,
        hostname: str,
        cpu_percent: float | None,
        load_avg: tuple[float, float, float] | None,
        disk_percent: float | None,
        nc_disk_percent: float | None,
        net_interface: str | None,
        temperatures: list[tuple[str, float]],
        nc_http_ok: bool | None,
        nc_http_detail: str,
        services: list[Any],
        thr: dict[str, Any],
    ) -> StatusSnapshot:
        snap = StatusSnapshot()
        items: list[tuple[str, Health]] = []

        # Host / OS
        if self.want.get("status_host"):
            short, detail = detect_os_label()
            snap.host_ok = True
            snap.host_name = hostname[:10]
            snap.os_label = short
            snap.os_detail = detail
            items.append(("HOST", "ok"))

        # NC HTTP
        if self.want.get("status_nc_http"):
            h = health_from_bool(nc_http_ok)
            snap.nc_http = h
            snap.nc_http_detail = nc_http_detail or ""
            items.append(("NC", h))

        # Services summary
        if self.want.get("status_services"):
            ok_n = sum(1 for s in services if getattr(s, "active", None) is True)
            bad_n = sum(1 for s in services if getattr(s, "active", None) is False)
            unk_n = sum(1 for s in services if getattr(s, "active", None) is None)
            total = len(services)
            snap.services_ok = ok_n
            snap.services_total = total
            snap.services_unknown = unk_n
            if total == 0:
                snap.services_health = "unknown"
            elif bad_n > 0:
                snap.services_health = "down" if bad_n >= max(1, total // 2) else "warn"
            elif unk_n == total:
                snap.services_health = "unknown"
            else:
                snap.services_health = "ok"
            items.append(("SVC", snap.services_health))

        # Disk
        if self.want.get("status_disk"):
            pct = nc_disk_percent if nc_disk_percent is not None else disk_percent
            crit = float(thr.get("nc_disk_percent", thr.get("disk_percent", 90)))
            warn = max(crit - 10, 50)
            snap.disk_percent = pct
            snap.disk_health = disk_health(pct, warn=warn, crit=crit)
            snap.disk_detail = f"{pct:.0f}%" if pct is not None else "n/a"
            items.append(("DSK", snap.disk_health))

        # Network + connectivity
        if self.want.get("status_network"):
            iface_ok, iface_detail = check_iface_up(net_interface)
            snap.network_iface = (net_interface or "")[:8]
            ping_enabled = bool(self.status_cfg.get("ping_enabled", True))
            target = str(self.status_cfg.get("ping_target") or "")
            conn_h, conn_d = check_connectivity(target, enabled=ping_enabled)
            if iface_ok is False:
                snap.network_health = "down"
                snap.network_detail = iface_detail
            elif iface_ok is True and conn_h == "ok":
                snap.network_health = "ok"
                snap.network_detail = conn_d
            elif iface_ok is True and conn_h == "down":
                snap.network_health = "warn"
                snap.network_detail = conn_d
            elif iface_ok is True:
                snap.network_health = "ok"
                snap.network_detail = iface_detail
            else:
                snap.network_health = conn_h if conn_h != "unknown" else "unknown"
                snap.network_detail = conn_d or iface_detail
            items.append(("NET", snap.network_health))

        # Thermal / load (N40)
        if self.want.get("status_thermal"):
            temp = temperatures[0][1] if temperatures else None
            load1 = load_avg[0] if load_avg else None
            temp_crit = float(thr.get("temperature_celsius", 85))
            snap.thermal_temp = temp
            snap.thermal_load = load1
            snap.thermal_health = thermal_health(
                temp,
                load1,
                temp_warn=temp_crit - 15,
                temp_crit=temp_crit,
            )
            parts = []
            if temp is not None:
                parts.append(f"{temp:.0f}C")
            if load1 is not None:
                parts.append(f"L{load1:.1f}")
            if cpu_percent is not None:
                parts.append(f"C{cpu_percent:.0f}")
            snap.thermal_detail = " ".join(parts) or "n/a"
            items.append(("THM", snap.thermal_health))

        snap.items = items

        # Overall
        if self.want.get("status_overall"):
            relevant = [h for _, h in items]
            # Host unknown doesn't count as failure
            snap.overall = worst(*relevant) if relevant else "unknown"
            labels = {"ok": "HEALTHY", "warn": "DEGRADED", "down": "DOWN", "unknown": "UNKNOWN"}
            snap.overall_label = labels.get(snap.overall, "UNKNOWN")
        elif items:
            snap.overall = worst(*(h for _, h in items))
            snap.overall_label = snap.overall.upper()

        return snap
