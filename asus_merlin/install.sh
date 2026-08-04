#!/bin/sh
# Install Pixoo Merlin monitor on AsusWRT-Merlin (+ Entware).
# Run ON the router as admin (ssh), from this directory or via:
#   sh install.sh
#
# Requires Entware (opkg). Uses python3 — package "python" does NOT exist.
set -eu

ADDON_DIR="/jffs/addons/pixoo_merlin"
CRU_NAME="PixooMerlin"
MARKER="# pixoo_merlin"
SERVICES_START="/jffs/scripts/services-start"

echo "==> Pixoo Merlin install → ${ADDON_DIR}"

if ! command -v opkg >/dev/null 2>&1; then
  echo "error: opkg not found. Install Entware first:" >&2
  echo "  https://github.com/Entware/Entware/wiki/Install-on-Asus-stock-firmware" >&2
  exit 1
fi

echo "==> opkg update"
opkg update

echo "==> opkg install python3 python3-pillow python3-yaml"
# Exact Entware package names — do NOT use "python" (missing on Merlin/Entware).
opkg install python3 python3-pillow python3-yaml

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 still not in PATH after opkg install" >&2
  exit 1
fi

PYTHON3="$(command -v python3)"
echo "==> using ${PYTHON3} ($("${PYTHON3}" --version 2>&1))"

# Resolve source directory (folder containing this script)
SRC="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"

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
