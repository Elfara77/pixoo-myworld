#!/usr/bin/env bash
# Thin wrapper → deploy_monitor.sh install
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec "${ROOT}/deploy_monitor.sh" install "$@"
