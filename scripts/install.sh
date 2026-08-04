#!/usr/bin/env bash
# Installe pipenv + dépendances (Debian 13 / macOS Silicon)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

print_help() {
  cat <<'EOF'
Usage: ./scripts/install.sh [options]

Installe pipenv, le venv projet et les dépendances Python.
Détecte Debian / macOS Apple Silicon.

Options:
  -h, --help          Affiche cette aide
  --yes, -y           Non-interactif (accepte les actions par défaut)
  --skip-system       Ne pas installer de paquets système (apt/brew)
  --with-sensors      Tente lm-sensors / rappelle osx-cpu-temp

Sans argument: mode interactif (confirme plateforme / extras).

Exemples:
  ./scripts/install.sh
  ./scripts/install.sh --yes
  ./scripts/install.sh --skip-system --yes
EOF
}

YES=0
SKIP_SYSTEM=0
WITH_SENSORS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) print_help; exit 0 ;;
    -y|--yes) YES=1; shift ;;
    --skip-system) SKIP_SYSTEM=1; shift ;;
    --with-sensors) WITH_SENSORS=1; shift ;;
    *) echo "Option inconnue: $1"; print_help; exit 1 ;;
  esac
done

OS="$(uname -s)"
ARCH="$(uname -m)"

if [[ "$YES" -eq 0 && -t 0 ]]; then
  echo "Pixoo Monitor — install ($OS $ARCH)"
  read -r -p "Continuer l'installation ? [O/n] " ans
  case "${ans:-O}" in
    n|N|non|Non) echo "Annulé"; exit 0 ;;
  esac
  if [[ "$SKIP_SYSTEM" -eq 0 ]]; then
    read -r -p "Installer aussi les paquets système utiles (fonts, sensors) ? [O/n] " ans2
    case "${ans2:-O}" in
      n|N|non|Non) SKIP_SYSTEM=1 ;;
    esac
  fi
  if [[ "$WITH_SENSORS" -eq 0 ]]; then
    read -r -p "Préparer les capteurs température (optionnel) ? [o/N] " ans3
    case "${ans3:-N}" in
      o|O|y|Y|oui|Oui) WITH_SENSORS=1 ;;
    esac
  fi
fi

echo "==> Pixoo Monitor — install ($OS $ARCH)"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_pipenv() {
  if need_cmd pipenv; then
    echo "    pipenv: $(command -v pipenv)"
    return
  fi
  echo "==> Installation de pipenv…"
  if [[ "$OS" == "Darwin" ]]; then
    if need_cmd brew; then
      brew install pipenv
    else
      python3 -m pip install --user pipenv
      export PATH="${HOME}/Library/Python/3.12/bin:${HOME}/.local/bin:${PATH}"
    fi
  else
    if need_cmd apt-get; then
      sudo apt-get update
      sudo apt-get install -y pipenv python3-pip python3-venv \
        fonts-dejavu-core || true
    fi
    if ! need_cmd pipenv; then
      python3 -m pip install --user pipenv
      export PATH="${HOME}/.local/bin:${PATH}"
    fi
  fi
  need_cmd pipenv || { echo "ERREUR: pipenv introuvable"; exit 1; }
}

pick_python() {
  if [[ -n "${PIPENV_PYTHON:-}" ]]; then
    echo "$PIPENV_PYTHON"
    return
  fi
  for cand in python3.12 python3.13 python3.11 python3; do
    if need_cmd "$cand"; then
      ver="$("$cand" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
      major="${ver%%.*}"
      minor="${ver#*.}"
      if [[ "$major" -eq 3 && "$minor" -ge 11 ]]; then
        echo "$(command -v "$cand")"
        return
      fi
    fi
  done
  echo "ERREUR: Python ≥ 3.11 requis" >&2
  exit 1
}

if [[ "$SKIP_SYSTEM" -eq 0 ]]; then
  if [[ "$OS" == "Linux" ]] && need_cmd apt-get; then
    echo "==> Paquets système (Debian)…"
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-pip fonts-dejavu-core \
      lm-sensors || true
    if [[ "$WITH_SENSORS" -eq 1 ]] && need_cmd sensors-detect; then
      echo "    Astuce: sudo sensors-detect && sensors"
    fi
  elif [[ "$OS" == "Darwin" ]]; then
    echo "==> macOS Silicon — température optionnelle via osx-cpu-temp"
    if [[ "$WITH_SENSORS" -eq 1 ]] && need_cmd brew && ! need_cmd osx-cpu-temp; then
      echo "    Optionnel: brew install osx-cpu-temp"
    fi
  fi
fi

install_pipenv
PY="$(pick_python)"
echo "==> Python: $PY"

export PIPENV_VENV_IN_PROJECT=1
export PIPENV_IGNORE_VIRTUALENVS=1

echo "==> pipenv install…"
pipenv --python "$PY" install

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$ROOT/configs/setups" "$ROOT/data/history" "$ROOT/assets/test_preview" "$ROOT/logs"

if [[ ! -f "$ROOT/config.toml" ]]; then
  cp "$ROOT/config.example.toml" "$ROOT/config.toml"
  echo "==> config.toml créé depuis config.example.toml"
fi

echo ""
echo "OK. Prochaines étapes:"
echo "  ./scripts/setup.sh     # wizard / setups nommés"
echo "  ./scripts/test.sh      # dry-run PNG"
echo "  ./scripts/run.sh       # monitoring live"
echo "  ./scripts/cron-setup.sh"
