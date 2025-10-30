#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

RED=$(tput setaf 1 || true); GREEN=$(tput setaf 2 || true); YELLOW=$(tput setaf 3 || true); NC=$(tput sgr0 || true)
ok(){ echo "${GREEN}[OK]${NC} $*"; }
warn(){ echo "${YELLOW}[WARN]${NC} $*"; }
fail(){ echo "${RED}[FAIL]${NC} $*"; }

echo "=== VESP Doctor (Ubuntu 24.04) ==="

# 1) Services
systemctl is-active --quiet bluetooth && ok "bluetooth active" || fail "bluetooth not active"
systemctl is-active --quiet bluetooth-meshd && ok "bluetooth-meshd active" || fail "bluetooth-meshd not active"

# 2) Adapter
if btmgmt info >/dev/null 2>&1; then ok "btmgmt reachable"; else fail "btmgmt not reachable"; fi

# 3) Mesh D-Bus
if busctl --system list | grep -q org.bluez.mesh; then ok "org.bluez.mesh on DBus"; else fail "org.bluez.mesh missing on DBus"; fi

# 4) Python env & imports
if [[ -d .venv ]]; then source .venv/bin/activate; else warn "No .venv found; running setup_python_env.sh…"; bash ./scripts/setup_python_env.sh; source .venv/bin/activate; fi

python - <<'PY' || { fail "Python deps (gi/pydbus) missing"; exit 2; }
import sys
try:
  import gi, pydbus
  print("pydbus / GI present")
except Exception as e:
  print(e); sys.exit(2)
PY
ok "Python deps OK"

# 5) Controller smoke (no attach to keep it safe)
python - <<'PY' || { fail "Controller import/export failed"; exit 3; }
from vesp.controller import Controller
c = Controller()
c.export()
c.start_glib_thread()
print("Controller constructed, exported, glib running")
PY
ok "Controller smoke OK"

echo "=== Doctor complete ==="

