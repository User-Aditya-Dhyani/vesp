#!/usr/bin/env bash
set -Eeuo pipefail

# ========== config ==========
APP_NAME="vesp"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_ROOT}/.install_logs"
mkdir -p "$LOG_DIR"

echo "[install] ${APP_NAME} installer starting…"
echo "[install] REPO_ROOT=${REPO_ROOT}"

require_sudo() {
  if [[ ${EUID:-$UID} -ne 0 ]]; then
    echo "[install] escalating to sudo for system tasks…"
    sudo -p "[sudo] password for %u: " true >/dev/null 2>&1 || {
      echo "[install] sudo not available or denied"; exit 1; }
  fi
}

# 1) System deps (best effort; continue if offline but warn)
echo "[install] Installing/ensuring system prerequisites…"
require_sudo
if ! sudo apt-get update -y >>"$LOG_DIR/apt.log" 2>&1; then
  echo "[install][WARN] apt update failed (offline?). Will continue, but setup may be incomplete."
fi
sudo apt-get install -y \
  bluetooth bluez bluez-meshd bluez-tools \
  dbus policykit-1 \
  python3 python3-venv python3-gi python3-gi-cairo python3-dbus \
  libgirepository1.0-dev \
  libwebkit2gtk-4.1-0 libwebkit2gtk-4.1-dev librsvg2-2 librsvg2-dev \
  pkg-config build-essential curl wget file libxdo-dev libssl-dev \
  libayatana-appindicator3-dev \
  >>"$LOG_DIR/apt.log" 2>&1 || echo "[install][WARN] apt install had errors; will verify in doctor."

# Ensure services running
sudo systemctl enable --now bluetooth || true
sudo systemctl enable --now bluetooth-meshd || true

# 2) Bluetooth controller prep (idempotent)
echo "[install] Preparing controller (idempotent)…"
sudo btmgmt --index 0 power off  >/dev/null 2>&1 || true
sudo btmgmt --index 0 le on       >/dev/null 2>&1 || true
sudo btmgmt --index 0 bredr off   >/dev/null 2>&1 || true
sudo btmgmt --index 0 connectable on >/dev/null 2>&1 || true
sudo btmgmt --index 0 bondable on >/dev/null 2>&1 || true
sudo btmgmt --index 0 power on    >/dev/null 2>&1 || true
sudo systemctl restart bluetooth-meshd || true

# 3) Python env (system-site so GI works without compiling)
echo "[install] Setting up Python environment…"
bash "${REPO_ROOT}/scripts/setup_python_env.sh"

# 4) Health check
echo "[install] Running doctor…"
bash "${REPO_ROOT}/scripts/doctor.sh" || {
  echo "[install][ERROR] Doctor reported failures. See messages above."; exit 2;
}

echo "[install] ${APP_NAME} install complete ✅"

