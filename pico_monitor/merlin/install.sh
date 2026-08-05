#!/bin/sh
# Install pico metrics exporter + Pixoo bridge on Asuswrt-Merlin (+ Entware).
# Run ON the router after upload (or via deploy_monitor.sh).
#
# BusyBox ash on Merlin often lacks the `command` builtin → never use
# `command -v`. Prefer `[ -x /path ]`. Do NOT source /opt/etc/profile:
# profile.d (mydisk.sh) may cd to AMTM and spam the SSH session.
set -eu

# Resolve install root BEFORE anything that might cd.
_case0=$0
case "${_case0}" in
  /*) _script=${_case0} ;;
  *) _script="$(pwd)/${_case0}" ;;
esac
ROOT="$(CDPATH= cd -- "$(dirname "${_script}")" && pwd)"
unset _case0 _script

export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:/bin:/sbin:/usr/bin:/usr/sbin"

OPKG=""
[ -x /opt/bin/opkg ] && OPKG="/opt/bin/opkg"
PYTHON=""
[ -x /opt/bin/python3 ] && PYTHON="/opt/bin/python3"
CRU=""
[ -x /usr/sbin/cru ] && CRU="/usr/sbin/cru"

CRU_NAME="PicoMonitor"
MARKER="# pico_monitor"
SERVICES_START="/jffs/scripts/services-start"
METRICS_PORT="${PICO_METRICS_PORT:-8088}"
PIXOO_IP="${PIXOO_IP:-192.168.52.4}"
PIXOO_BRIGHTNESS="${PIXOO_BRIGHTNESS:-50}"
PIXOO_SCREEN_SECONDS="${PIXOO_SCREEN_SECONDS:-8}"
PIXOO_FRAME_INTERVAL="${PIXOO_FRAME_INTERVAL:-1.05}"
PIXOO_COLOR_MODE="${PIXOO_COLOR_MODE:-mono}"
PIXOO_TEXT_SCROLL="${PIXOO_TEXT_SCROLL:-1}"
PIXOO_ALERT_BLINK="${PIXOO_ALERT_BLINK:-1}"
PIXOO_BLINK_PERIOD="${PIXOO_BLINK_PERIOD:-0.55}"
PIXOO_RATE_STYLE="${PIXOO_RATE_STYLE:-short}"

echo "==> pico_monitor install → ${ROOT}"

if [ -z "${OPKG}" ]; then
  echo "error: /opt/bin/opkg missing (Entware required)" >&2
  exit 1
fi

echo "==> opkg update (best effort)"
"${OPKG}" update >/dev/null 2>&1 || true
echo "==> opkg install python3 python3-pillow"
"${OPKG}" install python3 python3-pillow

[ -x /opt/bin/python3 ] && PYTHON="/opt/bin/python3"
if [ -z "${PYTHON}" ]; then
  echo "error: python3 missing after opkg install" >&2
  exit 1
fi
echo "==> python3: ${PYTHON} ($("${PYTHON}" --version 2>&1))"

if ! "${PYTHON}" -c "from PIL import Image" >/dev/null 2>&1; then
  echo "error: Pillow import failed after python3-pillow install" >&2
  exit 1
fi
echo "==> Pillow OK"

# config.env — create or refresh known keys (preserve unknown lines)
if [ ! -f "${ROOT}/config.env" ]; then
  cp "${ROOT}/config.example.env" "${ROOT}/config.env"
  echo "==> created config.env"
fi

_set_kv() {
  # $1=key $2=value — update or append in config.env
  key="$1"
  val="$2"
  if grep -q "^${key}=" "${ROOT}/config.env" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "${ROOT}/config.env"
  else
    echo "${key}=${val}" >> "${ROOT}/config.env"
  fi
}

_set_kv PICO_METRICS_PORT "${METRICS_PORT}"
_set_kv PIXOO_IP "${PIXOO_IP}"
_set_kv PIXOO_BRIGHTNESS "${PIXOO_BRIGHTNESS}"
_set_kv PIXOO_SCREEN_SECONDS "${PIXOO_SCREEN_SECONDS}"
_set_kv PIXOO_FRAME_INTERVAL "${PIXOO_FRAME_INTERVAL}"
_set_kv PIXOO_COLOR_MODE "${PIXOO_COLOR_MODE}"
_set_kv PIXOO_TEXT_SCROLL "${PIXOO_TEXT_SCROLL}"
_set_kv PIXOO_ALERT_BLINK "${PIXOO_ALERT_BLINK}"
_set_kv PIXOO_BLINK_PERIOD "${PIXOO_BLINK_PERIOD}"
_set_kv PIXOO_RATE_STYLE "${PIXOO_RATE_STYLE}"
_set_kv PIXOO_METRICS_URL "http://127.0.0.1:${METRICS_PORT}/metrics.json"

chmod 755 "${ROOT}/run.sh" "${ROOT}/watchdog.sh" "${ROOT}/install.sh" "${ROOT}/uninstall.sh" 2>/dev/null || true
[ -f "${ROOT}/run_pixoo.sh" ] && chmod 755 "${ROOT}/run_pixoo.sh" 2>/dev/null || true
mkdir -p "${ROOT}/run" "${ROOT}/logs"

if [ ! -d "${ROOT}/pixoo_bridge" ]; then
  echo "warn: ${ROOT}/pixoo_bridge missing — metrics only (re-upload with deploy_monitor.sh)" >&2
else
  echo "==> pixoo_bridge package present → Pixoo ${PIXOO_IP}"
fi

if [ -n "${CRU}" ]; then
  echo "==> register cru ${CRU_NAME}"
  "${CRU}" d "${CRU_NAME}" 2>/dev/null || true
  "${CRU}" a "${CRU_NAME}" "*/1 * * * * ${ROOT}/watchdog.sh"
  echo "==> cru l:"
  "${CRU}" l
else
  echo "warn: /usr/sbin/cru missing — only services-start will start the daemon" >&2
fi

echo "==> services-start hook"
mkdir -p "$(dirname "${SERVICES_START}")"
if [ ! -f "${SERVICES_START}" ]; then
  printf '%s\n' "#!/bin/sh" > "${SERVICES_START}"
  chmod 755 "${SERVICES_START}"
fi
tmp="${SERVICES_START}.tmp.$$"
grep -v "${MARKER}" "${SERVICES_START}" > "${tmp}" 2>/dev/null || printf '%s\n' "#!/bin/sh" > "${tmp}"
printf '%s\n' "${ROOT}/watchdog.sh ${MARKER}" >> "${tmp}"
mv "${tmp}" "${SERVICES_START}"
chmod 755 "${SERVICES_START}"
grep -n "${MARKER}" "${SERVICES_START}" || true

echo "==> start daemons (metrics + Pixoo bridge)"
"${ROOT}/watchdog.sh" reload || "${ROOT}/watchdog.sh" start
"${ROOT}/watchdog.sh" status || true

echo ""
echo "Install OK"
echo "  metrics : http://127.0.0.1:${METRICS_PORT}/metrics.json"
echo "  Pixoo   : ${PIXOO_IP} (bridge push loop)"
echo "  logs    : ${ROOT}/logs/pixoo_bridge.log  (+ /tmp/pixoo_bridge.log)"
echo "            ${ROOT}/logs/pico_metrics.log"
