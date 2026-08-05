#!/usr/bin/env bash
# Interactive / non-interactive deploy of Pico metrics exporter → Asuswrt-Merlin.
#
# Modes:
#   ./deploy_monitor.sh              # arrow-key menu (+ number fallback)
#   ./deploy_monitor.sh install      # non-interactive upload+install+start
#   ./deploy_monitor.sh uninstall
#   ./deploy_monitor.sh status
#   ./deploy_monitor.sh auto         # full pipeline (uninstall→upload→install→flash→run)
#   ./deploy_monitor.sh pilot        # remote pilotage submenu
#   ./deploy_monitor.sh start|stop|cron-on|cron-off
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
FIRMWARE_SRC="${ROOT}/firmware"
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

# Live status flags (yes|no|?) refreshed by compute_status
ST_SSH="?"
ST_UPLOADED="?"
ST_INSTALLED="?"
ST_RUNNING="?"
ST_CRU="?"
ST_METRICS="?"
ST_PICO="?"
ST_DETAIL_PID=""
ST_DETAIL_CRU=""

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

# --- status helpers ----------------------------------------------------------

mark_yes_no() {
  # $1 = yes|no|?
  case "${1}" in
    yes) printf '%s' 'YES' ;;
    no)  printf '%s' 'no ' ;;
    *)   printf '%s' '?  ' ;;
  esac
}

pico_ping_ok() {
  if ping -c 1 -W 2 "${PICO_HOST}" >/dev/null 2>&1; then
    return 0
  fi
  # macOS ping uses -t for timeout
  ping -c 1 -t 2 "${PICO_HOST}" >/dev/null 2>&1
}

metrics_http_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 4 "http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json" >/dev/null 2>&1
    return $?
  fi
  remote "wget -qO- --timeout=4 http://127.0.0.1:${METRICS_PORT}/metrics.json >/dev/null 2>&1" 2>/dev/null
}

# Probe Merlin + Pico; fills ST_* globals. Quiet (no chatter).
compute_status() {
  ST_SSH="?"
  ST_UPLOADED="?"
  ST_INSTALLED="?"
  ST_RUNNING="?"
  ST_CRU="?"
  ST_METRICS="?"
  ST_PICO="?"
  ST_DETAIL_PID=""
  ST_DETAIL_CRU=""

  if pico_ping_ok; then
    ST_PICO="yes"
  else
    ST_PICO="no"
  fi

  local blob
  if ! blob="$(remote "
    echo SSH_OK
    if [ -f '${REMOTE_PATH}/metrics_server.py' ] && [ -f '${REMOTE_PATH}/watchdog.sh' ]; then
      echo UPLOADED_YES
    else
      echo UPLOADED_NO
    fi
    if [ -x '${REMOTE_PATH}/watchdog.sh' ] && [ -x '${REMOTE_PATH}/install.sh' ]; then
      echo INSTALLED_YES
    else
      echo INSTALLED_NO
    fi
    if [ -x '${REMOTE_PATH}/watchdog.sh' ]; then
      out=\$( '${REMOTE_PATH}/watchdog.sh' status 2>/dev/null || true )
      echo \"WATCHDOG:\$out\"
      case \"\$out\" in
        *running*|*'pid='*) echo RUNNING_YES ;;
        *) echo RUNNING_NO ;;
      esac
    else
      echo RUNNING_NO
    fi
    if [ -x /usr/sbin/cru ] && /usr/sbin/cru l 2>/dev/null | grep -qi PicoMonitor; then
      echo CRU_YES
      /usr/sbin/cru l 2>/dev/null | grep -i PicoMonitor | head -n1
    else
      echo CRU_NO
    fi
    if [ -f /jffs/scripts/services-start ] && grep -q pico_monitor /jffs/scripts/services-start 2>/dev/null; then
      echo SVC_YES
    else
      echo SVC_NO
    fi
  " 2>/dev/null)"; then
    ST_SSH="no"
    ST_UPLOADED="?"
    ST_INSTALLED="?"
    ST_RUNNING="?"
    ST_CRU="?"
    if metrics_http_ok; then ST_METRICS="yes"; else ST_METRICS="no"; fi
    return 0
  fi

  ST_SSH="yes"
  echo "${blob}" | grep -q UPLOADED_YES && ST_UPLOADED="yes" || ST_UPLOADED="no"
  echo "${blob}" | grep -q INSTALLED_YES && ST_INSTALLED="yes" || ST_INSTALLED="no"
  echo "${blob}" | grep -q RUNNING_YES && ST_RUNNING="yes" || ST_RUNNING="no"
  if echo "${blob}" | grep -q CRU_YES; then
    ST_CRU="yes"
  elif echo "${blob}" | grep -q SVC_YES; then
    ST_CRU="yes"
  else
    ST_CRU="no"
  fi
  ST_DETAIL_PID="$(echo "${blob}" | sed -n 's/^WATCHDOG://p' | head -n1)"
  ST_DETAIL_CRU="$(echo "${blob}" | grep -i PicoMonitor | head -n1 || true)"

  if metrics_http_ok; then
    ST_METRICS="yes"
  else
    ST_METRICS="no"
  fi
}

render_status_block() {
  printf '%s\n' "── Status ─────────────────────────────────────────"
  printf '  Merlin SSH   %s  %s@%s:%s\n' "$(mark_yes_no "${ST_SSH}")" "${USER_NAME}" "${ROUTER_HOST}" "${PORT}"
  printf '  Uploaded     %s  %s\n' "$(mark_yes_no "${ST_UPLOADED}")" "${REMOTE_PATH}"
  printf '  Installed    %s  watchdog/install present\n' "$(mark_yes_no "${ST_INSTALLED}")"
  printf '  Running      %s  %s\n' "$(mark_yes_no "${ST_RUNNING}")" "${ST_DETAIL_PID:-daemon}"
  printf '  Autostart    %s  cru/services-start\n' "$(mark_yes_no "${ST_CRU}")"
  printf '  Metrics HTTP %s  http://%s:%s/metrics.json\n' "$(mark_yes_no "${ST_METRICS}")" "${ROUTER_HOST}" "${METRICS_PORT}"
  printf '  Pico ping    %s  %s (PICO_MERLIN_HOST)\n' "$(mark_yes_no "${ST_PICO}")" "${PICO_HOST}"
  printf '%s\n' "──────────────────────────────────────────────────"
}

ping_pico() {
  echo "==> ping Pico W ${PICO_HOST}"
  if pico_ping_ok; then
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

start_watchdog() {
  echo "==> start/reload watchdog on Merlin ${ROUTER_HOST}"
  remote "
    if [ -x '${REMOTE_PATH}/watchdog.sh' ]; then
      '${REMOTE_PATH}/watchdog.sh' reload 2>/dev/null || '${REMOTE_PATH}/watchdog.sh' start
      '${REMOTE_PATH}/watchdog.sh' status || true
    else
      echo 'watchdog missing — run upload + install first' >&2
      exit 1
    fi
  "
}

stop_watchdog() {
  echo "==> stop watchdog on Merlin ${ROUTER_HOST}"
  remote "
    if [ -x '${REMOTE_PATH}/watchdog.sh' ]; then
      '${REMOTE_PATH}/watchdog.sh' stop
      '${REMOTE_PATH}/watchdog.sh' status 2>/dev/null || echo stopped
    else
      echo 'watchdog missing — nothing to stop'
    fi
  "
}

cron_on() {
  echo "==> cron ON (cru a PicoMonitor) on Merlin ${ROUTER_HOST}"
  remote "
    if [ ! -x /usr/sbin/cru ]; then
      echo 'error: /usr/sbin/cru missing' >&2
      exit 1
    fi
    if [ ! -x '${REMOTE_PATH}/watchdog.sh' ]; then
      echo 'error: watchdog missing — run upload + install first' >&2
      exit 1
    fi
    /usr/sbin/cru d PicoMonitor 2>/dev/null || true
    /usr/sbin/cru a PicoMonitor '*/1 * * * * ${REMOTE_PATH}/watchdog.sh'
    echo '-- cru --'
    /usr/sbin/cru l 2>/dev/null | grep -i PicoMonitor || /usr/sbin/cru l
    echo 'cron: PicoMonitor ON'
  "
}

cron_off() {
  echo "==> cron OFF (cru d PicoMonitor) on Merlin ${ROUTER_HOST}"
  remote "
    if [ ! -x /usr/sbin/cru ]; then
      echo 'error: /usr/sbin/cru missing' >&2
      exit 1
    fi
    /usr/sbin/cru d PicoMonitor 2>/dev/null || true
    echo '-- cru --'
    if /usr/sbin/cru l 2>/dev/null | grep -qi PicoMonitor; then
      /usr/sbin/cru l 2>/dev/null | grep -i PicoMonitor
      echo 'warn: PicoMonitor entry still present'
    else
      echo '(no PicoMonitor cru entry)'
      echo 'cron: PicoMonitor OFF'
    fi
  "
}

# Detailed remote state for pilotage (pid, cru, services-start, metrics, Pico)
pilot_status() {
  echo "==> État détaillé — Merlin ${ROUTER_HOST} + Pico ${PICO_HOST}"
  compute_status
  render_status_block
  echo ""
  remote "
    echo '-- daemon (pid) --'
    if [ -x '${REMOTE_PATH}/watchdog.sh' ]; then
      '${REMOTE_PATH}/watchdog.sh' status 2>/dev/null || echo stopped
      if [ -f '${REMOTE_PATH}/run/pico_metrics.pid' ]; then
        echo \"pidfile=\$(cat '${REMOTE_PATH}/run/pico_metrics.pid' 2>/dev/null)\"
      fi
    else
      echo 'not installed (no watchdog.sh)'
    fi
    echo '-- cru --'
    if [ -x /usr/sbin/cru ]; then
      /usr/sbin/cru l 2>/dev/null | grep -i PicoMonitor || echo '(no PicoMonitor cru entry)'
    else
      echo 'cru missing'
    fi
    echo '-- services-start --'
    if [ -f /jffs/scripts/services-start ]; then
      grep -n pico_monitor /jffs/scripts/services-start 2>/dev/null || echo '(no pico_monitor hook)'
    else
      echo '(no services-start file)'
    fi
    echo '-- metrics local --'
    if [ -x /opt/bin/wget ]; then
      /opt/bin/wget -qO- --timeout=4 http://127.0.0.1:${METRICS_PORT}/metrics.json 2>/dev/null | head -c 120
      echo
    elif [ -x /usr/bin/wget ]; then
      /usr/bin/wget -qO- --timeout=4 http://127.0.0.1:${METRICS_PORT}/metrics.json 2>/dev/null | head -c 120
      echo
    else
      echo '(wget unavailable on router — use local curl below)'
    fi
  " 2>/dev/null || echo "(SSH unavailable — local probes only)"
  echo ""
  echo "-- metrics HTTP (from this host) --"
  if metrics_http_ok; then
    echo "YES  http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json"
  else
    echo "no   http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json"
  fi
  echo "-- Pico ping (PICO_MERLIN_HOST=${PICO_HOST}) --"
  if pico_ping_ok; then
    echo "YES  ${PICO_HOST}"
  else
    echo "no   ${PICO_HOST}"
  fi
}

# Ping Pico + optional HTTP; note that metrics live on Merlin (Pico is client)
test_link_pico() {
  echo "==> Test link Pico (PICO_MERLIN_HOST=${PICO_HOST})"
  echo "    Merlin metrics target: ${ROUTER_HOST}:${METRICS_PORT} (PICO_ROUTER_HOST)"
  echo ""
  if pico_ping_ok; then
    echo "ping: OK — Pico reachable at ${PICO_HOST}"
  else
    echo "ping: FAIL — Pico NOT reachable at ${PICO_HOST}"
    echo "  → check Wi‑Fi / flash firmware / PICO_MERLIN_HOST"
  fi
  echo ""
  echo "-- optional HTTP on Pico (usually none — Pico pulls metrics, does not serve them) --"
  local http_ok=0
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 3 "http://${PICO_HOST}/" >/dev/null 2>&1 \
      || curl -fsS --max-time 3 "http://${PICO_HOST}:${METRICS_PORT}/metrics.json" >/dev/null 2>&1; then
      http_ok=1
    fi
  fi
  if (( http_ok )); then
    echo "HTTP: something answered on Pico (unexpected but OK)"
  else
    echo "HTTP: no listener on Pico (expected) — OLED firmware fetches Merlin /metrics.json"
  fi
  echo ""
  echo "Note (Pico perspective): firmware ROUTER_HOST must be ${ROUTER_HOST}"
  echo "  and ROUTER_PORT=${METRICS_PORT}. Metrics are on Merlin, not on the Pico."
  echo ""
  if metrics_http_ok; then
    echo "Merlin /metrics.json: reachable from this host (what Pico should poll)"
  else
    echo "Merlin /metrics.json: NOT reachable from this host — Pico will show ROUTER OFFLINE"
  fi
  pico_ping_ok
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
        echo 'cru: NO PicoMonitor entry (run Install)'
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

# Soft clean: stop daemon + wipe remote tree without requiring uninstall.sh
clean_remote() {
  echo "==> clean remote ${REMOTE_PATH}"
  remote "
    [ -x '${REMOTE_PATH}/watchdog.sh' ] && '${REMOTE_PATH}/watchdog.sh' stop 2>/dev/null || true
    [ -x /usr/sbin/cru ] && /usr/sbin/cru d PicoMonitor 2>/dev/null || true
    if [ -f /jffs/scripts/services-start ]; then
      grep -v pico_monitor /jffs/scripts/services-start > /tmp/ss.\$\$ 2>/dev/null || true
      mv /tmp/ss.\$\$ /jffs/scripts/services-start
      chmod 755 /jffs/scripts/services-start 2>/dev/null || true
    fi
    cd / && rm -rf '${REMOTE_PATH}'
    echo 'clean OK'
  " || true
}

# Flash / sync firmware onto Pico (USB via mpremote/rshell if present)
flash_pico() {
  echo "==> Pico firmware (LAN target ${PICO_HOST})"
  echo "  Merlin metrics host for config.py: ROUTER_HOST=${ROUTER_HOST} ROUTER_PORT=${METRICS_PORT}"
  echo ""
  if [[ ! -d "${FIRMWARE_SRC}" ]]; then
    echo "error: missing ${FIRMWARE_SRC}" >&2
    return 1
  fi

  local tool=""
  if command -v mpremote >/dev/null 2>&1; then
    tool="mpremote"
  elif command -v rshell >/dev/null 2>&1; then
    tool="rshell"
  fi

  if [[ "${tool}" == "mpremote" ]]; then
    echo "Detected mpremote — syncing firmware/ to Pico (USB)…"
    echo "  Ensure Pico is connected over USB (not only Wi‑Fi)."
    if mpremote cp -r "${FIRMWARE_SRC}/." :; then
      echo "mpremote sync OK — soft-reset recommended: mpremote reset"
      mpremote reset 2>/dev/null || true
      return 0
    fi
    echo "mpremote sync failed (device busy / wrong port?). Manual steps below."
  elif [[ "${tool}" == "rshell" ]]; then
    echo "Detected rshell — copy firmware manually, e.g.:"
    echo "  rshell -p /dev/tty.usbmodem* cp -r ${FIRMWARE_SRC}/* /pyboard/"
  else
    echo "No mpremote/rshell in PATH — print manual flash steps."
  fi

  cat <<EOF

Manual flash (Thonny or mpremote):
  1. Connect Pico W over USB
  2. Copy pico_monitor/firmware/* onto the board
       mpremote cp -r firmware/. :
       # or open folder in Thonny → Save to Pico
  3. Edit firmware/config.py on device:
       WIFI_SSID / WIFI_PASSWORD
       ROUTER_HOST=${ROUTER_HOST}
       ROUTER_PORT=${METRICS_PORT}
       DEMO=0
  4. Soft-reset → expect PICO BOOT / WIFI OK / metrics pull
  5. Pico should appear on LAN as ${PICO_HOST}

EOF
  return 0
}

status_remote() {
  echo "==> Merlin ${ROUTER_HOST} + Pico ${PICO_HOST}"
  compute_status
  render_status_block
  echo ""
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
  " 2>/dev/null || echo "(SSH unavailable — status from local probes only)"
  test_metrics || true
  ping_pico || true
  echo ""
  echo "OLED blank? Metrics on Merlin do not paint the display."
  echo "  Flash firmware/ → Pico ${PICO_HOST}; ROUTER_HOST=${ROUTER_HOST}:${METRICS_PORT}"
}

# Full pipeline: clean slate → upload → install → flash hint → ensure running
auto_mode() {
  echo "╔══════════════════════════════════════════╗"
  echo "║  Mode automatique — pipeline complet     ║"
  echo "╚══════════════════════════════════════════╝"
  echo "  Merlin SSH : $(TARGET)"
  echo "  Pico W     : ${PICO_HOST}"
  echo "  Steps: uninstall → clean → upload → install → flash → start"
  echo ""

  check_prereq || {
    echo "error: prerequisites failed — fix SSH / hosts first" >&2
    return 1
  }

  echo ""
  echo "[1/6] Uninstall (if present)…"
  uninstall_remote || true

  echo ""
  echo "[2/6] Clean remote tree…"
  clean_remote || true

  echo ""
  echo "[3/6] Upload merlin package…"
  upload

  echo ""
  echo "[4/6] Install (opkg + cru + start)…"
  install_remote

  echo ""
  echo "[5/6] Flash / sync Pico firmware…"
  flash_pico || true

  echo ""
  echo "[6/6] Ensure watchdog running…"
  start_watchdog || true

  echo ""
  echo "==> Auto mode finished — live status:"
  compute_status
  render_status_block
  echo ""
  echo "Next: confirm OLED on Pico ${PICO_HOST} (WIFI + ROUTER_HOST=${ROUTER_HOST})."
}

# --- interactive menu (arrow keys + ENTER; number fallback) ------------------

clear_screen() {
  if command -v clear >/dev/null 2>&1; then
    clear
  else
    printf '\033[2J\033[H'
  fi
}

# Menu items: label|action  (action = function name or quit/back)
MENU_ITEMS=(
  "Mode automatique (pipeline complet)|auto_mode"
  "Prerequisites / SSH + ping Pico|check_prereq"
  "Configure hosts (Merlin + Pico)|configure_router"
  "Upload merlin package|upload"
  "Install (opkg + cru + start)|do_install"
  "Flash Pico firmware (mpremote/manual)|flash_pico"
  "Pilotage distant|pilotage_menu"
  "Start / restart watchdog|start_watchdog"
  "Autostart status (cru)|autostart"
  "Test /metrics.json (Merlin)|test_metrics"
  "Tail logs|show_logs"
  "Uninstall|uninstall_remote"
  "Refresh status|status_remote"
  "Quit|quit"
)

PILOT_MENU_ITEMS=(
  "Start metrics service (watchdog start/reload)|start_watchdog"
  "Stop metrics service|stop_watchdog"
  "Cron ON (cru a PicoMonitor)|cron_on"
  "Cron OFF (cru d PicoMonitor)|cron_off"
  "État détaillé|pilot_status"
  "Test link Pico|test_link_pico"
  "Test metrics Merlin|test_metrics"
  "Retour|back"
)

do_install() {
  upload
  install_remote
}

# Returns 0 if stdin is a TTY and we can use raw reads
menu_raw_supported() {
  [[ -t 0 ]] && [[ -t 1 ]] || return 1
  command -v stty >/dev/null 2>&1 || return 1
  # Probe: must restore on exit
  local saved
  saved="$(stty -g 2>/dev/null)" || return 1
  stty -echo -icanon time 0 min 0 2>/dev/null || return 1
  stty "${saved}" 2>/dev/null || true
  return 0
}

# Read one menu key: up|down|enter|quit|digit|other
# Escape sequences via read -n; -t uses whole seconds (bash 3.2 / macOS).
read_menu_key() {
  local saved key rest
  saved="$(stty -g 2>/dev/null)" || { echo other; return 1; }
  stty -echo -icanon time 0 min 1 2>/dev/null || {
    stty "${saved}" 2>/dev/null || true
    echo other
    return 1
  }
  # shellcheck disable=SC2162
  IFS= read -r -n 1 key || true
  case "${key}" in
    $'\x1b')
      # ESC [ A/B  or ESC O A/B (arrow keys)
      IFS= read -r -n 1 -t 1 rest || rest=""
      if [[ "${rest}" == "[" ]] || [[ "${rest}" == "O" ]]; then
        IFS= read -r -n 1 -t 1 rest || rest=""
        case "${rest}" in
          A) stty "${saved}" 2>/dev/null || true; echo up; return 0 ;;
          B) stty "${saved}" 2>/dev/null || true; echo down; return 0 ;;
        esac
      fi
      stty "${saved}" 2>/dev/null || true
      echo other
      return 0
      ;;
    ""|$'\n'|$'\r')
      stty "${saved}" 2>/dev/null || true
      echo enter
      return 0
      ;;
    q|Q)
      stty "${saved}" 2>/dev/null || true
      echo quit
      return 0
      ;;
    [0-9])
      stty "${saved}" 2>/dev/null || true
      echo "digit:${key}"
      return 0
      ;;
    *)
      stty "${saved}" 2>/dev/null || true
      echo other
      return 0
      ;;
  esac
}

menu_label() {
  local item="$1"
  printf '%s' "${item%%|*}"
}

menu_action() {
  local item="$1"
  printf '%s' "${item#*|}"
}

# Draw menu from items named by $1 (MENU_ITEMS|PILOT_MENU_ITEMS), selection $2
draw_menu() {
  local items_name="$1"
  local sel="$2"
  local i=0
  local n label
  local -a items

  case "${items_name}" in
    PILOT_MENU_ITEMS) items=("${PILOT_MENU_ITEMS[@]}") ;;
    *) items=("${MENU_ITEMS[@]}") ;;
  esac
  n=${#items[@]}

  clear_screen
  if [[ "${items_name}" == "PILOT_MENU_ITEMS" ]]; then
    cat <<EOF
╔══════════════════════════════════════════╗
║  Pilotage distant — Merlin / Pico        ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pico W:     ${PICO_HOST}
║  Remote:     ${REMOTE_PATH}
╚══════════════════════════════════════════╝

EOF
  else
    cat <<EOF
╔══════════════════════════════════════════╗
║  Pico Monitor → Merlin deploy            ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pico W:     ${PICO_HOST}
║  Remote:     ${REMOTE_PATH}
╚══════════════════════════════════════════╝

EOF
  fi
  render_status_block
  echo ""
  if [[ "${items_name}" == "PILOT_MENU_ITEMS" ]]; then
    echo "  ↑/↓ move  ·  ENTER run  ·  1-8 jump  ·  q quit"
  else
    echo "  ↑/↓ move  ·  ENTER run  ·  1-9 jump  ·  q quit"
  fi
  echo ""

  for ((i = 0; i < n; i++)); do
    label="$(menu_label "${items[$i]}")"
    if (( i == sel )); then
      printf '  \033[7m > %2d) %-48s \033[0m\n' "$((i + 1))" "${label}"
    else
      printf '     %2d) %s\n' "$((i + 1))" "${label}"
    fi
  done

  echo ""
  label="$(menu_label "${items[$sel]}")"
  printf '  Selected ▸ %s\n' "${label}"
  echo ""
  if [[ "${items_name}" == "PILOT_MENU_ITEMS" ]]; then
    echo "  start/stop/cron via SSH · Pico = PICO_MERLIN_HOST"
  else
    echo "  OLED: Merlin metrics ≠ Pico pixels."
    echo "  Flash firmware/ + WIFI + ROUTER_HOST=${ROUTER_HOST}"
  fi
}

pause_return() {
  echo ""
  read -r -p "Press ENTER to return to menu… " _
}

run_menu_action() {
  local action="$1"
  case "${action}" in
    quit) exit 0 ;;
    back) return 0 ;;
    auto_mode) auto_mode ;;
    check_prereq) check_prereq || true ;;
    configure_router) configure_router ;;
    upload) upload ;;
    do_install) do_install ;;
    flash_pico) flash_pico || true ;;
    pilotage_menu) pilotage_menu ;;
    start_watchdog) start_watchdog || true ;;
    stop_watchdog) stop_watchdog || true ;;
    cron_on) cron_on || true ;;
    cron_off) cron_off || true ;;
    pilot_status) pilot_status || true ;;
    test_link_pico) test_link_pico || true ;;
    autostart) autostart ;;
    test_metrics) test_metrics || true ;;
    show_logs) show_logs ;;
    uninstall_remote) uninstall_remote ;;
    status_remote) status_remote ;;
    *) echo "unknown action: ${action}" ;;
  esac
}

# Generic arrow menu. $1 = MENU_ITEMS|PILOT_MENU_ITEMS
# Returns when action is "back" (submenu). quit exits the process.
menu_arrow() {
  local items_name="${1:-MENU_ITEMS}"
  local sel=0
  local n key action idx
  local need_status=1
  local -a items

  case "${items_name}" in
    PILOT_MENU_ITEMS) items=("${PILOT_MENU_ITEMS[@]}") ;;
    *) items=("${MENU_ITEMS[@]}") ;;
  esac
  n=${#items[@]}

  while true; do
    if (( need_status )); then
      compute_status || true
      need_status=0
    fi
    draw_menu "${items_name}" "${sel}"
    key="$(read_menu_key)" || key="other"
    case "${key}" in
      up)
        sel=$(( (sel - 1 + n) % n ))
        ;;
      down)
        sel=$(( (sel + 1) % n ))
        ;;
      enter)
        action="$(menu_action "${items[$sel]}")"
        if [[ "${action}" == "back" ]]; then
          return 0
        fi
        if [[ "${action}" == "pilotage_menu" ]]; then
          clear_screen
          pilotage_menu
          need_status=1
          continue
        fi
        clear_screen
        run_menu_action "${action}"
        [[ "${action}" == "quit" ]] && exit 0
        pause_return
        need_status=1
        ;;
      quit)
        if [[ "${items_name}" == "PILOT_MENU_ITEMS" ]]; then
          return 0
        fi
        exit 0
        ;;
      digit:*)
        # Jump highlight to item N (1-9); ENTER confirms.
        idx="${key#digit:}"
        if [[ "${idx}" =~ ^[1-9]$ ]] && (( idx >= 1 && idx <= n )); then
          sel=$((idx - 1))
        fi
        ;;
      *)
        # ignore unknown keys; redraw
        ;;
    esac
  done
}

menu_number_fallback() {
  local items_name="${1:-MENU_ITEMS}"
  local c n i label action
  local -a items

  case "${items_name}" in
    PILOT_MENU_ITEMS) items=("${PILOT_MENU_ITEMS[@]}") ;;
    *) items=("${MENU_ITEMS[@]}") ;;
  esac
  n=${#items[@]}

  while true; do
    compute_status || true
    clear_screen
    if [[ "${items_name}" == "PILOT_MENU_ITEMS" ]]; then
      cat <<EOF
╔══════════════════════════════════════════╗
║  Pilotage distant — Merlin / Pico        ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pico W:     ${PICO_HOST}
║  Remote:     ${REMOTE_PATH}
╚══════════════════════════════════════════╝

EOF
    else
      cat <<EOF
╔══════════════════════════════════════════╗
║  Pico Monitor → Merlin deploy            ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pico W:     ${PICO_HOST}
║  Remote:     ${REMOTE_PATH}
╚══════════════════════════════════════════╝

EOF
    fi
    render_status_block
    echo ""
    echo "  (arrow keys unavailable — use numbers)"
    echo ""
    for ((i = 0; i < n; i++)); do
      label="$(menu_label "${items[$i]}")"
      printf '  %2d) %s\n' "$((i + 1))" "${label}"
    done
    echo ""
    read -r -p "Choice [1-${n}]: " c
    if [[ "${c}" =~ ^[0-9]+$ ]] && (( c >= 1 && c <= n )); then
      action="$(menu_action "${items[$((c - 1))]}")"
      if [[ "${action}" == "back" ]]; then
        return 0
      fi
      printf '  Selected ▸ %s\n\n' "$(menu_label "${items[$((c - 1))]}")"
      if [[ "${action}" == "pilotage_menu" ]]; then
        pilotage_menu
        continue
      fi
      run_menu_action "${action}"
      [[ "${action}" == "quit" ]] && exit 0
      pause_return
    else
      echo "?"
      sleep 1
    fi
  done
}

pilotage_menu() {
  if menu_raw_supported; then
    menu_arrow PILOT_MENU_ITEMS
  else
    menu_number_fallback PILOT_MENU_ITEMS
  fi
}

menu() {
  load_config
  if menu_raw_supported; then
    menu_arrow MENU_ITEMS
  else
    menu_number_fallback MENU_ITEMS
  fi
}

usage() {
  cat <<EOF
Usage: $0 [menu|install|uninstall|status|auto|upload|test|flash|pilot|start|stop|cron-on|cron-off]

  (no args) / menu   Interactive menu (↑/↓ + ENTER, or numbers)
  auto               Full pipeline: uninstall→clean→upload→install→flash→start
  install            Upload + install + start
  uninstall          Remove Merlin addon + cru
  status             Live Merlin + Pico status
  upload             Sync merlin/ only
  test               GET /metrics.json
  flash              Pico firmware sync (mpremote) or print steps
  pilot              Remote pilotage submenu (start/stop/cron/status/tests)
  start              Start/reload metrics watchdog on Merlin
  stop               Stop metrics watchdog on Merlin
  cron-on            Enable cru job PicoMonitor
  cron-off           Disable cru job PicoMonitor

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
  auto|automatic|auto_mode) auto_mode ;;
  install) check_prereq; upload; install_remote ;;
  uninstall) uninstall_remote ;;
  status) status_remote ;;
  upload) upload ;;
  test) test_metrics ;;
  flash) flash_pico ;;
  pilot|pilotage) pilotage_menu ;;
  start) start_watchdog ;;
  stop) stop_watchdog ;;
  cron-on|cron_on) cron_on ;;
  cron-off|cron_off) cron_off ;;
  *) usage; exit 2 ;;
esac
