# Asus Merlin → Pixoo 64

Affiche en permanence les métriques du routeur **AsusWRT-Merlin** sur un **Divoom Pixoo 64** (64×64), avec écrans rotatifs, animations et **setups nommés** (YAML).

---

## Prérequis routeur

1. Firmware **AsusWRT-Merlin**
2. **Entware** installé (`opkg` disponible) — [guide Entware](https://github.com/Entware/Entware/wiki/Install-on-Asus-stock-firmware)
3. Accès SSH (utilisateur `admin` ou compte custom)
4. Partition **/jffs** activée
5. Pixoo 64 joignable en HTTP sur le LAN (`http://<PIXOO_IP>/post`)

> Le paquet Entware s’appelle **`python3`**, pas `python` (`opkg install python` échoue).
>
> Entware place `opkg` / `python3` sous **`/opt/bin`**. Les scripts exportent ce PATH (et sourcent `/opt/etc/profile` si présent) car un SSH non interactif ne charge souvent pas le profil Entware.

Paquets installés automatiquement par `install.sh` :

```sh
opkg update
opkg install python3 python3-pillow python3-yaml
```

| Paquet | Rôle |
|--------|------|
| `python3` | runtime (stdlib / urllib) |
| `python3-pillow` | rendu des frames |
| `python3-yaml` | fichiers de setup |

---

## Quoi copier sur le routeur

Tout le dossier `asus_merlin/` (ce répertoire), ou au minimum :

```
pixoo_merlin/          # package Python
setups/                # default.yaml, setup2.yaml, …
install.sh
uninstall.sh
run.sh
watchdog.sh
config.example.env
README.md
```

Cible recommandée après install : **`/jffs/addons/pixoo_merlin/`**.

### Depuis le Mac (recommandé)

```bash
cd asus_merlin

# Variables (optionnel)
export MERLIN_HOST=192.168.1.1          # IP / hostname du routeur
export MERLIN_USER=admin                # ou elphara77, etc.
export MERLIN_PATH=/jffs/addons/pixoo_merlin

./upload_to_merlin.sh                   # upload seul
./upload_to_merlin.sh --install         # upload + lance install.sh via SSH
./upload_to_merlin.sh --install --host 192.168.50.1 --user elphara77
```

Le script utilise `rsync` si dispo, sinon `scp`. Voir `./upload_to_merlin.sh --help`.

### À la main (scp)

```bash
scp -r asus_merlin admin@192.168.1.1:/tmp/asus_merlin
ssh admin@192.168.1.1
cd /tmp/asus_merlin && chmod +x *.sh && ./install.sh
```

---

## Installation sur le routeur

Sur le routeur (SSH) :

```sh
cd /tmp/asus_merlin    # ou le dossier uploadé
chmod +x install.sh run.sh watchdog.sh uninstall.sh
./install.sh
```

`install.sh` fait dans l’ordre :

1. `opkg update`
2. `opkg install python3 python3-pillow python3-yaml`
3. Copie l’app sous `/jffs/addons/pixoo_merlin/`
4. Crée `config.env` depuis `config.example.env` si absent
5. Enregistre le watchdog **cru** `PixooMerlin` (toutes les minutes)
6. Ajoute une ligne dans `/jffs/scripts/services-start` (démarrage au boot)
7. Lance le daemon avec **`python3 -m pixoo_merlin run`**

---

## Configuration

Fichier : `/jffs/addons/pixoo_merlin/config.env`

```sh
vi /jffs/addons/pixoo_merlin/config.env
```

| Variable | Exemple | Description |
|----------|---------|-------------|
| `PIXOO_IP` | `192.168.1.50` | **Obligatoire** — IP du Pixoo 64 |
| `SETUP` | `default` | Nom du setup YAML (`setups/<nom>.yaml`) |
| `BRIGHTNESS` | `40` | Luminosité Pixoo 0–100 |
| `SCREEN_SECONDS` | `8` | Durée d’affichage par écran |
| `FRAME_INTERVAL` | `1.05` | Intervalle entre pushes (≥ 1 s) |
| `WAN_IFACE` | *(vide)* | Auto via `nvram` ; sinon forcer (`eth0`, …) |
| `PING_HOST` | `1.1.1.1` | Test « Internet OK » |
| `HISTORY_SECONDS` | `300` | Historique graphe D/U (secondes) |
| `STATS_SECONDS` | `3600` | Fenêtre min/max (défaut 1 h) |
| `TOP_CLIENTS` | `5` | Nb de top downloaders |
| `MARQUEE_SPEED` | `36` | Vitesse du défilement IP WAN |
| `DEMO` | `0` | `1` = métriques fictives (tests) |

Après édition :

```sh
/jffs/addons/pixoo_merlin/watchdog.sh
# ou tuer le pid puis relancer — le cru repartira tout seul
```

---

## Setups nommés

Les layouts sont des fichiers YAML dans `setups/` :

### `default` — layout complet (5 écrans)

1. **overview** — titre, nb clients (chiffre seul, liste Merlin/NMP), jauges `RAM`/`CPU` + temp `NN°C`  
2. **bandwidth** — `D` haut-gauche, `U` bas-droite, graphe au milieu  
3. **status** — online/offline, IP WAN (marquee rapide), USB2/USB3, `LAN1234` (LAN en cyan titre)  
4. **top_dl** — top clients en download (`1.iPhone…`, `2.Raph-Phone`…)  
5. **hour_stats** — min/max D/U, CPU, temp, RAM sur `STATS_SECONDS` (défaut 1 h)  

### `setup2` — écran overview seul

Copie de `default` avec les autres écrans en `enabled: false`.

### Créer / dériver un setup

Sur le routeur :

```sh
cd /jffs/addons/pixoo_merlin
./run.sh list-setups
./run.sh show-setup default

# Copier default → mon_salon
./run.sh copy-setup default mon_salon

# Ne garder que l’écran overview
./run.sh screen disable mon_salon bandwidth
./run.sh screen disable mon_salon status

# Activer ce setup
./run.sh use mon_salon
# → écrit SETUP=mon_salon dans config.env

# Widgets (ex. retirer la température)
./run.sh widget disable mon_salon overview temp
```

Ou éditer directement `setups/mon_salon.yaml` :

```yaml
setup:
  title: Asus Merlin
  screen_seconds: 8.0
screens:
  - id: overview
    enabled: true
    widgets: [title, clients, ram, cpu, temp]
```

Widgets : `title`, `clients`, `wan_rate`, `cpu`, `temp`, `ram`, `wan_graph`, `internet`, `usb`, `ethernet`, `wan_ip`, `uptime`, `top_clients`, `hour_stats`.

---

## Lancer / daemon / cron / uninstall

### Manuel (premier plan)

```sh
/jffs/addons/pixoo_merlin/run.sh run
# ou
cd /jffs/addons/pixoo_merlin && python3 -m pixoo_merlin run
```

### Daemon (permanent)

```sh
/jffs/addons/pixoo_merlin/watchdog.sh
```

- PID : `run/merlin.pid`
- Logs : `logs/merlin.log`

### Cron Merlin (`cru`)

Installé comme job `PixooMerlin` :

```text
*/1 * * * * /jffs/addons/pixoo_merlin/watchdog.sh
```

Vérifier : `cru l`

Au boot : ligne dans `/jffs/scripts/services-start`.

### Désinstallation

```sh
# Sur le routeur uniquement — ne jamais lancer ./uninstall.sh depuis le clone Mac
/jffs/addons/pixoo_merlin/uninstall.sh
# ou depuis le Mac :
# ssh elphara77@192.168.50.1 /jffs/addons/pixoo_merlin/uninstall.sh
```

> **Attention :** `uninstall.sh` ne doit tourner **que sur Merlin**. Il refuse de s’exécuter sans `/jffs` et ne supprime que des chemins sous `/jffs/…` (un ancien bug prenait le dossier du script et pouvait effacer le clone local).

Retire le daemon, le job **cru**, le hook `services-start`, puis **supprime entièrement** `/jffs/addons/pixoo_merlin/` (scripts, `pixoo_merlin/`, `setups/`, logs, …).  
Une copie de `config.env` est aussi sauvée sous `/tmp/pixoo_merlin.config.env.bak`.  
**Laisse** les paquets opkg par défaut.

Options :

```sh
# Garder uniquement config.env dans le dossier addon
KEEP_CONFIG=1 /jffs/addons/pixoo_merlin/uninstall.sh

# Aussi désinstaller python3 / pillow / yaml
UNINSTALL_OPKG=1 /jffs/addons/pixoo_merlin/uninstall.sh

# Ne pas supprimer les fichiers (cru + daemon seulement)
REMOVE_FILES=0 /jffs/addons/pixoo_merlin/uninstall.sh
```

---

## Demo desktop (Mac)

Sans routeur — génère des PNG de prévisualisation :

```bash
cd asus_merlin
# depuis la racine du repo si .venv existe :
../.venv/bin/pip install pyyaml pillow   # une fois
../.venv/bin/python -m pixoo_merlin --demo
# → asus_merlin/previews/*.png
```

Sur le routeur, les deps viennent **uniquement** de `opkg` (pas pip).

---

## Dépannage rapide

| Problème | Piste |
|----------|--------|
| `opkg not found` | Entware manquant, ou PATH sans `/opt/bin` — les scripts le fixent ; vérifier `ls /opt/bin/opkg` |
| `python: not found` | Utiliser **`python3`** ; relancer `install.sh` |
| `No module named PIL` | `opkg install python3-pillow` |
| `No module named yaml` | `opkg install python3-yaml` |
| Pixoo noir / erreur push | Vérifier `PIXOO_IP`, ping, firewall LAN |
| Daemon mort | `tail -f logs/merlin.log` puis `./watchdog.sh` |
| Métriques à 0 | Attendre 1–2 samples ; vérifier `WAN_IFACE` / `nvram get wan0_ifname` |
