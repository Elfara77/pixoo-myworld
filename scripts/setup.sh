#!/usr/bin/env bash
# Dynamic Setup & Config Menu for Future App
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CONFIG_FILE="${ROOT}/config.toml"
CONFIG_EXAMPLE="${ROOT}/config.example.toml"

ensure_config() {
  if [[ ! -f "$CONFIG_FILE" ]]; then
    if [[ -f "$CONFIG_EXAMPLE" ]]; then
      cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
      echo "Configuration initialisée depuis config.example.toml"
    else
      cat > "$CONFIG_FILE" <<'EOF'
# Configuration par défaut
[pixoo]
ip = "192.168.52.4"
brightness = 50

[engine]
host = "0.0.0.0"
port = 8000
refresh_interval = 1.0

[merlin]
host = "192.168.50.1"
user = "elphara77"
port = 22
EOF
      echo "Fichier config.toml créé avec les valeurs par défaut."
    fi
  fi
}

edit_config_interactive() {
  ensure_config
  echo "--- Édition interactive de config.toml ---"
  echo "Contenu actuel :"
  cat "$CONFIG_FILE"
  echo "-----------------------------------------"
  read -r -p "Appuyez sur Entrée pour modifier dans l'éditeur par défaut (${EDITOR:-nano})..."
  "${EDITOR:-nano}" "$CONFIG_FILE"
}

run_studio() {
  if [[ -f "./scripts/studio.sh" ]]; then
    ./scripts/studio.sh "$@"
  else
    python3 -m pixoo studio "$@"
  fi
}

run_designer() {
  if [[ -f "./scripts/designer.sh" ]]; then
    ./scripts/designer.sh "$@"
  else
    python3 -m pixoo_designer "$@"
  fi
}

run_monitor() {
  python3 -m pixoo_monitor "$@"
}

run_pico_deploy() {
  if [[ -f "./pico_monitor/deploy_monitor.sh" ]]; then
    ./pico_monitor/deploy_monitor.sh "$@"
  else
    echo "Module pico_monitor/deploy_monitor.sh non trouvé."
  fi
}

run_tests() {
  echo "==> Exécution des tests unitaires..."
  python3 -m unittest discover tests
}

main_menu() {
  ensure_config
  while true; do
    echo "=========================================="
    echo "       Future App - Console & Setup       "
    echo "=========================================="
    echo "1) Lancer Pixoo Studio (Qt GUI)"
    echo "2) Lancer Pixoo Designer"
    echo "3) Lancer Pixoo Monitor (System & Nextcloud)"
    echo "4) Lancer Déploiement Pico/Merlin / Pixoo Bridge"
    echo "5) Éditer la configuration (config.toml)"
    echo "6) Exécuter les tests unitaires"
    echo "7) Quitter"
    echo "=========================================="
    read -r -p "Choix [1-7]: " choice
    case "$choice" in
      1) run_studio ;;
      2) run_designer ;;
      3) run_monitor ;;
      4) run_pico_deploy ;;
      5) edit_config_interactive ;;
      6) run_tests ;;
      7) echo "Au revoir !"; exit 0 ;;
      *) echo "Option invalide." ;;
    esac
    echo ""
  done
}

if [[ $# -gt 0 ]]; then
  case "$1" in
    edit) edit_config_interactive ;;
    studio) shift; run_studio "$@" ;;
    designer) shift; run_designer "$@" ;;
    monitor) shift; run_monitor "$@" ;;
    pico) shift; run_pico_deploy "$@" ;;
    test) run_tests ;;
    *) main_menu ;;
  esac
else
  main_menu
fi
