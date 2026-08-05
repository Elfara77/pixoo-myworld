#!/bin/sh
# start | stop | reload | status for metrics server + Pixoo bridge.
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
METRICS_PIDFILE="${RUN_DIR}/pico_metrics.pid"
BRIDGE_PIDFILE="${RUN_DIR}/pixoo_bridge.pid"
METRICS_LOG="${LOG_DIR}/pico_metrics.log"
BRIDGE_LOG="${LOG_DIR}/pixoo_bridge.log"
# Easy-to-find mirror (tmpfs; cleared on reboot — jffs copy is authoritative)
BRIDGE_LOG_TMP="/tmp/pixoo_bridge.log"
ACTION="${1:-start}"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

log_bridge() {
  msg="$(ts) watchdog: $*"
  echo "${msg}" >> "${BRIDGE_LOG}"
  # Only mirror to /tmp when it is a separate file (not a symlink to BRIDGE_LOG)
  if [ -e "${BRIDGE_LOG_TMP}" ] && [ ! -L "${BRIDGE_LOG_TMP}" ]; then
    echo "${msg}" >> "${BRIDGE_LOG_TMP}" 2>/dev/null || true
  fi
}

log_metrics() {
  echo "$(ts) watchdog: $*" >> "${METRICS_LOG}"
}

is_running() {
  # $1 = pidfile
  [ -f "$1" ] || return 1
  pid="$(cat "$1" 2>/dev/null || true)"
  [ -n "${pid:-}" ] || return 1
  kill -0 "${pid}" 2>/dev/null
}

_kill_pattern() {
  # $1 = pattern for pgrep -f
  if [ -x /opt/bin/pgrep ]; then
    for p in $(/opt/bin/pgrep -f "$1" 2>/dev/null || true); do
      kill "${p}" 2>/dev/null || true
    done
  elif [ -x /usr/bin/pgrep ]; then
    for p in $(/usr/bin/pgrep -f "$1" 2>/dev/null || true); do
      kill "${p}" 2>/dev/null || true
    done
  fi
}

stop_one() {
  # $1=pidfile $2=pgrep_pattern $3=label $4=logfile_fn_name
  pf="$1"
  pat="$2"
  label="$3"
  if [ -f "${pf}" ]; then
    pid="$(cat "${pf}" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      sleep 1
      kill -9 "${pid}" 2>/dev/null || true
    fi
  fi
  rm -f "${pf}"
  _kill_pattern "${pat}"
  case "${label}" in
    bridge) log_bridge "stopped ${label}" ;;
    metrics) log_metrics "stopped ${label}" ;;
  esac
}

load_config() {
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
}

start_metrics() {
  is_running "${METRICS_PIDFILE}" && {
    echo "metrics already running pid=$(cat "${METRICS_PIDFILE}")"
    return 0
  }
  [ -n "${PYTHON}" ] && [ -x "${PYTHON}" ] || {
    echo "error: python3 missing (expected /opt/bin/python3)" >&2
    return 1
  }
  [ -f "${ROOT}/metrics_server.py" ] || {
    echo "error: metrics_server.py missing" >&2
    return 1
  }
  cd "${ROOT}"
  load_config
  nohup "${PYTHON}" "${ROOT}/metrics_server.py" >> "${METRICS_LOG}" 2>&1 &
  echo $! > "${METRICS_PIDFILE}"
  log_metrics "started metrics pid=$(cat "${METRICS_PIDFILE}")"
  echo "metrics started pid=$(cat "${METRICS_PIDFILE}")"
}

start_bridge() {
  is_running "${BRIDGE_PIDFILE}" && {
    echo "bridge already running pid=$(cat "${BRIDGE_PIDFILE}")"
    return 0
  }
  [ -n "${PYTHON}" ] && [ -x "${PYTHON}" ] || {
    echo "error: python3 missing (expected /opt/bin/python3)" >&2
    return 1
  }
  if [ ! -d "${ROOT}/pixoo_bridge" ] || [ ! -f "${ROOT}/pixoo_bridge/__main__.py" ]; then
    echo "warn: pixoo_bridge package missing — skip Pixoo push" >&2
    log_bridge "skip start: pixoo_bridge package missing"
    return 0
  fi
  # Pillow required for RGB frames
  if ! "${PYTHON}" -c "from PIL import Image" >/dev/null 2>&1; then
    echo "error: python3-pillow missing — opkg install python3-pillow" >&2
    log_bridge "skip start: Pillow import failed"
    return 1
  fi
  cd "${ROOT}"
  load_config
  PIXOO_IP="${PIXOO_IP:-192.168.52.4}"
  METRICS_PORT="${PICO_METRICS_PORT:-8088}"
  METRICS_URL="${PIXOO_METRICS_URL:-http://127.0.0.1:${METRICS_PORT}/metrics.json}"
  BRIGHTNESS="${PIXOO_BRIGHTNESS:-50}"
  SCREEN_S="${PIXOO_SCREEN_SECONDS:-8}"
  FRAME_S="${PIXOO_FRAME_INTERVAL:-1.05}"
  COLOR_MODE="${PIXOO_COLOR_MODE:-mono}"
  TEXT_SCROLL="${PIXOO_TEXT_SCROLL:-1}"
  ALERT_BLINK="${PIXOO_ALERT_BLINK:-1}"
  BLINK_PERIOD="${PIXOO_BLINK_PERIOD:-0.55}"

  export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
  # Logging goes to stdout/stderr → BRIDGE_LOG via nohup (no --log FileHandler
  # to avoid duplicate lines). /tmp symlink for easy discovery.
  nohup "${PYTHON}" -m pixoo_bridge \
    --pixoo "${PIXOO_IP}" \
    --metrics "${METRICS_URL}" \
    --brightness "${BRIGHTNESS}" \
    --screen-seconds "${SCREEN_S}" \
    --frame-interval "${FRAME_S}" \
    --color-mode "${COLOR_MODE}" \
    --text-scroll "${TEXT_SCROLL}" \
    --alert-blink "${ALERT_BLINK}" \
    --blink-period "${BLINK_PERIOD}" \
    >> "${BRIDGE_LOG}" 2>&1 &
  echo $! > "${BRIDGE_PIDFILE}"
  log_bridge "started bridge pid=$(cat "${BRIDGE_PIDFILE}") pixoo=${PIXOO_IP} metrics=${METRICS_URL} color=${COLOR_MODE} blink=${ALERT_BLINK}"
  ln -sf "${BRIDGE_LOG}" "${BRIDGE_LOG_TMP}" 2>/dev/null || \
    cp -f "${BRIDGE_LOG}" "${BRIDGE_LOG_TMP}" 2>/dev/null || true
  echo "bridge started pid=$(cat "${BRIDGE_PIDFILE}") → Pixoo ${PIXOO_IP}"
}

stop_metrics() {
  stop_one "${METRICS_PIDFILE}" "metrics_server.py" "metrics"
  echo "metrics stopped"
}

stop_bridge() {
  stop_one "${BRIDGE_PIDFILE}" "pixoo_bridge" "bridge"
  echo "bridge stopped"
}

start_all() {
  start_metrics
  start_bridge
}

stop_all() {
  stop_bridge
  stop_metrics
}

status_all() {
  ok=0
  if is_running "${METRICS_PIDFILE}"; then
    echo "metrics running pid=$(cat "${METRICS_PIDFILE}")"
  else
    echo "metrics stopped"
    ok=1
  fi
  if is_running "${BRIDGE_PIDFILE}"; then
    echo "bridge running pid=$(cat "${BRIDGE_PIDFILE}")"
  else
    echo "bridge stopped"
    ok=1
  fi
  return "${ok}"
}

case "${ACTION}" in
  start|"")
    # cru invokes every minute — start whatever is missing
    start_all
    ;;
  stop)
    stop_all
    echo stopped
    ;;
  reload|restart)
    stop_all
    sleep 1
    start_all
    echo reloaded
    ;;
  status)
    status_all
    ;;
  start-metrics) start_metrics ;;
  stop-metrics) stop_metrics ;;
  start-bridge|start-pixoo) start_bridge ;;
  stop-bridge|stop-pixoo) stop_bridge ;;
  *)
    echo "usage: $0 {start|stop|reload|status|start-metrics|stop-metrics|start-bridge|stop-bridge}" >&2
    exit 2
    ;;
esac
