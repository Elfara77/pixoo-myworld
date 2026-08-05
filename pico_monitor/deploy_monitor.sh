#!/usr/bin/env bash
# Interactive / non-interactive deploy of Pico metrics exporter → Asuswrt-Merlin.
#
# Modes:
#   ./deploy_monitor.sh              # menu
#   ./deploy_monitor.sh install      # non-interactive upload+install+start
#   ./deploy_monitor.sh uninstall
#   ./deploy_monitor.sh status
#
# Hosts (do not conflate):
#   PICO_ROUTER_HOST  Merlin LAN IP — SSH deploy + /metrics.json (default 192.168.50.1)
#   PICO_MERLIN_HOST  Pico W LAN IP — ping / flash target check (default 192.168.52.4)
# Firmware config.py ROUTER_HOST must match PICO_ROUTER_HOST.
#
# Merlin BusyBox ash often lacks the `command` builtin — remote scripts use
# `[ -x /path ]` / absolute binaries only. Never source /opt/etc/profile
# (AMTM spam + mydisk.sh cd).
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
MERLIN_SRC="${ROOT}/merlin"
CFG_HOME="${HOME}/.pico_monitor_config"
CFG_PROJECT="${ROOT}/.deploy.env"

# Merlin (SSH + metrics exporter)
ROUTER_HOST="${PICO_ROUTER_HOST:-192.168.50.1}"
# Pico W device (connectivity / docs — not SSH)
PICO_HOST="${PICO_MERLIN_HOST:-192.168.52.4}"
USER_NAME="${PICO_MERLIN_USER:-elphara77}"
REMOTE_PATH="${PICO_MERLIN_PATH:-/jffs/addons/pico_monitor}"
PORT="${PICO_MERLIN_PORT:-22}"
SSH_AUTH="${PICO_SSH_AUTH:-key}"  # key | password
SSH_PASS="${PICO_SSH_PASS:-}"
METRICS_PORT="${PICO_METRICS_PORT:-8088}"

REMOTE_PATH_ENV='export PATH=/opt/bin:/opt/sbin:/opt/usr/bin:/bin:/sbin:/usr/bin:/usr/sbin'

load_config() {
  local f
  for f in "${CFG_PROJECT}" "${CFG_HOME}"; do
    if [[ -f "${f}" ]]; then
      set -a
      while IFS= read -r line || [[ -n "${line}" ]]; do
        case "${line}" in
          ""|\#*) continue ;;
        esac
        if [[ "${line}" == PICO_SSH_PASS=* ]]; then
          continue
        fi
        export "${line?}"
      done < "${f}"
      set +a

      # Prefer explicit PICO_ROUTER_HOST. Legacy: if only PICO_MERLIN_HOST was
      # the router (.50.x) and no router key exists, treat it as router.
      if [[ -n "${PICO_ROUTER_HOST:-}" ]]; then
        ROUTER_HOST="${PICO_ROUTER_HOST}"
      elif [[ -n "${PICO_MERLIN_HOST:-}" && "${PICO_MERLIN_HOST}" == *.50.* ]]; then
        ROUTER_HOST="${PICO_MERLIN_HOST}"
      fi
      PICO_HOST="${PICO_MERLIN_HOST:-$PICO_HOST}"
      # If legacy put router IP into PICO_MERLIN_HOST, keep Pico default
      if [[ "${PICO_HOST}" == "${ROUTER_HOST}" ]]; then
        PICO_HOST="192.168.52.4"
      fi
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
# PICO_ROUTER_HOST = Merlin (SSH + metrics). PICO_MERLIN_HOST = Pico W (ping).
PICO_ROUTER_HOST=${ROUTER_HOST}
PICO_MERLIN_HOST=${PICO_HOST}
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
      echo "error: sshpass required for password auth (brew install sshpass)" >&2
      return 1
    fi
    if [[ -z "${SSH_PASS}" ]]; then
      read -r -s -p "SSH password for ${USER_NAME}@${ROUTER_HOST}: " SSH_PASS
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

TARGET() { echo "${USER_NAME}@${ROUTER_HOST}"; }

remote() {
  ssh_base "$(TARGET)" "${REMOTE_PATH_ENV}
$1"
}

ping_pico() {
  echo "==> ping Pico W ${PICO_HOST}"
  if ping -c 1 -W 2 "${PICO_HOST}" >/dev/null 2>&1 || \
     ping -c 1 -t 2 "${PICO_HOST}" >/dev/null 2>&1; then
    echo "Pico reachable at ${PICO_HOST}"
    return 0
  fi
  echo "Pico NOT reachable at ${PICO_HOST}"
  echo "  → flash firmware/, set WIFI_SSID/PASSWORD, expect LAN IP ${PICO_HOST}"
  echo "  → firmware ROUTER_HOST must be Merlin ${ROUTER_HOST}:${METRICS_PORT}"
  return 1
}

check_prereq() {
  echo "==> prerequisites"
  command -v ssh >/dev/null || { echo "ssh missing"; return 1; }
  command -v rsync >/dev/null || echo "warn: rsync missing — will use scp"
  if [[ "${SSH_AUTH}" == "password" ]]; then
    command -v sshpass >/dev/null || { echo "sshpass missing"; return 1; }
  fi
  [[ -d "${MERLIN_SRC}" ]] || { echo "missing ${MERLIN_SRC}"; return 1; }
  echo "OK router(SSH)=${ROUTER_HOST} pico=${PICO_HOST} user=${USER_NAME}"
  echo "   path=${REMOTE_PATH} metrics_port=${METRICS_PORT} auth=${SSH_AUTH}"
  if remote "echo OK" 2>/dev/null | grep -q OK; then
    echo "SSH Merlin: OK"
  else
    echo "SSH Merlin: FAIL (ssh-copy-id $(TARGET))" >&2
    return 1
  fi
  ping_pico || true
}

configure_router() {
  echo "Merlin = SSH + /metrics.json. Pico = OLED device (not SSH)."
  read -r -p "Merlin/router host [${ROUTER_HOST}]: " v; ROUTER_HOST="${v:-$ROUTER_HOST}"
  read -r -p "Pico W host [${PICO_HOST}]: " v; PICO_HOST="${v:-$PICO_HOST}"
  read -r -p "SSH user [${USER_NAME}]: " v; USER_NAME="${v:-$USER_NAME}"
  read -r -p "Remote path [${REMOTE_PATH}]: " v; REMOTE_PATH="${v:-$REMOTE_PATH}"
  read -r -p "SSH port [${PORT}]: " v; PORT="${v:-$PORT}"
  read -r -p "Metrics HTTP port [${METRICS_PORT}]: " v; METRICS_PORT="${v:-$METRICS_PORT}"
  read -r -p "Auth key/password [${SSH_AUTH}]: " v; SSH_AUTH="${v:-$SSH_AUTH}"
  save_config
  echo "firmware/config.py → ROUTER_HOST=${ROUTER_HOST} ROUTER_PORT=${METRICS_PORT}"
  echo "Pico expected Wi‑Fi IP → ${PICO_HOST}"
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
      "${MERLIN_SRC}/install.sh" \
      "${MERLIN_SRC}/uninstall.sh" \
      "${MERLIN_SRC}/config.example.env" \
      "$(TARGET):${REMOTE_PATH}/"
  fi
  remote "chmod 755 '${REMOTE_PATH}/run.sh' '${REMOTE_PATH}/watchdog.sh' '${REMOTE_PATH}/install.sh' '${REMOTE_PATH}/uninstall.sh'"
  echo "Upload OK"
}

install_remote() {
  echo "==> remote install (opkg python3 + cru + start)"
  remote "PICO_METRICS_PORT=${METRICS_PORT} /bin/sh '${REMOTE_PATH}/install.sh'"
  echo "Install OK — metrics: http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json"
  echo ""
  echo "NOTE: Merlin /metrics.json ≠ OLED pixels."
  echo "  Flash pico_monitor/firmware/ onto Pico W (LAN IP ~ ${PICO_HOST})"
  echo "  config.py: WIFI_* + ROUTER_HOST=${ROUTER_HOST} ROUTER_PORT=${METRICS_PORT}"
}

autostart() {
  echo "==> autostart (cru + services-start) on Merlin ${ROUTER_HOST}"
  remote "
    echo '-- cru --'
    if [ -x /usr/sbin/cru ]; then
      /usr/sbin/cru l
      if /usr/sbin/cru l 2>/dev/null | grep -qi PicoMonitor; then
        echo 'cru: PicoMonitor OK'
      else
        echo 'cru: NO PicoMonitor entry (run menu 4 Install)'
      fi
    else
      echo 'cru: /usr/sbin/cru missing'
    fi
    echo '-- services-start --'
    if [ -f /jffs/scripts/services-start ]; then
      grep -n pico_monitor /jffs/scripts/services-start || echo 'no pico_monitor hook'
    else
      echo 'no services-start file'
    fi
    echo '-- daemon --'
    if [ -x '${REMOTE_PATH}/watchdog.sh' ]; then
      '${REMOTE_PATH}/watchdog.sh' status || true
    else
      echo 'watchdog missing — not installed'
    fi
  "
}

test_metrics() {
  echo "==> GET http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 5 "http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json" | head -c 400
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
  remote "
    if [ -x '${REMOTE_PATH}/uninstall.sh' ]; then
      /bin/sh '${REMOTE_PATH}/uninstall.sh'
    else
      [ -x '${REMOTE_PATH}/watchdog.sh' ] && '${REMOTE_PATH}/watchdog.sh' stop 2>/dev/null || true
      [ -x /usr/sbin/cru ] && /usr/sbin/cru d PicoMonitor 2>/dev/null || true
      if [ -f /jffs/scripts/services-start ]; then
        grep -v pico_monitor /jffs/scripts/services-start > /tmp/ss.\$\$ 2>/dev/null || true
        mv /tmp/ss.\$\$ /jffs/scripts/services-start
        chmod 755 /jffs/scripts/services-start
      fi
      cd / && rm -rf '${REMOTE_PATH}'
      echo removed
    fi
  "
}

status_remote() {
  echo "==> Merlin ${ROUTER_HOST} + Pico ${PICO_HOST}"
  remote "
    echo '-- daemon --'
    if [ -x '${REMOTE_PATH}/watchdog.sh' ]; then
      '${REMOTE_PATH}/watchdog.sh' status 2>/dev/null || echo stopped
    else
      echo 'not installed'
    fi
    echo '-- cru --'
    if [ -x /usr/sbin/cru ]; then
      /usr/sbin/cru l 2>/dev/null | grep -i Pico || echo '(no PicoMonitor cru entry)'
    fi
    echo '-- services-start --'
    grep -n pico_monitor /jffs/scripts/services-start 2>/dev/null || echo '(no hook)'
  "
  test_metrics || true
  ping_pico || true
  echo ""
  echo "OLED blank? Metrics on Merlin do not paint the display."
  echo "  Flash firmware/ → Pico ${PICO_HOST}; ROUTER_HOST=${ROUTER_HOST}:${METRICS_PORT}"
}

menu() {
  load_config
  while true; do
    cat <<EOF

╔══════════════════════════════════════════╗
║  Pico Monitor → Merlin deploy            ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pico W:     ${PICO_HOST}
║  Remote:     ${REMOTE_PATH}
╚══════════════════════════════════════════╝
  1) Prerequisites / SSH + ping Pico
  2) Configure hosts (Merlin + Pico)
  3) Upload merlin package
  4) Install (opkg + cru + start)
  5) Autostart status
  6) Test /metrics.json (Merlin)
  7) Tail logs
  8) Uninstall
  9) Status (Merlin + Pico ping)
  0) Quit

  OLED: Merlin metrics ≠ Pico pixels.
  Flash firmware/ + WIFI + ROUTER_HOST=${ROUTER_HOST}
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
  PICO_ROUTER_HOST  Merlin LAN IP for SSH + metrics (default 192.168.50.1)
  PICO_MERLIN_HOST  Pico W LAN IP for ping/status   (default 192.168.52.4)
  PICO_MERLIN_USER  SSH user on Merlin              (default elphara77)
  PICO_MERLIN_PATH  remote addon path
  PICO_SSH_AUTH     key|password
  PICO_METRICS_PORT metrics HTTP port (default 8088)

Firmware (on Pico): ROUTER_HOST must equal PICO_ROUTER_HOST.
Mac preview: python3 preview.py
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
