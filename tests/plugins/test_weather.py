"""Weather + crypto builtin plugin tests with mocked HTTP."""

from __future__ import annotations

import httpx

from pixoo.plugins.builtin.crypto import CryptoPlugin
from pixoo.plugins.builtin.weather import WeatherPlugin


def test_weather_open_meteo(monkeypatch):
    plugin = WeatherPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "current_weather": {"temperature": 12.5, "weathercode": 1, "windspeed": 10},
                "hourly": {"relativehumidity_2m": [55]},
            },
        )

    def fake_client(timeout: float = 5.0):
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr("pixoo.plugins.builtin.weather.http_client", fake_client)
    val = plugin.fetch_data(
        {"provider": "open-meteo", "latitude": 48.85, "longitude": 2.35, "field": "temperature"}
    )
    assert val == 12.5
    allv = plugin.fetch_data(
        {"provider": "open-meteo", "latitude": 48.85, "longitude": 2.35, "field": "all"}
    )
    assert allv["humidity"] == 55


def test_crypto_coingecko(monkeypatch):
    plugin = CryptoPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"bitcoin": {"eur": 45000, "eur_24h_change": 1.5, "eur_24h_vol": 1e9}},
        )

    def fake_client(timeout: float = 5.0):
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr("pixoo.plugins.builtin.crypto.http_client", fake_client)
    assert plugin.fetch_data({"symbol": "bitcoin", "vs_currency": "eur", "field": "price"}) == 45000
