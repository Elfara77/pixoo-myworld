# Pico W + SSD1306 64×64 — Merlin monitor (V4)

Dashboard OLED 1-bit (6 écrans) alimenté par un **exporteur HTTP** sur Asuswrt-Merlin.

> **Pixoo ≠ Pico.** Un Divoom Pixoo 64 (souvent `192.168.52.4`, HTTP `/post`)
> n’affiche **jamais** le firmware MicroPython. Pour le Pixoo, utiliser
> [`pixoo_bridge/`](pixoo_bridge/) (push RGB, héritage `asus_merlin`).

```
Mac/Linux ──deploy_monitor.sh──► Merlin 192.168.50.1:8088 /metrics.json
Pico W (autre IP) ──Wi‑Fi──► Merlin 192.168.50.1:8088 /metrics.json
Pico W               ──I2C───► SSD1306 64×64

Mac ──pixoo_bridge──► Pixoo 192.168.52.4 /post   (RGB, pas le firmware)
```

**Merlin metrics ≠ OLED.** Si `/metrics.json` répond mais l’écran reste noir, le Pico n’a pas le firmware / Wi‑Fi / I2C corrects. Flasher `firmware/`.

## Deux hôtes distincts

| Variable | Rôle | Exemple |
|----------|------|---------|
| `PICO_ROUTER_HOST` | Merlin — SSH deploy + HTTP metrics | `192.168.50.1` |
| `PICO_MERLIN_HOST` | Pico W — ping (pas le Pixoo) | `192.168.52.10` |
| `PIXOO_IP` | Divoom Pixoo — `pixoo_bridge` | `192.168.52.4` |
| `firmware/config.py` → `ROUTER_HOST` | IP Merlin vue depuis le Pico | `192.168.50.1` |

Ne pas mettre l’IP du Pico dans `ROUTER_HOST`. Si `192.168.52.4` répond à l’API Pixoo, c’est `PIXOO_IP`, pas un Pico.

`/jffs/addons/pico_monitor` est préféré à `/opt` (survit à une réinstall Entware).

## Arborescence

```
pico_monitor/
├── deploy_monitor.sh      # menu ↑/↓ + auto|install|pilot|start|stop|cron-*
├── preview.py             # rendu Mac des écrans OLED → previews/*.png
├── pixoo_bridge/          # Merlin → Pixoo 64 (HTTP RGB) — si vous avez un Pixoo
├── firmware/              # à flasher sur le Pico W (+ SSD1306)
└── merlin/                # déployé sur le routeur
    ├── metrics_server.py run.sh watchdog.sh
    ├── install.sh uninstall.sh
    └── config.example.env
```

### Pixoo (écran 64×64 couleur)

```bash
./pixoo_bridge/run.sh --demo     # image immédiate
./pixoo_bridge/run.sh            # live depuis :8088/metrics.json
```

## Déployer le serveur métriques (Merlin)

Prérequis : SSH clé vers le **routeur** (`ssh-copy-id elphara77@192.168.50.1`), Entware (`opkg`).

```bash
cd pico_monitor
chmod +x deploy_monitor.sh install.sh uninstall.sh merlin/*.sh
cp -n .deploy.env.example .deploy.env   # éditer si besoin
./deploy_monitor.sh                 # menu interactif (↑/↓ + ENTER)
./deploy_monitor.sh auto            # pipeline complet
./deploy_monitor.sh install
./deploy_monitor.sh status          # cru + metrics + ping Pico
./deploy_monitor.sh pilot           # sous-menu pilotage distant
./deploy_monitor.sh start|stop|cron-on|cron-off
```

### Menu interactif

- Écran effacé à chaque affichage ; statut live (SSH, upload, install, running, cru, metrics HTTP, ping Pico).
- Navigation **↑/↓** + **ENTER** (surlignage + ligne `Selected ▸ …`). Numéros `1-9` pour sauter ; sinon menu numérique si le mode raw échoue.
- Premier item : **Mode automatique** — uninstall → clean → upload → install → flash Pico → start watchdog.
- **Pilotage distant** : sous-menu (même UX) pour start/stop watchdog, cron ON/OFF (`cru a|d PicoMonitor`), état détaillé, test link Pico (`PICO_MERLIN_HOST`), test `/metrics.json` Merlin.

CLI : `install|uninstall|status|upload|test|flash|auto|pilot|start|stop|cron-on|cron-off`.

`.deploy.env` / `~/.pico_monitor_config` (sans mot de passe) :

```
PICO_ROUTER_HOST=192.168.50.1
PICO_MERLIN_HOST=192.168.52.10   # Pico W (pas le Pixoo)
PIXOO_IP=192.168.52.4            # Divoom Pixoo → pixoo_bridge
```

Test metrics (Merlin) :
```bash
curl -s http://192.168.50.1:8088/metrics.json | head
```

## Flasher le Pico W

Via le menu (**Flash Pico firmware**) / `./deploy_monitor.sh flash` : tente `mpremote` si présent, sinon affiche les étapes Thonny/manuelles.

1. Copier `firmware/*` sur le Pico (Thonny / `mpremote cp -r firmware/. :`).
2. Éditer `firmware/config.py` :
   - `WIFI_SSID` / `WIFI_PASSWORD`
   - `ROUTER_HOST=192.168.50.1`  ← Merlin, pas l’IP du Pico
   - `ROUTER_PORT=8088`
   - `DEMO=0` (`1` = UI sans réseau)
3. Soft-reset → damier + `BOOT` **avant** le Wi‑Fi, puis `WIFI OK|FAIL` / `ROUTER OFFLINE`.
4. IP LAN du Pico : `PICO_MERLIN_HOST` (souvent **autre** que le Pixoo `192.168.52.4`).

Broches I2C : SCL=GP5, SDA=GP4, addr `0x3C` (fallback SoftI2C + `0x3D`).

### Preview sans hardware

```bash
cd pico_monitor && python3 preview.py
open previews/01_sys.png
```

## Écrans

| # | Code | Contenu |
|---|------|---------|
| 1 | SYS | Uptime, CPU/RAM, clients, débits |
| 2 | GRP | Graphes DOWN/UP |
| 3 | DL:UL | Top download / upload |
| 4 | TMP | Températures |
| 5 | PIE | JFFS / USB / RAM cache |
| 6 | SRV | VPN + jauges disque |

## Exporteur Merlin

Les métriques sont exposées par `merlin/metrics_server.py` (kbps→Mbps, temps Wi‑Fi, etc.). Rate-limit via `PICO_SAMPLE_MIN_S`.
