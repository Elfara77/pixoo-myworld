# pixoo_bridge — Merlin → Divoom Pixoo 64

**Pixoo ≠ Pico.**

| Device | How it gets pixels | Code |
|--------|-------------------|------|
| **Divoom Pixoo 64** | Mac/Merlin **HTTP push** RGB to `http://IP/post` | **this package** |
| **Pico W + SSD1306** | MicroPython firmware, I2C OLED, pulls `/metrics.json` | `../firmware/` |

If `192.168.52.4` answers Pixoo API (`Device/GetDeviceTime`), flashing `firmware/` will never light it.

## Quick start (Mac → Pixoo)

```bash
cd pico_monitor
chmod +x pixoo_bridge/run.sh
# optional: add PIXOO_IP=192.168.52.4 to .deploy.env
./pixoo_bridge/run.sh --demo              # fake metrics, immediate image
./pixoo_bridge/run.sh --once              # boot banner only
./pixoo_bridge/run.sh                     # live metrics from Merlin :8088
```

Timing mirrors the old `asus_merlin` stack: ~8 s/screen, ≥1.05 s between HTTP frames.

## Prerequisites

1. Pixoo on LAN (default `192.168.52.4`).
2. For live data: Merlin exporter running (`./deploy_monitor.sh start` → `:8088/metrics.json`).
3. Python + Pillow (repo `.venv` already has it).

## Probe

```bash
curl -s -X POST http://192.168.52.4/post \
  -H 'Content-Type: application/json' \
  -d '{"Command":"Device/GetDeviceTime"}'
# Pixoo → {"error_code":0,"UTCTime":...}
# Pico / nothing → connection refused or non-JSON
```
