#!/usr/bin/env bash
# Lance Pixoo Studio (GUI professionnelle PySide6)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
Usage: ./scripts/studio.sh [--help]

Lance Pixoo Studio — éditeur graphique 64×64 + auto-send + tray.

Options:
  -h, --help   Aide

Prérequis: ./scripts/install.sh
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
exec pipenv run python -m pixoo_studio "$@"
