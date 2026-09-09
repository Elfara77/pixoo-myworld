"""Exemple de plugin utilisateur — copier/adapter dans plugins/."""

from __future__ import annotations

from typing import Any

# Note: lorsque chargé via importlib depuis plugins/, l'import relatif
# du package studio n'est pas disponible. On enregistre une classe autonome
# compatible duck-typing avec DataSourcePlugin.


class ExamplePlugin:
    id = "example_const"
    name = "Exemple constante"
    description = "Plugin utilisateur démo"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "value": {"type": "number", "title": "Valeur", "default": 7.0},
            },
            "required": ["value"],
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        try:
            float(config.get("value", 0))
            return True
        except (TypeError, ValueError):
            return False

    def fetch_data(self, config: dict[str, Any], context=None) -> Any:
        return float(config.get("value") or 0)

    def extract_numeric(self, data: Any):
        try:
            return float(data)
        except (TypeError, ValueError):
            return None


PLUGIN = ExamplePlugin()
