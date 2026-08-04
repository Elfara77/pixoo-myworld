"""Tests unitaires — plugins Studio."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from pixoo_studio.plugins.builtin.builtin_psutil import BuiltinPsutilPlugin
from pixoo_studio.plugins.builtin.rest_jsonpath import RestJsonPathPlugin
from pixoo_studio.plugins.builtin.shell_command import ShellCommandPlugin
from pixoo_studio.plugins.builtin.static_value import StaticValuePlugin
from pixoo_studio.plugins.base import PluginLoader


def test_static_plugin():
    p = StaticValuePlugin()
    assert p.validate_config({"value": 12})
    assert p.fetch_data({"value": 12}) == 12.0
    assert not p.validate_config({"value": "x"})


def test_builtin_schema_and_cpu():
    p = BuiltinPsutilPlugin()
    schema = p.get_config_schema()
    assert "key" in schema["properties"]
    assert p.validate_config({"key": "cpu"})
    assert not p.validate_config({"key": "nope"})
    val = p.fetch_data({"key": "ram"})
    assert val is None or isinstance(val, float)


def test_shell_float_parse():
    p = ShellCommandPlugin()
    assert p.validate_config({"command": "echo 42"})
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(stdout="load 3.14 ok\n", stderr="", returncode=0)
        assert p.fetch_data({"command": "echo", "parse_mode": "float"}) == 3.14


def test_rest_jsonpath_validate_and_fetch():
    p = RestJsonPathPlugin()
    cfg = {"url": "https://example.com/x", "jsonpath": "$.a.b", "headers_json": "{}"}
    assert p.validate_config(cfg)
    assert not p.validate_config({"url": "", "jsonpath": "$"})
    assert not p.validate_config({"url": "http://x", "jsonpath": "$$$invalid"})

    payload = {"a": {"b": 77}}
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(payload).encode()
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=fake_resp):
        assert p.fetch_data(cfg) == 77.0


def test_loader_builtins():
    loader = PluginLoader()
    loader.load_builtins()
    assert "builtin_psutil" in loader.plugins
    assert "rest_jsonpath" in loader.plugins
    assert "shell_command" in loader.plugins
