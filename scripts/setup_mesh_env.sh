#!/usr/bin/env bash
set -Eeuo pipefail

echo "[mesh-env] Ensuring BlueZ/mesh prerequisites…"
sudo apt-get install -y bluetooth bluez bluez-meshd bluez-tools dbus policykit-1 >/dev/null 2>&1 || true

sudo systemctl enable --now bluetooth || true
sudo systemctl enable --now bluetooth-meshd || true

# Conservative controller prep
sudo btmgmt --index 0 power off  >/dev/null 2>&1 || true
sudo btmgmt --index 0 le on       >/dev/null 2>&1 || true
sudo btmgmt --index 0 bredr off   >/dev/null 2>&1 || true
sudo btmgmt --index 0 connectable on >/dev/null 2>&1 || true
sudo btmgmt --index 0 bondable on >/dev/null 2>&1 || true
sudo btmgmt --index 0 power on    >/dev/null 2>&1 || true
sudo systemctl restart bluetooth-meshd || true

echo "[mesh-env] Done."

