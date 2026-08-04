#!/bin/sh
# Uninstall Pixoo Merlin monitor (cru + services-start + daemon + files).
#
# By default removes /jffs/addons/pixoo_merlin entirely.
# Env:
#   KEEP_CONFIG=1     preserve config.env (recreate dir with only that file)
#   REMOVE_FILES=0    skip deleting the addon directory
#   UNINSTALL_OPKG=1  also opkg remove python3 / pillow / yaml
set -eu

# Entware: non-interactive SSH often skips profile
export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:${PATH}"
if [ -f /opt/etc/profile ]; then
  # shellcheck disable=SC1091
  . /opt/etc/profile
fi

OPKG="$(command -v opkg 2>/dev/null || true)"
if [ -z "${OPKG}" ] && [ -x /opt/bin/opkg ]; then
  OPKG="/opt/bin/opkg"
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SELF="${SCRIPT_DIR}/$(basename "$0")"

# Canonical install path; if invoked from a deployed tree, use that dir
ADDON_DIR="${ADDON_DIR:-/jffs/addons/pixoo_merlin}"
if [ -z "${UNINSTALL_REEXEC:-}" ] && [ -f "${SCRIPT_DIR}/watchdog.sh" ]; then
  ADDON_DIR="${SCRIPT_DIR}"
fi

# Re-exec from /tmp so rm -rf of the install dir cannot truncate this script mid-run
# (busybox ash reads the script as it executes; classic Merlin pitfall).
if [ "${UNINSTALL_REEXEC:-0}" != "1" ]; then
  TMP_UNINSTALL="/tmp/pixoo_merlin_uninstall.$$.sh"
  cp -f "${SELF}" "${TMP_UNINSTALL}"
  chmod 755 "${TMP_UNINSTALL}"
  export ADDON_DIR
  export KEEP_CONFIG="${KEEP_CONFIG:-0}"
  export REMOVE_FILES="${REMOVE_FILES:-1}"
  export UNINSTALL_OPKG="${UNINSTALL_OPKG:-0}"
  export PIXOO_UNINSTALL_TMP="${TMP_UNINSTALL}"
  export UNINSTALL_REEXEC=1
  exec /bin/sh "${TMP_UNINSTALL}"
fi

CRU_NAME="PixooMerlin"
MARKER="# pixoo_merlin"
SERVICES_START="/jffs/scripts/services-start"
PIDFILE="${ADDON_DIR}/run/merlin.pid"

cleanup_tmp() {
  rm -f "${PIXOO_UNINSTALL_TMP:-}"
}
trap cleanup_tmp EXIT

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
# Fallback: match the Python module only — never pgrep -f "pixoo_merlin"
# (that matched this script path and self-killed before rm -rf).
if command -v pgrep >/dev/null 2>&1; then
  for p in $(pgrep -f "-m pixoo_merlin" 2>/dev/null || true); do
    [ "${p}" = "$$" ] && continue
    [ "${p}" = "${PPID}" ] && continue
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
KEEP_CONFIG="${KEEP_CONFIG:-0}"

if [ "${REMOVE_FILES}" = "1" ]; then
  CONFIG_BAK=""
  if [ -f "${ADDON_DIR}/config.env" ]; then
    CONFIG_BAK="/tmp/pixoo_merlin.config.env.bak"
    cp -f "${ADDON_DIR}/config.env" "${CONFIG_BAK}" 2>/dev/null || true
    echo "    config.env backed up to ${CONFIG_BAK}"
  fi

  # Leave cwd outside the tree before deleting it
  cd /tmp || cd / || true
  echo "==> remove ${ADDON_DIR}"
  rm -rf "${ADDON_DIR}"

  if [ "${KEEP_CONFIG}" = "1" ] && [ -n "${CONFIG_BAK}" ] && [ -f "${CONFIG_BAK}" ]; then
    echo "==> KEEP_CONFIG=1 — restore config.env only"
    mkdir -p "${ADDON_DIR}"
    cp -f "${CONFIG_BAK}" "${ADDON_DIR}/config.env"
  fi

  if [ -d "${ADDON_DIR}" ] && [ "${KEEP_CONFIG}" != "1" ]; then
    echo "warn: ${ADDON_DIR} still exists after rm -rf" >&2
    ls -la "${ADDON_DIR}" >&2 || true
  elif [ ! -e "${ADDON_DIR}" ]; then
    echo "    removed OK"
  elif [ "${KEEP_CONFIG}" = "1" ]; then
    echo "    kept ${ADDON_DIR}/config.env only"
  fi
else
  echo "==> keeping files (REMOVE_FILES=0) at ${ADDON_DIR}"
fi

if [ "${UNINSTALL_OPKG:-0}" = "1" ]; then
  echo "==> remove opkg packages (UNINSTALL_OPKG=1)"
  if [ -n "${OPKG}" ] && [ -x "${OPKG}" ]; then
    "${OPKG}" remove python3-yaml python3-pillow python3 2>/dev/null || true
  else
    echo "warn: opkg not found — skip package removal" >&2
  fi
else
  echo "==> leaving opkg packages installed (python3 python3-pillow python3-yaml)"
  echo "    to remove them: UNINSTALL_OPKG=1 <path-to>/uninstall.sh"
fi

echo "Uninstall done."
