# Pico W + SSD1306 64×64 — Merlin monitor (V4)

Dashboard OLED 1-bit (6 écrans) alimenté par un **exporteur HTTP** sur Asuswrt-Merlin.

```
Mac/Linux ──deploy_monitor.sh──► Merlin :8088 /metrics.json
Pico W     ──Wi‑Fi + urequests──► Merlin :8088 /metrics.json
Pico W     ──I2C────────────────► SSD1306 64×64
```

`/jffs/addons/pico_monitor` est préféré à `/opt` (même pattern que `asus_merlin/`) : survit à une réinstall Entware.

## Arborescence

```
pico_monitor/
├── deploy_monitor.sh      # menu interactif + install|uninstall|status
├── install.sh / uninstall.sh
├── README.md
├── .deploy.env.example
├── firmware/              # à flasher sur le Pico W
│   ├── boot.py main.py config.py
│   ├── router_client.py display.py screens.py icons.py
│   └── lib/ssd1306.py fonts.py
└── merlin/                # déployé sur le routeur
    ├── metrics_server.py run.sh watchdog.sh
    └── config.example.env
```

## Déployer le serveur métriques (Merlin)

Prérequis : SSH clé (`ssh-copy-id elphara77@192.168.50.1`), Entware (`opkg`).

```bash
cd pico_monitor
chmod +x deploy_monitor.sh install.sh uninstall.sh merlin/*.sh
./deploy_monitor.sh                 # menu
# ou non-interactif :
./deploy_monitor.sh install
./deploy_monitor.sh status
./deploy_monitor.sh uninstall
```

Config sauvée dans `pico_monitor/.deploy.env` et `~/.pico_monitor_config` (**sans mot de passe**).

Auth mot de passe optionnelle : `PICO_SSH_AUTH=password` (+ `sshpass`).

Test rapide :
```bash
curl -s http://192.168.50.1:8088/metrics.json | head
```

Contrôle sur le routeur :
```bash
/jffs/addons/pico_monitor/watchdog.sh status|reload|stop
```

## Flasher le Pico W

1. Copier `firmware/*` sur le Pico (Thonny / `mpremote cp -r firmware/ :`).
2. Éditer `firmware/config.py` :
   - `WIFI_SSID` / `WIFI_PASSWORD`
   - `ROUTER_HOST=192.168.50.1`
   - `ROUTER_PORT=8088`
   - `DEMO=0` (mettre `1` pour tester l’UI sans réseau)
3. Soft-reset → `boot.py` (Wi‑Fi + OLED) puis `main.py` (fetch 3s, écrans 4s).

Broches I2C par défaut : SCL=GP5, SDA=GP4, addr `0x3C`.

## Écrans

| # | Code | Contenu |
|---|------|---------|
| 1 | SYS | Uptime, CPU/RAM jauges, clients, débits |
| 2 | GRP | Graphes DOWN/UP (64 pts) |
| 3 | DL:UL | Top 2 download / upload |
| 4 | TMP | Grille températures |
| 5 | PIE | JFFS / USB / RAM cache |
| 6 | SRV | VPN toggles + jauges disque |

## Lien avec `asus_merlin/`

Sémantique proche de `pixoo_merlin/metrics.py` (WAN bytes, `wl` temps/clients, df jffs/usb).  
Le serveur Pico **rate-limite** les samples (`PICO_SAMPLE_MIN_S`) pour éviter de saturier le routeur.
