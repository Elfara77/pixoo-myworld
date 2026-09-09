# Troubleshooting external sources

## Timeout / slow APIs

- Cap is **10s** per call (`pixoo.utils.network_utils.MAX_TIMEOUT_S`).
- Raise `cache_ttl` (60–300s) for rate-limited APIs (CoinGecko).
- Check `GET /api/v1/sources` for `last_error` and `last_ms`.

## Auth failures (401/403)

- Prefer `${ENV:TOKEN}` in `.env`, not hard-coded secrets in `.pixoo`.
- For Home Assistant, use a long-lived access token with `auth_type: bearer`.

## JSONPath returns null

- Test the path with the Studio wizard **Test fetch**.
- Legacy key `jsonpath` is aliased to `extract_path`.
- For lists use `$[0].field` or `$.data[0].temperature`.

## MQTT / WebSocket stuck on fallback

- Streaming plugins keep the **last value**; until the first message arrives you see `fallback_value`.
- Confirm broker/topic and that the engine process was not blocked by firewall.
- Daemon calls `plugin.start()` on load / config reload.

## Scraper empty

- Site may require JS (not supported). Prefer an official API.
- Verify CSS selector in browser DevTools; try `attribute: text` + regex.

## Database errors

- SQLite path must be reachable from the engine working directory.
- Use bound parameters via `params_json` — do not concatenate user input into SQL.
- Postgres/MySQL need optional extras: `pipenv install -e ".[db]"` (or install drivers manually).

## Studio offline vs engine

- Local preview uses `DataFetcher` in-process.
- **Push config** requires a running daemon (`pixoo daemon`) with matching `api_version`.
