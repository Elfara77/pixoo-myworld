#!/usr/bin/env bash
# Mode test: collecte métriques + rendu PNG (sans Pixoo requis)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

print_help() {
  cat <<'EOF'
Usage: ./scripts/test.sh [options]

Dry-run: collecte les métriques et rend des PNG 64×64 (sans Pixoo requis).
Respecte display.render_mode (native|scaled) et disk_style (bar|pie).

Options:
  -h, --help          Affiche cette aide
  -c, --config PATH   Chemin config.toml
  -p, --profile NAME  Forcer un profil
  -o, --out DIR       Dossier PNG (défaut: assets/test_preview)
  --pixoo             Tente un push si l'IP est joignable
  --samples N         Nombre de collectes (défaut 2)
  --interactive       Force les prompts (défaut si aucun argument)

Sans argument: mode interactif (profil, push Pixoo, dossier sortie).

Exemples:
  ./scripts/test.sh
  ./scripts/test.sh --pixoo
  ./scripts/test.sh --profile status -o /tmp/pixoo
EOF
}

if [[ $# -gt 0 ]]; then
  case "${1:-}" in
    -h|--help) print_help; exit 0 ;;
  esac
fi

export PIPENV_VENV_IN_PROJECT=1
export PIPENV_IGNORE_VIRTUALENVS=1
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -d "$ROOT/.venv" ]] && ! pipenv --venv >/dev/null 2>&1; then
  echo "Environnement absent. Lance: ./scripts/install.sh"
  exit 1
fi

if [[ ! -f "$ROOT/config.toml" ]]; then
  cp "$ROOT/config.example.toml" "$ROOT/config.toml"
  echo "config.toml créé depuis l'exemple"
fi

if [[ $# -eq 0 ]]; then
  exec pipenv run python -m pixoo_monitor.test_mode --interactive
fi
exec pipenv run python -m pixoo_monitor.test_mode "$@"
