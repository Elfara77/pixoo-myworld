#!/usr/bin/env bash
# Lance le monitoring live vers le Pixoo 64
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

print_help() {
  cat <<'EOF'
Usage: ./scripts/run.sh [options]

Lance le monitoring live vers le Pixoo 64 (boucle ou une frame).

Options:
  -h, --help          Affiche cette aide
  -c, --config PATH   Chemin config.toml
  -p, --profile NAME  Forcer un profil (status, n40, nextcloud_full, …)
  --once              Envoie une seule frame puis quitte
  --interactive       Force les prompts (défaut si aucun argument)

Sans argument: mode interactif (profil, once, confirmation IP).

Exemples:
  ./scripts/run.sh
  ./scripts/run.sh --once
  ./scripts/run.sh --profile status
  ./scripts/run.sh --profile nextcloud_full -c ./config.toml
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

if [[ ! -f "$ROOT/config.toml" ]]; then
  echo "Pas de config.toml — lance ./scripts/setup.sh"
  exit 1
fi

if [[ ! -d "$ROOT/.venv" ]] && ! pipenv --venv >/dev/null 2>&1; then
  echo "Environnement absent. Lance: ./scripts/install.sh"
  exit 1
fi

if [[ $# -eq 0 ]]; then
  exec pipenv run python -m pixoo_monitor --interactive
fi
exec pipenv run python -m pixoo_monitor "$@"
