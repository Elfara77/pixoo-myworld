#!/usr/bin/env bash
# Interactive / non-interactive deploy of Merlin metrics + Pixoo bridge.
#
# Modes:
#   ./deploy_monitor.sh              # arrow-key menu (+ number fallback)
#   ./deploy_monitor.sh install      # non-interactive upload+install+start
#   ./deploy_monitor.sh uninstall
#   ./deploy_monitor.sh status
#   ./deploy_monitor.sh auto         # upload→install→start bridge (no wipe)
#   ./deploy_monitor.sh pilot        # remote pilotage submenu
#   ./deploy_monitor.sh start|stop|cron-on|cron-off
#   ./deploy_monitor.sh logs         # pull router logs → pico_monitor/logs/
#   ./deploy_monitor.sh snapshot     # last Pixoo 64×64 frame → logs/snapshots/*.png
#
# Hosts (do not conflate):
#   PICO_ROUTER_HOST  Merlin LAN IP — SSH deploy + /metrics.json (default 192.168.50.1)
#   PIXOO_IP          Divoom Pixoo 64 — HTTP /post push target (default 192.168.52.4)
#   PICO_MERLIN_HOST  Optional Pico W LAN IP for OLED ping (not required for Pixoo)
#
# Auto install starts metrics_server AND pixoo_bridge ON Merlin (Entware).
#
# Merlin BusyBox ash often lacks the `command` builtin — remote scripts use
# `[ -x /path ]` / absolute binaries only. Never source /opt/etc/profile
# (AMTM spam + mydisk.sh cd).
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
MERLIN_SRC="${ROOT}/merlin"
BRIDGE_SRC="${ROOT}/pixoo_bridge"
FIRMWARE_SRC="${ROOT}/firmware"
LOCAL_LOGS="${ROOT}/logs"
LOCAL_SNAPS="${ROOT}/logs/snapshots"
CFG_HOME="${HOME}/.pico_monitor_config"
CFG_PROJECT="${ROOT}/.deploy.env"

# Merlin (SSH + metrics exporter + Pixoo bridge daemon)
ROUTER_HOST="${PICO_ROUTER_HOST:-192.168.50.1}"
# Divoom Pixoo 64 (HTTP push) — primary display for this stack
PIXOO_IP="${PIXOO_IP:-192.168.52.4}"
# Optional Pico W (OLED) — ping only; not needed for Pixoo
PICO_HOST="${PICO_MERLIN_HOST:-}"
USER_NAME="${PICO_MERLIN_USER:-elphara77}"
REMOTE_PATH="${PICO_MERLIN_PATH:-/jffs/addons/pico_monitor}"
PORT="${PICO_MERLIN_PORT:-22}"
SSH_AUTH="${PICO_SSH_AUTH:-key}"  # key | password
SSH_PASS="${PICO_SSH_PASS:-}"
METRICS_PORT="${PICO_METRICS_PORT:-8088}"
PIXOO_BRIGHTNESS="${PIXOO_BRIGHTNESS:-50}"
PIXOO_SCREEN_SECONDS="${PIXOO_SCREEN_SECONDS:-8}"
PIXOO_HEAVY_SCREEN_DWELL="${PIXOO_HEAVY_SCREEN_DWELL:-1}"
PIXOO_HEAVY_SCREEN_MULTIPLIER="${PIXOO_HEAVY_SCREEN_MULTIPLIER:-2}"
PIXOO_FRAME_INTERVAL="${PIXOO_FRAME_INTERVAL:-1.05}"
PIXOO_COLOR_MODE="${PIXOO_COLOR_MODE:-mono}"
PIXOO_TEXT_SCROLL="${PIXOO_TEXT_SCROLL:-1}"
PIXOO_ALERT_BLINK="${PIXOO_ALERT_BLINK:-1}"
PIXOO_BLINK_PERIOD="${PIXOO_BLINK_PERIOD:-0.55}"
PIXOO_RATE_STYLE="${PIXOO_RATE_STYLE:-short}"
PIXOO_WLC_GRAPH_MODE="${PIXOO_WLC_GRAPH_MODE:-overlay}"
PIXOO_WAN_MAX_DOWN_MBPS="${PIXOO_WAN_MAX_DOWN_MBPS:-190}"
PIXOO_WAN_MAX_UP_MBPS="${PIXOO_WAN_MAX_UP_MBPS:-12}"
PIXOO_SCREENS="${PIXOO_SCREENS:-all}"

REMOTE_PATH_ENV='export PATH=/opt/bin:/opt/sbin:/opt/usr/bin:/bin:/sbin:/usr/bin:/usr/sbin'

# Live status flags (yes|no|?) refreshed by compute_status
ST_SSH="?"
ST_UPLOADED="?"
ST_INSTALLED="?"
ST_RUNNING="?"
ST_BRIDGE="?"
ST_CRU="?"
ST_METRICS="?"
ST_PIXOO="?"
ST_PIXOO_VIA=""
ST_PICO="?"
ST_DETAIL_PID=""
ST_DETAIL_CRU=""
ST_DETAIL_BRIDGE=""

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
      # Pico W ping target (optional). If legacy .deploy.env put Pixoo IP in
      # PICO_MERLIN_HOST, do not treat that as a Pico — keep PICO_HOST empty.
      if [[ -n "${PICO_MERLIN_HOST:-}" ]]; then
        if [[ "${PICO_MERLIN_HOST}" == "${PIXOO_IP}" ]] || [[ "${PICO_MERLIN_HOST}" == "${ROUTER_HOST}" ]]; then
          PICO_HOST=""
        else
          PICO_HOST="${PICO_MERLIN_HOST}"
        fi
      fi
      USER_NAME="${PICO_MERLIN_USER:-$USER_NAME}"
      REMOTE_PATH="${PICO_MERLIN_PATH:-$REMOTE_PATH}"
      PORT="${PICO_MERLIN_PORT:-$PORT}"
      SSH_AUTH="${PICO_SSH_AUTH:-$SSH_AUTH}"
      METRICS_PORT="${PICO_METRICS_PORT:-$METRICS_PORT}"
      PIXOO_BRIGHTNESS="${PIXOO_BRIGHTNESS:-50}"
      PIXOO_SCREEN_SECONDS="${PIXOO_SCREEN_SECONDS:-8}"
      PIXOO_HEAVY_SCREEN_DWELL="${PIXOO_HEAVY_SCREEN_DWELL:-1}"
      PIXOO_HEAVY_SCREEN_MULTIPLIER="${PIXOO_HEAVY_SCREEN_MULTIPLIER:-2}"
      PIXOO_FRAME_INTERVAL="${PIXOO_FRAME_INTERVAL:-1.05}"
      PIXOO_COLOR_MODE="${PIXOO_COLOR_MODE:-mono}"
      PIXOO_TEXT_SCROLL="${PIXOO_TEXT_SCROLL:-1}"
      PIXOO_ALERT_BLINK="${PIXOO_ALERT_BLINK:-1}"
      PIXOO_BLINK_PERIOD="${PIXOO_BLINK_PERIOD:-0.55}"
      PIXOO_RATE_STYLE="${PIXOO_RATE_STYLE:-short}"
      PIXOO_WLC_GRAPH_MODE="${PIXOO_WLC_GRAPH_MODE:-overlay}"
      PIXOO_WAN_MAX_DOWN_MBPS="${PIXOO_WAN_MAX_DOWN_MBPS:-190}"
      PIXOO_WAN_MAX_UP_MBPS="${PIXOO_WAN_MAX_UP_MBPS:-12}"
      PIXOO_SCREENS="${PIXOO_SCREENS:-all}"
      break
    fi
  done
}

save_config() {
  mkdir -p "$(dirname "${CFG_HOME}")"
  cat > "${CFG_PROJECT}" <<EOF
# Merlin + Pixoo deploy (no passwords stored)
# PICO_ROUTER_HOST = Merlin (SSH + metrics + bridge). PIXOO_IP = Divoom Pixoo.
PICO_ROUTER_HOST=${ROUTER_HOST}
PIXOO_IP=${PIXOO_IP}
PICO_MERLIN_HOST=${PICO_HOST}
PICO_MERLIN_USER=${USER_NAME}
PICO_MERLIN_PATH=${REMOTE_PATH}
PICO_MERLIN_PORT=${PORT}
PICO_SSH_AUTH=${SSH_AUTH}
PICO_METRICS_PORT=${METRICS_PORT}
PIXOO_BRIGHTNESS=${PIXOO_BRIGHTNESS}
PIXOO_SCREEN_SECONDS=${PIXOO_SCREEN_SECONDS}
PIXOO_HEAVY_SCREEN_DWELL=${PIXOO_HEAVY_SCREEN_DWELL}
PIXOO_HEAVY_SCREEN_MULTIPLIER=${PIXOO_HEAVY_SCREEN_MULTIPLIER}
PIXOO_FRAME_INTERVAL=${PIXOO_FRAME_INTERVAL}
PIXOO_COLOR_MODE=${PIXOO_COLOR_MODE}
PIXOO_TEXT_SCROLL=${PIXOO_TEXT_SCROLL}
PIXOO_ALERT_BLINK=${PIXOO_ALERT_BLINK}
PIXOO_BLINK_PERIOD=${PIXOO_BLINK_PERIOD}
PIXOO_RATE_STYLE=${PIXOO_RATE_STYLE}
PIXOO_WLC_GRAPH_MODE=${PIXOO_WLC_GRAPH_MODE}
PIXOO_WAN_MAX_DOWN_MBPS=${PIXOO_WAN_MAX_DOWN_MBPS}
PIXOO_WAN_MAX_UP_MBPS=${PIXOO_WAN_MAX_UP_MBPS}
PIXOO_SCREENS=${PIXOO_SCREENS}
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
  [[ -n "${PICO_HOST}" ]] || return 1
  if ping -c 1 -W 2 "${PICO_HOST}" >/dev/null 2>&1; then
    return 0
  fi
  # macOS ping uses -t for timeout
  ping -c 1 -t 2 "${PICO_HOST}" >/dev/null 2>&1
}

pixoo_http_ok() {
  # Prefer direct probe from this host; Pixoo is often on a guest/IoT VLAN
  # unreachable from the laptop — fall back to probing via Merlin (where the
  # bridge runs). Direct success ⇒ yes; Merlin-only ⇒ yes (via Merlin).
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 3 -X POST "http://${PIXOO_IP}/post" \
      -H 'Content-Type: application/json' \
      -d '{"Command":"Device/GetDeviceTime"}' >/dev/null 2>&1; then
      ST_PIXOO_VIA=""
      return 0
    fi
  fi
  # Bridge path: Merlin → Pixoo (authoritative for "can the push loop work?").
  if remote "
    if [ -x /opt/bin/curl ]; then
      /opt/bin/curl -fsS --max-time 3 -X POST 'http://${PIXOO_IP}/post' \
        -H 'Content-Type: application/json' \
        -d '{\"Command\":\"Device/GetDeviceTime\"}' >/dev/null 2>&1
    elif [ -x /usr/bin/curl ]; then
      /usr/bin/curl -fsS --max-time 3 -X POST 'http://${PIXOO_IP}/post' \
        -H 'Content-Type: application/json' \
        -d '{\"Command\":\"Device/GetDeviceTime\"}' >/dev/null 2>&1
    else
      wget -qO- --timeout=3 --post-data='{\"Command\":\"Device/GetDeviceTime\"}' \
        --header='Content-Type: application/json' \
        'http://${PIXOO_IP}/post' >/dev/null 2>&1
    fi
  " 2>/dev/null; then
    ST_PIXOO_VIA="merlin"
    return 0
  fi
  ST_PIXOO_VIA=""
  return 1
}

metrics_http_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 4 "http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json" >/dev/null 2>&1
    return $?
  fi
  remote "wget -qO- --timeout=4 http://127.0.0.1:${METRICS_PORT}/metrics.json >/dev/null 2>&1" 2>/dev/null
}

# Probe Merlin + Pixoo; fills ST_* globals. Quiet (no chatter).
compute_status() {
  ST_SSH="?"
  ST_UPLOADED="?"
  ST_INSTALLED="?"
  ST_RUNNING="?"
  ST_BRIDGE="?"
  ST_CRU="?"
  ST_METRICS="?"
  ST_PIXOO="?"
  ST_PIXOO_VIA=""
  ST_PICO="?"
  ST_DETAIL_PID=""
  ST_DETAIL_CRU=""
  ST_DETAIL_BRIDGE=""

  if pixoo_http_ok; then
    ST_PIXOO="yes"
  else
    ST_PIXOO="no"
    ST_PIXOO_VIA=""
  fi

  if [[ -n "${PICO_HOST}" ]]; then
    if pico_ping_ok; then ST_PICO="yes"; else ST_PICO="no"; fi
  else
    ST_PICO="?"
  fi

  local blob
  if ! blob="$(remote "
    echo SSH_OK
    if [ -f '${REMOTE_PATH}/metrics_server.py' ] && [ -f '${REMOTE_PATH}/watchdog.sh' ]; then
      echo UPLOADED_YES
    else
      echo UPLOADED_NO
    fi
    if [ -d '${REMOTE_PATH}/pixoo_bridge' ] && [ -f '${REMOTE_PATH}/pixoo_bridge/__main__.py' ]; then
      echo BRIDGE_PKG_YES
    else
      echo BRIDGE_PKG_NO
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
        *'metrics running'*) echo RUNNING_YES ;;
        *) echo RUNNING_NO ;;
      esac
      case \"\$out\" in
        *'bridge running'*) echo BRIDGE_YES ;;
        *) echo BRIDGE_NO ;;
      esac
    else
      echo RUNNING_NO
      echo BRIDGE_NO
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
    ST_BRIDGE="?"
    ST_CRU="?"
    if metrics_http_ok; then ST_METRICS="yes"; else ST_METRICS="no"; fi
    return 0
  fi

  ST_SSH="yes"
  echo "${blob}" | grep -q UPLOADED_YES && ST_UPLOADED="yes" || ST_UPLOADED="no"
  echo "${blob}" | grep -q INSTALLED_YES && ST_INSTALLED="yes" || ST_INSTALLED="no"
  echo "${blob}" | grep -q RUNNING_YES && ST_RUNNING="yes" || ST_RUNNING="no"
  echo "${blob}" | grep -q BRIDGE_YES && ST_BRIDGE="yes" || ST_BRIDGE="no"
  if echo "${blob}" | grep -q CRU_YES; then
    ST_CRU="yes"
  elif echo "${blob}" | grep -q SVC_YES; then
    ST_CRU="yes"
  else
    ST_CRU="no"
  fi
  ST_DETAIL_PID="$(echo "${blob}" | sed -n 's/^WATCHDOG://p' | tr '\n' ' ' | head -c 120)"
  ST_DETAIL_CRU="$(echo "${blob}" | grep -i PicoMonitor | head -n1 || true)"
  ST_DETAIL_BRIDGE="$(echo "${blob}" | grep -E 'BRIDGE_(PKG_)?(YES|NO)' | head -n1 || true)"

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
  printf '  Metrics      %s  %s\n' "$(mark_yes_no "${ST_RUNNING}")" "${ST_DETAIL_PID:-daemon}"
  printf '  Pixoo bridge %s  push loop on Merlin\n' "$(mark_yes_no "${ST_BRIDGE}")"
  printf '  Autostart    %s  cru/services-start\n' "$(mark_yes_no "${ST_CRU}")"
  printf '  Metrics HTTP %s  http://%s:%s/metrics.json\n' "$(mark_yes_no "${ST_METRICS}")" "${ROUTER_HOST}" "${METRICS_PORT}"
  if [[ "${ST_PIXOO}" == "yes" && "${ST_PIXOO_VIA}" == "merlin" ]]; then
    printf '  Pixoo API    %s  %s /post (via Merlin; laptop VLAN blocked)\n' \
      "$(mark_yes_no "${ST_PIXOO}")" "${PIXOO_IP}"
  else
    printf '  Pixoo API    %s  %s /post\n' "$(mark_yes_no "${ST_PIXOO}")" "${PIXOO_IP}"
  fi
  if [[ -n "${PICO_HOST}" ]]; then
    printf '  Pico ping    %s  %s (optional OLED)\n' "$(mark_yes_no "${ST_PICO}")" "${PICO_HOST}"
  fi
  printf '%s\n' "──────────────────────────────────────────────────"
}

ping_pico() {
  if [[ -z "${PICO_HOST}" ]]; then
    echo "==> no PICO_MERLIN_HOST set (optional Pico W OLED) — skip"
    return 0
  fi
  echo "==> ping Pico W ${PICO_HOST}"
  if pico_ping_ok; then
    echo "Pico reachable at ${PICO_HOST}"
    return 0
  fi
  echo "Pico NOT reachable at ${PICO_HOST}"
  return 1
}

ping_pixoo() {
  echo "==> Pixoo API ${PIXOO_IP}"
  ST_PIXOO_VIA=""
  if pixoo_http_ok; then
    if [[ "${ST_PIXOO_VIA}" == "merlin" ]]; then
      echo "Pixoo OK at ${PIXOO_IP} (via Merlin SSH — laptop cannot reach guest/IoT VLAN)"
    else
      echo "Pixoo OK at ${PIXOO_IP} (Device/GetDeviceTime)"
    fi
    return 0
  fi
  echo "Pixoo NOT answering /post at ${PIXOO_IP} (tried laptop + Merlin)"
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
  [[ -d "${BRIDGE_SRC}" ]] || { echo "missing ${BRIDGE_SRC}"; return 1; }
  echo "OK router(SSH)=${ROUTER_HOST} pixoo=${PIXOO_IP} user=${USER_NAME}"
  echo "   path=${REMOTE_PATH} metrics_port=${METRICS_PORT} auth=${SSH_AUTH}"
  if remote "echo OK" 2>/dev/null | grep -q OK; then
    echo "SSH Merlin: OK"
  else
    echo "SSH Merlin: FAIL (ssh-copy-id $(TARGET))" >&2
    return 1
  fi
  ping_pixoo || true
  ping_pico || true
}

configure_router() {
  echo "Merlin = SSH + /metrics.json + Pixoo bridge. PIXOO_IP = Divoom display."
  read -r -p "Merlin/router host [${ROUTER_HOST}]: " v; ROUTER_HOST="${v:-$ROUTER_HOST}"
  read -r -p "Pixoo IP [${PIXOO_IP}]: " v; PIXOO_IP="${v:-$PIXOO_IP}"
  read -r -p "Pico W host (optional) [${PICO_HOST:-none}]: " v; PICO_HOST="${v:-$PICO_HOST}"
  read -r -p "SSH user [${USER_NAME}]: " v; USER_NAME="${v:-$USER_NAME}"
  read -r -p "Remote path [${REMOTE_PATH}]: " v; REMOTE_PATH="${v:-$REMOTE_PATH}"
  read -r -p "SSH port [${PORT}]: " v; PORT="${v:-$PORT}"
  read -r -p "Metrics HTTP port [${METRICS_PORT}]: " v; METRICS_PORT="${v:-$METRICS_PORT}"
  read -r -p "Pixoo brightness [${PIXOO_BRIGHTNESS}]: " v; PIXOO_BRIGHTNESS="${v:-$PIXOO_BRIGHTNESS}"
  read -r -p "Auth key/password [${SSH_AUTH}]: " v; SSH_AUTH="${v:-$SSH_AUTH}"
  save_config
  echo "Pixoo bridge will push to ${PIXOO_IP}; metrics on ${ROUTER_HOST}:${METRICS_PORT}"
}

# Default visual profile (recommended)
visual_defaults() {
  PIXOO_COLOR_MODE="mono"
  PIXOO_TEXT_SCROLL="1"
  PIXOO_ALERT_BLINK="1"
  PIXOO_BLINK_PERIOD="0.55"
  PIXOO_BRIGHTNESS="50"
  PIXOO_SCREEN_SECONDS="8"
  PIXOO_HEAVY_SCREEN_DWELL="1"
  PIXOO_HEAVY_SCREEN_MULTIPLIER="2"
  PIXOO_FRAME_INTERVAL="1.05"
  PIXOO_RATE_STYLE="short"
  PIXOO_WLC_GRAPH_MODE="overlay"
  PIXOO_WAN_MAX_DOWN_MBPS="190"
  PIXOO_WAN_MAX_UP_MBPS="12"
  PIXOO_SCREENS="all"
}

# Canonical screen ids (must match pixoo_bridge.render)
# ALL_PIXOO_SCREENS = default "all" rotation (SUM excluded)
ALL_PIXOO_SCREENS=(SYS LOD TMP GRP WLC TOP CLI NET PIE SRV)
ALL_PIXOO_SCREEN_LABELS=(
  "SYS System"
  "LOD Load CPU/RAM"
  "TMP Temps"
  "GRP Traffic WAN"
  "WLC WiFi/LAN traffic"
  "TOP Top clients"
  "CLI Clients"
  "NET Ports"
  "PIE Disks"
  "SRV Services"
)
# Optional (not in "all") — pick explicitly or all,SUM / all,SUM_GRAPH
OPT_PIXOO_SCREENS=(SUM SUM_GRAPH)
OPT_PIXOO_SCREEN_LABELS=(
  "SUM Summary health (opt, no banner)"
  "SUM_GRAPH WAN down/up history 64 samples (opt)"
)

print_visual_profile() {
  local nscr="${PIXOO_SCREENS}"
  if [[ "${nscr}" == "all" || -z "${nscr}" ]]; then
    nscr="all (${#ALL_PIXOO_SCREENS[@]})"
  fi
  cat <<EOF
  ┌─ Profil visuel Pixoo ─────────────────────
  │  Couleur texte     : ${PIXOO_COLOR_MODE}   (mono|poly)
  │  Scroll titres     : ${PIXOO_TEXT_SCROLL}      (1=on 0=off)
  │  Alert blink       : ${PIXOO_ALERT_BLINK}      (1=on 0=off)
  │  Période blink     : ${PIXOO_BLINK_PERIOD}s
  │  Luminosité        : ${PIXOO_BRIGHTNESS}     (0–100)
  │  Temps par écran   : ${PIXOO_SCREEN_SECONDS}s  (rotation)
  │  Écrans lourds     : ${PIXOO_HEAVY_SCREEN_DWELL}  (1=×${PIXOO_HEAVY_SCREEN_MULTIPLIER} LOD/TMP/GRP/WLC…)
  │  Rafraîchissement  : ${PIXOO_FRAME_INTERVAL}s  (push HTTP frame)
  │  Unités débit      : ${PIXOO_RATE_STYLE}  (short=K/M/G · long=Kb/s)
  │  Graphes trafic    : ${PIXOO_WLC_GRAPH_MODE}  (overlay=same · split=gauche/droite)
  │  WAN max Down/Up   : ${PIXOO_WAN_MAX_DOWN_MBPS}/${PIXOO_WAN_MAX_UP_MBPS} M  (SUM Net)
  │  Écrans actifs     : ${nscr}
  └───────────────────────────────────────────
EOF
}

_ask_choice() {
  # $1=prompt $2=default $3=allowed regex (optional)
  local prompt="$1" def="$2" re="${3:-}"
  local v
  read -r -p "${prompt} [${def}]: " v
  v="${v:-$def}"
  if [[ -n "${re}" ]] && ! [[ "${v}" =~ ${re} ]]; then
    echo "  (valeur invalide — conservation de ${def})" >&2
    echo "${def}"
    return
  fi
  echo "${v}"
}

configure_visual() {
  echo "╔══════════════════════════════════════════╗"
  echo "║  Assistant paramétrage visuel Pixoo      ║"
  echo "╚══════════════════════════════════════════╝"
  echo ""
  echo "Profil par défaut recommandé :"
  # Show defaults without clobbering current until accepted
  local _cm="${PIXOO_COLOR_MODE}" _ts="${PIXOO_TEXT_SCROLL}" _ab="${PIXOO_ALERT_BLINK}"
  local _bp="${PIXOO_BLINK_PERIOD}" _br="${PIXOO_BRIGHTNESS}" _ss="${PIXOO_SCREEN_SECONDS}"
  local _hd="${PIXOO_HEAVY_SCREEN_DWELL}" _hm="${PIXOO_HEAVY_SCREEN_MULTIPLIER}"
  local _fi="${PIXOO_FRAME_INTERVAL}" _rs="${PIXOO_RATE_STYLE}" _wg="${PIXOO_WLC_GRAPH_MODE}"
  local _wd="${PIXOO_WAN_MAX_DOWN_MBPS}" _wu="${PIXOO_WAN_MAX_UP_MBPS}"
  local _sc="${PIXOO_SCREENS}"
  visual_defaults
  print_visual_profile
  # restore current while asking
  PIXOO_COLOR_MODE="${_cm}"
  PIXOO_TEXT_SCROLL="${_ts}"
  PIXOO_ALERT_BLINK="${_ab}"
  PIXOO_BLINK_PERIOD="${_bp}"
  PIXOO_BRIGHTNESS="${_br}"
  PIXOO_SCREEN_SECONDS="${_ss}"
  PIXOO_HEAVY_SCREEN_DWELL="${_hd}"
  PIXOO_HEAVY_SCREEN_MULTIPLIER="${_hm}"
  PIXOO_FRAME_INTERVAL="${_fi}"
  PIXOO_RATE_STYLE="${_rs}"
  PIXOO_WLC_GRAPH_MODE="${_wg}"
  PIXOO_WAN_MAX_DOWN_MBPS="${_wd}"
  PIXOO_WAN_MAX_UP_MBPS="${_wu}"
  PIXOO_SCREENS="${_sc:-all}"

  echo ""
  echo "Profil actuel :"
  print_visual_profile
  echo ""
  local ans
  read -r -p "Valider le profil par défaut ? [Y/n/c=personnaliser]: " ans
  ans="${ans:-Y}"
  case "${ans}" in
    Y|y|yes|YES|o|O|oui|OUI)
      visual_defaults
      echo "→ profil par défaut appliqué."
      ;;
    n|N|no|NO|non|NON)
      echo "→ conservation des valeurs actuelles."
      ;;
    c|C|*)
      echo ""
      echo "Personnalisation (Entrée = garder) :"
      PIXOO_COLOR_MODE="$(_ask_choice "Couleur texte mono|poly" "${PIXOO_COLOR_MODE}" '^(mono|poly)$')"
      PIXOO_TEXT_SCROLL="$(_ask_choice "Scroll titres 1|0" "${PIXOO_TEXT_SCROLL}" '^[01]$')"
      PIXOO_ALERT_BLINK="$(_ask_choice "Alert blink 1|0" "${PIXOO_ALERT_BLINK}" '^[01]$')"
      PIXOO_BLINK_PERIOD="$(_ask_choice "Période blink (s)" "${PIXOO_BLINK_PERIOD}" '^[0-9]+([.][0-9]+)?$')"
      PIXOO_BRIGHTNESS="$(_ask_choice "Luminosité 0–100" "${PIXOO_BRIGHTNESS}" '^[0-9]+$')"
      if (( PIXOO_BRIGHTNESS > 100 )); then PIXOO_BRIGHTNESS=100; fi
      PIXOO_SCREEN_SECONDS="$(_ask_choice "Temps par écran (s) — rotation" "${PIXOO_SCREEN_SECONDS}" '^[0-9]+([.][0-9]+)?$')"
      PIXOO_HEAVY_SCREEN_DWELL="$(_ask_choice "Écrans lourds ×2 1|0" "${PIXOO_HEAVY_SCREEN_DWELL}" '^[01]$')"
      PIXOO_HEAVY_SCREEN_MULTIPLIER="$(_ask_choice "Multiplicateur écrans lourds" "${PIXOO_HEAVY_SCREEN_MULTIPLIER}" '^[0-9]+([.][0-9]+)?$')"
      PIXOO_FRAME_INTERVAL="$(_ask_choice "Intervalle refresh HTTP (s)" "${PIXOO_FRAME_INTERVAL}" '^[0-9]+([.][0-9]+)?$')"
      PIXOO_RATE_STYLE="$(_ask_choice "Unités débit short|long" "${PIXOO_RATE_STYLE}" '^(short|long)$')"
      PIXOO_WLC_GRAPH_MODE="$(_ask_choice "Graphes trafic overlay|split" "${PIXOO_WLC_GRAPH_MODE}" '^(overlay|split)$')"
      PIXOO_WAN_MAX_DOWN_MBPS="$(_ask_choice "WAN max Down (Mbps, SUM)" "${PIXOO_WAN_MAX_DOWN_MBPS}" '^[0-9]+([.][0-9]+)?$')"
      PIXOO_WAN_MAX_UP_MBPS="$(_ask_choice "WAN max Up (Mbps, SUM)" "${PIXOO_WAN_MAX_UP_MBPS}" '^[0-9]+([.][0-9]+)?$')"
      echo ""
      echo "Nouveau profil :"
      print_visual_profile
      ;;
  esac

  # Always confirm screen dwell time (often adjusted independently)
  echo ""
  PIXOO_SCREEN_SECONDS="$(_ask_choice "Temps par écran (secondes, rotation des écrans)" "${PIXOO_SCREEN_SECONDS}" '^[0-9]+([.][0-9]+)?$')"
  echo "→ temps par écran = ${PIXOO_SCREEN_SECONDS}s"

  echo ""
  configure_screens

  save_config
  apply_visual_remote || true
}

# Interactive screen picker — all or ≥1. Updates PIXOO_SCREENS.
# SUM is optional and never part of bare "all".
configure_screens() {
  echo "╔══════════════════════════════════════════╗"
  echo "║  Sélection des écrans Pixoo              ║"
  echo "╚══════════════════════════════════════════╝"
  echo "  all = défauts (sans SUM) · SUM / SUM_GRAPH = résumés optionnels · ≥1 requis"
  echo ""

  local -a on=() pick=()
  local i sid label tok
  pick=("${ALL_PIXOO_SCREENS[@]}" "${OPT_PIXOO_SCREENS[@]}")
  # Seed from current PIXOO_SCREENS
  if [[ -z "${PIXOO_SCREENS}" || "${PIXOO_SCREENS}" == "all" ]]; then
    on=("${ALL_PIXOO_SCREENS[@]}")
  else
    IFS=',' read -r -a tok <<< "${PIXOO_SCREENS}"
    for sid in "${tok[@]}"; do
      sid="$(echo "${sid}" | tr '[:lower:]' '[:upper:]' | tr -d ' ')"
      if [[ "${sid}" == "ALL" ]]; then
        for x in "${ALL_PIXOO_SCREENS[@]}"; do
          local found=0 j
          for (( j=0; j<${#on[@]}; j++ )); do
            [[ "${on[$j]}" == "${x}" ]] && found=1
          done
          (( found )) || on+=("${x}")
        done
      elif [[ -n "${sid}" ]]; then
        on+=("${sid}")
      fi
    done
  fi
  if (( ${#on[@]} < 1 )); then
    on=("${ALL_PIXOO_SCREENS[@]}")
  fi

  _screen_on() {
    local s="$1" i
    for (( i=0; i<${#on[@]}; i++ )); do
      [[ "${on[$i]}" == "${s}" ]] && return 0
    done
    return 1
  }
  _screen_toggle() {
    local s="$1" tmp=() i
    if _screen_on "${s}"; then
      for (( i=0; i<${#on[@]}; i++ )); do
        [[ "${on[$i]}" != "${s}" ]] && tmp+=("${on[$i]}")
      done
      on=()
      if (( ${#tmp[@]} > 0 )); then
        on=("${tmp[@]}")
      fi
    else
      on+=("${s}")
    fi
  }

  while true; do
    echo "  Écrans (x = actif) :"
    for i in "${!pick[@]}"; do
      sid="${pick[$i]}"
      if (( i < ${#ALL_PIXOO_SCREENS[@]} )); then
        label="${ALL_PIXOO_SCREEN_LABELS[$i]}"
      else
        label="${OPT_PIXOO_SCREEN_LABELS[$((i - ${#ALL_PIXOO_SCREENS[@]}))]}"
      fi
      if _screen_on "${sid}"; then
        printf '   %d) [x] %s\n' "$((i + 1))" "${label}"
      else
        printf '   %d) [ ] %s\n' "$((i + 1))" "${label}"
      fi
    done
    echo "   a) défauts (sans SUM)   s) SUM seul   g) SUM_GRAPH   n) aucun   d) done"
    echo ""
    local c
    read -r -p "Toggle [1-${#pick[@]}/a/s/g/n/d]: " c
    c="${c:-d}"
    case "${c}" in
      a|A|all)
        on=("${ALL_PIXOO_SCREENS[@]}")
        ;;
      s|S|sum|SUM)
        on=("SUM")
        ;;
      g|G|sum_graph|SUM_GRAPH|graph|GRAPH)
        on=("SUM_GRAPH")
        ;;
      n|N|none)
        on=()
        ;;
      d|D|done|""|q|Q)
        if (( ${#on[@]} < 1 )); then
          echo "  ⚠ au moins 1 écran requis."
          continue
        fi
        break
        ;;
      *)
        if [[ "${c}" =~ ^[0-9]+$ ]] && (( c >= 1 && c <= ${#pick[@]} )); then
          _screen_toggle "${pick[$((c - 1))]}"
        else
          echo "  ?"
        fi
        ;;
    esac
    echo ""
  done

  # Always persist the exact selected ids (no "all" shorthand on the wire).
  # Ambiguous "all" made deselected defaults reappear after reload/parse mismatches.
  if (( ${#on[@]} < 1 )); then
    echo "  ⚠ au moins 1 écran requis — conservation de la sélection précédente."
    return 1
  fi
  # Dedupe preserving order (nounset-safe: empty uniq[@] is OK)
  local -a uniq=()
  local x u dup
  for x in "${on[@]}"; do
    dup=0
    if ((${#uniq[@]} > 0)); then
      for u in "${uniq[@]}"; do
        [[ "${u}" == "${x}" ]] && { dup=1; break; }
      done
    fi
    (( dup )) || uniq+=("${x}")
  done
  on=("${uniq[@]}")
  PIXOO_SCREENS="$(IFS=,; echo "${on[*]}")"
  echo "→ écrans = ${PIXOO_SCREENS} (${#on[@]} actif(s))"
}

configure_screens_and_apply() {
  configure_screens
  save_config
  apply_visual_remote || true
}

apply_visual_remote() {
  # Push visual keys to Merlin config.env and reload bridge if installed
  if ! remote "echo OK" 2>/dev/null | grep -q OK; then
    echo "SSH Merlin indisponible — config locale sauvée ; relancer install/start plus tard."
    return 1
  fi
  if ! remote "test -f '${REMOTE_PATH}/config.env'" 2>/dev/null; then
    echo "Pas encore de config.env distant — sera pris à la prochaine install."
    return 0
  fi
  echo "==> appliquer le profil visuel sur Merlin…"
  # Quote screens for remote sed (commas are fine; escape | and \&)
  local screens_q="${PIXOO_SCREENS//\\/\\\\}"
  screens_q="${screens_q//|/\\|}"
  screens_q="${screens_q//&/\\&}"
  remote "
    CFG='${REMOTE_PATH}/config.env'
    _set() {
      k=\"\$1\"; v=\"\$2\"
      if grep -q \"^\${k}=\" \"\${CFG}\" 2>/dev/null; then
        sed -i \"s|^\${k}=.*|\${k}=\${v}|\" \"\${CFG}\"
      else
        echo \"\${k}=\${v}\" >> \"\${CFG}\"
      fi
    }
    _set PIXOO_IP '${PIXOO_IP}'
    _set PIXOO_BRIGHTNESS '${PIXOO_BRIGHTNESS}'
    _set PIXOO_SCREEN_SECONDS '${PIXOO_SCREEN_SECONDS}'
    _set PIXOO_HEAVY_SCREEN_DWELL '${PIXOO_HEAVY_SCREEN_DWELL}'
    _set PIXOO_HEAVY_SCREEN_MULTIPLIER '${PIXOO_HEAVY_SCREEN_MULTIPLIER}'
    _set PIXOO_FRAME_INTERVAL '${PIXOO_FRAME_INTERVAL}'
    _set PIXOO_COLOR_MODE '${PIXOO_COLOR_MODE}'
    _set PIXOO_TEXT_SCROLL '${PIXOO_TEXT_SCROLL}'
    _set PIXOO_ALERT_BLINK '${PIXOO_ALERT_BLINK}'
    _set PIXOO_BLINK_PERIOD '${PIXOO_BLINK_PERIOD}'
    _set PIXOO_RATE_STYLE '${PIXOO_RATE_STYLE}'
    _set PIXOO_WLC_GRAPH_MODE '${PIXOO_WLC_GRAPH_MODE}'
    _set PIXOO_WAN_MAX_DOWN_MBPS '${PIXOO_WAN_MAX_DOWN_MBPS}'
    _set PIXOO_WAN_MAX_UP_MBPS '${PIXOO_WAN_MAX_UP_MBPS}'
    _set PIXOO_SCREENS '${screens_q}'
    echo 'config.env updated'
    grep '^PIXOO_SCREENS=' \"\${CFG}\" || true
  "
  if remote "test -x '${REMOTE_PATH}/watchdog.sh'" 2>/dev/null; then
    remote "'${REMOTE_PATH}/watchdog.sh' reload" || remote "'${REMOTE_PATH}/watchdog.sh' start" || true
    echo "Bridge rechargé — écrans: ${PIXOO_SCREENS}"
  else
    echo "Watchdog absent — profil sauvé ; démarrer après install."
  fi
}

upload() {
  echo "==> upload → $(TARGET):${REMOTE_PATH}"
  [[ -d "${BRIDGE_SRC}" ]] || { echo "error: missing ${BRIDGE_SRC}" >&2; return 1; }
  remote "mkdir -p '${REMOTE_PATH}' '${REMOTE_PATH}/run' '${REMOTE_PATH}/logs' '${REMOTE_PATH}/pixoo_bridge'"
  if command -v rsync >/dev/null 2>&1; then
    local rssh="ssh -p ${PORT}"
    [[ "${SSH_AUTH}" == "key" ]] && rssh="${rssh} -o BatchMode=yes"
    local -a rsync_common=(
      -az --delete
      --exclude 'logs/' --exclude 'run/' --exclude 'config.env'
      --exclude 'pixoo_bridge/' --exclude '__pycache__/' --exclude '*.pyc'
      -e "${rssh}"
    )
    if [[ "${SSH_AUTH}" == "password" ]]; then
      sshpass -p "${SSH_PASS}" rsync "${rsync_common[@]}" \
        "${MERLIN_SRC}/" "$(TARGET):${REMOTE_PATH}/"
      sshpass -p "${SSH_PASS}" rsync -az --delete \
        --exclude '__pycache__/' --exclude '*.pyc' \
        -e "${rssh}" \
        "${BRIDGE_SRC}/" "$(TARGET):${REMOTE_PATH}/pixoo_bridge/"
    else
      rsync "${rsync_common[@]}" \
        "${MERLIN_SRC}/" "$(TARGET):${REMOTE_PATH}/"
      rsync -az --delete \
        --exclude '__pycache__/' --exclude '*.pyc' \
        -e "${rssh}" \
        "${BRIDGE_SRC}/" "$(TARGET):${REMOTE_PATH}/pixoo_bridge/"
    fi
  else
    scp_base -r \
      "${MERLIN_SRC}/metrics_server.py" \
      "${MERLIN_SRC}/run.sh" \
      "${MERLIN_SRC}/run_pixoo.sh" \
      "${MERLIN_SRC}/watchdog.sh" \
      "${MERLIN_SRC}/install.sh" \
      "${MERLIN_SRC}/uninstall.sh" \
      "${MERLIN_SRC}/config.example.env" \
      "$(TARGET):${REMOTE_PATH}/"
    scp_base -r \
      "${BRIDGE_SRC}/__init__.py" \
      "${BRIDGE_SRC}/__main__.py" \
      "${BRIDGE_SRC}/client.py" \
      "${BRIDGE_SRC}/render.py" \
      "$(TARGET):${REMOTE_PATH}/pixoo_bridge/"
  fi
  remote "chmod 755 '${REMOTE_PATH}/run.sh' '${REMOTE_PATH}/run_pixoo.sh' '${REMOTE_PATH}/watchdog.sh' '${REMOTE_PATH}/install.sh' '${REMOTE_PATH}/uninstall.sh' 2>/dev/null || true"
  echo "Upload OK (merlin + pixoo_bridge)"
}

install_remote() {
  echo "==> remote install (opkg python3+pillow + cru + metrics + Pixoo bridge)"
  remote "PICO_METRICS_PORT=${METRICS_PORT} PIXOO_IP=${PIXOO_IP} PIXOO_BRIGHTNESS=${PIXOO_BRIGHTNESS} PIXOO_SCREEN_SECONDS=${PIXOO_SCREEN_SECONDS} PIXOO_HEAVY_SCREEN_DWELL=${PIXOO_HEAVY_SCREEN_DWELL} PIXOO_HEAVY_SCREEN_MULTIPLIER=${PIXOO_HEAVY_SCREEN_MULTIPLIER} PIXOO_FRAME_INTERVAL=${PIXOO_FRAME_INTERVAL} PIXOO_COLOR_MODE=${PIXOO_COLOR_MODE} PIXOO_TEXT_SCROLL=${PIXOO_TEXT_SCROLL} PIXOO_ALERT_BLINK=${PIXOO_ALERT_BLINK} PIXOO_BLINK_PERIOD=${PIXOO_BLINK_PERIOD} PIXOO_RATE_STYLE=${PIXOO_RATE_STYLE} PIXOO_WLC_GRAPH_MODE=${PIXOO_WLC_GRAPH_MODE} PIXOO_WAN_MAX_DOWN_MBPS=${PIXOO_WAN_MAX_DOWN_MBPS} PIXOO_WAN_MAX_UP_MBPS=${PIXOO_WAN_MAX_UP_MBPS} PIXOO_SCREENS=${PIXOO_SCREENS} /bin/sh '${REMOTE_PATH}/install.sh'"
  echo "Install OK — metrics: http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json"
  echo "           — Pixoo bridge → ${PIXOO_IP} (daemon on Merlin)"
}

start_watchdog() {
  echo "==> start/ensure metrics + Pixoo bridge on Merlin ${ROUTER_HOST}"
  remote "
    if [ -x '${REMOTE_PATH}/watchdog.sh' ]; then
      # start is idempotent (cru-safe); does not kill healthy daemons
      '${REMOTE_PATH}/watchdog.sh' start
      '${REMOTE_PATH}/watchdog.sh' status || true
    else
      echo 'watchdog missing — run upload + install first' >&2
      exit 1
    fi
  "
}

reload_watchdog() {
  echo "==> reload metrics + Pixoo bridge on Merlin ${ROUTER_HOST}"
  remote "
    if [ -x '${REMOTE_PATH}/watchdog.sh' ]; then
      '${REMOTE_PATH}/watchdog.sh' reload
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
  # Rates need ≥1 previous sample (~2.5s). After a fresh start the first dump
  # is all zeros / empty histories — wait then print a short live summary.
  local raw summary
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 5 "http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json" >/dev/null 2>&1 || true
    sleep 3
    raw="$(curl -fsS --max-time 5 "http://${ROUTER_HOST}:${METRICS_PORT}/metrics.json" || true)"
    if [[ -z "${raw}" ]]; then
      echo "metrics unreachable" >&2
      return 1
    fi
    if command -v python3 >/dev/null 2>&1; then
      summary="$(printf '%s' "${raw}" | python3 -c '
import json,sys
m=json.load(sys.stdin)
hd=m.get("wan_history_down") or []
print(
  f"uptime={m.get(\"uptime_str\")} cpu={m.get(\"cpu\")} ram={m.get(\"ram\")} "
  f"clients={m.get(\"clients\")} wan_down={m.get(\"wan_down\")} wan_up={m.get(\"wan_up\")} "
  f"hist={len(hd)} top_down={m.get(\"top_down\")}"
)' 2>/dev/null || true)"
      echo "${summary}"
      if [[ "${summary}" == *'hist=0'* ]] || [[ "${summary}" == *'hist=1 '* ]]; then
        echo "(note: histories refill after restart — wait ~1 min for a full sparkline)"
      fi
      printf '%s\n' "${raw}" | python3 -m json.tool
    else
      printf '%s\n' "${raw}"
    fi
  else
    remote "wget -qO- http://127.0.0.1:${METRICS_PORT}/metrics.json 2>/dev/null; echo"
  fi
}

show_logs() {
  echo "==> Merlin logs (tail)"
  remote "
    echo '-- pixoo_bridge.log --'
    tail -n 40 '${REMOTE_PATH}/logs/pixoo_bridge.log' 2>/dev/null \
      || tail -n 40 /tmp/pixoo_bridge.log 2>/dev/null \
      || echo '(no pixoo_bridge log yet)'
    echo '-- pico_metrics.log --'
    tail -n 40 '${REMOTE_PATH}/logs/pico_metrics.log' 2>/dev/null || echo '(no metrics log yet)'
  "
}

pull_logs() {
  echo "==> pull logs → ${LOCAL_LOGS}/"
  mkdir -p "${LOCAL_LOGS}"
  local stamp
  stamp="$(date '+%Y%m%d_%H%M%S')"
  local dest="${LOCAL_LOGS}/${stamp}"
  mkdir -p "${dest}"
  # Prefer jffs persistent logs; also try /tmp mirror
  scp_base \
    "$(TARGET):${REMOTE_PATH}/logs/pixoo_bridge.log" \
    "$(TARGET):${REMOTE_PATH}/logs/pico_metrics.log" \
    "${dest}/" 2>/dev/null || true
  scp_base "$(TARGET):/tmp/pixoo_bridge.log" "${dest}/pixoo_bridge.tmp.log" 2>/dev/null || true
  # Symlink "latest" for convenience
  ln -sfn "${stamp}" "${LOCAL_LOGS}/latest" 2>/dev/null || true
  if [[ -f "${dest}/pixoo_bridge.log" ]] || [[ -f "${dest}/pico_metrics.log" ]] || [[ -f "${dest}/pixoo_bridge.tmp.log" ]]; then
    echo "Logs saved under ${dest}"
    ls -la "${dest}"
    echo ""
    echo "Quick peek (bridge):"
    tail -n 20 "${dest}/pixoo_bridge.log" 2>/dev/null \
      || tail -n 20 "${dest}/pixoo_bridge.tmp.log" 2>/dev/null \
      || echo "(empty)"
  else
    echo "warn: no log files found on router — is the bridge installed/started?" >&2
    return 1
  fi
}

# Pull last 64×64 frame (+ up to 10 hist) the bridge pushed to Pixoo (PNG).
pull_pixoo_snapshot() {
  echo "==> snapshot Pixoo frame (+ hist ≤10) → ${LOCAL_SNAPS}/"
  mkdir -p "${LOCAL_SNAPS}"
  local stamp dest dest_dir remote_png remote_txt remote_hist sid
  stamp="$(date '+%Y%m%d_%H%M%S')"
  dest_dir="${LOCAL_SNAPS}/${stamp}"
  dest="${dest_dir}/pixoo_last.png"
  remote_png="${REMOTE_PATH}/run/pixoo_last.png"
  remote_txt="${REMOTE_PATH}/run/pixoo_last.txt"
  remote_hist="${REMOTE_PATH}/run/hist"

  _try_scp_snap() {
    mkdir -p "${dest_dir}"
    scp_base "$(TARGET):${remote_png}" "${dest}" 2>/dev/null
  }

  if ! _try_scp_snap; then
    echo "Snapshot absent on Merlin — upload bridge + reload, then retry…"
    upload || true
    reload_watchdog || start_watchdog || true
    echo "Waiting 2s for first frame…"
    sleep 2
    if ! _try_scp_snap; then
      echo "warn: still no ${remote_png}" >&2
      echo "  Check: bridge running? Pillow OK? See ./deploy_monitor.sh logs" >&2
      return 1
    fi
  fi

  # Pull rolling history (best-effort; may be empty right after first start).
  mkdir -p "${dest_dir}/hist"
  scp_base -r "$(TARGET):${remote_hist}/." "${dest_dir}/hist/" 2>/dev/null || true
  # Flatten empty scp quirks: remove empty hist dir if nothing landed
  if [[ -d "${dest_dir}/hist" ]] && [[ -z "$(ls -A "${dest_dir}/hist" 2>/dev/null || true)" ]]; then
    rmdir "${dest_dir}/hist" 2>/dev/null || true
  fi

  ln -sfn "${stamp}/pixoo_last.png" "${LOCAL_SNAPS}/latest.png" 2>/dev/null || true
  ln -sfn "${stamp}" "${LOCAL_SNAPS}/latest" 2>/dev/null || true
  sid=""
  if scp_base "$(TARGET):${remote_txt}" "${dest_dir}/pixoo_last.txt" 2>/dev/null; then
    sid="$(tr -d '\r\n' < "${dest_dir}/pixoo_last.txt" 2>/dev/null || true)"
  fi
  local n_hist=0
  n_hist="$(find "${dest_dir}/hist" -name '*.png' 2>/dev/null | wc -l | tr -d ' ')"
  echo "OK 64×64 PNG: ${dest}${sid:+  (screen=${sid})}  hist=${n_hist}/10"
  ls -la "${dest}"
  if [[ -d "${dest_dir}/hist" ]]; then
    ls -la "${dest_dir}/hist" 2>/dev/null || true
  fi
  if command -v open >/dev/null 2>&1; then
    open "${dest_dir}" 2>/dev/null || open "${dest}" 2>/dev/null || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${dest_dir}" 2>/dev/null || xdg-open "${dest}" 2>/dev/null || true
  fi
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
  echo "==> Merlin ${ROUTER_HOST} + Pixoo ${PIXOO_IP}"
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
    echo '-- recent bridge log --'
    tail -n 8 '${REMOTE_PATH}/logs/pixoo_bridge.log' 2>/dev/null || echo '(no bridge log)'
  " 2>/dev/null || echo "(SSH unavailable — status from local probes only)"
  test_metrics || true
  ping_pixoo || true
  echo ""
  echo "Blank Pixoo? Metrics alone do not paint pixels — bridge must run on Merlin."
  echo "  ./deploy_monitor.sh auto   # or start after install"
  echo "  ./deploy_monitor.sh logs   # pull ${REMOTE_PATH}/logs/"
}

# Full pipeline: upload → install → start → verify.
# Does NOT uninstall/wipe — wiping stopped the bridge and left the Pixoo stuck
# on its last frame. Use menu « Uninstall » for a destructive reset.
auto_mode() {
  echo "╔══════════════════════════════════════════╗"
  echo "║  Mode automatique — Merlin + Pixoo       ║"
  echo "╚══════════════════════════════════════════╝"
  echo "  Merlin SSH : $(TARGET)"
  echo "  Pixoo      : ${PIXOO_IP}"
  echo "  Steps: upload → install → start → verify  (no wipe)"
  echo ""

  check_prereq || {
    echo "error: prerequisites failed — fix SSH / hosts first" >&2
    return 1
  }

  echo ""
  echo "[1/4] Upload merlin + pixoo_bridge…"
  upload

  echo ""
  echo "[2/4] Install (opkg + cru + metrics + Pixoo bridge)…"
  install_remote

  echo ""
  echo "[3/4] Ensure watchdog (metrics + bridge) running…"
  start_watchdog || true

  echo ""
  echo "[4/4] Verify metrics + Pixoo…"
  sleep 3
  test_metrics || true
  ping_pixoo || true

  echo ""
  echo "==> Auto mode finished — live status:"
  compute_status
  render_status_block
  echo ""
  if [[ "${ST_BRIDGE}" == "yes" ]] && [[ "${ST_METRICS}" == "yes" ]]; then
    echo "OK — Pixoo bridge running on Merlin → ${PIXOO_IP}."
    if [[ "${ST_PIXOO}" != "yes" ]]; then
      echo "WARN — Pixoo /post unreachable from laptop AND Merlin; check PIXOO_IP / VLAN."
    elif [[ "${ST_PIXOO_VIA}" == "merlin" ]]; then
      echo "Note — Pixoo not reachable from this laptop (guest/IoT VLAN); bridge path OK."
    fi
  else
    echo "WARN — check logs: ./deploy_monitor.sh logs"
    echo "  bridge=${ST_BRIDGE} metrics_http=${ST_METRICS} pixoo_api=${ST_PIXOO}"
  fi
  echo "Logs on router: ${REMOTE_PATH}/logs/pixoo_bridge.log"
  echo ""
  echo "==> Assistant paramétrage visuel"
  configure_visual
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
  "Mode automatique (Merlin + Pixoo)|auto_mode"
  "Prerequisites / SSH + Pixoo API|check_prereq"
  "Configure hosts (Merlin + Pixoo)|configure_router"
  "Assistant paramétrage visuel|configure_visual"
  "Sélection écrans Pixoo|configure_screens_and_apply"
  "Upload merlin + pixoo_bridge|upload"
  "Install (opkg + cru + start)|do_install"
  "Pilotage distant|pilotage_menu"
  "Start / restart (metrics+bridge)|start_watchdog"
  "Autostart status (cru)|autostart"
  "Test /metrics.json (Merlin)|test_metrics"
  "Test Pixoo API|ping_pixoo"
  "Snapshot Pixoo → PNG (+hist≤10)|pull_pixoo_snapshot"
  "Tail logs (remote)|show_logs"
  "Récupérer logs → local|pull_logs"
  "Uninstall|uninstall_remote"
  "Refresh status|status_remote"
  "Quit|quit"
)

PILOT_MENU_ITEMS=(
  "Start metrics+bridge (watchdog)|start_watchdog"
  "Stop metrics+bridge|stop_watchdog"
  "Cron ON (cru a PicoMonitor)|cron_on"
  "Cron OFF (cru d PicoMonitor)|cron_off"
  "Paramétrage visuel|configure_visual"
  "Sélection écrans|configure_screens_and_apply"
  "État détaillé|pilot_status"
  "Test Pixoo API|ping_pixoo"
  "Snapshot Pixoo → PNG (+hist≤10)|pull_pixoo_snapshot"
  "Test metrics Merlin|test_metrics"
  "Récupérer logs|pull_logs"
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
║  Pilotage distant — Merlin / Pixoo       ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pixoo:      ${PIXOO_IP}
║  Remote:     ${REMOTE_PATH}
╚══════════════════════════════════════════╝

EOF
  else
    cat <<EOF
╔══════════════════════════════════════════╗
║  Merlin metrics + Pixoo bridge deploy    ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pixoo:      ${PIXOO_IP}
║  Remote:     ${REMOTE_PATH}
╚══════════════════════════════════════════╝

EOF
  fi
  render_status_block
  echo ""
  if [[ "${items_name}" == "PILOT_MENU_ITEMS" ]]; then
    echo "  ↑/↓ move  ·  ENTER run  ·  1-9 jump  ·  q quit"
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
    echo "  start/stop/cron via SSH · Pixoo = ${PIXOO_IP}"
  else
    echo "  Auto: upload+install+start (no wipe). Uninstall = menu item."
    echo "  Logs: ${REMOTE_PATH}/logs/  →  ./deploy_monitor.sh logs"
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
    configure_visual) configure_visual ;;
    configure_screens_and_apply) configure_screens_and_apply ;;
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
    ping_pixoo) ping_pixoo || true ;;
    pull_pixoo_snapshot) pull_pixoo_snapshot || true ;;
    autostart) autostart ;;
    test_metrics) test_metrics || true ;;
    show_logs) show_logs ;;
    pull_logs) pull_logs || true ;;
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
        # Skip SSH status refresh — that was the multi-second lag after ENTER.
        # User can run "Refresh status" when they want a live probe.
        need_status=0
        clear_screen
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
║  Pilotage distant — Merlin / Pixoo       ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pixoo:      ${PIXOO_IP}
║  Remote:     ${REMOTE_PATH}
╚══════════════════════════════════════════╝

EOF
    else
      cat <<EOF
╔══════════════════════════════════════════╗
║  Merlin metrics + Pixoo bridge deploy    ║
║  Merlin SSH: ${USER_NAME}@${ROUTER_HOST}
║  Pixoo:      ${PIXOO_IP}
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
Usage: $0 [menu|install|uninstall|status|auto|upload|test|flash|pilot|start|stop|cron-on|cron-off|logs|snapshot|visual|screens]

  (no args) / menu   Interactive menu (↑/↓ + ENTER, or numbers)
  auto               Full pipeline + assistant paramétrage visuel
  visual             Assistant paramétrage visuel (mono/poly, blink, refresh…)
  screens            Sélection des écrans actifs (≥1)
  install            Upload + install + start (metrics + Pixoo bridge on Merlin)
  uninstall          Remove Merlin addon + cru
  status             Live Merlin + Pixoo status
  upload             Sync merlin/ + pixoo_bridge/
  test               GET /metrics.json
  logs               Pull router logs → pico_monitor/logs/
  snapshot           Pull last 64×64 Pixoo frame + hist≤10 → pico_monitor/logs/snapshots/
  flash              Pico OLED firmware sync (optional; not for Pixoo)
  pilot              Remote pilotage submenu (start/stop/cron/status/tests)
  start              Start/reload metrics + Pixoo bridge on Merlin
  stop               Stop metrics + Pixoo bridge on Merlin
  cron-on            Enable cru job PicoMonitor
  cron-off           Disable cru job PicoMonitor

Env / .deploy.env:
  PICO_ROUTER_HOST  Merlin LAN IP for SSH + metrics (default 192.168.50.1)
  PIXOO_IP          Divoom Pixoo 64 (HTTP /post)     (default 192.168.52.4)
  PICO_MERLIN_HOST  Optional Pico W LAN IP (OLED ping only)
  PICO_MERLIN_USER  SSH user on Merlin              (default elphara77)
  PICO_MERLIN_PATH  remote addon path
  PICO_SSH_AUTH     key|password
  PICO_METRICS_PORT metrics HTTP port (default 8088)
  PIXOO_BRIGHTNESS / PIXOO_SCREEN_SECONDS / PIXOO_FRAME_INTERVAL
  PIXOO_COLOR_MODE   mono|poly (default mono — sharp pixel text)
  PIXOO_TEXT_SCROLL  1|0 scroll long titles/labels (default 1)
  PIXOO_ALERT_BLINK  1|0 blink critical text/gauges (default 1)
  PIXOO_BLINK_PERIOD half-cycle seconds for blink (default 0.55)
  PIXOO_RATE_STYLE   short|long (K/M/G vs Kb/s)
  PIXOO_SCREENS       all | all,SUM | SUM | SYS,LOD,... (SUM = résumé opt., hors défaut)

Pixoo display: auto install starts pixoo_bridge ON Merlin (Entware).
Logs: ${REMOTE_PATH:-/jffs/addons/pico_monitor}/logs/pixoo_bridge.log
      pull with: ./deploy_monitor.sh logs
EOF
}

load_config
CMD="${1:-menu}"
case "${CMD}" in
  -h|--help|help) usage ;;
  menu) menu ;;
  auto|automatic|auto_mode) auto_mode ;;
  visual|visuel|configure_visual|configure-visual) configure_visual ;;
  screens|ecrans|configure_screens|configure-screens) configure_screens_and_apply ;;
  install) check_prereq; upload; install_remote ;;
  uninstall) uninstall_remote ;;
  status) status_remote ;;
  upload) upload ;;
  test) test_metrics ;;
  logs|pull-logs|pull_logs) pull_logs ;;
  snapshot|snap|pixoo-snap|pull_snapshot) pull_pixoo_snapshot ;;
  flash) flash_pico ;;
  pilot|pilotage) pilotage_menu ;;
  start) start_watchdog ;;
  stop) stop_watchdog ;;
  cron-on|cron_on) cron_on ;;
  cron-off|cron_off) cron_off ;;
  *) usage; exit 2 ;;
esac
