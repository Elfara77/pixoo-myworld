#!/bin/sh
# Foreground Pixoo bridge (Entware python3) — Merlin → Pixoo HTTP push.
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
  echo "error: python3 missing — opkg install python3 python3-pillow" >&2
  exit 1
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
PIXOO_IP="${PIXOO_IP:-192.168.52.4}"
METRICS_PORT="${PICO_METRICS_PORT:-8088}"
METRICS_URL="${PIXOO_METRICS_URL:-http://127.0.0.1:${METRICS_PORT}/metrics.json}"
LOG="${ROOT}/logs/pixoo_bridge.log"
mkdir -p "${ROOT}/logs" "${ROOT}/run"

exec "${PYTHON}" -m pixoo_bridge \
  --pixoo "${PIXOO_IP}" \
  --metrics "${METRICS_URL}" \
  --brightness "${PIXOO_BRIGHTNESS:-50}" \
  --screen-seconds "${PIXOO_SCREEN_SECONDS:-8}" \
  --heavy-screen-dwell "${PIXOO_HEAVY_SCREEN_DWELL:-1}" \
  --heavy-screen-multiplier "${PIXOO_HEAVY_SCREEN_MULTIPLIER:-2}" \
  --frame-interval "${PIXOO_FRAME_INTERVAL:-1.05}" \
  --color-mode "${PIXOO_COLOR_MODE:-mono}" \
  --text-scroll "${PIXOO_TEXT_SCROLL:-1}" \
  --alert-blink "${PIXOO_ALERT_BLINK:-1}" \
  --blink-period "${PIXOO_BLINK_PERIOD:-0.55}" \
  --rate-style "${PIXOO_RATE_STYLE:-short}" \
  --time-12h "${PIXOO_TIME_12H:-0}" \
  --wlc-graph-mode "${PIXOO_WLC_GRAPH_MODE:-overlay}" \
  --wan-max-down "${PIXOO_WAN_MAX_DOWN_MBPS:-190}" \
  --wan-max-up "${PIXOO_WAN_MAX_UP_MBPS:-12}" \
  --screens "${PIXOO_SCREENS:-all}" \
  --log "${LOG}" \
  --snapshot-path "${ROOT}/run/pixoo_last.png" \
  "$@"
