#!/bin/sh
# Foreground runner — always python3 (never "python").
set -eu

# Resolve install root BEFORE Entware profile (profile.d may cd to USB mount).
_case0=$0
case "${_case0}" in
  /*) _script=${_case0} ;;
  *) _script="$(pwd)/${_case0}" ;;
esac
ROOT="$(CDPATH= cd -- "$(dirname "${_script}")" && pwd)"
unset _case0 _script

# Entware: non-interactive / cru shells often skip profile
export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:${PATH}"
if [ -f /opt/etc/profile ]; then
  # shellcheck disable=SC1091
  . /opt/etc/profile
fi

PYTHON="$(command -v python3 2>/dev/null || true)"
if [ -z "${PYTHON}" ] && [ -x /opt/bin/python3 ]; then
  PYTHON="/opt/bin/python3"
fi

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

if [ -z "${PYTHON}" ] || [ ! -x "${PYTHON}" ]; then
  echo "error: python3 not found. Run install.sh (opkg install python3 python3-pillow python3-yaml)" >&2
  echo "  PATH=${PATH}" >&2
  exit 1
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON}" -m pixoo_merlin "$@"
