#!/bin/sh
# Watchdog / control: start | stop | reload
# Invoked by cru + services-start (default = start if not running).
#
# Reload config.env / code:
#   /jffs/addons/pixoo_merlin/watchdog.sh reload
set -eu

# Resolve install root BEFORE Entware profile (profile.d may cd to USB mount).
_case0=$0
case "${_case0}" in
  /*) _script=${_case0} ;;
  *) _script="$(pwd)/${_case0}" ;;
esac
ROOT="$(CDPATH= cd -- "$(dirname "${_script}")" && pwd)"
unset _case0 _script

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

RUN_DIR="${ROOT}/run"
LOG_DIR="${ROOT}/logs"
PIDFILE="${RUN_DIR}/merlin.pid"
LOGFILE="${LOG_DIR}/merlin.log"
ACTION="${1:-start}"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

is_running() {
  if [ ! -f "${PIDFILE}" ]; then
    return 1
  fi
  pid="$(cat "${PIDFILE}" 2>/dev/null || true)"
  [ -n "${pid:-}" ] || return 1
  kill -0 "${pid}" 2>/dev/null
}

stop_daemon() {
  if [ -f "${PIDFILE}" ]; then
    pid="$(cat "${PIDFILE}" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      sleep 1
      kill -9 "${pid}" 2>/dev/null || true
      echo "$(date) watchdog: stopped pid=${pid}" >> "${LOGFILE}"
    fi
  fi
  rm -f "${PIDFILE}"
  # Fallback if pidfile was stale
  if command -v pgrep >/dev/null 2>&1; then
    for p in $(pgrep -f "-m pixoo_merlin run" 2>/dev/null || true); do
      [ "${p}" = "$$" ] && continue
      kill "${p}" 2>/dev/null || true
    done
  fi
}

start_daemon() {
  if is_running; then
    echo "already running pid=$(cat "${PIDFILE}")"
    return 0
  fi

  if [ -z "${PYTHON}" ] || [ ! -x "${PYTHON}" ]; then
    echo "$(date) watchdog: python3 missing (PATH=${PATH})" >> "${LOGFILE}"
    echo "error: python3 not found" >&2
    return 1
  fi

  rm -f "${PIDFILE}"
  cd "${ROOT}"
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

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

  nohup "${PYTHON}" -m pixoo_merlin run >> "${LOGFILE}" 2>&1 &
  echo $! > "${PIDFILE}"
  echo "$(date) watchdog: started pid=$(cat "${PIDFILE}")" >> "${LOGFILE}"
  echo "started pid=$(cat "${PIDFILE}")"
}

case "${ACTION}" in
  start|"")
    # cru default: only start if down
    if is_running; then
      exit 0
    fi
    start_daemon
    ;;
  stop)
    stop_daemon
    echo "stopped"
    ;;
  reload|restart)
    stop_daemon
    sleep 1
    start_daemon
    echo "reloaded (config.env re-read)"
    ;;
  status)
    if is_running; then
      echo "running pid=$(cat "${PIDFILE}")"
      exit 0
    fi
    echo "stopped"
    exit 1
    ;;
  *)
    echo "usage: $0 {start|stop|reload|restart|status}" >&2
    exit 2
    ;;
esac
