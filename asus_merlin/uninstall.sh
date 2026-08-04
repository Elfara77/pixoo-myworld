#!/bin/sh
# Uninstall Pixoo Merlin monitor (cru + services-start + daemon).
# Does NOT remove opkg packages by default (python3 / pillow / yaml stay).
# Optional: UNINSTALL_OPKG=1 ./uninstall.sh
set -eu

ADDON_DIR="/jffs/addons/pixoo_merlin"
# Allow running from deployed tree
if [ -f "$(dirname "$0")/watchdog.sh" ]; then
  ADDON_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
fi

CRU_NAME="PixooMerlin"
MARKER="# pixoo_merlin"
SERVICES_START="/jffs/scripts/services-start"
PIDFILE="${ADDON_DIR}/run/merlin.pid"

echo "==> stop daemon"
if [ -f "${PIDFILE}" ]; then
  pid="$(cat "${PIDFILE}" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    sleep 1
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${PIDFILE}"
fi
# fallback pkill by path
if command -v pgrep >/dev/null 2>&1; then
  pgrep -f "pixoo_merlin" 2>/dev/null | while read -r p; do
    kill "${p}" 2>/dev/null || true
  done
fi

if command -v cru >/dev/null 2>&1; then
  echo "==> remove cru ${CRU_NAME}"
  cru d "${CRU_NAME}" 2>/dev/null || true
fi

if [ -f "${SERVICES_START}" ] && grep -q "${MARKER}" "${SERVICES_START}" 2>/dev/null; then
  echo "==> remove services-start hook"
  tmp="${SERVICES_START}.tmp.$$"
  grep -v "${MARKER}" "${SERVICES_START}" > "${tmp}" || true
  mv "${tmp}" "${SERVICES_START}"
  chmod 755 "${SERVICES_START}"
fi

REMOVE_FILES="${REMOVE_FILES:-1}"
if [ "${REMOVE_FILES}" = "1" ]; then
  echo "==> remove ${ADDON_DIR} (set REMOVE_FILES=0 to keep)"
  # Keep config.env backup aside if present
  if [ -f "${ADDON_DIR}/config.env" ]; then
    cp -f "${ADDON_DIR}/config.env" "/tmp/pixoo_merlin.config.env.bak" 2>/dev/null || true
    echo "    config.env backed up to /tmp/pixoo_merlin.config.env.bak"
  fi
  rm -rf "${ADDON_DIR}"
fi

if [ "${UNINSTALL_OPKG:-0}" = "1" ]; then
  echo "==> remove opkg packages (UNINSTALL_OPKG=1)"
  if command -v opkg >/dev/null 2>&1; then
    opkg remove python3-yaml python3-pillow python3 2>/dev/null || true
  fi
else
  echo "==> leaving opkg packages installed (python3 python3-pillow python3-yaml)"
  echo "    to remove them: UNINSTALL_OPKG=1 ${0}"
fi

echo "Uninstall done."
