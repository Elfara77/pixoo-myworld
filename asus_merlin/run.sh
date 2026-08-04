#!/bin/sh
# Foreground runner — always python3 (never "python").
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "${ROOT}"

if [ -f "${ROOT}/config.env" ]; then
  # shellcheck disable=SC1090
  set -a
  # Export KEY=VAL lines
  while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
      ""|\#*) continue ;;
    esac
    export "${line?}"
  done < "${ROOT}/config.env"
  set +a
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found. Run install.sh (opkg install python3 python3-pillow python3-yaml)" >&2
  exit 1
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m pixoo_merlin "$@"
