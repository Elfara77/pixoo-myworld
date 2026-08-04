#!/bin/sh
# Install Pixoo Merlin monitor on AsusWRT-Merlin (+ Entware).
# Run ON the router as admin (ssh), from this directory or via:
#   sh install.sh
#
# Requires Entware (opkg). Uses python3 — package "python" does NOT exist.
set -eu

# Resolve package source BEFORE sourcing Entware profile — profile.d scripts
# (e.g. mydisk.sh) may cd to /tmp/mnt/AMTM and would break relative $0 → SRC.
_case0=$0
case "${_case0}" in
  /*) _script=${_case0} ;;
  *) _script="$(pwd)/${_case0}" ;;
esac
SRC="$(CDPATH= cd -- "$(dirname "${_script}")" && pwd)"
unset _case0 _script

# Entware: non-interactive SSH often skips profile, so opkg/python3 are missing from PATH
export PATH="/opt/bin:/opt/sbin:/opt/usr/bin:${PATH}"
if [ -f /opt/etc/profile ]; then
  # shellcheck disable=SC1091
  . /opt/etc/profile
fi

OPKG="$(command -v opkg 2>/dev/null || true)"
if [ -z "${OPKG}" ] && [ -x /opt/bin/opkg ]; then
  OPKG="/opt/bin/opkg"
fi

PYTHON="$(command -v python3 2>/dev/null || true)"
if [ -z "${PYTHON}" ] && [ -x /opt/bin/python3 ]; then
  PYTHON="/opt/bin/python3"
fi

ADDON_DIR="/jffs/addons/pixoo_merlin"
CRU_NAME="PixooMerlin"
MARKER="# pixoo_merlin"
SERVICES_START="/jffs/scripts/services-start"

echo "==> Pixoo Merlin install → ${ADDON_DIR}"

if [ -z "${OPKG}" ] || [ ! -x "${OPKG}" ]; then
  echo "error: opkg not found (Entware required)." >&2
  echo "  Expected at /opt/bin/opkg after Entware install." >&2
  echo "  Guide: https://github.com/Entware/Entware/wiki/Install-on-Asus-stock-firmware" >&2
  echo "  PATH=${PATH}" >&2
  echo "  ls /opt/bin/opkg:" >&2
  ls -la /opt/bin/opkg 2>&1 >&2 || true
  exit 1
fi

echo "==> using opkg at ${OPKG}"
echo "==> opkg update"
"${OPKG}" update

echo "==> opkg install python3 python3-pillow python3-yaml"
# Exact Entware package names — do NOT use "python" (missing on Merlin/Entware).
"${OPKG}" install python3 python3-pillow python3-yaml

# Re-resolve after install (PATH already includes /opt/bin)
PYTHON="$(command -v python3 2>/dev/null || true)"
if [ -z "${PYTHON}" ] && [ -x /opt/bin/python3 ]; then
  PYTHON="/opt/bin/python3"
fi

if [ -z "${PYTHON}" ] || [ ! -x "${PYTHON}" ]; then
  echo "error: python3 still not found after opkg install" >&2
  echo "  PATH=${PATH}" >&2
  echo "  ls /opt/bin/python3:" >&2
  ls -la /opt/bin/python3 2>&1 >&2 || true
  exit 1
fi

echo "==> using ${PYTHON} ($("${PYTHON}" --version 2>&1))"

if [ ! -d "${SRC}/pixoo_merlin" ]; then
  echo "error: package not found at ${SRC}/pixoo_merlin" >&2
  echo "  Run install from /jffs/addons/pixoo_merlin after upload_to_merlin.sh" >&2
  exit 1
fi
echo "==> source package ${SRC}"

echo "==> deploy files to ${ADDON_DIR}"
mkdir -p "${ADDON_DIR}"
# Copy package + setups + helpers (preserve structure)
# Prefer tar to keep permissions; fall back to cp
if command -v tar >/dev/null 2>&1; then
  tar -C "${SRC}" -cf - \
    pixoo_merlin setups \
    run.sh watchdog.sh uninstall.sh config.example.env README.md \
    2>/dev/null | tar -C "${ADDON_DIR}" -xf - 
else
  cp -a "${SRC}/pixoo_merlin" "${ADDON_DIR}/"
  cp -a "${SRC}/setups" "${ADDON_DIR}/"
  cp -f "${SRC}/run.sh" "${SRC}/watchdog.sh" "${SRC}/uninstall.sh" "${ADDON_DIR}/"
  cp -f "${SRC}/config.example.env" "${ADDON_DIR}/"
  [ -f "${SRC}/README.md" ] && cp -f "${SRC}/README.md" "${ADDON_DIR}/"
fi

# Ensure helpers executable
chmod 755 "${ADDON_DIR}/run.sh" "${ADDON_DIR}/watchdog.sh" "${ADDON_DIR}/uninstall.sh" 2>/dev/null || true
chmod 755 "${ADDON_DIR}/install.sh" 2>/dev/null || true
# Keep a copy of install.sh too
cp -f "${SRC}/install.sh" "${ADDON_DIR}/install.sh" 2>/dev/null || true
chmod 755 "${ADDON_DIR}/install.sh" 2>/dev/null || true

if [ ! -f "${ADDON_DIR}/config.env" ]; then
  echo "==> create config.env (edit PIXOO_IP !)"
  cp -f "${ADDON_DIR}/config.example.env" "${ADDON_DIR}/config.env"
  echo "    → ${ADDON_DIR}/config.env"
else
  echo "==> keep existing config.env"
fi

mkdir -p "${ADDON_DIR}/logs" "${ADDON_DIR}/run"

# cru watchdog every minute
if command -v cru >/dev/null 2>&1; then
  echo "==> register cru watchdog (${CRU_NAME})"
  cru d "${CRU_NAME}" 2>/dev/null || true
  cru a "${CRU_NAME}" "*/1 * * * * ${ADDON_DIR}/watchdog.sh"
else
  echo "warn: cru not found — add crontab manually for ${ADDON_DIR}/watchdog.sh" >&2
fi

# services-start hook (boot)
echo "==> services-start hook"
mkdir -p "$(dirname "${SERVICES_START}")"
if [ ! -f "${SERVICES_START}" ]; then
  printf '%s\n' "#!/bin/sh" > "${SERVICES_START}"
  chmod 755 "${SERVICES_START}"
fi
# Remove old marker lines then append
if grep -q "${MARKER}" "${SERVICES_START}" 2>/dev/null; then
  # portable strip
  tmp="${SERVICES_START}.tmp.$$"
  grep -v "${MARKER}" "${SERVICES_START}" > "${tmp}" || true
  mv "${tmp}" "${SERVICES_START}"
  chmod 755 "${SERVICES_START}"
fi
printf '%s\n' "${ADDON_DIR}/watchdog.sh ${MARKER}" >> "${SERVICES_START}"
chmod 755 "${SERVICES_START}"

echo "==> start daemon"
"${ADDON_DIR}/watchdog.sh" || true

echo ""
echo "Install OK."
echo "  1. Edit ${ADDON_DIR}/config.env  (PIXOO_IP=...  SETUP=default)"
echo "  2. Restart: ${ADDON_DIR}/watchdog.sh"
echo "  3. Logs:    ${ADDON_DIR}/logs/merlin.log"
echo "  4. Uninstall: ${ADDON_DIR}/uninstall.sh"
echo ""
echo "opkg packages left installed: python3 python3-pillow python3-yaml"
