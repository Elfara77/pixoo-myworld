# pixoo_bridge — Merlin → Divoom Pixoo 64

**Pixoo ≠ Pico.**

| Device | How it gets pixels | Code |
|--------|-------------------|------|
| **Divoom Pixoo 64** | Merlin (or Mac) **HTTP push** RGB to `http://IP/post` | **this package** |
| **Pico W + SSD1306** | MicroPython firmware, I2C OLED, pulls `/metrics.json` | `../firmware/` |

Production path: **daemon on Merlin** started by `../deploy_monitor.sh auto`
(watchdog + `cru`). Mac `run.sh` is for debug only.

## Merlin (preferred)

```bash
cd ../
./deploy_monitor.sh auto     # uploads this package + starts bridge
./deploy_monitor.sh logs     # pull /jffs/.../logs/pixoo_bridge.log
```

On the router: `python3 -m pixoo_bridge` (via `watchdog.sh`), metrics from
`http://127.0.0.1:8088/metrics.json`, demo fallback if metrics fail.

## Mac debug

```bash
cd pico_monitor
./pixoo_bridge/run.sh --demo
./pixoo_bridge/run.sh --once
./pixoo_bridge/run.sh --color-mode poly   # full color palette
./pixoo_bridge/run.sh --color-mode mono   # default: sharp B/W pixel text
```

## Render options

| Env / flag | Default | Meaning |
|------------|---------|---------|
| `PIXOO_COLOR_MODE` / `--color-mode` | `mono` | `mono` = all **text** one solid color; `poly` = colored labels. Gauges/graphs stay colored either way. |
| `PIXOO_TEXT_SCROLL` / `--text-scroll` | `1` | Scroll titles/labels longer than the 64px width |
| `PIXOO_ALERT_BLINK` / `--alert-blink` | `1` | Blink critical text/gauge fills (CPU/RAM≥90, temps, disk≥90, WAN off) |
| `PIXOO_BLINK_PERIOD` / `--blink-period` | `0.55` | Half-cycle seconds (~1 Hz full blink with default frame interval) |
| `PIXOO_RATE_STYLE` / `--rate-style` | `short` | `short`=K/M/G · `long`=Kb/s\|Mb/s\|Gb/s |
| `PIXOO_SCREEN_SECONDS` / `--screen-seconds` | `8` | Temps de base par écran (rotation) |
| `PIXOO_HEAVY_SCREEN_DWELL` / `--heavy-screen-dwell` | `1` | `1` = LOD/TMP/GRP/WLC/TOP/CLI restent ×2 plus longtemps ; `0` = même durée pour tous |
| `PIXOO_HEAVY_SCREEN_MULTIPLIER` / `--heavy-screen-multiplier` | `2` | Multiplicateur sur les écrans « lourds » (graphes, listes) |
| `PIXOO_WLC_GRAPH_MODE` / `--wlc-graph-mode` | `overlay` | GRP WAN + WiFi/Eth : `overlay` = down+up même graphe ; `split` = down à gauche, up à droite |
| `PIXOO_FRAME_INTERVAL` / `--frame-interval` | `1.05` | Intervalle minimum entre pushes HTTP |
| `PIXOO_BRIGHTNESS` / `--brightness` | `50` | Luminosité Pixoo 0–100 |
| `PIXOO_SCREENS` / `--screens` | `all` | `all` = défauts **sans SUM**. Optionnel : `SUM` (résumé santé, sans bannière), seul ou mélangé (`all,SUM` / `SUM,SYS,…`). Pastille position si >1 écran (sauf SUM qui n’a pas de bannière). |

Ordre logique défaut : System → Load → Temps → Traffic → WiFi/LAN → Top → Clients → Ports → Disk → Services. **SUM** = écran résumé HP% (CPU/RAM/TMP/DSK + trafic + clients + ports), non inclus dans `all`.

## Probe

```bash
curl -s -X POST http://192.168.52.4/post \
  -H 'Content-Type: application/json' \
  -d '{"Command":"Device/GetDeviceTime"}'
# Pixoo → {"error_code":0,"UTCTime":...}
```
