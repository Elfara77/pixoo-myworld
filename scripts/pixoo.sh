#!/usr/bin/env bash
# Pixoo CLI — studio | daemon | render | version
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
Usage: ./scripts/pixoo.sh <command> [options]

Commands (delegated to `python -m pixoo`):
  version
  studio [--project PATH]
  daemon --project PATH [--pixoo-ip IP] [--host HOST] [--port PORT]
  render --project PATH --output PATH.png

Examples:
  ./scripts/pixoo.sh version
  ./scripts/pixoo.sh studio -p projects/demo_v2.pixoo
  ./scripts/pixoo.sh daemon -p projects/demo_v2.pixoo --pixoo-ip 192.168.52.4
  ./scripts/pixoo.sh render -p projects/demo_v2.pixoo -o /tmp/pixoo.png

Prérequis: ./scripts/install.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -eq 0 ]]; then
  usage
  [[ $# -eq 0 ]] && exit 1 || exit 0
fi

if [[ ! -d .venv ]]; then
  echo "Environnement manquant — lance ./scripts/install.sh" >&2
  exit 1
fi

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
exec pipenv run python -m pixoo "$@"
