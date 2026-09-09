# External source examples

## Weather (Paris, Open-Meteo)

Plugin `weather`:

```json
{
  "provider": "open-meteo",
  "latitude": 48.85,
  "longitude": 2.35,
  "field": "all",
  "cache_ttl": 300
}
```

Text: `{weather.temperature:.1f}°C` — or use template `weather_paris`.

Equivalent raw REST:

```json
{
  "url": "https://api.open-meteo.com/v1/forecast",
  "params_json": "{\"latitude\":48.85,\"longitude\":2.35,\"current_weather\":true}",
  "extract_path": "$.current_weather.temperature",
  "cache_ttl": 60
}
```

## Bitcoin (CoinGecko)

Plugin `crypto`:

```json
{
  "exchange": "coingecko",
  "symbol": "bitcoin",
  "vs_currency": "eur",
  "field": "all",
  "cache_ttl": 60
}
```

Template: `bitcoin_price`.

## System monitor

Plugin `system` with keys `cpu` / `ram` / `disk`. Template: `system_monitor`.

## Home Assistant sensor

```json
{
  "url": "http://homeassistant.local:8123/api/states/sensor.temperature",
  "auth_type": "bearer",
  "auth_token": "${ENV:HA_TOKEN}",
  "extract_path": "$.state",
  "cache_ttl": 30
}
```

## MQTT Zigbee sensor

```json
{
  "broker": "192.168.1.100",
  "topic": "zigbee2mqtt/temperature_sensor",
  "payload_type": "json",
  "extract_path": "$.temperature",
  "cache_ttl": 30
}
```

## Web scraper

```json
{
  "url": "https://example.com/meteo",
  "selector": ".current-temp",
  "attribute": "text",
  "regex": "(\\d+(?:\\.\\d+)?)",
  "cache_ttl": 300
}
```

## SQLite metric

```json
{
  "type": "sqlite",
  "connection_string": "sqlite:///./data/metrics.db",
  "query": "SELECT value FROM metrics ORDER BY id DESC LIMIT 1",
  "extract_path": "$[0].value",
  "cache_ttl": 60
}
```
