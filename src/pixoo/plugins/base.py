"""Data source plugin contract."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger("pixoo.plugins")


class DataSourcePlugin(ABC):
    """Base class for all data sources."""

    name: str = "plugin_name"
    description: str = "Plugin description"
    supports_streaming: bool = False

    @abstractmethod
    def fetch_data(self, config: dict[str, Any]) -> Any:
        """Fetch data from the source."""

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> bool:
        """Return True if configuration is valid."""

    @abstractmethod
    def get_config_schema(self) -> dict[str, Any]:
        """Return a schema dict used to build configuration forms."""

    def extract_numeric(self, data: Any) -> float | None:
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
        if isinstance(data, dict):
            for key in ("value", "price", "temperature", "state", "temp"):
                if key in data:
                    return self.extract_numeric(data[key])
        return None

    def extract_value(self, data: Any) -> Any:
        """Return structured or scalar value for binding (default: passthrough)."""
        return data

    def start(self, config: dict[str, Any] | None = None) -> None:
        """Optional lifecycle for streaming plugins (MQTT/WS)."""

    def stop(self) -> None:
        """Optional lifecycle teardown."""


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, DataSourcePlugin] = {}

    def register(self, plugin: DataSourcePlugin) -> None:
        self._plugins[plugin.name] = plugin
        logger.info("Registered plugin: %s", plugin.name)

    def get(self, name: str) -> DataSourcePlugin | None:
        return self._plugins.get(name)

    @property
    def plugins(self) -> dict[str, DataSourcePlugin]:
        return dict(self._plugins)

    def load_builtins(self) -> None:
        modules = (
            "system",
            "rest_api",
            "shell",
            "web_scraper",
            "mqtt",
            "websocket",
            "database",
            "builtin.weather",
            "builtin.crypto",
            "builtin.calendar",
            "builtin.stock",
        )
        for mod_name in modules:
            try:
                mod = importlib.import_module(f"pixoo.plugins.{mod_name}")
                plugin = getattr(mod, "PLUGIN", None)
                if plugin is not None:
                    self.register(plugin)
            except Exception as exc:
                logger.error("Failed loading builtin %s: %s", mod_name, exc)

    def load_directory(self, directory: str | Path) -> int:
        directory = Path(directory)
        if not directory.is_dir():
            return 0
        count = 0
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                mod_name = f"pixoo_ext_{path.stem}"
                spec = importlib.util.spec_from_file_location(mod_name, path)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
                plugin = getattr(mod, "PLUGIN", None)
                if plugin is not None:
                    self.register(plugin)
                    count += 1
            except Exception as exc:
                logger.error("User plugin %s failed: %s", path, exc)
        return count

    def start_streaming(self, sources: list[Any]) -> None:
        for src in sources:
            plugin = self.get(getattr(src, "plugin", ""))
            if plugin and getattr(plugin, "supports_streaming", False):
                try:
                    plugin.start(getattr(src, "config", None))
                except Exception as exc:
                    logger.error("start %s failed: %s", plugin.name, exc)

    def stop_all(self) -> None:
        for plugin in self._plugins.values():
            try:
                plugin.stop()
            except Exception:
                pass


_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
        _registry.load_builtins()
        root = Path(__file__).resolve().parents[3]
        _registry.load_directory(root / "plugins")
    return _registry


def reset_registry() -> None:
    """Test helper to force reload."""
    global _registry
    if _registry is not None:
        _registry.stop_all()
    _registry = None
