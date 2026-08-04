#!/usr/bin/env bash
# Upload asus_merlin package from Mac/dev → AsusWRT-Merlin router.
#
# Usage:
#   ./upload_to_merlin.sh
#   ./upload_to_merlin.sh --install
#   ./upload_to_merlin.sh --host 192.168.1.1 --user admin --install
#   MERLIN_HOST=router.lan MERLIN_USER=elphara77 ./upload_to_merlin.sh --install
#
# Env (overridden by flags):
#   MERLIN_HOST   router IP/hostname   (required unless --host)
#   MERLIN_USER   SSH user             (default: admin)
#   MERLIN_PATH   remote directory     (default: /jffs/addons/pixoo_merlin)
#   MERLIN_PORT   SSH port             (default: 22)
#   MERLIN_SSH    extra ssh options
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
HOST="${MERLIN_HOST:-}"
USER_NAME="${MERLIN_USER:-admin}"
REMOTE_PATH="${MERLIN_PATH:-/jffs/addons/pixoo_merlin}"
PORT="${MERLIN_PORT:-22}"
DO_INSTALL=0
SSH_OPTS=${MERLIN_SSH:-}

usage() {
  cat <<'EOF'
Upload Pixoo Merlin files to an AsusWRT-Merlin router.

Usage:
  ./upload_to_merlin.sh [options]

Options:
  --host HOST       Router IP/hostname (or MERLIN_HOST)
  --user USER       SSH user (default: admin, or MERLIN_USER)
  --path PATH       Remote dir (default: /jffs/addons/pixoo_merlin)
  --port PORT       SSH port (default: 22)
  --install         After upload, ssh and run install.sh on the router
  -h, --help        This help

Examples:
  MERLIN_HOST=192.168.1.1 ./upload_to_merlin.sh --install
  ./upload_to_merlin.sh --host 192.168.50.1 --user elphara77 --install
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --user) USER_NAME="${2:-}"; shift 2 ;;
    --path) REMOTE_PATH="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --install) DO_INSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "${HOST}" ]]; then
  echo "error: set MERLIN_HOST or pass --host" >&2
  usage
  exit 2
fi

SSH=(ssh -p "${PORT}")
SCP=(scp -P "${PORT}")
# shellcheck disable=SC2206
[[ -n "${SSH_OPTS}" ]] && SSH+=(${SSH_OPTS}) && SCP+=(${SSH_OPTS})

TARGET="${USER_NAME}@${HOST}"
echo "==> target ${TARGET}:${REMOTE_PATH}"

# Files / dirs to sync (keep install helpers + package + setups)
INCLUDE=(
  pixoo_merlin
  setups
  install.sh
  uninstall.sh
  run.sh
  watchdog.sh
  upload_to_merlin.sh
  config.example.env
  README.md
)

for item in "${INCLUDE[@]}"; do
  if [[ ! -e "${ROOT}/${item}" ]]; then
    echo "warn: missing ${item} (skip)" >&2
  fi
done

echo "==> ensure remote directory"
"${SSH[@]}" "${TARGET}" "mkdir -p '${REMOTE_PATH}'"

if command -v rsync >/dev/null 2>&1; then
  echo "==> rsync → ${TARGET}:${REMOTE_PATH}/"
  RSYNC_SSH="ssh -p ${PORT}"
  [[ -n "${SSH_OPTS}" ]] && RSYNC_SSH="${RSYNC_SSH} ${SSH_OPTS}"
  # shellcheck disable=SC2086
  rsync -az --delete \
    --exclude 'previews/' \
    --exclude 'logs/' \
    --exclude 'run/' \
    --exclude 'config.env' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    -e "${RSYNC_SSH}" \
    "${ROOT}/pixoo_merlin" \
    "${ROOT}/setups" \
    "${ROOT}/install.sh" \
    "${ROOT}/uninstall.sh" \
    "${ROOT}/run.sh" \
    "${ROOT}/watchdog.sh" \
    "${ROOT}/config.example.env" \
    "${ROOT}/README.md" \
    "${TARGET}:${REMOTE_PATH}/"
  # optional local helper kept on remote for reference
  if [[ -f "${ROOT}/upload_to_merlin.sh" ]]; then
    rsync -az -e "${RSYNC_SSH}" "${ROOT}/upload_to_merlin.sh" "${TARGET}:${REMOTE_PATH}/"
  fi
else
  echo "==> scp (rsync not found)"
  TMP_REMOTE="/tmp/pixoo_merlin_upload_$$"
  "${SSH[@]}" "${TARGET}" "rm -rf '${TMP_REMOTE}' && mkdir -p '${TMP_REMOTE}'"
  "${SCP[@]}" -r \
    "${ROOT}/pixoo_merlin" \
    "${ROOT}/setups" \
    "${ROOT}/install.sh" \
    "${ROOT}/uninstall.sh" \
    "${ROOT}/run.sh" \
    "${ROOT}/watchdog.sh" \
    "${ROOT}/config.example.env" \
    "${ROOT}/README.md" \
    "${TARGET}:${TMP_REMOTE}/"
  "${SSH[@]}" "${TARGET}" \
    "mkdir -p '${REMOTE_PATH}' && \
     cp -a '${TMP_REMOTE}/'* '${REMOTE_PATH}/' && \
     rm -rf '${TMP_REMOTE}'"
fi

echo "==> chmod +x scripts"
"${SSH[@]}" "${TARGET}" "chmod 755 '${REMOTE_PATH}/install.sh' '${REMOTE_PATH}/uninstall.sh' '${REMOTE_PATH}/run.sh' '${REMOTE_PATH}/watchdog.sh' 2>/dev/null || true"

if [[ "${DO_INSTALL}" -eq 1 ]]; then
  echo "==> remote install.sh (opkg python3 python3-pillow python3-yaml)"
  "${SSH[@]}" "${TARGET}" "cd '${REMOTE_PATH}' && ./install.sh"
  echo ""
  echo "Next: edit config if needed:"
  echo "  ssh ${TARGET} vi ${REMOTE_PATH}/config.env"
else
  echo ""
  echo "Upload OK. On the router run:"
  echo "  ssh ${TARGET}"
  echo "  cd ${REMOTE_PATH} && ./install.sh"
  echo "Or re-run: $0 --host ${HOST} --user ${USER_NAME} --install"
fi
