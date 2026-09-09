#!/usr/bin/env bash
# Push Merlin /metrics.json frames to a Divoom Pixoo 64.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
PY="${REPO}/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m pixoo_bridge "$@"
