# Pixoo 64 Monitor

Monitoring système / **Nextcloud** / **Minisforum N40** vers un **Divoom Pixoo 64** (64×64), isolé avec **Pipenv**.

Compatible **Debian 13** et **macOS Apple Silicon**. Les checks Nextcloud / systemd sont *best-effort* (pas de crash si absents).

## Démarrage rapide

```bash
./scripts/install.sh      # pipenv + deps (interactif si sans args)
./scripts/setup.sh        # menu: wizard / setups nommés
./scripts/test.sh         # dry-run : métriques + PNG
./scripts/run.sh          # live → Pixoo
./scripts/cron-setup.sh   # automation arrière-plan
./scripts/pixoo.sh        # CLI unifiée (studio | daemon | render)
./scripts/studio.sh       # Pixoo Studio GUI (engine + canvas)
./scripts/designer.sh     # shim → Studio
```

Tous les scripts supportent **`-h` / `--help`**. Sans argument → **mode interactif**.

### Architecture Studio + Engine

Deux couches sous `src/pixoo/` : **engine** headless (render + FastAPI + envoi Pixoo) et **studio** PySide6 (édition WYSIWYG, sync HTTP).

```bash
./scripts/pixoo.sh version
./scripts/pixoo.sh studio -p projects/demo_v2.pixoo
./scripts/pixoo.sh daemon -p projects/demo_v2.pixoo --pixoo-ip 192.168.52.4
./scripts/pixoo.sh render -p projects/demo_v2.pixoo -o /tmp/pixoo.png
```

Docs : [ARCHITECTURE.md](docs/ARCHITECTURE.md) · [API.md](docs/API.md) · [PLUGINS.md](docs/PLUGINS.md) · [SOURCES.md](docs/SOURCES.md) · [TEMPLATES.md](docs/TEMPLATES.md) · [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) · legacy [STUDIO.md](docs/STUDIO.md).

Plugins externes : REST, scraper, MQTT, WebSocket, DB, weather/crypto/calendar/stock — secrets via `.env` (`${ENV:NAME}`).

## Profils

| Profil | Rôle |
|---|---|
| `system` | Hôte générique (CPU, RAM, disque, réseau…) |
| `priority` | Priorité haute Nextcloud : disque data, services, php-fpm, DB, Redis |
| `nextcloud_files` | Files : data dir, `/status.php`, cron, erreurs log, montages |
| `n40` | Matériel N40 : CPU / RAM / swap / temp / net / load (vue thermique) |
| `status` | Santé globale OK/WARN/DOWN |
| `nextcloud_full` | Combo priority + files + N40 + status |

```bash
./scripts/run.sh --profile status
./scripts/test.sh --profile nextcloud_full
```

## Setups nommés

Snapshots complets sous `configs/setups/<nom>.toml`. `config.toml` reste la config **active**.

```bash
./scripts/setup.sh --save nextcloud-n40
./scripts/setup.sh --load nextcloud-n40   # bascule l’actif
./scripts/setup.sh --list
./scripts/setup.sh --delete old-setup --force
```

Le wizard propose aussi « Sauvegarder ce setup sous un nom ? » à la fin. Champ optionnel `setup_name` dans `config.toml`.

## Affichage

### Mode de rendu — `display.render_mode`

| Valeur | Effet |
|---|---|
| `native` | Canvas 64×64, police bitmap, barres/camembert en pixels entiers (net) |
| `scaled` | Canvas 2× + fonts TrueType puis réduction LANCZOS (plus doux) |

Choix dans le setup (IP / refresh / display).

### Écrans personnalisés + pie/barre par mesure

Dans le setup, après les métriques du profil :

1. **Organiser en écrans** — cocher les métriques pour l’écran 1, puis « Ajouter un écran supplémentaire ? »
2. **Titre** — par défaut (dérivé des métriques) ou personnalisé
3. **Style par mesure %** — barre (jauge) ou camembert (pie) pour CPU, RAM, Swap, Disque, NC disk, php-fpm

```toml
[[screens]]
id = "s1"
title = "Charge"
title_default = false
metrics = ["cpu", "load_avg"]
styles = { cpu = "pie" }

[[screens]]
id = "s2"
title = ""
title_default = true
metrics = ["disk", "ram"]
styles = { disk = "pie", ram = "bar" }
```

Sans écrans custom, `[metric_styles]` permet pie/barre par mesure ; `display.disk_style` reste un défaut legacy.

### Historique / sparklines — `[history]`

Par métrique numérique : page `hist_<metric>` (colonnes = moyennes de buckets sur la fenêtre).

```toml
[history]
default_period = "15m"
buckets = 56

[history.metrics.cpu]
enabled = true
period = "15m"

[history.metrics.disk]
enabled = true
period = "7j"
```

**Unités de durée :** `s` secondes · `m` minutes · `h` heures · `j` jours · `M` mois (~30j) · `a` années (~365j).  
Ex. `45s`, `30m`, `2h`, `7j`, `1M`, `1a` (nombre seul = minutes).  
Données : `data/history/<metric>.json`. Barre cyan→verte = progression jusqu’à fenêtre pleine.

## Multi-setup / wizard

`./scripts/setup.sh` :

1. Menu : wizard / charger / sauver / lister / supprimer
2. Wizard : profils + métriques, écrans (titre + pie/barre), rendu, historique (durée s/m/h/j/M/a)
3. Relancer sans effacer les autres profils

## Configuration (`config.toml`)

Voir `config.example.toml`. Extrait :

```toml
active_profiles = ["status", "n40"]
setup_name = "lab-n40"

[display]
render_mode = "native"

[history]
default_period = "15m"
buckets = 56

[history.metrics.cpu]
enabled = true
period = "30m"
```

## Automation — `./scripts/cron-setup.sh`

- **Debian** : `systemd --user` (daemon continu)
- **Fallback** : crontab (`--once`)
- Sans args : menu interactif

```bash
./scripts/cron-setup.sh enable --systemd
./scripts/cron-setup.sh status
```

## Scripts

| Script | Sans args | `--help` |
|---|---|---|
| `install.sh` | Confirme plateforme / extras | oui |
| `setup.sh` | Menu setups + wizard | oui |
| `test.sh` | Profil / Pixoo / dossier PNG | oui |
| `run.sh` | Profil / once / IP | oui |
| `cron-setup.sh` | Menu enable/disable/… | oui |
| `studio.sh` | Pixoo Studio (GUI pro) | oui |
| `designer.sh` | Shim → Studio | oui |

## Structure

```
monitoring_pixoo64/
├── config.example.toml / config.toml
├── configs/setups/          # setups nommés
├── data/history/            # ring buffers JSON
├── assets/test_preview/     # PNG dry-run
├── scripts/
└── src/pixoo_monitor/
    ├── display.py           # native/scaled, pie, sparklines
    ├── history.py
    ├── setups.py
    ├── setup.py
    └── …
```

## Dépannage

| Problème | Piste |
|---|---|
| Texte flou | `render_mode = "native"` dans setup |
| Services `?` sous macOS | Normal — pas de systemd |
| Pixoo injoignable | Même Wi‑Fi, `./scripts/test.sh` puis `--pixoo` |
| Graphe vide au début | Normal — barre de progression jusqu’à fenêtre pleine |

## Licence

Usage personnel / labo. Push via API HTTP Divoom (`http://<ip>/post`).
