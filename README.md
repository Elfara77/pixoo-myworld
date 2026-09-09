# monitoring_pixoo64

Deux cibles **distinctes** (ne pas les mélanger) :

| Cible | IP typique | Comment ça affiche | Package |
|-------|------------|--------------------|---------|
| **Divoom Pixoo 64** | `192.168.52.4` (HTTP `:80/post`) | Push RGB depuis le Mac / Merlin | [`pico_monitor/pixoo_bridge/`](pico_monitor/pixoo_bridge/) |
| **Pico W + SSD1306** | autre IP LAN | Firmware MicroPython flasché, I2C OLED | [`pico_monitor/firmware/`](pico_monitor/firmware/) |

L’exporteur Merlin (`:8088/metrics.json`) alimente les deux.

## Quickstart & Menu d'installation / configuration

Lancer la console principale d'installation, configuration et exécution :

```bash
./scripts/setup.sh
```

Ou utiliser les scripts dédiés :

```bash
./scripts/setup.sh        # Menu interactif principal (Studio, Designer, Monitor, Deploy)
./scripts/pixoo.sh        # CLI unifiée (studio | daemon | render | version)
./scripts/studio.sh       # Pixoo Studio GUI (engine + canvas)
./scripts/designer.sh     # Pixoo Designer GUI
./scripts/cron-setup.sh   # Automation arrière-plan
```

Tous les scripts supportent **`-h` / `--help`**.

### Architecture Studio + Engine

Deux couches sous `src/pixoo/` : **engine** headless (render + FastAPI + envoi Pixoo) et **studio** PySide6 (édition WYSIWYG, sync HTTP).

```bash
./scripts/pixoo.sh version
./scripts/pixoo.sh studio -p projects/demo_v2.pixoo
./scripts/pixoo.sh daemon -p projects/demo_v2.pixoo --pixoo-ip 192.168.52.4
./scripts/pixoo.sh render -p projects/demo_v2.pixoo -o /tmp/pixoo.png
```

Docs : [ARCHITECTURE.md](docs/ARCHITECTURE.md) · [API.md](docs/API.md) · [PLUGINS.md](docs/PLUGINS.md) · [SOURCES.md](docs/SOURCES.md) · [TEMPLATES.md](docs/TEMPLATES.md) · [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) · [STUDIO.md](docs/STUDIO.md).

Plugins externes : REST, scraper, MQTT, WebSocket, DB, weather/crypto/calendar/stock — secrets via `.env` (`${ENV:NAME}`).

## Pico OLED & Bridge Pixoo sur Merlin

```bash
cd pico_monitor
./deploy_monitor.sh             # Déploiement interactif Merlin metrics & Pixoo bridge
# puis flasher firmware/ sur le Pico (Thonny / mpremote)
```

Détails : [pico_monitor/README.md](pico_monitor/README.md).

## Profils (Pixoo Monitor)

| Profil | Rôle |
|---|---|
| `system` | Hôte générique (CPU, RAM, disque, réseau…) |
| `priority` | Priorité haute Nextcloud : disque data, services, php-fpm, DB, Redis |
| `nextcloud_files` | Files : data dir, `/status.php`, cron, erreurs log, montages |
| `n40` | Matériel N40 : CPU / RAM / swap / temp / net / load (vue thermique) |
| `status` | Santé globale OK/WARN/DOWN |
| `nextcloud_full` | Combo priority + files + N40 + status |

## Affichage & Performance

### Mode de rendu — `display.render_mode`

| Valeur | Effet |
|---|---|
| `native` | Canvas 64×64, police bitmap, barres/camembert en pixels entiers (net) |
| `scaled` | Canvas 2× + fonts TrueType puis réduction LANCZOS (plus doux) |

Choix dans la configuration (`config.toml`).

## Structure du projet

```
monitoring_pixoo64/
├── config.example.toml / config.toml
├── configs/setups/          # setups nommés
├── data/history/            # ring buffers JSON
├── assets/                  # ressources graphiques
├── scripts/                 # scripts CLI et setup
├── pico_monitor/            # exporter Merlin, Pixoo bridge et firmware Pico W
└── src/                     # pixoo (engine & studio), pixoo_designer, pixoo_monitor
```

## Licence

Usage personnel / labo. Push via API HTTP Divoom (`http://<ip>/post`).
