"""Stock quotes: Yahoo Finance / Alpha Vantage."""

from __future__ import annotations

from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.network_utils import clamp_timeout, http_client, with_retries
from pixoo.utils.secrets import resolve_secrets


class StockPlugin(DataSourcePlugin):
    name = "stock"
    description = "Stock quotes (Yahoo / Alpha Vantage)"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "source": {
                "type": "string",
                "label": "Source",
                "enum": ["yahoo", "alpha_vantage"],
                "default": "yahoo",
            },
            "symbol": {"type": "string", "label": "Symbol", "default": "AAPL"},
            "field": {
                "type": "string",
                "label": "Field",
                "enum": ["price", "change", "volume", "all"],
                "default": "price",
            },
            "api_key": {"type": "string", "label": "Alpha Vantage key", "default": "${ENV:ALPHA_VANTAGE_KEY}"},
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 60},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("symbol") or "").strip())

    def fetch_data(self, config: dict[str, Any]) -> Any:
        cfg = resolve_secrets(dict(config))
        source = str(cfg.get("source") or "yahoo")
        symbol = str(cfg.get("symbol") or "AAPL").upper()
        field = str(cfg.get("field") or "price")
        timeout = clamp_timeout(cfg.get("timeout"), 8)

        if source == "alpha_vantage":
            data = self._alpha(symbol, str(cfg.get("api_key") or ""), timeout)
        else:
            data = self._yahoo(symbol, timeout)

        if field == "all":
            return data
        return data.get(field)

    def _yahoo(self, symbol: str, timeout: float) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            with http_client(timeout=timeout) as client:
                r = client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"interval": "1d", "range": "1d"},
                    headers={"User-Agent": "Mozilla/5.0 pixoo-engine/2.0"},
                )
                r.raise_for_status()
                return r.json()

        raw = with_retries(_do, retries=2)
        result = ((raw.get("chart") or {}).get("result") or [None])[0] or {}
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = None
        if price is not None and prev:
            change = float(price) - float(prev)
        return {
            "price": price,
            "change": change,
            "volume": meta.get("regularMarketVolume"),
        }

    def _alpha(self, symbol: str, api_key: str, timeout: float) -> dict[str, Any]:
        if not api_key:
            raise ValueError("Alpha Vantage requires api_key")

        def _do() -> dict[str, Any]:
            with http_client(timeout=timeout) as client:
                r = client.get(
                    "https://www.alphavantage.co/query",
                    params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key},
                )
                r.raise_for_status()
                return r.json()

        raw = with_retries(_do, retries=2)
        q = raw.get("Global Quote") or {}
        return {
            "price": float(q["05. price"]) if q.get("05. price") else None,
            "change": float(q["09. change"]) if q.get("09. change") else None,
            "volume": float(q["06. volume"]) if q.get("06. volume") else None,
        }


PLUGIN = StockPlugin()
