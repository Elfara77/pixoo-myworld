#!/usr/bin/env bash
# Lance le Pixoo 64 Designer (UI graphique PySide6)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
Usage: ./scripts/designer.sh [--help]

Lance l'application graphique Pixoo 64 Designer.

Sans argument : démarre l'UI.
Options:
  -h, --help   Cette aide

Prérequis: ./scripts/install.sh (Pipenv + PySide6)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -d .venv ]]; then
  echo "Environnement manquant — lance ./scripts/install.sh" >&2
  exit 1
fi

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
exec pipenv run python -m pixoo_designer "$@"
