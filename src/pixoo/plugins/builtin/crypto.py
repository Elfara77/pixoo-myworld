"""Crypto prices: CoinGecko / Binance."""

from __future__ import annotations

from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.network_utils import clamp_timeout, http_client, with_retries
from pixoo.utils.secrets import resolve_secrets


class CryptoPlugin(DataSourcePlugin):
    name = "crypto"
    description = "Cryptocurrency prices (CoinGecko / Binance)"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "exchange": {
                "type": "string",
                "label": "Exchange",
                "enum": ["coingecko", "binance"],
                "default": "coingecko",
            },
            "symbol": {"type": "string", "label": "Symbol / id", "default": "bitcoin"},
            "vs_currency": {"type": "string", "label": "VS currency", "default": "eur"},
            "field": {
                "type": "string",
                "label": "Field",
                "enum": ["price", "change_24h", "volume", "all"],
                "default": "price",
            },
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 60},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("symbol") or "").strip())

    def fetch_data(self, config: dict[str, Any]) -> Any:
        cfg = resolve_secrets(dict(config))
        exchange = str(cfg.get("exchange") or "coingecko")
        symbol = str(cfg.get("symbol") or "bitcoin")
        vs = str(cfg.get("vs_currency") or "eur").lower()
        field = str(cfg.get("field") or "price")
        timeout = clamp_timeout(cfg.get("timeout"), 8)

        if exchange == "binance":
            data = self._binance(symbol, vs, timeout)
        else:
            data = self._coingecko(symbol, vs, timeout)

        if field == "all":
            return data
        return data.get(field)

    def _coingecko(self, symbol: str, vs: str, timeout: float) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            with http_client(timeout=timeout) as client:
                r = client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={
                        "ids": symbol,
                        "vs_currencies": vs,
                        "include_24hr_change": "true",
                        "include_24hr_vol": "true",
                    },
                )
                r.raise_for_status()
                return r.json()

        raw = with_retries(_do, retries=2)
        block = raw.get(symbol) or {}
        return {
            "price": block.get(vs),
            "change_24h": block.get(f"{vs}_24h_change"),
            "volume": block.get(f"{vs}_24h_vol"),
            vs: block.get(vs),
            f"{vs}_24h_change": block.get(f"{vs}_24h_change"),
        }

    def _binance(self, symbol: str, vs: str, timeout: float) -> dict[str, Any]:
        pair = symbol.upper()
        if not pair.endswith(vs.upper()):
            # bitcoin + eur → not on binance; map common ids
            mapping = {"bitcoin": "BTC", "ethereum": "ETH"}
            base = mapping.get(symbol.lower(), symbol.upper())
            pair = f"{base}{vs.upper()}"

        def _do() -> dict[str, Any]:
            with http_client(timeout=timeout) as client:
                r = client.get("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": pair})
                r.raise_for_status()
                return r.json()

        raw = with_retries(_do, retries=2)
        return {
            "price": float(raw.get("lastPrice") or 0),
            "change_24h": float(raw.get("priceChangePercent") or 0),
            "volume": float(raw.get("volume") or 0),
        }


PLUGIN = CryptoPlugin()
