# Pixoo 64 Designer

Application graphique (**PySide6**) pour composer, prévisualiser et pousser des dashboards **64×64** vers un Divoom Pixoo — sans passer par le wizard CLI.

## Lancer

```bash
./scripts/install.sh      # une fois (Pipenv + deps, dont PySide6)
./scripts/designer.sh     # UI
# ou:
pipenv run python -m pixoo_designer
```

## Fenêtre

| Zone | Rôle |
|---|---|
| **Menu / barre d’outils** | Nouveau, Ouvrir, Sauver, Zoom, Rafraîchir, Pousser → Pixoo |
| **Liste écrans** | Ajouter / dupliquer / supprimer des pages |
| **Liste éléments** | Texte, valeur, barre, camembert, sparkline, pastille, rectangle, pattern |
| **Aperçu** | Rendu pixel-perfect agrandi (nearest-neighbor ×6–×10) |
| **Inspecteur** | Titre, durée, couleurs, position, source, période graphe, seuils |
| **Onglet Sources** | Builtin psutil, commande shell + parse, HTTP, valeur static |

## Sources de données

Chaque valeur affichée est liée à une **source** :

| Type | Usage |
|---|---|
| `builtin` | `cpu`, `ram`, `swap`, `disk`, `load`, … |
| `command` | Shell (ex. `df -P / \| awk 'END{print $5}'`) |
| `http` | GET + parse du body |
| `static` | Valeur fixe pour maquetter |

**Parse du résultat :**

- `float` — premier nombre trouvé
- `percent` — nombre éventuellement suivi de `%`
- `regex` — expression avec **groupe 1** = valeur (`parse_expr`)
- `json_path` — chemin `a.b.0.c`
- `line_field` — `ligne:champ` ou `ligne:champ:séparateur` (0-based)

Bouton **Tester** dans l’onglet Sources pour valider commande + parse.

## Éléments

- **text** — libellé (`{title}` possible)
- **value** — valeur formatée (`{v:.0f}{u}`)
- **bar** / **pie** — jauges % avec seuils warn/crit et couleurs
- **sparkline** — historique + période (`15m`, `1h`, `7j`, `30s`…) + barre de progression
- **status_dot** — pastille vert/jaune/rouge
- **pattern** — fond `grid` / `dots` / `scanlines` / `diagonal` / `noise`
- **rect** — bloc de couleur

## Fichiers projet

Format JSON versionné : `*.pixoo.json` (dossier suggéré `projects/`).

```json
{
  "version": 1,
  "meta": { "name": "Demo", "pixoo_ip": "192.168.1.137", "brightness": 60 },
  "sources": [ … ],
  "screens": [ { "id": "…", "title": "CPU", "elements": [ … ] } ]
}
```

Export PNG de l’aperçu : **Fichier → Exporter aperçu PNG**.

## Relation avec le moniteur CLI

| | CLI (`pixoo_monitor`) | Designer |
|---|---|---|
| Config | `config.toml` + profils | `*.pixoo.json` |
| Usage | daemon / cron / setup wizard | composition visuelle |
| Rendu | pages auto / screens TOML | éléments libres + preview live |

Les deux partagent le client HTTP Pixoo (`pixoo_monitor.pixoo_client`) pour l’envoi réel.

## Raccourcis

- `Ctrl/Cmd+N` Nouveau · `O` Ouvrir · `S` Sauver
- Rafraîchissement auto des valeurs ~2 s

## Dépannage

| Problème | Piste |
|---|---|
| PySide6 manquant | `pipenv install` / `./scripts/install.sh` |
| Preview vide | Vérifier qu’un écran a des éléments visibles |
| Commande = `None` | **Tester** la source ; ajuster parse/regex |
| Envoi Pixoo KO | IP dans les meta projet / ping appareil |
