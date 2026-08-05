# monitoring_pixoo64

Deux livrables actifs pour afficher des métriques AsusWRT-Merlin :

| Package | Cible | Doc |
|---|---|---|
| [`asus_merlin/`](asus_merlin/) | Pixoo 64 (rendu sur le routeur) | [asus_merlin/README.md](asus_merlin/README.md) |
| [`pico_monitor/`](pico_monitor/) | Pico W + OLED SSD1306 64×64 (+ exporteur HTTP Merlin) | [pico_monitor/README.md](pico_monitor/README.md) |

## Démarrage rapide

**Pixoo sur Merlin**

```bash
cd asus_merlin
./upload_to_merlin.sh --install
```

**Pico W + exporteur métriques**

```bash
cd pico_monitor
./deploy_monitor.sh          # menu install / status / uninstall
# puis flasher firmware/ sur le Pico (voir README du package)
```

L’ancien moniteur Mac (`src/pixoo_monitor/`, Pipenv, `scripts/`) a été retiré ; il est remplacé par les packages ci-dessus.
