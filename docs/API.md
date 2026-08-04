# Engine REST API (`/api/v1`)

Default bind: `http://127.0.0.1:8765` (see `runtime.api_host` / `api_port`).

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/version` | `api_version`, `engine_version`, `config_version` |
| GET | `/api/v1/status` | Uptime, last send, error count, Pixoo IP |
| GET | `/api/v1/current` | Base64 PNG of last/current frame + `screen_id` |
| POST | `/api/v1/config` | Body = full project JSON (or `{"project": …}`) |
| GET | `/api/v1/logs?limit=` | Recent engine log lines |
| GET | `/api/v1/sources` | Per-source stats + recent fetch logs |
| POST | `/api/v1/force-refresh` | Fetch + render + push now |
| POST | `/api/v1/shutdown` | Stop daemon |

## Compatibility

Studio calls `/version` before `/config`. If `api_version` ≠ studio’s `API_VERSION`, push is aborted (`VersionMismatchError`).

## Example

```bash
curl -s http://127.0.0.1:8765/api/v1/status | jq
curl -s -X POST http://127.0.0.1:8765/api/v1/force-refresh
```
