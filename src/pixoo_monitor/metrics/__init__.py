from __future__ import annotations

import platform
import socket
import time
from dataclasses import dataclass, field
from typing import Any

import psutil

from . import temperature as temp_mod
from .nextcloud import NextcloudCollector, NextcloudSnapshot, ServiceStatus
from .status import StatusCollector, StatusSnapshot


@dataclass
class Snapshot:
    ts: float
    hostname: str
    platform: str
    cpu_percent: float | None = None
    cpu_per_core: list[float] | None = None
    load_avg: tuple[float, float, float] | None = None
    ram_percent: float | None = None
    ram_used_gb: float | None = None
    ram_total_gb: float | None = None
    swap_percent: float | None = None
    swap_used_gb: float | None = None
    swap_total_gb: float | None = None
    disk_percent: float | None = None
    disk_used_gb: float | None = None
    disk_total_gb: float | None = None
    disk_path: str | None = None
    net_up_kbps: float | None = None
    net_down_kbps: float | None = None
    net_interface: str | None = None
    temperatures: list[tuple[str, float]] = field(default_factory=list)
    uptime_hours: float | None = None
    top_processes: list[tuple[str, float]] = field(default_factory=list)
    nc: NextcloudSnapshot = field(default_factory=NextcloudSnapshot)
    status: StatusSnapshot = field(default_factory=StatusSnapshot)


_SYSTEM_KEYS = (
    "cpu",
    "cpu_per_core",
    "load_avg",
    "ram",
    "swap",
    "disk",
    "network",
    "temperature",
    "uptime",
    "processes",
)
_NC_KEYS = (
    "services",
    "php_fpm_workers",
    "db_health",
    "redis",
    "nc_disk",
    "nc_http",
    "nc_cron",
    "nc_errors",
    "nc_external_storage",
)
_STATUS_KEYS = (
    "status_host",
    "status_nc_http",
    "status_services",
    "status_disk",
    "status_network",
    "status_thermal",
    "status_overall",
)


class Collector:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        metrics = cfg.get("_resolved_metrics")
        if not isinstance(metrics, dict):
            from ..config import resolve_active_metrics

            metrics = resolve_active_metrics(cfg)
        all_keys = _SYSTEM_KEYS + _NC_KEYS + _STATUS_KEYS
        self.want = {k: bool(metrics.get(k, False)) for k in all_keys}

        # Status profile peut nécessiter des sous-collectes sans les avoir cochées
        # explicitement comme pages dédiées — on active la collecte sous-jacente.
        if self.want.get("status_services") and not self.want.get("services"):
            self.want["services"] = True
        if self.want.get("status_nc_http") and not self.want.get("nc_http"):
            self.want["nc_http"] = True
        if self.want.get("status_disk"):
            if not self.want.get("disk") and not self.want.get("nc_disk"):
                self.want["nc_disk"] = True
                self.want["disk"] = True
        if self.want.get("status_network") and not self.want.get("network"):
            self.want["network"] = True
        if self.want.get("status_thermal"):
            if not self.want.get("temperature"):
                self.want["temperature"] = True
            if not self.want.get("load_avg"):
                self.want["load_avg"] = True

        disk_cfg = cfg.get("disk") if isinstance(cfg.get("disk"), dict) else {}
        net_cfg = cfg.get("network") if isinstance(cfg.get("network"), dict) else {}
        path = (disk_cfg or {}).get("path") or ""
        nc_cfg = cfg.get("nextcloud") if isinstance(cfg.get("nextcloud"), dict) else {}
        if not path.strip() and self.want.get("disk") and (nc_cfg or {}).get("data_dir"):
            if self.want.get("services") or self.want.get("nc_disk") or self.want.get("status_disk"):
                path = str((nc_cfg or {}).get("data_dir") or "")
        self.disk_path = path.strip() or self._default_disk_path()
        self.net_iface = ((net_cfg or {}).get("interface") or "").strip()
        self._prev_net: tuple[float, int, int] | None = None
        self._cpu_primed = False
        self._nc = NextcloudCollector(cfg, self.want)
        self._status = StatusCollector(cfg, self.want)

    @staticmethod
    def _default_disk_path() -> str:
        if platform.system() == "Darwin":
            data = "/System/Volumes/Data"
            try:
                psutil.disk_usage(data)
                return data
            except OSError:
                return "/"
        return "/"

    def _pick_interface(self) -> str | None:
        if self.net_iface:
            return self.net_iface
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()

        def score(name: str) -> tuple[int, str]:
            if name in ("en0", "eth0", "wlan0", "wlp0s20f3"):
                return (0, name)
            if name.startswith("en") or name.startswith("eth") or name.startswith("wl"):
                return (1, name)
            return (2, name)

        candidates: list[str] = []
        skip_prefixes = (
            "lo", "Loopback", "awdl", "llw", "utun", "bridge", "docker",
            "veth", "br-", "anpi", "ap", "gif", "stf", "XHC", "iBridge",
        )
        for name, st in stats.items():
            if not st.isup:
                continue
            if name.startswith(skip_prefixes):
                continue
            if name not in addrs:
                continue
            has_v4 = any(getattr(a, "family", None) == socket.AF_INET for a in addrs[name])
            if not has_v4:
                continue
            candidates.append(name)
        if not candidates:
            return None
        candidates.sort(key=score)
        return candidates[0]

    def collect(self) -> Snapshot:
        snap = Snapshot(
            ts=time.time(),
            hostname=platform.node().split(".")[0][:12],
            platform=platform.system(),
        )

        if self.want["cpu"] or self.want["cpu_per_core"]:
            if not self._cpu_primed:
                psutil.cpu_percent(interval=None)
                self._cpu_primed = True
            if self.want["cpu"]:
                snap.cpu_percent = float(psutil.cpu_percent(interval=None))
            if self.want["cpu_per_core"]:
                snap.cpu_per_core = [
                    float(x) for x in psutil.cpu_percent(interval=None, percpu=True)
                ]

        if self.want["load_avg"]:
            try:
                snap.load_avg = psutil.getloadavg()
            except (AttributeError, OSError):
                snap.load_avg = None

        if self.want["ram"]:
            vm = psutil.virtual_memory()
            snap.ram_percent = float(vm.percent)
            snap.ram_used_gb = vm.used / (1024**3)
            snap.ram_total_gb = vm.total / (1024**3)

        if self.want["swap"]:
            sw = psutil.swap_memory()
            snap.swap_percent = float(sw.percent)
            snap.swap_used_gb = sw.used / (1024**3)
            snap.swap_total_gb = sw.total / (1024**3)

        if self.want["disk"]:
            try:
                du = psutil.disk_usage(self.disk_path)
                snap.disk_percent = float(du.percent)
                snap.disk_used_gb = du.used / (1024**3)
                snap.disk_total_gb = du.total / (1024**3)
                snap.disk_path = self.disk_path
            except OSError:
                pass

        if self.want["network"]:
            iface = self._pick_interface()
            counters = psutil.net_io_counters(pernic=True)
            if iface and iface in counters:
                c = counters[iface]
                now = time.time()
                if self._prev_net is not None:
                    prev_ts, prev_sent, prev_recv = self._prev_net
                    dt = max(now - prev_ts, 1e-6)
                    snap.net_up_kbps = (c.bytes_sent - prev_sent) * 8 / 1000 / dt
                    snap.net_down_kbps = (c.bytes_recv - prev_recv) * 8 / 1000 / dt
                self._prev_net = (now, c.bytes_sent, c.bytes_recv)
                snap.net_interface = iface

        if self.want["temperature"]:
            snap.temperatures = temp_mod.read_temperatures()

        if self.want["uptime"]:
            snap.uptime_hours = (time.time() - psutil.boot_time()) / 3600.0

        if self.want["processes"]:
            procs: list[tuple[str, float]] = []
            for p in psutil.process_iter(["name", "cpu_percent"]):
                try:
                    info = p.info
                    name = (info.get("name") or "?")[:10]
                    cpu = float(info.get("cpu_percent") or 0.0)
                    procs.append((name, cpu))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            procs.sort(key=lambda x: x[1], reverse=True)
            snap.top_processes = procs[:3]

        need_nc = any(self.want.get(k) for k in _NC_KEYS)
        if need_nc:
            snap.nc = self._nc.collect()

        need_status = any(self.want.get(k) for k in _STATUS_KEYS)
        if need_status:
            thr = self.cfg.get("thresholds") if isinstance(self.cfg.get("thresholds"), dict) else {}
            snap.status = self._status.build(
                hostname=snap.hostname,
                cpu_percent=snap.cpu_percent,
                load_avg=snap.load_avg,
                disk_percent=snap.disk_percent,
                nc_disk_percent=snap.nc.nc_disk_percent,
                net_interface=snap.net_interface,
                temperatures=snap.temperatures,
                nc_http_ok=snap.nc.nc_http_ok,
                nc_http_detail=snap.nc.nc_http_detail,
                services=snap.nc.services,
                thr=thr or {},
            )

        return snap


__all__ = [
    "Snapshot",
    "Collector",
    "NextcloudSnapshot",
    "ServiceStatus",
    "StatusSnapshot",
]
