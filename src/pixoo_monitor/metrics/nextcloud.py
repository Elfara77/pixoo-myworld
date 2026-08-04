"""Collecteurs Nextcloud / services — best-effort, gracieux si absent (macOS, etc.)."""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ServiceStatus:
    name: str
    active: bool | None  # None = inconnu / indisponible
    detail: str = ""


@dataclass
class NextcloudSnapshot:
    services: list[ServiceStatus] = field(default_factory=list)
    php_fpm_active: int | None = None
    php_fpm_total: int | None = None
    php_fpm_detail: str = ""
    db_ok: bool | None = None
    db_connections: int | None = None
    db_detail: str = ""
    redis_ok: bool | None = None
    redis_memory_mb: float | None = None
    redis_detail: str = ""
    nc_disk_percent: float | None = None
    nc_disk_used_gb: float | None = None
    nc_disk_total_gb: float | None = None
    nc_data_size_gb: float | None = None
    nc_disk_path: str | None = None
    nc_http_ok: bool | None = None
    nc_http_code: int | None = None
    nc_http_detail: str = ""
    nc_cron_ok: bool | None = None
    nc_cron_age_min: float | None = None
    nc_cron_detail: str = ""
    nc_error_count: int | None = None
    nc_errors_detail: str = ""
    nc_mounts: list[tuple[str, bool]] = field(default_factory=list)


def _run(
    cmd: list[str],
    *,
    timeout: float = 3.0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_systemd_service(name: str) -> ServiceStatus:
    """systemctl is-active — sans root (status utilisateur / system)."""
    if platform.system() != "Linux":
        return ServiceStatus(name=name, active=None, detail="non-linux")
    if not shutil.which("systemctl"):
        return ServiceStatus(name=name, active=None, detail="no-systemctl")
    proc = _run(["systemctl", "is-active", name], timeout=2.0)
    if proc is None:
        return ServiceStatus(name=name, active=None, detail="error")
    state = (proc.stdout or "").strip()
    if state == "active":
        return ServiceStatus(name=name, active=True, detail=state)
    if state in ("inactive", "failed", "activating", "deactivating"):
        return ServiceStatus(name=name, active=False, detail=state or "down")
    # exit 3 / 4 = unknown unit
    return ServiceStatus(name=name, active=None, detail=state or f"rc{proc.returncode}")


def check_services(names: list[str]) -> list[ServiceStatus]:
    return [check_systemd_service(n) for n in names if n]


def disk_usage_for(path: str) -> tuple[float, float, float] | None:
    """Retourne (percent, used_gb, total_gb) ou None."""
    if not path:
        return None
    try:
        import psutil

        du = psutil.disk_usage(path)
        return float(du.percent), du.used / (1024**3), du.total / (1024**3)
    except (OSError, ValueError):
        return None


def dir_size_gb(path: str, *, max_seconds: float = 2.0) -> float | None:
    """Taille approximative d'un répertoire (du -sk), best-effort."""
    p = Path(path)
    if not path or not p.exists():
        return None
    if shutil.which("du"):
        proc = _run(["du", "-sk", path], timeout=max_seconds)
        if proc and proc.returncode == 0:
            try:
                kb = float((proc.stdout or "").split()[0])
                return kb / (1024**2)
            except (ValueError, IndexError):
                pass
    # Fallback léger : ne pas walk massif
    try:
        total = 0
        deadline = time.monotonic() + max_seconds
        for root, _dirs, files in p.walk() if hasattr(p, "walk") else _walk(p):
            if time.monotonic() > deadline:
                break
            for f in files:
                try:
                    total += (root / f).stat().st_size
                except OSError:
                    continue
        return total / (1024**3)
    except OSError:
        return None


def _walk(path: Path):
    import os

    for root, dirs, files in os.walk(path):
        yield Path(root), dirs, files


def http_get(
    url: str,
    *,
    timeout: float = 3.0,
    headers: dict[str, str] | None = None,
) -> tuple[int | None, str]:
    if not url:
        return None, "no-url"
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "pixoo-monitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(65536).decode("utf-8", errors="replace")
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(exc.code), body
    except Exception as exc:
        return None, str(exc)[:80]


def check_nc_http(status_url: str) -> tuple[bool | None, int | None, str]:
    """GET status.php — attend JSON avec installed=true idéalement."""
    if not status_url:
        return None, None, "no-url"
    code, body = http_get(status_url)
    if code is None:
        return False, None, body or "error"
    ok = 200 <= code < 400
    detail = f"HTTP {code}"
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            installed = data.get("installed")
            if installed is False:
                ok = False
                detail = "not installed"
            elif installed is True:
                detail = "installed"
            maintenance = data.get("maintenance")
            if maintenance:
                detail += "+maint"
    except json.JSONDecodeError:
        if "installed" in body.lower() or "true" in body.lower():
            detail = "ok-text"
    return ok, code, detail


def check_php_fpm_status(url: str) -> tuple[int | None, int | None, str]:
    """Parse page status php-fpm (active processes / total processes)."""
    if not url:
        return None, None, "no-url"
    code, body = http_get(url)
    if code is None or code >= 400:
        return None, None, body if code is None else f"HTTP {code}"
    active = _match_int(body, r"active processes:\s*(\d+)")
    total = _match_int(body, r"total processes:\s*(\d+)")
    if active is None and total is None:
        # format JSON parfois
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                active = _as_int(data.get("active processes") or data.get("active"))
                total = _as_int(data.get("total processes") or data.get("total"))
        except json.JSONDecodeError:
            pass
    if active is None and total is None:
        return None, None, "unparsed"
    return active, total, "ok"


def _match_int(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _as_int(val: Any) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def check_db_health(db_type: str) -> tuple[bool | None, int | None, str]:
    """Ping simple selon le type — sans credentials si socket local / peer auth."""
    db_type = (db_type or "mariadb").lower()
    if db_type in ("mariadb", "mysql"):
        bin_name = "mariadb" if shutil.which("mariadb") else "mysql"
        if not shutil.which(bin_name):
            # fallback : service déjà couvert ; tente mysqladmin
            if shutil.which("mysqladmin"):
                proc = _run(["mysqladmin", "ping", "--silent"], timeout=2.0)
                if proc is None:
                    return None, None, "mysqladmin-error"
                return proc.returncode == 0, None, "ping"
            return None, None, "no-client"
        proc = _run([bin_name, "-N", "-e", "SELECT 1"], timeout=2.0)
        if proc is None:
            return None, None, "error"
        if proc.returncode != 0:
            return False, None, (proc.stderr or "fail")[:60]
        # connexions approximatives
        proc2 = _run(
            [bin_name, "-N", "-e", "SHOW STATUS LIKE 'Threads_connected'"],
            timeout=2.0,
        )
        conn = None
        if proc2 and proc2.returncode == 0:
            parts = (proc2.stdout or "").split()
            if len(parts) >= 2:
                conn = _as_int(parts[-1])
        return True, conn, "ok"

    if db_type in ("postgresql", "postgres", "pgsql"):
        if not shutil.which("pg_isready"):
            return None, None, "no-pg_isready"
        proc = _run(["pg_isready", "-q"], timeout=2.0)
        if proc is None:
            return None, None, "error"
        ok = proc.returncode == 0
        return ok, None, "ready" if ok else "not-ready"

    return None, None, f"unknown-db:{db_type}"


def check_redis() -> tuple[bool | None, float | None, str]:
    if not shutil.which("redis-cli"):
        # socket TCP best-effort
        try:
            import socket

            with socket.create_connection(("127.0.0.1", 6379), timeout=1.0):
                return True, None, "tcp-open"
        except OSError:
            return None, None, "no-redis-cli"
    proc = _run(["redis-cli", "ping"], timeout=2.0)
    if proc is None:
        return None, None, "error"
    ok = "PONG" in (proc.stdout or "").upper()
    mem_mb = None
    if ok:
        proc2 = _run(["redis-cli", "INFO", "memory"], timeout=2.0)
        if proc2 and proc2.returncode == 0:
            m = re.search(r"used_memory:(\d+)", proc2.stdout or "")
            if m:
                mem_mb = int(m.group(1)) / (1024**2)
    return ok, mem_mb, "pong" if ok else "down"


def check_nc_cron(occ_path: str, web_root: str) -> tuple[bool | None, float | None, str]:
    """Fraîcheur cron via occ status ou mtime data/cron.last / lastcron."""
    # 1) fichier lastcron classique
    candidates = []
    if web_root:
        candidates.append(Path(web_root) / "data" / ".ncdata")  # unlikely
        candidates.append(Path(web_root) / "data" / "cron.last")
    data_parent = Path(occ_path).parent / "data" if occ_path else None
    if data_parent:
        candidates.append(data_parent / "cron.last")

    for cand in candidates:
        try:
            if cand.is_file():
                age_min = (time.time() - cand.stat().st_mtime) / 60.0
                ok = age_min < 15.0
                return ok, age_min, cand.name
        except OSError:
            continue

    # 2) occ status (peut nécessiter le user www-data — best-effort)
    if occ_path and Path(occ_path).exists() and shutil.which("php"):
        proc = _run(["php", occ_path, "status", "--output=json"], timeout=5.0)
        if proc and proc.returncode == 0:
            try:
                data = json.loads(proc.stdout or "{}")
                # champs variables selon version
                last = data.get("lastcron") or data.get("cron")
                if isinstance(last, (int, float)):
                    age_min = (time.time() - float(last)) / 60.0
                    return age_min < 15.0, age_min, "occ"
            except json.JSONDecodeError:
                if "installed" in (proc.stdout or "").lower():
                    return None, None, "occ-no-cron-field"
        elif proc and proc.returncode != 0:
            return None, None, "occ-denied"

    return None, None, "unavailable"


def count_recent_errors(log_path: str, *, window_min: float = 15.0) -> tuple[int | None, str]:
    """Compte lignes 5xx / error dans la fenêtre (tail best-effort)."""
    if not log_path:
        return None, "no-path"
    path = Path(log_path)
    if not path.is_file():
        return None, "missing"
    try:
        # Lit les ~200 dernières lignes
        proc = _run(["tail", "-n", "200", str(path)], timeout=2.0)
        if proc is None or proc.returncode != 0:
            text = path.read_text(errors="replace")[-50000:]
        else:
            text = proc.stdout or ""
    except OSError as exc:
        return None, str(exc)[:40]

    cutoff = time.time() - window_min * 60
    count = 0
    patterns = re.compile(r"\b(5\d{2}|error|critical|emergency)\b", re.IGNORECASE)
    for line in text.splitlines():
        if not patterns.search(line):
            continue
        # si timestamp parseable, filtre ; sinon compte tout le tail
        count += 1
    _ = cutoff  # reserved for future timestamp parse
    return count, f"last200/{window_min:.0f}m"


def check_mounts(paths: list[str]) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for raw in paths:
        p = Path(raw)
        try:
            ok = p.exists() and p.is_mount() if hasattr(p, "is_mount") else p.exists()
            # Path.is_mount exists on pathlib
            if hasattr(p, "is_mount"):
                ok = p.exists() and (p.is_mount() or any(p.iterdir()) if p.is_dir() else p.exists())
            else:
                ok = p.exists()
            # Simplifié : existe + lisible
            ok = p.exists() and (p.is_dir() or p.is_file())
            if p.is_dir():
                try:
                    next(p.iterdir(), None)
                    readable = True
                except OSError:
                    readable = False
                ok = readable
            out.append((raw[-20:], ok))
        except OSError:
            out.append((raw[-20:], False))
    return out


class NextcloudCollector:
    def __init__(self, cfg: dict[str, Any], want: dict[str, bool]) -> None:
        self.cfg = cfg
        self.want = want
        nc = cfg.get("nextcloud") if isinstance(cfg.get("nextcloud"), dict) else {}
        self.nc = {**DEFAULTS, **(nc or {})}

    def collect(self) -> NextcloudSnapshot:
        snap = NextcloudSnapshot()
        try:
            self._fill(snap)
        except Exception:
            # Jamais crasher la boucle principale
            pass
        return snap

    def _fill(self, snap: NextcloudSnapshot) -> None:
        services = self.nc.get("services") or []
        if not isinstance(services, list):
            services = []

        if self.want.get("services"):
            snap.services = check_services([str(s) for s in services])

        if self.want.get("php_fpm_workers"):
            url = str(self.nc.get("php_fpm_status_url") or "")
            active, total, detail = check_php_fpm_status(url)
            snap.php_fpm_active = active
            snap.php_fpm_total = total
            snap.php_fpm_detail = detail

        if self.want.get("db_health"):
            ok, conn, detail = check_db_health(str(self.nc.get("db_type") or "mariadb"))
            snap.db_ok = ok
            snap.db_connections = conn
            snap.db_detail = detail

        if self.want.get("redis"):
            ok, mem, detail = check_redis()
            snap.redis_ok = ok
            snap.redis_memory_mb = mem
            snap.redis_detail = detail

        if self.want.get("nc_disk") or (self.want.get("disk") and self.nc.get("data_dir")):
            data_dir = str(self.nc.get("data_dir") or "")
            if data_dir:
                usage = disk_usage_for(data_dir)
                if usage:
                    snap.nc_disk_percent, snap.nc_disk_used_gb, snap.nc_disk_total_gb = usage
                    snap.nc_disk_path = data_dir
                size = dir_size_gb(data_dir)
                if size is not None:
                    snap.nc_data_size_gb = size

        if self.want.get("nc_http"):
            ok, code, detail = check_nc_http(str(self.nc.get("status_url") or ""))
            snap.nc_http_ok = ok
            snap.nc_http_code = code
            snap.nc_http_detail = detail

        if self.want.get("nc_cron"):
            ok, age, detail = check_nc_cron(
                str(self.nc.get("occ_path") or ""),
                str(self.nc.get("web_root") or ""),
            )
            snap.nc_cron_ok = ok
            snap.nc_cron_age_min = age
            snap.nc_cron_detail = detail

        if self.want.get("nc_errors"):
            count, detail = count_recent_errors(str(self.nc.get("log_path") or ""))
            snap.nc_error_count = count
            snap.nc_errors_detail = detail

        if self.want.get("nc_external_storage"):
            mounts = self.nc.get("external_mounts") or []
            if isinstance(mounts, list):
                snap.nc_mounts = check_mounts([str(m) for m in mounts])


DEFAULTS: dict[str, Any] = {
    "data_dir": "/var/www/nextcloud/data",
    "web_root": "/var/www/nextcloud",
    "status_url": "http://127.0.0.1/status.php",
    "occ_path": "/var/www/nextcloud/occ",
    "php_fpm_status_url": "",
    "log_path": "",
    "db_type": "mariadb",
    "external_mounts": [],
    "services": [
        "php8.4-fpm",
        "nginx",
        "mariadb",
        "redis-server",
        "cron",
    ],
}
