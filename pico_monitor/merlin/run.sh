#!/bin/sh
# Foreground metrics HTTP server (Entware python3)
set -eu

_case0=$0
case "${_case0}" in
  /*) _script=${_case0} ;;
  *) _script="$(pwd)/${_case0}" ;;
esac
ROOT="$(CDPATH= cd -- "$(dirname "${_script}")" && pwd)"
unset _case0 _script

export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:/bin:/sbin:/usr/bin:/usr/sbin:${PATH}"

PYTHON=""
if [ -x /opt/bin/python3 ]; then
  PYTHON="/opt/bin/python3"
elif [ -x /opt/usr/bin/python3 ]; then
  PYTHON="/opt/usr/bin/python3"
fi

cd "${ROOT}"
if [ -f "${ROOT}/config.env" ]; then
  set -a
  while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
      ""|\#*) continue ;;
    esac
    export "${line?}"
  done < "${ROOT}/config.env"
  set +a
fi

if [ -z "${PYTHON}" ] || [ ! -x "${PYTHON}" ]; then
  echo "error: python3 missing — opkg install python3" >&2
  exit 1
fi

exec "${PYTHON}" "${ROOT}/metrics_server.py"
