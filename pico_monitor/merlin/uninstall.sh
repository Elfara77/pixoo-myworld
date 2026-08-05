#!/bin/sh
# Remove pico metrics exporter (cru + services-start + files).
set -eu

_case0=$0
case "${_case0}" in
  /*) _script=${_case0} ;;
  *) _script="$(pwd)/${_case0}" ;;
esac
ROOT="$(CDPATH= cd -- "$(dirname "${_script}")" && pwd)"
unset _case0 _script

export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:/bin:/sbin:/usr/bin:/usr/sbin"

CRU_NAME="PicoMonitor"
MARKER="# pico_monitor"
SERVICES_START="/jffs/scripts/services-start"

echo "==> pico_monitor uninstall ${ROOT}"

if [ -x "${ROOT}/watchdog.sh" ]; then
  "${ROOT}/watchdog.sh" stop 2>/dev/null || true
fi

if [ -x /usr/sbin/cru ]; then
  /usr/sbin/cru d "${CRU_NAME}" 2>/dev/null || true
  echo "==> cru ${CRU_NAME} removed"
fi

if [ -f "${SERVICES_START}" ]; then
  tmp="${SERVICES_START}.tmp.$$"
  grep -v "${MARKER}" "${SERVICES_START}" > "${tmp}" 2>/dev/null || true
  mv "${tmp}" "${SERVICES_START}"
  chmod 755 "${SERVICES_START}"
  echo "==> services-start cleaned"
fi

cd / || true
rm -rf "${ROOT}"
echo "removed ${ROOT}"
