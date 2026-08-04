"""Cache manager + data fetcher tests."""

from __future__ import annotations

from pixoo.common.models import DataSourceConfig, default_project
from pixoo.engine.cache_manager import CacheManager
from pixoo.engine.data_fetcher import DataFetcher
from pixoo.plugins.base import PluginRegistry
from pixoo.plugins.system import PLUGIN as SYSTEM


def test_cache_ttl_and_stale():
    cache = CacheManager(persist_path=None)
    cache.set("a", 42, ttl=60)
    assert cache.get("a") == 42
    cache._store["a"].expires_at = 0
    assert cache.get("a") is None
    assert cache.get_stale("a") == 42


def test_fetcher_system_parallel():
    reg = PluginRegistry()
    reg.register(SYSTEM)
    fetcher = DataFetcher(reg, persist_cache=False, max_workers=4)
    project = default_project()
    values = fetcher.fetch_all(project)
    assert "system.cpu" in values
    assert values["system.cpu"] is not None
    fetcher.close()


def test_fetcher_fallback_on_error():
    from pixoo.plugins.base import DataSourcePlugin

    class Boom(DataSourcePlugin):
        name = "boom"
        description = "x"

        def get_config_schema(self):
            return {}

        def validate_config(self, config):
            return True

        def fetch_data(self, config):
            raise RuntimeError("fail")

    reg = PluginRegistry()
    reg.register(Boom())
    fetcher = DataFetcher(reg, persist_cache=False)
    src = DataSourceConfig(id="x", plugin="boom", config={"fallback_value": 7, "cache_ttl": 1})
    from pixoo.common.models import Project

    project = Project(sources=[src], screens=[])
    out = fetcher.fetch_all(project)
    assert out["x"] == 7
    fetcher.close()
