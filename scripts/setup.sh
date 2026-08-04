#!/usr/bin/env bash
# Wizard interactif → config.toml + setups nommés
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

print_help() {
  cat <<'EOF'
Usage: ./scripts/setup.sh [options]

Configure le monitoring Pixoo (profils, rendu, disque camembert, historique,
setups nommés).

Sans argument: menu interactif
  • wizard de (re)configuration
  • charger / sauver / lister / supprimer un setup nommé

Options:
  -h, --help          Affiche cette aide
  --wizard            Lancer directement le wizard
  --save NAME         Sauver config.toml → configs/setups/NAME.toml
  --load NAME         Charger un setup nommé comme config active
  --list              Lister les setups sauvegardés
  --delete NAME       Supprimer un setup nommé
  --force             Écraser (--save) ou supprimer sans confirmation
  --help-profiles     Liste les profils disponibles

Exemples:
  ./scripts/setup.sh
  ./scripts/setup.sh --wizard
  ./scripts/setup.sh --save nextcloud-n40
  ./scripts/setup.sh --load nextcloud-n40
  ./scripts/setup.sh --list

Setups: configs/setups/<nom>.toml  |  actif: config.toml
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
  echo "Environnement absent. Lance d'abord: ./scripts/install.sh"
  exit 1
fi

exec pipenv run python -m pixoo_monitor.setup "$@"
