"""Builtin plugin: métriques psutil."""

from __future__ import annotations

from typing import Any

import psutil

from ..base import DataSourcePlugin, FetchContext

KEYS = {
    "cpu": "CPU %",
    "ram": "RAM %",
    "swap": "Swap %",
    "disk": "Disk / %",
    "load": "Load 1m",
    "load5": "Load 5m",
    "uptime_h": "Uptime hours",
}


class BuiltinPsutilPlugin(DataSourcePlugin):
    id = "builtin_psutil"
    name = "Builtin (psutil)"
    description = "Métriques système locales via psutil"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "title": "Métrique",
                    "enum": list(KEYS.keys()),
                    "enumLabels": list(KEYS.values()),
                    "default": "cpu",
                }
            },
            "required": ["key"],
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        return str(config.get("key") or "") in KEYS

    def fetch_data(self, config: dict[str, Any], context: FetchContext | None = None) -> Any:
        key = str(config.get("key") or "cpu")
        if key == "cpu":
            return float(psutil.cpu_percent(interval=None))
        if key == "ram":
            return float(psutil.virtual_memory().percent)
        if key == "swap":
            return float(psutil.swap_memory().percent)
        if key == "disk":
            return float(psutil.disk_usage("/").percent)
        if key == "load":
            return float(psutil.getloadavg()[0])
        if key == "load5":
            return float(psutil.getloadavg()[1])
        if key == "uptime_h":
            import time

            return (time.time() - psutil.boot_time()) / 3600.0
        return None


PLUGIN = BuiltinPsutilPlugin()
