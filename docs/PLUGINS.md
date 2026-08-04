# Data source plugins

Plugins implement `pixoo.plugins.base.DataSourcePlugin` and expose a module-level `PLUGIN` instance.

## Built-ins

| Name | Purpose | Config keys |
|---|---|---|
| `system` | Host metrics via psutil | `key`: `cpu`, `ram`, `disk`, `swap`, `temp`, … |
| `rest_api` | HTTP JSON + jsonpath | `url`, `jsonpath`, `timeout`, … |
| `shell` | Run a shell command, parse float | `command`, `timeout` |

## Project wiring

```json
{
  "id": "system.cpu",
  "label": "CPU",
  "plugin": "system",
  "config": { "key": "cpu" },
  "unit": "%"
}
```

Elements reference sources by id (`gauge.source`, `{system.cpu}` placeholders in text).

## Custom plugins

Drop a `.py` file in repo-root `plugins/` with:

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

The registry loads builtins then that directory on first `get_registry()` call.

## Schema form

`get_config_schema()` returns a dict used by Studio’s plugin inspector (`type`, `label`, `default`, `enum`, `required`).
