#!/bin/sh
# Install pico metrics exporter on Asuswrt-Merlin (+ Entware).
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

echo "==> pico_monitor install → ${ROOT}"

if [ -z "${OPKG}" ]; then
  echo "error: /opt/bin/opkg missing (Entware required)" >&2
  exit 1
fi

echo "==> opkg update (best effort)"
"${OPKG}" update >/dev/null 2>&1 || true
echo "==> opkg install python3"
"${OPKG}" install python3

[ -x /opt/bin/python3 ] && PYTHON="/opt/bin/python3"
if [ -z "${PYTHON}" ]; then
  echo "error: python3 missing after opkg install" >&2
  exit 1
fi
echo "==> python3: ${PYTHON} ($("${PYTHON}" --version 2>&1))"

if [ ! -f "${ROOT}/config.env" ]; then
  cp "${ROOT}/config.example.env" "${ROOT}/config.env"
  echo "==> created config.env"
fi
if grep -q '^PICO_METRICS_PORT=' "${ROOT}/config.env" 2>/dev/null; then
  sed -i "s/^PICO_METRICS_PORT=.*/PICO_METRICS_PORT=${METRICS_PORT}/" "${ROOT}/config.env"
else
  echo "PICO_METRICS_PORT=${METRICS_PORT}" >> "${ROOT}/config.env"
fi

chmod 755 "${ROOT}/run.sh" "${ROOT}/watchdog.sh" "${ROOT}/install.sh" "${ROOT}/uninstall.sh" 2>/dev/null || true
mkdir -p "${ROOT}/run" "${ROOT}/logs"

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

echo "==> start daemon"
"${ROOT}/watchdog.sh" reload || "${ROOT}/watchdog.sh" start
"${ROOT}/watchdog.sh" status || true

echo "Install OK — metrics: http://127.0.0.1:${METRICS_PORT}/metrics.json"
echo "Pico firmware must use ROUTER_HOST=<lan-ip> ROUTER_PORT=${METRICS_PORT}"
