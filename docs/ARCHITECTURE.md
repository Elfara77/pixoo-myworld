# Pixoo architecture — Studio + Engine

Two-layer design under `src/pixoo/`:

| Layer | Package | Role |
|---|---|---|
| **Engine** | `pixoo.engine` | Headless: plugins → render 64×64 → Pixoo HTTP + FastAPI control plane |
| **Studio** | `pixoo.studio` | PySide6 GUI: edit `.pixoo`, local preview, sync to engine |
| **Common** | `pixoo.common` | Pydantic models, ConfigManager, API schemas |
| **Plugins** | `pixoo.plugins` | Data sources (`system`, `rest_api`, `shell` + user `plugins/`) |

```
Studio (GUI)  --HTTP-->  Engine daemon (FastAPI :8765)
                              |
                         Scheduler / Renderer
                              |
                         Divoom Pixoo /post
```

## CLI

```bash
pixoo version
pixoo studio --project projects/demo_v2.pixoo
pixoo daemon --project projects/demo_v2.pixoo --pixoo-ip 192.168.x.x
pixoo render --project projects/demo_v2.pixoo --output /tmp/out.png
```

Or: `./scripts/pixoo.sh …` / `./scripts/studio.sh`.

## Config gate

Projects must set `config_version = "2.0"`. Legacy `pixoo_studio` JSON is migrated on load when possible.

## Rate limit

Engine pushes at most once per `runtime.send_interval_s` (minimum **1.0 s**).

## Versions

- Package: `pixoo.__version__`
- REST: `API_VERSION` (`/api/v1/version`)
- File format: `CONFIG_VERSION`

Studio refuses to push config if the engine `api_version` mismatches.
