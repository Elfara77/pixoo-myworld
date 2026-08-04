# Data source plugins

Guide to configure and extend Pixoo external data sources (`src/pixoo/plugins`).

## Built-in plugins

| Name | Role |
|---|---|
| `system` | Host metrics (psutil) |
| `rest_api` | Generic HTTP REST + JSONPath |
| `web_scraper` | HTML CSS/XPath + regex |
| `mqtt` | MQTT subscriber (background thread) |
| `websocket` | WebSocket stream (background thread) |
| `database` | SQLAlchemy (sqlite/postgres/mysql) + optional MongoDB |
| `shell` | Shell command → float |
| `weather` | Open-Meteo / OpenWeatherMap / WeatherAPI |
| `crypto` | CoinGecko / Binance |
| `calendar` | iCal / ICS URL |
| `stock` | Yahoo Finance / Alpha Vantage |

User plugins: drop `PLUGIN = …` modules in repo-root [`plugins/`](../plugins/).

## REST API (basic)

```json
{
  "url": "https://api.example.com/data",
  "method": "GET",
  "extract_path": "$.value",
  "cache_ttl": 60,
  "retries": 3,
  "timeout": 5
}
```

### With Bearer auth

```json
{
  "url": "https://api.example.com/data",
  "headers_json": "{}",
  "auth_type": "bearer",
  "auth_token": "${ENV:HA_TOKEN}",
  "extract_path": "$.state"
}
```

Legacy keys `jsonpath` / `headers_json` / `body_json` remain supported.

## Secrets

Store tokens in `.env` (never commit):

```bash
HA_TOKEN=xxxx
OPENWEATHER_API_KEY=yyyy
```

Reference them as `${ENV:HA_TOKEN}` in plugin configs. Resolved by `pixoo.utils.secrets`.

## Tags in text elements

See also [SOURCES.md](SOURCES.md). Examples:

- `{system.cpu}%`
- `{weather.temperature:.1f}°C`
- `{btc.price:,.0f}`
- `{time:%H:%M}`

## Custom plugin

```python
from pixoo.plugins.base import DataSourcePlugin

class MyPlugin(DataSourcePlugin):
    name = "my_plugin"
    description = "…"
    def fetch_data(self, config): ...
    def validate_config(self, config): ...
    def get_config_schema(self): ...

PLUGIN = MyPlugin()
```

## Architecture helpers

- `DataFetcher` — parallel fetch + stats
- `CacheManager` — TTL + stale fallback (`~/.cache/pixoo/cache.json`)
- Studio: **Sources → Add source…** wizard, **Templates** menu
