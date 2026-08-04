from __future__ import annotations

import platform
import re
import shutil
import subprocess
from typing import Callable


def read_temperatures() -> list[tuple[str, float]]:
    """Retourne [(label, °C), ...] — best-effort Linux / macOS."""
    readers: list[Callable[[], list[tuple[str, float]]]] = [
        _from_psutil,
        _from_linux_thermal,
        _from_osx_cpu_temp,
        _from_macos_powermetrics,
        _from_macos_system_profiler_fallback,
    ]
    for reader in readers:
        try:
            values = reader()
        except Exception:
            continue
        if values:
            return values
    return []


def _from_psutil() -> list[tuple[str, float]]:
    import psutil

    if not hasattr(psutil, "sensors_temperatures"):
        return []
    data = psutil.sensors_temperatures(fahrenheit=False) or {}
    out: list[tuple[str, float]] = []
    for chip, entries in data.items():
        for entry in entries:
            label = entry.label or chip
            if entry.current is None:
                continue
            out.append((str(label)[:8], float(entry.current)))
    return out[:4]


def _from_linux_thermal() -> list[tuple[str, float]]:
    if platform.system() != "Linux":
        return []
    from pathlib import Path

    out: list[tuple[str, float]] = []
    thermal = Path("/sys/class/thermal")
    if not thermal.is_dir():
        return []
    for zone in sorted(thermal.glob("thermal_zone*")):
        try:
            temp_raw = (zone / "temp").read_text().strip()
            typ = (zone / "type").read_text().strip() if (zone / "type").is_file() else zone.name
            val = float(temp_raw) / 1000.0
            if val <= 0 or val > 150:
                continue
            out.append((typ[:8], val))
        except (OSError, ValueError):
            continue
    return out[:4]


def _from_osx_cpu_temp() -> list[tuple[str, float]]:
    """Outil optionnel: brew install osx-cpu-temp"""
    if platform.system() != "Darwin":
        return []
    bin_path = shutil.which("osx-cpu-temp")
    if not bin_path:
        return []
    proc = subprocess.run(
        [bin_path],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    if proc.returncode != 0:
        return []
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", proc.stdout)
    if not m:
        return []
    return [("CPU", float(m.group(1)))]


def _from_macos_powermetrics() -> list[tuple[str, float]]:
    """Nécessite souvent sudo — ignoré silencieusement si non disponible."""
    if platform.system() != "Darwin":
        return []
    # Trop lourd / privilégié pour une boucle monitoring — skip par défaut
    return []


def _from_macos_system_profiler_fallback() -> list[tuple[str, float]]:
    """Pas de température fiable sans outil SMC ; retourne vide."""
    return []
