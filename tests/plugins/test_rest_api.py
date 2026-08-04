"""REST API plugin tests with httpx mock transport."""

from __future__ import annotations

import httpx
import pytest

from pixoo.plugins.rest_api import RestApiPlugin


def test_rest_api_jsonpath(monkeypatch):
    plugin = RestApiPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"temperature": 12.5}]})

    transport = httpx.MockTransport(handler)

    def fake_client(timeout: float = 5.0):
        return httpx.Client(transport=transport, timeout=timeout)

    monkeypatch.setattr("pixoo.plugins.rest_api.http_client", fake_client)
    cfg = {
        "url": "https://api.example.com/v1/data",
        "method": "GET",
        "extract_path": "$.data[0].temperature",
        "timeout": 5,
        "retries": 0,
    }
    assert plugin.validate_config(cfg)
    assert plugin.fetch_data(cfg) == 12.5


def test_rest_api_timeout_fallback(monkeypatch):
    plugin = RestApiPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    transport = httpx.MockTransport(handler)

    def fake_client(timeout: float = 5.0):
        return httpx.Client(transport=transport, timeout=timeout)

    monkeypatch.setattr("pixoo.plugins.rest_api.http_client", fake_client)
    cfg = {
        "url": "https://api.example.com/slow",
        "extract_path": "$.x",
        "retries": 0,
        "fallback_value": "N/A",
    }
    with pytest.raises(Exception):
        plugin.fetch_data(cfg)


def test_rest_api_bearer(monkeypatch):
    plugin = RestApiPlugin()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"value": 1})

    def fake_client(timeout: float = 5.0):
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr("pixoo.plugins.rest_api.http_client", fake_client)
    val = plugin.fetch_data(
        {
            "url": "https://api.example.com/x",
            "extract_path": "$.value",
            "auth_type": "bearer",
            "auth_token": "SECRET",
            "retries": 0,
        }
    )
    assert val == 1
    assert seen["auth"] == "Bearer SECRET"
