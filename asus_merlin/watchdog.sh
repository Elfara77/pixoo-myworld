#!/bin/sh
# Watchdog: start daemon if not running. Invoked by cru + services-start.
set -eu

# Entware: cru / services-start often skip profile — ensure /opt/bin is on PATH
export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:${PATH}"
if [ -f /opt/etc/profile ]; then
  # shellcheck disable=SC1091
  . /opt/etc/profile
fi

PYTHON="$(command -v python3 2>/dev/null || true)"
if [ -z "${PYTHON}" ] && [ -x /opt/bin/python3 ]; then
  PYTHON="/opt/bin/python3"
fi

ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
RUN_DIR="${ROOT}/run"
LOG_DIR="${ROOT}/logs"
PIDFILE="${RUN_DIR}/merlin.pid"
LOGFILE="${LOG_DIR}/merlin.log"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

is_running() {
  if [ ! -f "${PIDFILE}" ]; then
    return 1
  fi
  pid="$(cat "${PIDFILE}" 2>/dev/null || true)"
  [ -n "${pid:-}" ] || return 1
  kill -0 "${pid}" 2>/dev/null
}

if is_running; then
  exit 0
fi

if [ -z "${PYTHON}" ] || [ ! -x "${PYTHON}" ]; then
  echo "$(date) watchdog: python3 missing (PATH=${PATH})" >> "${LOGFILE}"
  exit 1
fi

# stale pid
rm -f "${PIDFILE}"

cd "${ROOT}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

# Load env for child
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

# Background daemon via python3 -m pixoo_merlin run
nohup "${PYTHON}" -m pixoo_merlin run >> "${LOGFILE}" 2>&1 &
echo $! > "${PIDFILE}"
echo "$(date) watchdog: started pid=$(cat "${PIDFILE}")" >> "${LOGFILE}"
