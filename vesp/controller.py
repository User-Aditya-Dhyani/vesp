# vesp/controller.py
from __future__ import annotations
from typing import Callable, Optional, Any, Dict
from pydbus import SystemBus
from gi.repository import GLib

from .dbus_mesh import (
    APP_ROOT, AGENT_PATH, ELEM0_PATH,
    AppRoot, ProvisionAgent, Element0,
    build_object_manager_map,
)
from .util import (
    save_token, load_token, clear_token,
    default_node_uuid_bytes, parse_unprov_uuid, LOG_DIR,
    persist_node_uuid,
)

MESH_BUS = "org.bluez.mesh"
MESH_PATH = "/org/bluez/mesh"


class Controller:
    """
    ADV-only Bluetooth Mesh controller:
      - Exports Application1, ProvisionAgent1, Provisioner1, Element1
      - CreateNetwork/Attach (laptop becomes a node)
      - UnprovisionedScan, AddNode by UUID (PB-ADV)
      - DevKey/AppKey helpers (Config Client-style ops)
    """

    def __init__(self):
        # Remember the UUID we attempted to join with (persist only on success)
        self._pending_uuid: bytes | None = None

        # D-Bus connection + root "Network1" object
        self.bus = SystemBus()
        self.mesh = self.bus.get(MESH_BUS, MESH_PATH)

        # Exported objects
        self.app = AppRoot()
        self.agent = ProvisionAgent()
        self.elem0 = Element0()
        for obj in (self.app, self.agent, self.elem0):
            obj.controller = self


        self.node_path: Optional[str] = None  # Path returned by Attach()
        self.mgmt = None                      # Proxy bound to self.node_path

        # GUI callbacks
        self._log_cb: Callable[[str], None] = lambda s: print(s)
        self._scan_cb: Callable[[str, int], None] = lambda uuid_hex, rssi: None

        # Simple address allocator used by Provisioner.RequestProvData
        self._next_unicast = 0x0005

        # GLib main loop (for D-Bus callbacks)
        self._glib_loop: Optional[GLib.MainLoop] = None

    # ---------------- GUI hooks ----------------
    def set_gui_callbacks(self,
                          log_cb: Optional[Callable[[str], None]] = None,
                          scan_cb: Optional[Callable[[str, int], None]] = None):
        if log_cb:
            self._log_cb = log_cb
        if scan_cb:
            self._scan_cb = scan_cb

    def log(self, msg: str):
        try:
            self._log_cb(msg)
        finally:
            pass

    # ---------------- Export objects ----------------
    def export(self):
        # Register objects using explicit introspection XML
        self.bus.register_object(APP_ROOT,   self.app,   type(self.app).__dbus_xml__)
        self.bus.register_object(AGENT_PATH, self.agent, type(self.agent).__dbus_xml__)
        self.bus.register_object(ELEM0_PATH, self.elem0, type(self.elem0).__dbus_xml__)

        self.app._children = build_object_manager_map(self.app, self.agent, self.elem0)
        self.log(f"Exported objects under {APP_ROOT}")


    # ---------------- GLib loop ----------------
    def start_glib_thread(self):
        if self._glib_loop:
            return
        self._glib_loop = GLib.MainLoop()
        import threading
        threading.Thread(target=self._glib_loop.run, daemon=True).start()
        self.log("GLib main loop started (background thread)")

    # ---------------- Token + Join/Attach ----------------
    def create_network(self):
        """
        Create our local node in the daemon DB (ADV bearer, No-OOB).
        Fast path: CreateNetwork(app_root, uuid)
        Fallback:  Import(app_root, uuid, dev_key, net_key, 0, flags, 0, 0x0001)
        """
        from gi.repository import GLib
        from .util import default_node_uuid_bytes
        import os

        dev_uuid = default_node_uuid_bytes()
        self._pending_uuid = dev_uuid  # remember until JoinComplete
        self.log(f"CreateNetwork UUID={dev_uuid.hex()} (len={len(dev_uuid)})")
        if len(dev_uuid) != 16:
            return False, "CreateNetwork: bad UUID length"

        # ---------- fast path (CreateNetwork) ----------
        def do_create():
            # Prefer explicit DBus type 'ay'
            try:
                self.mesh.CreateNetwork(APP_ROOT, GLib.Variant('ay', dev_uuid))
                return
            except Exception as e1:
                # Fallback: some bindings accept list[int] for 'ay'
                try:
                    self.mesh.CreateNetwork(APP_ROOT, list(dev_uuid))
                    return
                except Exception as e2:
                    raise RuntimeError(
                        f"CreateNetwork fast path failed: ay='{e1}', list[int]='{e2}'"
                    )

        ok, msg = self._safe_call(do_create, "CreateNetwork")
        if ok:
            return ok, msg

        # ---------- fallback (Import with seeded keys) ----------
        dev_key = os.urandom(16)
        net_key = os.urandom(16)
        flags = {
            "IvUpdate":   GLib.Variant('b', False),
            "KeyRefresh": GLib.Variant('b', False),
        }

        def do_import():
            self.mesh.Import(
                APP_ROOT,
                bytes(dev_uuid),   # uuid (ay)
                bytes(dev_key),    # dev_key (ay)
                bytes(net_key),    # net_key (ay)
                0,                 # net_index (uint16)
                flags,             # dict{sv} with plain bools
                0,                 # iv_index (uint32)
                0x0001,            # unicast (uint16)
            )

        return self._safe_call(do_import, "Import")

    def attach(self, token: Optional[int] = None):
        """
        Attach to our node (gets node object path + config). If token not passed,
        it is loaded from ~/.config/vesp/token.json.
        """
        tok = token if token is not None else load_token()
        if tok is None:
            raise RuntimeError("No token found. Run create_network() first.")

        self.log(f"Attach(APP_ROOT, token={tok})")

        def do_attach():
            try:
                node, _cfg = self.mesh.Attach(APP_ROOT, int(tok))
                self.node_path = str(node)
                self.mgmt = self.bus.get(MESH_BUS, self.node_path)
                self.log(f"Attached. Node path: {self.node_path}")
            except Exception as e:
                emsg = e.args[0] if e.args else str(e)
                if ("org.bluez.mesh.Error.AlreadyExists" in emsg or
                    "org.bluez.mesh.Error.Busy" in emsg):
                    if self.node_path:
                        self.mgmt = self.bus.get(MESH_BUS, self.node_path)
                        self.log("Attach: daemon reports already attached; rebound mgmt proxy.")
                    else:
                        raise
                else:
                    raise

        return self._safe_call(do_attach, "Attach")

    def rebind_local(self):
        """Recreate the Management1 proxy using cached node_path (when daemon says AlreadyExists)."""
        if self.mgmt:
            return True, "Rebind: already bound"
        if not self.node_path:
            return False, "Rebind failed: no cached node_path"

        def do_rebind():
            self.mgmt = self.bus.get(MESH_BUS, self.node_path)
            self.log(f"Rebound to existing node at {self.node_path}")
        return self._safe_call(do_rebind, "Rebind")

    # ---------------- Provisioner flow (ADV-only) ----------------
    def scan_start(self, seconds: Optional[int] = None):
        """Start UnprovisionedScan (PB-ADV). Optional 'seconds' stops automatically."""
        if not self.mgmt:
            raise RuntimeError("Not attached yet")
        opts: Dict[str, Any] = {}
        if seconds is not None:
            s = max(1, min(int(seconds), 600))  # 1..600 clamp
            opts["Seconds"] = GLib.Variant('q', s)  # uint16
            self.log(f"UnprovisionedScan({s}s)")
        else:
            self.log("UnprovisionedScan({})  # until cancel")
        return self._safe_call(lambda: self.mgmt.UnprovisionedScan(opts), "UnprovisionedScan")

    def scan_stop(self):
        if self.mgmt:
            self.log("UnprovisionedScanCancel()")
            return self._safe_call(lambda: self.mgmt.UnprovisionedScanCancel(), "UnprovisionedScanCancel")

    def provision_uuid(self, uuid_hex: str):
        """Provision a specific device UUID (32 hex chars, no dashes) over ADV bearer."""
        if not self.mgmt:
            raise RuntimeError("Not attached yet")
        uh = uuid_hex.replace("-", "").strip().lower()
        if len(uh) != 32:
            raise ValueError("UUID must be 16 bytes (32 hex chars)")
        self.log(f"AddNode({uuid_hex})")
        return self._safe_call(lambda: self.mgmt.AddNode(bytes.fromhex(uh), {}), "AddNode")

    # ---------------- Config Client helpers ----------------
    def reset_remote_node(self, unicast_str: str):
        """
        Send Configuration 'Node Reset' (0x8049) to a remote node's primary unicast.
        Makes the device erase its provisioning data and start advertising again.
        """
        if not self.mgmt:
            raise RuntimeError("Not attached yet")

        s = unicast_str.strip().lower()
        try:
            if s.startswith("0x"):
                dest = int(s, 16)
            elif all(c in "0123456789abcdef" for c in s) and len(s) <= 4:
                dest = int(s, 16)   # hex without 0x
            else:
                dest = int(s, 10)   # decimal
        except ValueError:
            raise ValueError("Unicast address must be hex (e.g. 0x1201 or 1201) or decimal.")

        if not (0x0001 <= dest <= 0x7FFF):
            raise ValueError("Unicast address out of range (0x0001..0x7FFF).")

        opcode = bytes([0x80, 0x49])  # Config Node Reset
        return self._safe_call(
            lambda: self.mgmt.DevKeySend(ELEM0_PATH, dest, True, 0x000, {}, opcode),
            "ConfigNodeReset"
        )

    def _ensure_appkey(self, app_index: int = 0, net_index: int = 0):
        """Create AppKey in local key DB if missing (idempotent)."""
        def do():
            try:
                self.mgmt.CreateAppKey(int(net_index), int(app_index))
                self.log(f"CreateAppKey: net={net_index}, app={app_index}")
            except Exception as e:
                emsg = e.args[0] if e.args else str(e)
                if "AlreadyExists" in emsg:
                    self.log(f"CreateAppKey: app {app_index} already exists (local)")
                else:
                    raise
        return self._safe_call(do, "CreateAppKey")

    def add_appkey_to_node(self, unicast: int, app_index: int = 0, net_index: int = 0, update: bool = False):
        """Send Config AppKey Add/Update to the remote node using our Element0."""
        def do():
            self.mgmt.AddAppKey(ELEM0_PATH, int(unicast), int(app_index), int(net_index), bool(update))
            self.log(f"AddAppKey -> node 0x{unicast:04x} (app={app_index}, net={net_index}, update={update})")
        return self._safe_call(do, f"AddAppKey(0x{unicast:04x})")

    # ---------------- App/node lifecycle ----------------
    @property
    def is_attached(self) -> bool:
        return self.node_path is not None and self.mgmt is not None

    def detach_local(self):
        """Drop local proxies only (daemon stays attached)."""
        if not self.is_attached:
            return False, "Detach skipped: not attached."
        def do_detach():
            self.log("Detaching locally (closing mgmt proxy; keeping node_path)")
            self.mgmt = None
        return self._safe_call(do_detach, "Detach(local)")

    def leave_network(self):
        """
        Ask bluetooth-meshd to forget/delete our node (by token),
        then clear local token and proxies.
        """
        tok = load_token()
        if tok is None:
            return False, "Leave failed: no token found (nothing to forget)"

        def do_leave():
            self.log(f"Leave({tok})")
            self.mesh.Leave(int(tok))  # Network1.Leave(uint64 token)
            clear_token()
            self.mgmt = None
            self.node_path = None
            self.log("Leave: OK (daemon node removed; local token cleared)")
        return self._safe_call(do_leave, "Leave")

    # ---------------- Callbacks from our exported objects ----------------
    def on_join_complete(self, token: int):
        self.log(f"JoinComplete token=0x{token:016x}")
        save_token(token)

        # Persist the UUID only now (first successful join)
        if self._pending_uuid is not None:
            try:
                persist_node_uuid(self._pending_uuid)
                self.log(f"Persisted node UUID: {self._pending_uuid.hex()}")
            except Exception as e:
                self.log(f"Persist UUID failed: {e}")
            finally:
                self._pending_uuid = None

        # Auto-attach for convenience
        try:
            self.attach(token)
        except Exception as e:
            self.log(f"Auto-attach failed: {e}")

    def on_join_failed(self, reason: str):
        self.log(f"JoinFailed: {reason}")

    def on_scan_result(self, rssi: int, adv: bytes, options: Optional[Dict[str, Any]]):
        # Try to parse UUID directly from ADV (PB-ADV/Mesh Beacon/Service Data).
        self.log(f"[Scan] rssi={rssi} len={len(adv)} adv={adv.hex()[:64]}...")
        uuid_hex = parse_unprov_uuid(adv)
        if uuid_hex:
            self.log(f"[Scan] unprov UUID={uuid_hex}")
            self._scan_cb(uuid_hex, rssi)
        else:
            self.log(f"[Scan] no UUID parsed (rssi={rssi}) adv={adv.hex()}")

    def alloc_unicast(self, count: int) -> int:
        start = self._next_unicast
        self._next_unicast += int(count)
        self.log(f"Alloc unicast: 0x{start:04x}..+{count-1}")
        return start

    def on_add_node_complete(self, uuid_bytes: bytes, unicast: int, count: int):
        self.log(f"AddNodeComplete: uuid={uuid_bytes.hex()} unicast=0x{unicast:04x} elements={count}")
        # Ensure AppKey(0) exists locally and push it to the new node's primary address.
        self._ensure_appkey(app_index=0, net_index=0)
        ok, msg = self.add_appkey_to_node(unicast, app_index=0, net_index=0, update=False)
        if not ok:
            self.log(msg)
        else:
            self.log("AppKey(0) added to remote node (bind model as needed later).")

    def on_add_node_failed(self, uuid_bytes: bytes, reason: str):
        self.log(f"AddNodeFailed: uuid={uuid_bytes.hex()} reason={reason}")

    # Incoming access/DevKey messages to our Element0
    def on_element_message(self, source: int, key_index: int, destination, data: bytes):
        try:
            # Basic on/off status peek (0x82 0x04)
            info = "unknown"
            if len(data) >= 3 and data[0] == 0x82 and data[1] == 0x04:
                info = f"GenericOnOffStatus(on={data[2]})"
            line = (
                f"APPMSG src=0x{source:04x} app_idx={key_index} "
                f"len={len(data)} data={data.hex()} dec={info}"
            )
            self.log(line)
            # Append to log file
            (LOG_DIR / "mesh_app.log").open("a", encoding="utf-8").write(line + "\n")
        except Exception as e:
            self.log(f"[Element0] MessageReceived error: {e}")

    def on_element_devkey_message(self, source: int, remote: bool, net_index: int, data: bytes):
        try:
            line = (
                f"DEVKEY src=0x{source:04x} remote={remote} "
                f"net_idx=0x{net_index:03x} len={len(data)} data={data.hex()}"
            )
            self.log(line)
            (LOG_DIR / "mesh_devkey.log").open("a", encoding="utf-8").write(line + "\n")
        except Exception as e:
            self.log(f"[Element0] DevKeyMessageReceived error: {e}")

    # ---------------- Utilities ----------------
    def _safe_call(self, fn, label: str):
        try:
            fn()
            return True, f"{label}: OK"
        except Exception as e:
            emsg = e.args[0] if e.args else str(e)
            self.log(f"{label} failed: {emsg}")
            return False, f"{label} failed: {emsg}"

