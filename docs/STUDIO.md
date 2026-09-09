# Pixoo Studio

Application de bureau professionnelle (**PySide6**) pour composer, prévisualiser et pousser des dashboards **64×64** vers un Divoom Pixoo.

> **Architecture v2** (`src/pixoo/`) : Studio GUI + engine headless. Voir [ARCHITECTURE.md](ARCHITECTURE.md), [API.md](API.md), [PLUGINS.md](PLUGINS.md).
> Le package legacy `pixoo_studio` reste disponible (`pipenv run studio-legacy`).

## Lancer

```bash
./scripts/install.sh
./scripts/studio.sh
./scripts/pixoo.sh studio -p projects/demo_v2.pixoo
# engine seul :
./scripts/pixoo.sh daemon -p projects/demo_v2.pixoo --pixoo-ip 192.168.52.4
./scripts/designer.sh   # shim → studio
```

Compatible **Windows / macOS / Linux** (wheels PySide6).

## Interface

| Zone | Rôle |
|---|---|
| Menu Fichier / Édition / Profils / Aide | Nouveau, Ouvrir/Sauver `.pixoo`, export PNG, paramètres |
| Toolbar | Auto-send ▶/■, Push once, Refresh, Zoom |
| Liste écrans / éléments | Composition multi-pages |
| Canvas central | Preview WYSIWYG 64×64 (nearest) + animations |
| Panneau droit | Propriétés écran / élément / sources (formulaires auto) / status |
| Dock Logs | INFO / WARN / ERROR |
| System Tray | Démarrer/arrêter send, ouvrir/masquer éditeur, logs, quitter |
| LED statut | Vert OK · Jaune dégradé · Rouge down |

## Plugins de données

Contrat `DataSourcePlugin` (`fetch_data` / `validate_config` / `get_config_schema`).

Chargement :

- builtins : `src/pixoo_studio/plugins/builtin/`
- utilisateur : dossier [`plugins/`](../plugins/) à la racine du repo

| Plugin | Id | Usage |
|---|---|---|
| Builtin psutil | `builtin_psutil` | CPU, RAM, disk, load… |
| Shell | `shell_command` | Commande + parse float/regex/line |
| REST JSONPath | `rest_jsonpath` | URL + JSONPath (+ headers JSON) |
| Static | `static_value` | Maquette |

Dans l’UI : onglet **Sources** → choisir le plugin → remplir le formulaire généré → **Tester** → lier à un élément.

Exemple plugin utilisateur (`plugins/my_plugin.py`) :

```python
from pixoo_studio.plugins.base import DataSourcePlugin, FetchContext

class MyPlugin(DataSourcePlugin):
    id = "my_plugin"
    name = "Mon plugin"
    def get_config_schema(self):
        return {"type":"object","properties":{"x":{"type":"number","default":1}}}
    def validate_config(self, config): return True
    def fetch_data(self, config, context=None): return float(config.get("x", 0))

PLUGIN = MyPlugin()
```

## Fichier `.pixoo`

JSON versionné (`version: 2`) :

- `meta` — nom, IP Pixoo, luminosité, FPS UI
- `runtime` — auto_send, intervalle, backoff
- `sources[]` — plugin_id + config
- `screens[]` / `elements[]` — layout, couleurs, overflow marquee, transitions

Les anciens `*.pixoo.json` (designer v1) sont migrés automatiquement à l’ouverture.

Démo : [`projects/demo.pixoo`](../projects/demo.pixoo).

## Runtime

- Auto-send périodique (configurable)
- Reconnexion avec **backoff exponentiel**
- Mode dégradé : dernière valeur connue si source KO
- Stats : envois OK/KO, uptime, dernière erreur
- Cache de frames 64×64 + préchargement polices

## Animations

- Texte **marquee** si overflow
- Transitions **fade** / **slide** entre écrans
- Preview temps réel (horloge UI FPS)

## Tests

```bash
pipenv run pytest tests/plugins -q
```

## Architecture

Voir le package `pixoo_studio/` : `domain` · `plugins` · `render` · `runtime` · `ui` · `persistence`.
Le moniteur CLI (`pixoo_monitor`) reste intact et fournit le client HTTP Pixoo.
