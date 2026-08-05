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
| `PIXOO_COLOR_MODE` / `--color-mode` | `mono` | `mono` = B/W pixel text; `poly` = color palette |
| `PIXOO_TEXT_SCROLL` / `--text-scroll` | `1` | Scroll titles/labels longer than the 64px width |

Screens use 5×7 pixel fonts (no antialias). Titles: System, Traffic, Top, Temps, Disk Space, Services.

## Probe

```bash
curl -s -X POST http://192.168.52.4/post \
  -H 'Content-Type: application/json' \
  -d '{"Command":"Device/GetDeviceTime"}'
# Pixoo → {"error_code":0,"UTCTime":...}
```
