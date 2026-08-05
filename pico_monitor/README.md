# Pico W + SSD1306 64×64 — Merlin monitor (V4)

Dashboard OLED 1-bit (6 écrans) alimenté par un **exporteur HTTP** sur Asuswrt-Merlin.

```
Mac/Linux ──deploy_monitor.sh──► Merlin 192.168.50.1:8088 /metrics.json
Pico W 192.168.52.4 ──Wi‑Fi──► Merlin 192.168.50.1:8088 /metrics.json
Pico W               ──I2C───► SSD1306 64×64
```

**Merlin metrics ≠ OLED.** Si `/metrics.json` répond mais l’écran reste noir, le Pico n’a pas le firmware / Wi‑Fi / I2C corrects. Flasher `firmware/`.

## Deux hôtes distincts

| Variable | Rôle | Exemple |
|----------|------|---------|
| `PICO_ROUTER_HOST` | Merlin — SSH deploy + HTTP metrics | `192.168.50.1` |
| `PICO_MERLIN_HOST` | Pico W — ping / cible Wi‑Fi | `192.168.52.4` |
| `firmware/config.py` → `ROUTER_HOST` | IP Merlin vue depuis le Pico | `192.168.50.1` |

Ne pas mettre l’IP du Pico dans `ROUTER_HOST` (le Pico ne sert pas `/metrics.json`).

`/jffs/addons/pico_monitor` est préféré à `/opt` (survit à une réinstall Entware).

## Arborescence

```
pico_monitor/
├── deploy_monitor.sh      # menu + install|uninstall|status
├── preview.py             # rendu Mac des écrans → previews/*.png
├── firmware/              # à flasher sur le Pico W
└── merlin/                # déployé sur le routeur
    ├── metrics_server.py run.sh watchdog.sh
    ├── install.sh uninstall.sh
    └── config.example.env
```

## Déployer le serveur métriques (Merlin)

Prérequis : SSH clé vers le **routeur** (`ssh-copy-id elphara77@192.168.50.1`), Entware (`opkg`).

```bash
cd pico_monitor
chmod +x deploy_monitor.sh install.sh uninstall.sh merlin/*.sh
cp -n .deploy.env.example .deploy.env   # éditer si besoin
./deploy_monitor.sh                 # menu
./deploy_monitor.sh install
./deploy_monitor.sh status          # cru + metrics + ping Pico
```

`.deploy.env` / `~/.pico_monitor_config` (sans mot de passe) :

```
PICO_ROUTER_HOST=192.168.50.1
PICO_MERLIN_HOST=192.168.52.4
```

Test metrics (Merlin) :
```bash
curl -s http://192.168.50.1:8088/metrics.json | head
```

## Flasher le Pico W

1. Copier `firmware/*` sur le Pico (Thonny / `mpremote cp -r firmware/ :`).
2. Éditer `firmware/config.py` :
   - `WIFI_SSID` / `WIFI_PASSWORD`
   - `ROUTER_HOST=192.168.50.1`  ← Merlin, pas l’IP du Pico
   - `ROUTER_PORT=8088`
   - `DEMO=0` (`1` = UI sans réseau)
3. Soft-reset → bannières `PICO BOOT` / `WIFI OK|FAIL` / `ROUTER OFFLINE` si pas de metrics.
4. IP LAN attendue du Pico : **192.168.52.4** (`PICO_MERLIN_HOST`) — utile pour `ping` depuis le Mac.

Broches I2C : SCL=GP5, SDA=GP4, addr `0x3C`.

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

## Lien avec `asus_merlin/`

Sémantique proche de `pixoo_merlin/metrics.py`. Rate-limit via `PICO_SAMPLE_MIN_S`.
