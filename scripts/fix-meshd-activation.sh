#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

echo "[VESP] Fixing bluetooth-meshd DBus activation..."

# Find the daemon binary
BIN=""
for p in /usr/libexec/bluetooth/bluetooth-meshd /usr/lib/bluetooth/bluetooth-meshd /usr/sbin/bluetooth-meshd; do
  [[ -x "$p" ]] && BIN="$p" && break
done
if [[ -z "$BIN" ]]; then
  echo "[VESP] ERROR: bluetooth-meshd binary not found. Install/repair BlueZ first."
  exit 1
fi
echo "[VESP] Using daemon: $BIN"

# Create a proper systemd unit with the DBus alias expected by org.bluez.mesh
UNIT=/etc/systemd/system/bluetooth-meshd.service
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Bluetooth Mesh daemon
Documentation=man:bluetooth-meshd(8)
Requires=bluetooth.service
After=bluetooth.service

[Service]
Type=dbus
BusName=org.bluez.mesh
ExecStart=$BIN
User=root
Restart=on-failure
# hardening (optional)
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
Alias=dbus-org.bluez.mesh.service
EOF

echo "[VESP] Reloading systemd units..."
sudo systemctl daemon-reload

echo "[VESP] Enabling & starting bluetooth-meshd..."
sudo systemctl enable --now bluetooth-meshd

echo "[VESP] Status:"
systemctl --no-pager --full status bluetooth-meshd || true

