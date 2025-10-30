#!/usr/bin/env bash
set -Eeuo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[uninstall] This removes the local Python venv only."
read -r -p "Remove ${REPO_ROOT}/.venv ? [y/N] " ans
if [[ "${ans:-N}" =~ ^[Yy]$ ]]; then
  rm -rf "${REPO_ROOT}/.venv"
  echo "[uninstall] .venv removed."
else
  echo "[uninstall] Skipped .venv removal."
fi

echo "[uninstall] Note: system packages (bluez, python3-gi, etc.) were not removed."

