"""Shell command plugin (optional builtin)."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from pixoo.plugins.base import DataSourcePlugin


class ShellPlugin(DataSourcePlugin):
    name = "shell"
    description = "Run a shell command and parse stdout"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "command": {"type": "string", "label": "Command", "required": True},
            "timeout": {"type": "integer", "label": "Timeout (s)", "default": 3},
            "regex": {"type": "string", "label": "Regex (group 1)", "default": r"([-+]?\d+(?:\.\d+)?)"},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("command") or "").strip())

    def fetch_data(self, config: dict[str, Any]) -> Any:
        proc = subprocess.run(
            str(config["command"]),
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(0.2, float(config.get("timeout") or 3)),
            check=False,
        )
        pattern = str(config.get("regex") or r"([-+]?\d+(?:\.\d+)?)")
        m = re.search(pattern, proc.stdout or "")
        if not m:
            return None
        return float(m.group(1) if m.lastindex else m.group(0))


PLUGIN = ShellPlugin()
