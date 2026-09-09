"""Plugin system — DataSourcePlugin ABC + loader dynamique."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("pixoo_studio.plugins")


@dataclass
class FetchContext:
    """Contexte passé à fetch_data (extensible)."""

    project_dir: Path | None = None
    last_value: Any = None
    extras: dict[str, Any] = field(default_factory=dict)


class DataSourcePlugin(ABC):
    """
    Contrat plugin de source de données.

    Chaque plugin expose un schéma de config (formulaires auto UI),
    valide la config, et fetch une valeur (scalaire ou dict).
    """

    id: str = "base"
    name: str = "Base"
    description: str = ""

    @abstractmethod
    def get_config_schema(self) -> dict[str, Any]:
        """JSON-Schema-like pour génération de formulaires."""

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> bool:
        ...

    @abstractmethod
    def fetch_data(self, config: dict[str, Any], context: FetchContext | None = None) -> Any:
        ...

    def extract_numeric(self, data: Any) -> float | None:
        """Helper: extrait un float d'un résultat plugin."""
        if data is None:
            return None
        if isinstance(data, bool):
            return float(data)
        if isinstance(data, (int, float)):
            return float(data)
        if isinstance(data, str):
            try:
                return float(data.strip().rstrip("%"))
            except ValueError:
                return None
        if isinstance(data, dict) and "value" in data:
            return self.extract_numeric(data["value"])
        return None


class PluginLoader:
    """Charge les plugins builtin + dossier `plugins/` utilisateur via importlib."""

    def __init__(self) -> None:
        self._plugins: dict[str, DataSourcePlugin] = {}

    @property
    def plugins(self) -> dict[str, DataSourcePlugin]:
        return dict(self._plugins)

    def get(self, plugin_id: str) -> DataSourcePlugin | None:
        return self._plugins.get(plugin_id)

    def register(self, plugin: DataSourcePlugin) -> None:
        if not getattr(plugin, "id", None):
            raise ValueError("Plugin sans id")
        self._plugins[plugin.id] = plugin
        logger.info("Plugin enregistré: %s (%s)", plugin.id, plugin.name)

    def load_builtins(self) -> None:
        from . import builtin

        for mod_name in ("builtin_psutil", "shell_command", "rest_jsonpath", "static_value"):
            try:
                mod = importlib.import_module(f".builtin.{mod_name}", package=__package__)
                plugin = getattr(mod, "PLUGIN", None) or getattr(mod, "create_plugin", lambda: None)()
                if plugin is not None:
                    self.register(plugin)
            except Exception as exc:
                logger.error("Échec chargement builtin %s: %s", mod_name, exc)

    def load_directory(self, directory: str | Path) -> int:
        """Charge tous les modules *.py d'un dossier (hors __init__)."""
        directory = Path(directory)
        if not directory.is_dir():
            return 0
        count = 0
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                plugin = self._load_file(path)
                if plugin:
                    self.register(plugin)
                    count += 1
            except Exception as exc:
                logger.error("Plugin %s: %s", path, exc)
        return count

    def _load_file(self, path: Path) -> DataSourcePlugin | None:
        mod_name = f"pixoo_user_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        plugin = getattr(mod, "PLUGIN", None)
        if plugin is None and hasattr(mod, "create_plugin"):
            plugin = mod.create_plugin()
        return plugin

    def load_all(self, user_plugins_dir: str | Path | None = None) -> None:
        self.load_builtins()
        root = Path(__file__).resolve().parents[3]
        default_user = root / "plugins"
        self.load_directory(user_plugins_dir or default_user)


_default_loader: PluginLoader | None = None


def get_loader() -> PluginLoader:
    global _default_loader
    if _default_loader is None:
        _default_loader = PluginLoader()
        _default_loader.load_all()
    return _default_loader
