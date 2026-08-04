"""Plugin registry + builtins."""

from pixoo.plugins.base import get_registry


def test_builtins_registered():
    reg = get_registry()
    assert "system" in reg.plugins
    assert "rest_api" in reg.plugins
    assert "shell" in reg.plugins


def test_system_cpu():
    plug = get_registry().get("system")
    assert plug is not None
    assert plug.validate_config({"key": "cpu"})
    val = plug.fetch_data({"key": "cpu"})
    assert isinstance(val, (int, float))
