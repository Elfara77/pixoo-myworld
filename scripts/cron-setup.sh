#!/usr/bin/env bash
# Automatise le monitoring Pixoo en arrière-plan.
# Préfère un timer systemd --user sur Debian ; sinon crontab utilisateur.
#
# Usage:
#   ./scripts/cron-setup.sh              # menu interactif
#   ./scripts/cron-setup.sh enable
#   ./scripts/cron-setup.sh disable
#   ./scripts/cron-setup.sh status
#   ./scripts/cron-setup.sh uninstall
#   ./scripts/cron-setup.sh enable --cron          # forcer crontab
#   ./scripts/cron-setup.sh enable --systemd       # forcer systemd user
#   ./scripts/cron-setup.sh enable --interval 60   # cron: toutes les 60s via --once
#   ./scripts/cron-setup.sh enable --profile status
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UNIT_NAME="pixoo-monitor"
SERVICE_FILE="${HOME}/.config/systemd/user/${UNIT_NAME}.service"
TIMER_FILE="${HOME}/.config/systemd/user/${UNIT_NAME}.timer"
LOG_DIR="${ROOT}/logs"
LOG_FILE="${LOG_DIR}/monitor.log"
CRON_TAG="# pixoo-monitor"
MARKER="PIXOO_MONITOR_CRON"

export PIPENV_VENV_IN_PROJECT=1
export PIPENV_IGNORE_VIRTUALENVS=1

MODE=""
FORCE=""
INTERVAL=60
PROFILE=""
ACTION="${1:-}"
shift || true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cron) FORCE="cron"; shift ;;
    --systemd) FORCE="systemd"; shift ;;
    --interval) INTERVAL="${2:-60}"; shift 2 ;;
    --profile) PROFILE="${2:-}"; shift 2 ;;
    enable|disable|status|uninstall|help)
      ACTION="$1"; shift ;;
    -h|--help) ACTION="help"; shift ;;
    *) echo "Option inconnue: $1"; ACTION="help"; shift ;;
  esac
done

resolve_python() {
  if [[ -x "${ROOT}/.venv/bin/python" ]]; then
    echo "${ROOT}/.venv/bin/python"
  elif command -v pipenv >/dev/null 2>&1 && pipenv --venv >/dev/null 2>&1; then
    echo "pipenv run python"
  else
    echo ""
  fi
}

run_cmd_prefix() {
  local py
  py="$(resolve_python)"
  if [[ -z "$py" ]]; then
    echo "Environnement Python absent. Lance ./scripts/install.sh" >&2
    return 1
  fi
  if [[ "$py" == "pipenv run python" ]]; then
    echo "cd \"$ROOT\" && export PYTHONPATH=\"$ROOT/src\" PIPENV_VENV_IN_PROJECT=1 PIPENV_IGNORE_VIRTUALENVS=1 && pipenv run python -m pixoo_monitor"
  else
    echo "cd \"$ROOT\" && export PYTHONPATH=\"$ROOT/src\" && \"$py\" -m pixoo_monitor"
  fi
}

has_systemd_user() {
  command -v systemctl >/dev/null 2>&1 || return 1
  # macOS n'a pas systemd
  [[ "$(uname -s)" == "Linux" ]] || return 1
  systemctl --user show-environment >/dev/null 2>&1
}

choose_backend() {
  if [[ -n "$FORCE" ]]; then
    echo "$FORCE"
    return
  fi
  if has_systemd_user; then
    echo "systemd"
  else
    echo "cron"
  fi
}

ensure_config() {
  if [[ ! -f "$ROOT/config.toml" ]]; then
    echo "Pas de config.toml — lance ./scripts/setup.sh d'abord"
    exit 1
  fi
}

mkdir -p "$LOG_DIR"

profile_args() {
  if [[ -n "$PROFILE" ]]; then
    echo -- --profile "$PROFILE"
  else
    echo ""
  fi
}

install_systemd() {
  ensure_config
  mkdir -p "${HOME}/.config/systemd/user"
  local prefix
  prefix="$(run_cmd_prefix)"
  local prof=""
  if [[ -n "$PROFILE" ]]; then
    prof=" --profile ${PROFILE}"
  fi

  cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Pixoo 64 system monitor (Nextcloud / N40)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${ROOT}
Environment=PYTHONPATH=${ROOT}/src
Environment=PIPENV_VENV_IN_PROJECT=1
Environment=PIPENV_IGNORE_VIRTUALENVS=1
ExecStart=/bin/bash -lc '${prefix}${prof}'
Restart=on-failure
RestartSec=10
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

[Install]
WantedBy=default.target
EOF

  # Timer optionnel : si INTERVAL > 0 et on veut --once périodique.
  # Par défaut on utilise un service daemon continu (meilleur pour Pixoo).
  cat >"$TIMER_FILE" <<EOF
[Unit]
Description=Timer keep-alive for pixoo-monitor (optional)
# Le service tourne en continu ; ce timer sert surtout de rappel / redémarrage soft.

[Timer]
OnBootSec=30
OnUnitActiveSec=${INTERVAL:-3600}s
AccuracySec=10s
Persistent=true
Unit=${UNIT_NAME}.service

[Install]
WantedBy=timers.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable --now "${UNIT_NAME}.service"
  # Activer aussi le lingering hint
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$(id -un)" 2>/dev/null || true
  fi
  echo "systemd --user: ${UNIT_NAME}.service activé"
  echo "Logs: ${LOG_FILE}"
  echo "Commandes: systemctl --user status ${UNIT_NAME}.service"
}

uninstall_systemd() {
  if has_systemd_user; then
    systemctl --user disable --now "${UNIT_NAME}.timer" 2>/dev/null || true
    systemctl --user disable --now "${UNIT_NAME}.service" 2>/dev/null || true
    systemctl --user daemon-reload 2>/dev/null || true
  fi
  rm -f "$SERVICE_FILE" "$TIMER_FILE"
  echo "systemd user units retirés (si présents)"
}

install_cron() {
  ensure_config
  local prefix
  prefix="$(run_cmd_prefix)"
  local prof=""
  if [[ -n "$PROFILE" ]]; then
    prof=" --profile ${PROFILE}"
  fi
  # Toutes les minutes : une frame (--once). Pour continuum préférer systemd.
  local schedule="* * * * *"
  if [[ "$INTERVAL" -ge 120 ]]; then
    local mins=$(( INTERVAL / 60 ))
    [[ "$mins" -lt 1 ]] && mins=1
    schedule="*/${mins} * * * *"
  fi
  local line="${schedule} ${MARKER} ${prefix} --once${prof} >>\"${LOG_FILE}\" 2>&1 ${CRON_TAG}"

  local tmp
  tmp="$(mktemp)"
  crontab -l 2>/dev/null | grep -v "${MARKER}" | grep -v "${CRON_TAG}" >"$tmp" || true
  echo "$line" >>"$tmp"
  crontab "$tmp"
  rm -f "$tmp"
  echo "crontab installé (${schedule}) — frame --once"
  echo "Logs: ${LOG_FILE}"
  echo "Note: pour une boucle continue, préfère: $0 enable --systemd"
}

uninstall_cron() {
  if crontab -l 2>/dev/null | grep -q "${MARKER}\|${CRON_TAG}"; then
    local tmp
    tmp="$(mktemp)"
    crontab -l 2>/dev/null | grep -v "${MARKER}" | grep -v "${CRON_TAG}" >"$tmp" || true
    if [[ -s "$tmp" ]]; then
      crontab "$tmp"
    else
      crontab -r 2>/dev/null || true
    fi
    rm -f "$tmp"
    echo "entrées crontab pixoo-monitor retirées"
  else
    echo "pas d'entrée crontab pixoo-monitor"
  fi
}

do_status() {
  echo "=== pixoo-monitor automation ==="
  echo "Root: $ROOT"
  echo "Log:  $LOG_FILE"
  if has_systemd_user; then
    echo "--- systemd --user ---"
    systemctl --user status "${UNIT_NAME}.service" --no-pager 2>&1 | head -n 20 || echo "(service absent)"
  else
    echo "systemd --user: non disponible"
  fi
  echo "--- crontab ---"
  crontab -l 2>/dev/null | grep -E "${MARKER}|${CRON_TAG}" || echo "(aucune entrée)"
  if [[ -f "$LOG_FILE" ]]; then
    echo "--- derniers logs ---"
    tail -n 15 "$LOG_FILE" || true
  fi
}

do_enable() {
  local backend
  backend="$(choose_backend)"
  echo "Backend: $backend"
  if [[ "$backend" == "systemd" ]]; then
    uninstall_cron || true
    install_systemd
  else
    uninstall_systemd || true
    install_cron
  fi
}

do_disable() {
  if has_systemd_user && systemctl --user is-enabled "${UNIT_NAME}.service" >/dev/null 2>&1; then
    systemctl --user disable --now "${UNIT_NAME}.service" 2>/dev/null || true
    systemctl --user disable --now "${UNIT_NAME}.timer" 2>/dev/null || true
    echo "systemd service stoppé / désactivé (fichiers conservés)"
  fi
  uninstall_cron || true
}

do_uninstall() {
  uninstall_systemd || true
  uninstall_cron || true
  echo "Désinstallation automation terminée"
}

interactive_menu() {
  echo "Pixoo monitor — automation"
  echo "  1) enable"
  echo "  2) disable"
  echo "  3) status"
  echo "  4) uninstall"
  echo "  5) quit"
  read -r -p "> " choice
  case "$choice" in
    1) ACTION=enable ;;
    2) ACTION=disable ;;
    3) ACTION=status ;;
    4) ACTION=uninstall ;;
    *) exit 0 ;;
  esac
  if [[ "$ACTION" == "enable" ]]; then
    if has_systemd_user; then
      read -r -p "Backend [systemd/cron] (défaut systemd): " b
      case "$b" in
        cron) FORCE=cron ;;
        *) FORCE=systemd ;;
      esac
    else
      FORCE=cron
    fi
    read -r -p "Profil optionnel (vide = active_profiles): " PROFILE
  fi
}

print_help() {
  cat <<EOF
Usage: ./scripts/cron-setup.sh [action] [options]

Automatise le monitoring Pixoo en arrière-plan.
Debian: systemd --user (daemon continu). Sinon: crontab (--once périodique).

Sans argument: menu interactif (enable / disable / status / uninstall).

Actions:
  enable              Active l'automation
  disable             Stoppe sans supprimer les fichiers unit
  status              Affiche systemd / crontab / logs
  uninstall           Retire systemd + crontab
  help                Cette aide

Options:
  -h, --help          Cette aide
  --systemd           Forcer systemd --user
  --cron              Forcer crontab
  --interval N        Intervalle secondes (cron; défaut 60)
  --profile NAME      Ex: status, n40, nextcloud_full

Exemples:
  ./scripts/cron-setup.sh
  ./scripts/cron-setup.sh enable --systemd
  ./scripts/cron-setup.sh enable --cron --interval 60 --profile status
  ./scripts/cron-setup.sh status
  ./scripts/cron-setup.sh uninstall

Logs: ${LOG_FILE}
EOF
}

if [[ -z "$ACTION" ]]; then
  if [[ -t 0 ]]; then
    interactive_menu
  else
    ACTION=help
  fi
fi

case "$ACTION" in
  enable) do_enable ;;
  disable) do_disable ;;
  status) do_status ;;
  uninstall) do_uninstall ;;
  help|*) print_help; [[ "$ACTION" == "help" ]] || exit 1 ;;
esac
