# Pixoo / Merlin monitor (V4)

Dashboard **Divoom Pixoo 64** (RGB) alimenté par un exporteur HTTP + bridge
sur Asuswrt-Merlin. Le firmware MicroPython sous `firmware/` est pour un
**Pico W + SSD1306** optionnel — il n’allume **jamais** un Pixoo.

```
Mac ──deploy_monitor.sh auto──► Merlin 192.168.50.1
                                  ├─ metrics_server :8088 /metrics.json
                                  └─ pixoo_bridge ──HTTP /post──► Pixoo 192.168.52.4
```

**Cause classique d’écran noir :** `auto` déployait seulement `/metrics.json`
sans démarrer le bridge. Corrigé : l’install démarre **les deux** daemons
sur le routeur (Entware `python3` + `python3-pillow`, `cru` + watchdog).

## Hôtes

| Variable | Rôle | Exemple |
|----------|------|---------|
| `PICO_ROUTER_HOST` | Merlin — SSH + metrics + bridge | `192.168.50.1` |
| `PIXOO_IP` | Divoom Pixoo — push RGB | `192.168.52.4` |
| `PICO_MERLIN_HOST` | Pico W OLED (optionnel, ping) | autre IP |

`/jffs/addons/pico_monitor` survit à une réinstall Entware.

## Install automatique

```bash
cd pico_monitor
chmod +x deploy_monitor.sh merlin/*.sh pixoo_bridge/run.sh
cp -n .deploy.env.example .deploy.env   # PIXOO_IP=192.168.52.4
./deploy_monitor.sh auto                # metrics + bridge ON Merlin
./deploy_monitor.sh status
```

Après `auto`, le Pixoo doit afficher la bannière puis les 6 écrans.
Si les métriques sont down, le bridge bascule en **demo** (écran non vide).

Rendu : `./deploy_monitor.sh visual` — mono/poly, blink, luminosité, temps/écran,
unités, sélection d’écrans. 10 écrans dont **Clients**, **Load** (CPU/RAM),
**WiFi/LAN**. Voir `pixoo_bridge/README.md`.

## Logs (routeur → Mac)

Sur Merlin (persistants jffs) :
- `/jffs/addons/pico_monitor/logs/pixoo_bridge.log`
- `/jffs/addons/pico_monitor/logs/pico_metrics.log`
- miroir : `/tmp/pixoo_bridge.log`

```bash
./deploy_monitor.sh logs     # → pico_monitor/logs/<timestamp>/ + latest/
# menu : « Récupérer logs → local »
```

## Commandes utiles

```bash
./deploy_monitor.sh install|start|stop|status|test|logs
./deploy_monitor.sh pilot    # sous-menu distant
# Mac only (debug) :
./pixoo_bridge/run.sh --demo
./pixoo_bridge/run.sh --once
```

## Arborescence déployée

```
/jffs/addons/pico_monitor/
├── metrics_server.py  watchdog.sh  install.sh …
├── pixoo_bridge/      # package Python push RGB
├── run/               # *.pid
└── logs/              # pixoo_bridge.log, pico_metrics.log
```
