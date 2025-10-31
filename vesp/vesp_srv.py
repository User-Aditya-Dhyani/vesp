#!/usr/bin/env python3
"""
JSON-RPC-ish stdio bridge for Tauri.

Usage:
  source .venv/bin/activate
  python -m vesp.vesp_srv
"""
from __future__ import annotations
import sys, json, traceback
from collections import deque
from time import time

from vesp.controller import Controller
from vesp.util import load_token

# --- state ---
LOGQ = deque(maxlen=2000)
_SEEN = {}  # uuid_hex -> {"uuid_hex":..., "rssi": int, "last_seen": float}

# --- controller & glib ---
ctrl = Controller()
def _bridge_log(s: str):
    try:
        LOGQ.append(str(s))
    except Exception:
        pass

def _bridge_scan(uuid_hex: str, rssi: int):
    """Controller.on_scan_result() calls scan_cb with (uuid_hex, rssi) when parse_unprov_uuid succeeds."""
    now = time()
    prev = _SEEN.get(uuid_hex)
    if (not prev) or (int(rssi) > prev["rssi"]):
        _SEEN[uuid_hex] = {"uuid_hex": uuid_hex, "rssi": int(rssi), "last_seen": now}
    LOGQ.append(f"[ScanUUID] uuid={uuid_hex} rssi={rssi}")

ctrl.set_gui_callbacks(log_cb=_bridge_log, scan_cb=_bridge_scan)
ctrl.export()
ctrl.start_glib_thread()

# --- helpers ---
def ok(data=None): return {"ok": True, "data": data}
def err(msg): return {"ok": False, "error": msg}

# --- request handler ---
def handle(req):
    m = req.get("method")
    p = req.get("params") or {}

    try:
        if m == "create_network":
            return ok(ctrl.create_network())

        if m == "attach":
            # If the UI sent a token, use it; otherwise let Controller.attach() load from disk.
            tok = p.get("token", None)
            return ok(ctrl.attach(tok))

        if m == "scan_start":
            secs = p.get("seconds")
            return ok(ctrl.scan_start(secs))

        if m == "scan_stop":
            return ok(ctrl.scan_stop())

        if m == "scan_seen":
            # Return most-recent-first list of seen unprovisioned UUIDs
            rows = sorted(_SEEN.values(), key=lambda x: x["last_seen"], reverse=True)
            k = int(p.get("limit", 100))
            return ok(rows[:k])

        if m == "provision_uuid":
            return ok(ctrl.provision_uuid(p["uuid_hex"]))

        if m == "reset_node":
            return ok(ctrl.reset_remote_node(p["unicast"]))

        if m == "forget_node_uuid":
            # actively remove a remote node from daemon’s DB (best-effort; requires cfgclient or D-Bus support)
            return ok(ctrl.forget_node_uuid(p["uuid_hex"]))

        if m == "leave":
            return ok(ctrl.leave_network(bool(p.get("deep", False))))

        if m == "purge":
            return ok(ctrl.purge_local_node())

        if m == "poll_logs":
            out = []
            while LOGQ:
                out.append(LOGQ.popleft())
            return ok(out)

        return err(f"unknown method: {m}")

    except Exception as e:
        traceback.print_exc()
        return err(str(e))

# --- main loop: line-delimited JSON ---
def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            sys.stdout.write(json.dumps(err("bad json")) + "\n"); sys.stdout.flush(); continue
        resp = handle(req)
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()

