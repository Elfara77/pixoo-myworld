#!/usr/bin/env bash
# Interactive / non-interactive deploy of Pico metrics exporter → Asuswrt-Merlin.
#
# Modes:
#   ./deploy_monitor.sh              # menu
#   ./deploy_monitor.sh install      # non-interactive upload+install+start
#   ./deploy_monitor.sh uninstall
#   ./deploy_monitor.sh status
#
# Auth: SSH keys (BatchMode) preferred — same as asus_merlin/upload_to_merlin.sh.
# Optional password mode via sshpass if SSH_AUTH=password.
#
# Defaults: host 192.168.50.1, user elphara77, remote /jffs/addons/pico_monitor
# (/jffs preferred over /opt — survives Entware reinstall; matches pixoo_merlin layout)
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
MERLIN_SRC="${ROOT}/merlin"
CFG_HOME="${HOME}/.pico_monitor_config"
CFG_PROJECT="${ROOT}/.deploy.env"

HOST="${PICO_MERLIN_HOST:-192.168.50.1}"
USER_NAME="${PICO_MERLIN_USER:-elphara77}"
REMOTE_PATH="${PICO_MERLIN_PATH:-/jffs/addons/pico_monitor}"
PORT="${PICO_MERLIN_PORT:-22}"
SSH_AUTH="${PICO_SSH_AUTH:-key}"  # key | password
SSH_PASS="${PICO_SSH_PASS:-}"
METRICS_PORT="${PICO_METRICS_PORT:-8088}"

load_config() {
  local f
  for f in "${CFG_PROJECT}" "${CFG_HOME}"; do
    if [[ -f "${f}" ]]; then
      # shellcheck disable=SC1090
      set -a
      # only KEY=VAL, no password required in file
      while IFS= read -r line || [[ -n "${line}" ]]; do
        case "${line}" in
          ""|\#*) continue ;;
        esac
        if [[ "${line}" == PICO_SSH_PASS=* ]]; then
          continue  # never auto-load password from disk
        fi
        export "${line?}"
      done < "${f}"
      set +a
      HOST="${PICO_MERLIN_HOST:-$HOST}"
      USER_NAME="${PICO_MERLIN_USER:-$USER_NAME}"
      REMOTE_PATH="${PICO_MERLIN_PATH:-$REMOTE_PATH}"
      PORT="${PICO_MERLIN_PORT:-$PORT}"
      SSH_AUTH="${PICO_SSH_AUTH:-$SSH_AUTH}"
      METRICS_PORT="${PICO_METRICS_PORT:-$METRICS_PORT}"
      break
    fi
  done
}

save_config() {
  mkdir -p "$(dirname "${CFG_HOME}")"
  cat > "${CFG_PROJECT}" <<EOF
# Pico monitor deploy (no passwords stored)
PICO_MERLIN_HOST=${HOST}
PICO_MERLIN_USER=${USER_NAME}
PICO_MERLIN_PATH=${REMOTE_PATH}
PICO_MERLIN_PORT=${PORT}
PICO_SSH_AUTH=${SSH_AUTH}
PICO_METRICS_PORT=${METRICS_PORT}
EOF
  cp -f "${CFG_PROJECT}" "${CFG_HOME}"
  echo "Saved ${CFG_PROJECT} and ${CFG_HOME}"
}

ssh_base() {
  local -a cmd=(ssh -p "${PORT}" -o ConnectTimeout=8)
  if [[ "${SSH_AUTH}" == "key" ]]; then
    cmd+=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
  else
    cmd+=(-o StrictHostKeyChecking=accept-new)
  fi
  if [[ "${SSH_AUTH}" == "password" ]]; then
    if ! command -v sshpass >/dev/null 2>&1; then
      echo "error: sshpass required for password auth (brew install sshpass / apt install sshpass)" >&2
      return 1
    fi
    if [[ -z "${SSH_PASS}" ]]; then
      read -r -s -p "SSH password for ${USER_NAME}@${HOST}: " SSH_PASS
      echo
    fi
    sshpass -p "${SSH_PASS}" "${cmd[@]}" "$@"
  else
    "${cmd[@]}" "$@"
  fi
}

scp_base() {
  local -a cmd=(scp -P "${PORT}" -o ConnectTimeout=8)
  if [[ "${SSH_AUTH}" == "key" ]]; then
    cmd+=(-o BatchMode=yes)
  fi
  if [[ "${SSH_AUTH}" == "password" ]]; then
    sshpass -p "${SSH_PASS}" "${cmd[@]}" "$@"
  else
    "${cmd[@]}" "$@"
  fi
}

TARGET() { echo "${USER_NAME}@${HOST}"; }

remote() {
  ssh_base "$(TARGET)" "$@"
}

check_prereq() {
  echo "==> prerequisites"
  command -v ssh >/dev/null || { echo "ssh missing"; return 1; }
  command -v rsync >/dev/null || echo "warn: rsync missing — will use scp"
  if [[ "${SSH_AUTH}" == "password" ]]; then
    command -v sshpass >/dev/null || { echo "sshpass missing"; return 1; }
  fi
  [[ -d "${MERLIN_SRC}" ]] || { echo "missing ${MERLIN_SRC}"; return 1; }
  echo "OK host=${HOST} user=${USER_NAME} path=${REMOTE_PATH} auth=${SSH_AUTH}"
  if remote "echo OK" 2>/dev/null | grep -q OK; then
    echo "SSH connectivity: OK"
  else
    echo "SSH connectivity: FAIL (check key: ssh-copy-id $(TARGET))" >&2
    return 1
  fi
}

configure_router() {
  read -r -p "Host [${HOST}]: " v; HOST="${v:-$HOST}"
  read -r -p "User [${USER_NAME}]: " v; USER_NAME="${v:-$USER_NAME}"
  read -r -p "Remote path [${REMOTE_PATH}]: " v; REMOTE_PATH="${v:-$REMOTE_PATH}"
  read -r -p "SSH port [${PORT}]: " v; PORT="${v:-$PORT}"
  read -r -p "Metrics HTTP port [${METRICS_PORT}]: " v; METRICS_PORT="${v:-$METRICS_PORT}"
  read -r -p "Auth key/password [${SSH_AUTH}]: " v; SSH_AUTH="${v:-$SSH_AUTH}"
  save_config
}

upload() {
  echo "==> upload → $(TARGET):${REMOTE_PATH}"
  remote "mkdir -p '${REMOTE_PATH}' '${REMOTE_PATH}/run' '${REMOTE_PATH}/logs'"
  if command -v rsync >/dev/null 2>&1; then
    local rssh="ssh -p ${PORT}"
    [[ "${SSH_AUTH}" == "key" ]] && rssh="${rssh} -o BatchMode=yes"
    if [[ "${SSH_AUTH}" == "password" ]]; then
      sshpass -p "${SSH_PASS}" rsync -az --delete \
        --exclude 'logs/' --exclude 'run/' --exclude 'config.env' \
        -e "${rssh}" \
        "${MERLIN_SRC}/" "$(TARGET):${REMOTE_PATH}/"
    else
      rsync -az --delete \
        --exclude 'logs/' --exclude 'run/' --exclude 'config.env' \
        -e "${rssh}" \
        "${MERLIN_SRC}/" "$(TARGET):${REMOTE_PATH}/"
    fi
  else
    scp_base -r \
      "${MERLIN_SRC}/metrics_server.py" \
      "${MERLIN_SRC}/run.sh" \
      "${MERLIN_SRC}/watchdog.sh" \
      "${MERLIN_SRC}/config.example.env" \
      "$(TARGET):${REMOTE_PATH}/"
  fi
  remote "chmod 755 '${REMOTE_PATH}/run.sh' '${REMOTE_PATH}/watchdog.sh'"
  echo "Upload OK"
}

install_remote() {
  echo "==> remote install (opkg python3 + config + cru)"
  remote "export PATH=/opt/bin:/opt/sbin:\$PATH
    [ -f /opt/etc/profile ] && . /opt/etc/profile
    OPKG=\$(command -v opkg || echo /opt/bin/opkg)
    \$OPKG update >/dev/null 2>&1 || true
    \$OPKG install python3
    if [ ! -f '${REMOTE_PATH}/config.env' ]; then
      cp '${REMOTE_PATH}/config.example.env' '${REMOTE_PATH}/config.env'
    fi
    # ensure port
    grep -q PICO_METRICS_PORT '${REMOTE_PATH}/config.env' 2>/dev/null || \
      echo PICO_METRICS_PORT=${METRICS_PORT} >> '${REMOTE_PATH}/config.env'
    sed -i 's/^PICO_METRICS_PORT=.*/PICO_METRICS_PORT=${METRICS_PORT}/' '${REMOTE_PATH}/config.env' 2>/dev/null || true
    chmod 755 '${REMOTE_PATH}/run.sh' '${REMOTE_PATH}/watchdog.sh'
    if command -v cru >/dev/null 2>&1; then
      cru d PicoMonitor 2>/dev/null || true
      cru a PicoMonitor \"*/1 * * * * ${REMOTE_PATH}/watchdog.sh\"
    fi
    SS=/jffs/scripts/services-start
    mkdir -p /jffs/scripts
    [ -f \$SS ] || { echo '#!/bin/sh' > \$SS; chmod 755 \$SS; }
    grep -q pico_monitor \$SS 2>/dev/null || echo '${REMOTE_PATH}/watchdog.sh # pico_monitor' >> \$SS
    ${REMOTE_PATH}/watchdog.sh reload || ${REMOTE_PATH}/watchdog.sh start
  "
  echo "Install OK — metrics: http://${HOST}:${METRICS_PORT}/metrics.json"
  echo "Set firmware/config.py ROUTER_HOST=${HOST} ROUTER_PORT=${METRICS_PORT}"
}

autostart() {
  remote "command -v cru >/dev/null && cru l | grep -i Pico || echo 'no cru entry'
    grep -n pico_monitor /jffs/scripts/services-start 2>/dev/null || echo 'no services-start hook'"
}

test_metrics() {
  echo "==> GET http://${HOST}:${METRICS_PORT}/metrics.json"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 5 "http://${HOST}:${METRICS_PORT}/metrics.json" | head -c 400
    echo
  else
    remote "wget -qO- http://127.0.0.1:${METRICS_PORT}/metrics.json 2>/dev/null | head -c 400; echo"
  fi
}

show_logs() {
  remote "tail -n 40 '${REMOTE_PATH}/logs/pico_metrics.log' 2>/dev/null || echo '(no log yet)'"
}

uninstall_remote() {
  echo "==> uninstall ${REMOTE_PATH}"
  remote "export PATH=/opt/bin:\$PATH
    ${REMOTE_PATH}/watchdog.sh stop 2>/dev/null || true
    cru d PicoMonitor 2>/dev/null || true
    if [ -f /jffs/scripts/services-start ]; then
      grep -v pico_monitor /jffs/scripts/services-start > /tmp/ss.$$ 2>/dev/null || true
      mv /tmp/ss.$$ /jffs/scripts/services-start
      chmod 755 /jffs/scripts/services-start
    fi
    cd / && rm -rf '${REMOTE_PATH}'
    echo removed
  "
}

status_remote() {
  remote "${REMOTE_PATH}/watchdog.sh status 2>/dev/null || echo 'not installed'
    echo ---
    cru l 2>/dev/null | grep -i Pico || true
  "
  test_metrics || true
}

menu() {
  load_config
  while true; do
    cat <<EOF

╔══════════════════════════════════════════╗
║  Pico Monitor → Merlin deploy            ║
║  ${USER_NAME}@${HOST}:${REMOTE_PATH}
╚══════════════════════════════════════════╝
  1) Prerequisites / SSH check
  2) Configure router target
  3) Upload merlin package
  4) Install (opkg + cru + start)
  5) Autostart status
  6) Test /metrics.json
  7) Tail logs
  8) Uninstall
  9) Status
  0) Quit
EOF
    read -r -p "Choice: " c
    case "${c}" in
      1) check_prereq || true ;;
      2) configure_router ;;
      3) upload ;;
      4) upload; install_remote ;;
      5) autostart ;;
      6) test_metrics ;;
      7) show_logs ;;
      8) uninstall_remote ;;
      9) status_remote ;;
      0|q|Q) exit 0 ;;
      *) echo "?" ;;
    esac
  done
}

usage() {
  cat <<EOF
Usage: $0 [install|uninstall|status|menu]

Env / .deploy.env:
  PICO_MERLIN_HOST  (default 192.168.50.1)
  PICO_MERLIN_USER  (default elphara77)
  PICO_MERLIN_PATH  (default /jffs/addons/pico_monitor)
  PICO_SSH_AUTH     key|password (default key)
  PICO_METRICS_PORT (default 8088)
EOF
}

load_config
CMD="${1:-menu}"
case "${CMD}" in
  -h|--help|help) usage ;;
  menu) menu ;;
  install) check_prereq; upload; install_remote ;;
  uninstall) uninstall_remote ;;
  status) status_remote ;;
  upload) upload ;;
  test) test_metrics ;;
  *) usage; exit 2 ;;
esac
