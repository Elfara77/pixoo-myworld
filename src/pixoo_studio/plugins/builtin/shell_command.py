"""Builtin plugin: commande shell + parse."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from ..base import DataSourcePlugin, FetchContext


class ShellCommandPlugin(DataSourcePlugin):
    id = "shell_command"
    name = "Commande shell"
    description = "Exécute une commande et parse le stdout"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "title": "Commande", "default": ""},
                "cwd": {"type": "string", "title": "Répertoire", "default": ""},
                "timeout_s": {"type": "number", "title": "Timeout (s)", "default": 3.0},
                "parse_mode": {
                    "type": "string",
                    "title": "Parse",
                    "enum": ["float", "percent", "regex", "line_field"],
                    "default": "float",
                },
                "parse_expr": {
                    "type": "string",
                    "title": "Expression (regex / line:field)",
                    "default": "",
                },
            },
            "required": ["command"],
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("command") or "").strip())

    def fetch_data(self, config: dict[str, Any], context: FetchContext | None = None) -> Any:
        cmd = str(config.get("command") or "")
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(0.2, float(config.get("timeout_s") or 3)),
            cwd=str(config.get("cwd") or "") or None,
            check=False,
        )
        return self._parse(proc.stdout or "", config)

    def _parse(self, text: str, config: dict[str, Any]) -> float | None:
        mode = str(config.get("parse_mode") or "float")
        expr = str(config.get("parse_expr") or "")
        try:
            if mode == "float":
                m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
                return float(m.group(0)) if m else None
            if mode == "percent":
                m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%?", text)
                return float(m.group(1)) if m else None
            if mode == "regex":
                m = re.search(expr or r"([-+]?\d+(?:\.\d+)?)", text, re.M | re.S)
                if not m:
                    return None
                return float(m.group(1) if m.lastindex else m.group(0))
            if mode == "line_field":
                parts = expr.split(":")
                li = int(parts[0]) if parts and parts[0] != "" else 0
                fi = int(parts[1]) if len(parts) > 1 and parts[1] != "" else 0
                sep = parts[2] if len(parts) > 2 else None
                lines = text.splitlines()
                row = lines[li].split(sep) if sep else lines[li].split()
                return float(row[fi])
        except Exception:
            return None
        return None


PLUGIN = ShellCommandPlugin()
