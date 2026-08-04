#!/bin/sh
# Watchdog: start daemon if not running. Invoked by cru + services-start.
set -eu

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

if ! command -v python3 >/dev/null 2>&1; then
  echo "$(date) watchdog: python3 missing" >> "${LOGFILE}"
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
nohup python3 -m pixoo_merlin run >> "${LOGFILE}" 2>&1 &
echo $! > "${PIDFILE}"
echo "$(date) watchdog: started pid=$(cat "${PIDFILE}")" >> "${LOGFILE}"
