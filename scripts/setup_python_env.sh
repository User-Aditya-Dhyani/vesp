#!/usr/bin/env bash
set -Eeuo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${REPO_ROOT}/.venv"

have_gi_in_venv() {
  if [[ -d "$VENV_DIR" ]]; then
    source "$VENV_DIR/bin/activate"
    python - <<'PY' >/dev/null 2>&1 || return 1
import sys
try:
  import gi
  sys.exit(0)
except Exception:
  sys.exit(1)
PY
    deactivate >/dev/null 2>&1 || true
    return 0
  fi
  return 1
}

echo "[pyenv] Ensuring system packages for GI are present…"
sudo apt-get install -y python3-gi python3-gi-cairo libgirepository1.0-dev python3-dbus python3-venv >/dev/null 2>&1 || true

if have_gi_in_venv; then
  echo "[pyenv] Existing venv already exposes 'gi' — keeping it."
else
  if [[ -d "$VENV_DIR" ]]; then
    ts=$(date +%Y%m%d_%H%M%S)
    echo "[pyenv][WARN] Existing venv lacks 'gi'. Backing up to .venv.bak.${ts}"
    mv "$VENV_DIR" "${VENV_DIR}.bak.${ts}"
  fi
  echo "[pyenv] Creating new venv with --system-site-packages…"
  python3 -m venv "$VENV_DIR" --system-site-packages
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel setuptools >/dev/null
pip install pydbus >/dev/null

# Smoke test
python - <<'PY'
import gi, pydbus
print("[pyenv] GI and pydbus import OK")
PY

echo "[pyenv] Done."

