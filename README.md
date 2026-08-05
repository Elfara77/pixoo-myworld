# monitoring_pixoo64

Moniteur de métriques AsusWRT-Merlin pour Pico W + OLED SSD1306 64×64, avec exporteur HTTP installé sur le routeur.

| Package | Cible | Doc |
|---|---|---|
| [`pico_monitor/`](pico_monitor/) | Pico W + OLED SSD1306 64×64 (+ exporteur HTTP Merlin) | [pico_monitor/README.md](pico_monitor/README.md) |

## Démarrage rapide

```bash
cd pico_monitor
./deploy_monitor.sh          # menu install / status / uninstall
# puis flasher firmware/ sur le Pico (voir README du package)
```

L’ancien moniteur Mac (`src/pixoo_monitor/`, Pipenv, `scripts/`) et la pile Pixoo sur Merlin (`asus_merlin/`) ont été retirés ; le livrable actif est `pico_monitor/`.
