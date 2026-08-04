"""Web scraper plugin tests."""

from __future__ import annotations

import httpx

from pixoo.plugins.web_scraper import WebScraperPlugin


HTML = """
<html><body>
  <div class="current-temp">Temp 21°C</div>
  <a class="link" href="/next">go</a>
</body></html>
"""


def test_web_scraper_css_regex(monkeypatch):
    plugin = WebScraperPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML)

    def fake_client(timeout: float = 5.0):
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr("pixoo.plugins.web_scraper.http_client", fake_client)
    val = plugin.fetch_data(
        {
            "url": "https://example.com/meteo",
            "selector": ".current-temp",
            "attribute": "text",
            "regex": r"(\d+)",
            "retries": 0,
        }
    )
    assert val == "21"


def test_web_scraper_attribute(monkeypatch):
    plugin = WebScraperPlugin()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HTML)

    def fake_client(timeout: float = 5.0):
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr("pixoo.plugins.web_scraper.http_client", fake_client)
    val = plugin.fetch_data(
        {"url": "https://example.com/", "selector": "a.link", "attribute": "href", "retries": 0}
    )
    assert val == "/next"
