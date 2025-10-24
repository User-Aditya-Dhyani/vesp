#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# ----- Config -----
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

echo "[VESP] Installing dependencies for Ubuntu 24.04 (ADV-only BlueZ Mesh)..."

# ----- APT packages -----
echo "[VESP] Updating apt and installing system packages..."
sudo apt-get update -y
sudo apt-get install -y \
  bluez \
  dbus dbus-user-session \
  python3 python3-pip python3-venv \
  python3-gi gir1.2-glib-2.0 libglib2.0-bin \
  python3-tk \
  pkg-config

# (Optional, useful tools)
if ! command -v btmgmt >/dev/null 2>&1; then
  echo "[VESP] Installing bluez tools (btmgmt)..."
  sudo apt-get install -y bluez
fi

# ----- Check/enable mesh daemon -----
MESH_D_BIN=""
for p in /usr/lib/bluetooth/bluetooth-meshd /usr/libexec/bluetooth/bluetooth-meshd /usr/sbin/bluetooth-meshd; do
  if [[ -x "$p" ]]; then MESH_D_BIN="$p"; break; fi
done

if [[ -z "$MESH_D_BIN" ]]; then
  echo "[VESP] ERROR: bluetooth-meshd binary not found after installing bluez."
  echo "       On Ubuntu 24.04 it should be part of the 'bluez' package."
  echo "       Please ensure BlueZ >= 5.50 is installed. Aborting."
  exit 1
fi
echo "[VESP] Found mesh daemon: $MESH_D_BIN"

# Try enabling the systemd unit if present (not all distros ship a unit)
if systemctl list-unit-files | grep -q '^bluetooth-meshd\.service'; then
  echo "[VESP] Enabling and starting bluetooth-meshd..."
  sudo systemctl enable --now bluetooth-meshd
else
  echo "[VESP] Note: No bluetooth-meshd.service unit found."
  echo "      The daemon is typically socket/dbus-activated on Ubuntu. Proceeding."
fi

# Ensure main bluetooth service is up
if systemctl list-unit-files | grep -q '^bluetooth\.service'; then
  sudo systemctl enable --now bluetooth || true
fi

# ----- Python venv (must include system site-packages so python3-gi is visible) -----
if [[ -d "$VENV_DIR" ]]; then
  echo "[VESP] Found existing venv at $VENV_DIR"
  if ! grep -q '^include-system-site-packages = true' "$VENV_DIR/pyvenv.cfg" 2>/dev/null; then
    echo "[VESP] Existing venv lacks system-site-packages; recreating..."
    rm -rf "$VENV_DIR"
    python3 -m venv --system-site-packages "$VENV_DIR"
  fi
else
  echo "[VESP] Creating Python virtual environment at $VENV_DIR (with system site-packages)..."
  python3 -m venv --system-site-packages "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip wheel setuptools
python -m pip install --no-cache-dir pydbus

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip wheel setuptools

echo "[VESP] Installing Python packages into venv..."
# pydbus uses PyGObject via system packages we already installed
python -m pip install --no-cache-dir pydbus

# ----- Sanity checks -----
echo "[VESP] Running sanity checks..."
python - <<'PY'
import sys
try:
    import gi
    from gi.repository import GLib
    import pydbus
except Exception as e:
    sys.stderr.write(f"[SANITY] Python import failure: {e}\n")
    raise SystemExit(1)
print("[SANITY] Python imports OK (gi, GLib, pydbus)")
PY

# Check we can see the system bus
python - <<'PY'
import sys
from pydbus import SystemBus
try:
    bus = SystemBus()
    print("[SANITY] System bus reachable.")
except Exception as e:
    sys.stderr.write(f"[SANITY] Failed to reach system bus: {e}\n")
    raise SystemExit(1)
PY

# Basic adapter power-on (safe even if already on)
if command -v btmgmt >/dev/null 2>&1; then
  echo "[VESP] Ensuring adapter is powered on (btmgmt)..."
  sudo btmgmt power on || true
else
  echo "[VESP] 'btmgmt' not found; skipping adapter power check."
fi

# ----- Done -----
cat <<'TXT'

[VESP] Install complete ✅

Usage (inside project root):
  # Activate venv for this shell
  source .venv/bin/activate

  # GUI app (requires desktop session)
  python3 run_gui.py

  # Headless logger (ssh/headless OK):
  python3 run_logger.py --create      # first run (creates local node)
  python3 run_logger.py               # afterwards (attach & log)
  python3 run_logger.py --scan 20     # scan unprovisioned via ADV
  python3 run_logger.py --provision DDDD441D64BD1F0E0000000000000000

Notes:
- We use ADV-only provisioning (PB-ADV). No GATT, no proxy.
- If you previously created a node with other tools, do NOT "create" again;
  just 'Attach' (GUI) or run logger without --create.
- Your logs live at: ~/.config/vesp/logs/
TXT

