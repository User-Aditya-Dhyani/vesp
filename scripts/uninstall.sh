#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
STATE_DIR="${HOME}/.config/vesp"

echo "[VESP] Uninstall starting..."

# 1) Remove Python venv
if [[ -d "$VENV_DIR" ]]; then
  echo "[VESP] Removing Python venv at $VENV_DIR ..."
  rm -rf "$VENV_DIR"
else
  echo "[VESP] No venv found at $VENV_DIR (skipping)."
fi

# 2) Remove local app state (token, logs)
if [[ -d "$STATE_DIR" ]]; then
  echo "[VESP] Removing local state at $STATE_DIR ..."
  rm -rf "$STATE_DIR"
else
  echo "[VESP] No state directory at $STATE_DIR (skipping)."
fi

# 3) Optional: stop daemons (not required)
if [[ "${VESP_STOP_DAEMONS:-0}" == "1" ]]; then
  if systemctl list-unit-files | grep -q '^bluetooth-meshd\.service'; then
    echo "[VESP] Stopping bluetooth-meshd..."
    sudo systemctl stop bluetooth-meshd || true
  fi
  if systemctl list-unit-files | grep -q '^bluetooth\.service'; then
    echo "[VESP] Stopping bluetooth..."
    sudo systemctl stop bluetooth || true
  fi
fi

# 4) Optional: purge apt packages (DANGEROUS)
# Only do this if you are sure; it may affect other Bluetooth apps.
if [[ "${VESP_PURGE_APT:-0}" == "1" ]]; then
  echo "[VESP] Purging apt packages (this may affect other software)..."
  sudo apt-get purge -y bluez python3-gi gir1.2-glib-2.0 libglib2.0-bin python3-tk python3-venv || true
  sudo apt-get autoremove -y || true
else
  echo "[VESP] Leaving system packages intact. Set VESP_PURGE_APT=1 to purge."
fi

echo "[VESP] Uninstall complete."

