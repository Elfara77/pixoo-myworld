# monitoring_pixoo64

Deux cibles **distinctes** (ne pas les mélanger) :

| Cible | IP typique | Comment ça affiche | Package |
|-------|------------|--------------------|---------|
| **Divoom Pixoo 64** | `192.168.52.4` (HTTP `:80/post`) | Push RGB depuis le Mac / Merlin | [`pico_monitor/pixoo_bridge/`](pico_monitor/pixoo_bridge/) |
| **Pico W + SSD1306** | autre IP LAN | Firmware MicroPython flasché, I2C OLED | [`pico_monitor/firmware/`](pico_monitor/firmware/) |

L’exporteur Merlin (`:8088/metrics.json`) alimente les deux.

## Voir une image **maintenant** (Pixoo)

Si `curl` sur `/post` répond `error_code: 0`, c’est un **Pixoo** — pas un Pico :

```bash
cd pico_monitor
./pixoo_bridge/run.sh --demo    # image immédiate
./deploy_monitor.sh start       # metrics Merlin (pour le mode live)
./pixoo_bridge/run.sh           # live
```

## Pico OLED

```bash
cd pico_monitor
./deploy_monitor.sh             # Merlin metrics
# puis flasher firmware/ sur le Pico (Thonny / mpremote)
```

Détails : [pico_monitor/README.md](pico_monitor/README.md).
