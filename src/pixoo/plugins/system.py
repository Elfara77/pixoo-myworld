"""Built-in system metrics plugin (CPU, RAM, disk, load)."""

from __future__ import annotations

from typing import Any

import psutil

from pixoo.plugins.base import DataSourcePlugin

KEYS = ("cpu", "ram", "swap", "disk", "load", "load5")


class SystemPlugin(DataSourcePlugin):
    name = "system"
    description = "Local system metrics via psutil"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "key": {
                "type": "string",
                "label": "Metric",
                "required": True,
                "enum": list(KEYS),
                "default": "cpu",
            }
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        return str(config.get("key") or "") in KEYS

    def fetch_data(self, config: dict[str, Any]) -> Any:
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
        return None


PLUGIN = SystemPlugin()
