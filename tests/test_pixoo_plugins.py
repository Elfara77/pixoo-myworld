"""Plugin registry + builtins."""

from pixoo.plugins.base import get_registry


def test_builtins_registered():
    reg = get_registry()
    for name in (
        "system",
        "rest_api",
        "shell",
        "web_scraper",
        "mqtt",
        "websocket",
        "database",
        "weather",
        "crypto",
        "calendar",
        "stock",
    ):
        assert name in reg.plugins, name


def test_system_cpu():
    plug = get_registry().get("system")
    assert plug is not None
    assert plug.validate_config({"key": "cpu"})
    val = plug.fetch_data({"key": "cpu"})
    assert isinstance(val, (int, float))
