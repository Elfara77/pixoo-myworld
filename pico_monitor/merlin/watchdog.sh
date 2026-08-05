#!/bin/sh
# start | stop | reload | status for pico metrics server
# Invoked by cru + services-start.
#
# BusyBox ash may lack `command` — never use `command -v`.
# Resolve ROOT before any Entware profile (mydisk.sh may cd to AMTM).
set -eu

_case0=$0
case "${_case0}" in
  /*) _script=${_case0} ;;
  *) _script="$(pwd)/${_case0}" ;;
esac
ROOT="$(CDPATH= cd -- "$(dirname "${_script}")" && pwd)"
unset _case0 _script

# Entware binaries without sourcing noisy /opt/etc/profile
export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:/bin:/sbin:/usr/bin:/usr/sbin:${PATH}"

PYTHON=""
if [ -x /opt/bin/python3 ]; then
  PYTHON="/opt/bin/python3"
elif [ -x /opt/usr/bin/python3 ]; then
  PYTHON="/opt/usr/bin/python3"
fi

RUN_DIR="${ROOT}/run"
LOG_DIR="${ROOT}/logs"
PIDFILE="${RUN_DIR}/pico_metrics.pid"
LOGFILE="${LOG_DIR}/pico_metrics.log"
ACTION="${1:-start}"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

is_running() {
  [ -f "${PIDFILE}" ] || return 1
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
    fi
  fi
  rm -f "${PIDFILE}"
  # Best-effort cleanup without pgrep/command -v
  if [ -x /opt/bin/pgrep ]; then
    for p in $(/opt/bin/pgrep -f "metrics_server.py" 2>/dev/null || true); do
      kill "${p}" 2>/dev/null || true
    done
  elif [ -x /usr/bin/pgrep ]; then
    for p in $(/usr/bin/pgrep -f "metrics_server.py" 2>/dev/null || true); do
      kill "${p}" 2>/dev/null || true
    done
  fi
}

start_daemon() {
  is_running && {
    echo "already running pid=$(cat "${PIDFILE}")"
    return 0
  }
  [ -n "${PYTHON}" ] && [ -x "${PYTHON}" ] || {
    echo "error: python3 missing (expected /opt/bin/python3)" >&2
    return 1
  }
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
  nohup "${PYTHON}" "${ROOT}/metrics_server.py" >> "${LOGFILE}" 2>&1 &
  echo $! > "${PIDFILE}"
  echo "started pid=$(cat "${PIDFILE}")"
}

case "${ACTION}" in
  start|"")
    is_running && exit 0
    start_daemon
    ;;
  stop) stop_daemon; echo stopped ;;
  reload|restart) stop_daemon; sleep 1; start_daemon; echo reloaded ;;
  status)
    if is_running; then echo "running pid=$(cat "${PIDFILE}")"; exit 0; fi
    echo stopped; exit 1
    ;;
  *) echo "usage: $0 {start|stop|reload|status}" >&2; exit 2 ;;
esac
