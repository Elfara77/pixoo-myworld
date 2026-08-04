"""Builtin plugin: valeur fixe (maquette)."""

from __future__ import annotations

from typing import Any

from ..base import DataSourcePlugin, FetchContext


class StaticValuePlugin(DataSourcePlugin):
    id = "static_value"
    name = "Valeur fixe"
    description = "Valeur constante pour maquetter le design"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "value": {"type": "number", "title": "Valeur", "default": 42.0},
            },
            "required": ["value"],
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        try:
            float(config.get("value", 0))
            return True
        except (TypeError, ValueError):
            return False

    def fetch_data(self, config: dict[str, Any], context: FetchContext | None = None) -> Any:
        return float(config.get("value") or 0)


PLUGIN = StaticValuePlugin()
