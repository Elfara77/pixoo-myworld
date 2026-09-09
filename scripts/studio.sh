#!/usr/bin/env bash
# Lance Pixoo Studio (GUI professionnelle PySide6)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
Usage: ./scripts/studio.sh [--help]

Lance Pixoo Studio (architecture engine + GUI) — canvas 64×64, sync daemon.

Options:
  -h, --help              Aide
  -p, --project PATH      Fichier .pixoo (config_version 2.0)

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
exec pipenv run python -m pixoo studio "$@"
