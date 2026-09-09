"""Sources de valeurs — builtin, commande shell, HTTP, static."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from typing import Any

import psutil

from .model import DataSource


def _builtin_value(key: str) -> float | None:
    key = (key or "").strip().lower()
    try:
        if key in ("cpu", "cpu_percent"):
            return float(psutil.cpu_percent(interval=None))
        if key in ("ram", "memory", "mem"):
            return float(psutil.virtual_memory().percent)
        if key == "swap":
            return float(psutil.swap_memory().percent)
        if key == "disk":
            return float(psutil.disk_usage("/").percent)
        if key in ("load", "load_avg", "load1"):
            return float(psutil.getloadavg()[0])
        if key == "load5":
            return float(psutil.getloadavg()[1])
        if key == "net_down":
            # instant counter not rate — return bytes recv / 1e6 as rough demo
            return float(psutil.net_io_counters().bytes_recv % 100000) / 1000.0
        if key == "net_up":
            return float(psutil.net_io_counters().bytes_sent % 100000) / 1000.0
        if key == "uptime_h":
            import time

            return (time.time() - psutil.boot_time()) / 3600.0
    except Exception:
        return None
    return None


def _parse_value(raw: str, source: DataSource) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    mode = source.parse_mode
    expr = (source.parse_expr or "").strip()

    try:
        if mode == "float":
            # première occurrence numérique
            m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
            return float(m.group(0)) if m else None

        if mode == "percent":
            m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%?", text)
            return float(m.group(1)) if m else None

        if mode == "regex":
            pattern = expr or r"([-+]?\d+(?:\.\d+)?)"
            m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
            if not m:
                return None
            if m.lastindex:
                return float(m.group(1))
            return float(m.group(0))

        if mode == "json_path":
            data = json.loads(text)
            cur: Any = data
            path = expr or ""
            for part in path.split("."):
                if part == "":
                    continue
                if isinstance(cur, list) and part.isdigit():
                    cur = cur[int(part)]
                elif isinstance(cur, dict):
                    cur = cur[part]
                else:
                    return None
            return float(cur)

        if mode == "line_field":
            # expr: "line:field" 0-based, sep whitespace or custom "line:field:,"
            parts = expr.split(":")
            line_i = int(parts[0]) if parts and parts[0] != "" else 0
            field_i = int(parts[1]) if len(parts) > 1 and parts[1] != "" else 0
            sep = parts[2] if len(parts) > 2 else None
            lines = text.splitlines()
            if line_i < 0 or line_i >= len(lines):
                return None
            row = lines[line_i].split(sep) if sep else lines[line_i].split()
            return float(row[field_i])
    except Exception:
        return None
    return None


def resolve_source(source: DataSource) -> tuple[float | None, str]:
    """
    Retourne (valeur, détail/debug).
    Ne lève pas — best-effort pour le designer.
    """
    kind = source.kind
    try:
        if kind == "static":
            return float(source.static_value), "static"

        if kind == "builtin":
            v = _builtin_value(source.builtin_key)
            return v, f"builtin:{source.builtin_key}"

        if kind == "command":
            if not source.command.strip():
                return None, "command vide"
            proc = subprocess.run(
                source.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=max(0.2, float(source.timeout_s)),
                cwd=source.cwd or None,
                check=False,
            )
            out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
            val = _parse_value(proc.stdout or "", source)
            detail = f"exit={proc.returncode} raw={((proc.stdout or '')[:80])!r}"
            return val, detail

        if kind == "http":
            if not source.url.strip():
                return None, "url vide"
            req = urllib.request.Request(source.url, headers={"User-Agent": "pixoo-designer/0.1"})
            with urllib.request.urlopen(req, timeout=max(0.5, float(source.timeout_s))) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            return _parse_value(body, source), f"http {source.url[:60]}"
    except Exception as exc:
        return None, f"error: {exc}"
    return None, "unknown kind"


def resolve_all(sources: list[DataSource]) -> dict[str, float | None]:
    # prime cpu
    try:
        psutil.cpu_percent(interval=None)
    except Exception:
        pass
    return {s.id: resolve_source(s)[0] for s in sources}


BUILTIN_KEYS: list[tuple[str, str]] = [
    ("cpu", "CPU %"),
    ("ram", "RAM %"),
    ("swap", "Swap %"),
    ("disk", "Disque / %"),
    ("load", "Load average 1m"),
    ("load5", "Load average 5m"),
    ("net_down", "Réseau ↓ (demo)"),
    ("net_up", "Réseau ↑ (demo)"),
    ("uptime_h", "Uptime (heures)"),
]
