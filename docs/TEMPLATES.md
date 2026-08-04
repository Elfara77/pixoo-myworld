# Plugin templates

Templates live in [`src/pixoo/plugins/templates/`](../src/pixoo/plugins/templates/).

| Id | Description |
|---|---|
| `weather_paris` | Open-Meteo temperature for Paris |
| `bitcoin_price` | CoinGecko BTC/EUR |
| `system_monitor` | CPU/RAM gauges |

## Import in Studio

Menu **Templates → &lt;name&gt;** merges sources and appends screens into the current project.

## CLI / code

```python
from pixoo.studio.template_manager import TemplateManager
from pixoo.common.models import default_project

tm = TemplateManager()
project = default_project()
tm.apply_to_project(project, "weather_paris")
```

## Authoring a template

JSON shape:

```json
{
  "name": "My template",
  "description": "…",
  "config": {
    "sources": [ { "id": "…", "plugin": "…", "config": {} } ],
    "screens": [ { "id": "…", "title": "…", "elements": [] } ]
  }
}
```

Save as `src/pixoo/plugins/templates/my_template.json`.
