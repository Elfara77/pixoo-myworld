#!/bin/sh
# Uninstall Pixoo Merlin monitor (cru + services-start + daemon + files).
#
# By default removes /jffs/addons/pixoo_merlin entirely.
# Env:
#   KEEP_CONFIG=1     preserve config.env (recreate dir with only that file)
#   REMOVE_FILES=0    skip deleting the addon directory
#   UNINSTALL_OPKG=1  also opkg remove python3 / pillow / yaml
#
# Prefer invoking from outside the install tree to avoid parent-shell getcwd
# errors after rm -rf:
#   cd / && /jffs/addons/pixoo_merlin/uninstall.sh
set -eu

# Resolve script path BEFORE Entware profile — profile.d (mydisk.sh) may cd
# to /tmp/mnt/AMTM and would break relative $0.
_case0=$0
case "${_case0}" in
  /*) _script=${_case0} ;;
  *) _script="$(pwd)/${_case0}" ;;
esac
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "${_script}")" && pwd)"
SELF="${SCRIPT_DIR}/$(basename "${_script}")"
# Parent/session cwd before we move (for getcwd warning after rm -rf)
INVOKER_PWD="$(pwd -P 2>/dev/null || pwd 2>/dev/null || echo "")"
unset _case0 _script

# Leave any doomed cwd immediately (helps this process; parent shell may still
# need `cd /` after we delete the install tree).
cd /tmp 2>/dev/null || cd / || true

# Entware: non-interactive SSH often skips profile
export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:${PATH}"
if [ -f /opt/etc/profile ]; then
  # shellcheck disable=SC1091
  . /opt/etc/profile
fi
# Profile may have cd'd again (e.g. to USB mount) — leave before deletes.
cd /tmp 2>/dev/null || cd / || true

OPKG="$(command -v opkg 2>/dev/null || true)"
if [ -z "${OPKG}" ] && [ -x /opt/bin/opkg ]; then
  OPKG="/opt/bin/opkg"
fi

# ONLY ever delete the Merlin install path under /jffs — never the local git clone.
# (Older logic set ADDON_DIR=$SCRIPT_DIR whenever watchdog.sh was present, which
#  wiped ~/.../monitoring_pixoo64/asus_merlin when run on a Mac.)
CANONICAL_ADDON="/jffs/addons/pixoo_merlin"
ADDON_DIR="${ADDON_DIR:-$CANONICAL_ADDON}"

case "${ADDON_DIR}" in
  /jffs/*) ;;
  *)
    echo "error: refusing to uninstall outside /jffs (ADDON_DIR=${ADDON_DIR})" >&2
    echo "  This script is for the Merlin router only." >&2
    echo "  On the router: cd / && ${CANONICAL_ADDON}/uninstall.sh" >&2
    echo "  From Mac: ssh user@router ${CANONICAL_ADDON}/uninstall.sh" >&2
    exit 1
    ;;
esac

# If invoked from the deployed tree on Merlin, prefer that path (still under /jffs)
if [ -z "${UNINSTALL_REEXEC:-}" ] && [ -f "${SCRIPT_DIR}/watchdog.sh" ]; then
  case "${SCRIPT_DIR}" in
    /jffs/*) ADDON_DIR="${SCRIPT_DIR}" ;;
  esac
fi

# Refuse to run on a machine that has no /jffs (dev laptop)
if [ ! -d /jffs ] && [ "${FORCE_UNINSTALL:-0}" != "1" ]; then
  echo "error: /jffs not found — looks like you are not on the Merlin router." >&2
  echo "  Do not run ./uninstall.sh from your Mac repo clone." >&2
  echo "  Use: ssh user@router ${CANONICAL_ADDON}/uninstall.sh" >&2
  exit 1
fi

# Warn if the invoking session was sitting inside the tree we will delete.
# We cannot fix the parent cwd from a child process — only advise.
case "${INVOKER_PWD}/" in
  "${ADDON_DIR}"/*)
    echo "warn: your shell was under ${ADDON_DIR}" >&2
    echo "  After uninstall it may print: getcwd: No such file or directory" >&2
    echo "  Prefer next time:  cd / && ${ADDON_DIR}/uninstall.sh" >&2
    echo "  After this run:     cd /" >&2
    ;;
esac

# Re-exec from /tmp so rm -rf of the install dir cannot truncate this script mid-run
# (busybox ash reads the script as it executes; classic Merlin pitfall).
if [ "${UNINSTALL_REEXEC:-0}" != "1" ]; then
  if [ ! -f "${SELF}" ]; then
    echo "error: cannot find uninstall script at ${SELF}" >&2
    echo "  Run with absolute path: cd / && /jffs/addons/pixoo_merlin/uninstall.sh" >&2
    exit 1
  fi
  TMP_UNINSTALL="/tmp/pixoo_merlin_uninstall.$$.sh"
  cp -f "${SELF}" "${TMP_UNINSTALL}"
  chmod 755 "${TMP_UNINSTALL}"
  export ADDON_DIR
  export KEEP_CONFIG="${KEEP_CONFIG:-0}"
  export REMOVE_FILES="${REMOVE_FILES:-1}"
  export UNINSTALL_OPKG="${UNINSTALL_OPKG:-0}"
  export FORCE_UNINSTALL="${FORCE_UNINSTALL:-0}"
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

  # Final safety: never rm anything outside /jffs
  case "${ADDON_DIR}" in
    /jffs/*) ;;
    *)
      echo "error: refusing rm -rf outside /jffs (${ADDON_DIR})" >&2
      exit 1
      ;;
  esac
  if [ -z "${ADDON_DIR}" ] || [ "${ADDON_DIR}" = "/" ] || [ "${ADDON_DIR}" = "/jffs" ]; then
    echo "error: refusing dangerous ADDON_DIR=${ADDON_DIR}" >&2
    exit 1
  fi

  # Leave cwd outside the tree before deleting it
  cd /tmp 2>/dev/null || cd / || true
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
echo ""
echo "If your SSH prompt shows « getcwd: No such file or directory », your"
echo "session was still inside the deleted folder. Fix with:"
echo "  cd /"
echo "Next time prefer:"
echo "  cd / && /jffs/addons/pixoo_merlin/uninstall.sh"
