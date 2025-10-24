# vesp/gui.py
from __future__ import annotations
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from typing import Dict, Optional

from .controller import Controller
from .util import LOG_DIR

class VespGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("VESP Mesh (ADV-only)")

        # Controller
        self.ctrl = Controller()
        self.ctrl.set_gui_callbacks(log_cb=self._post_log, scan_cb=self._post_scan)
        self.ctrl.export()
        self.ctrl.start_glib_thread()

        # UI State
        self.scan_items: Dict[str, int] = {}  # uuid_hex -> best RSSI

        # Layout
        self._build_ui()

        self._log(f"Logs directory: {LOG_DIR}")
        self._log("Ready. If this is your first time, click 'Create Network' to make your local node.")

    # ---------- UI construction ----------
    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        # Row 0: Control buttons
        row0 = ttk.Frame(outer)
        row0.pack(fill="x", pady=(0, 8))

        self.btn_create = ttk.Button(row0, text="Create Network", command=self._do_create)
        self.btn_attach = ttk.Button(row0, text="Attach", command=self._do_attach)
        self.btn_detach = ttk.Button(row0, text="Detach (local)", command=self._do_detach)
        self.btn_leave  = ttk.Button(row0, text="Leave (forget node)", command=self._do_leave)

        for w in (self.btn_create, self.btn_attach, self.btn_detach, self.btn_leave):
            w.pack(side="left", padx=(0, 6))

        # Row 1: Scan controls
        row1 = ttk.Frame(outer)
        row1.pack(fill="x", pady=(0, 8))

        ttk.Label(row1, text="Scan (s):").pack(side="left")
        self.ent_secs = ttk.Entry(row1, width=6)
        self.ent_secs.insert(0, "15")
        self.ent_secs.pack(side="left", padx=(4, 8))

        self.btn_scan_start = ttk.Button(row1, text="Start Scan", command=self._do_scan_start)
        self.btn_scan_stop = ttk.Button(row1, text="Stop Scan", command=self._do_scan_stop)
        self.btn_scan_start.pack(side="left", padx=(0, 6))
        self.btn_scan_stop.pack(side="left", padx=(0, 6))

        # Row 2: Unprovisioned list + actions
        row2 = ttk.Frame(outer)
        row2.pack(fill="both", expand=True)

        left = ttk.Frame(row2)
        left.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="Unprovisioned (UUID | RSSI)").pack(anchor="w")
        self.list_scan = tk.Listbox(left, height=10, activestyle="dotbox")
        self.list_scan.pack(fill="both", expand=True, pady=(4, 8))

        actions = ttk.Frame(left)
        actions.pack(fill="x")

        self.btn_prov_sel = ttk.Button(actions, text="Provision Selected", command=self._do_provision_selected)
        self.btn_prov_sel.pack(side="left", padx=(0, 6))

        ttk.Label(actions, text="or UUID:").pack(side="left")
        self.ent_uuid = ttk.Entry(actions, width=40)
        self.ent_uuid.pack(side="left", padx=(4, 6))
        self.btn_prov_uuid = ttk.Button(actions, text="Provision UUID", command=self._do_provision_uuid)
        self.btn_prov_uuid.pack(side="left", padx=(0, 6))

        # Row 3: Config ops (Node Reset)
        row3 = ttk.Frame(outer)
        row3.pack(fill="x", pady=(8, 8))
        ttk.Label(row3, text="Node Reset unicast:").pack(side="left")
        self.ent_unicast = ttk.Entry(row3, width=10)
        self.ent_unicast.insert(0, "00aa")  # example from your transcript
        self.ent_unicast.pack(side="left", padx=(4, 6))
        ttk.Button(row3, text="Reset", command=self._do_reset).pack(side="left")

        # Row 4: Log pane
        row4 = ttk.Frame(outer)
        row4.pack(fill="both", expand=True)

        ttk.Label(row4, text="Log").pack(anchor="w")
        self.txt_log = ScrolledText(row4, height=16, wrap="none", state="disabled")
        self.txt_log.pack(fill="both", expand=True, pady=(4, 0))

        # Status bar
        self.var_status = tk.StringVar(value="Status: idle")
        bar = ttk.Label(outer, textvariable=self.var_status, anchor="w")
        bar.pack(fill="x", pady=(8, 0))

        # Quit handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- Thread-safe GUI posting ----------
    def _post_log(self, s: str):
        self.root.after(0, self._log, s)

    def _post_scan(self, uuid_hex: str, rssi: int):
        self.root.after(0, self._scan_add_or_update, uuid_hex, rssi)

    # ---------- Logging / list helpers ----------
    def _log(self, s: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", s + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _scan_add_or_update(self, uuid_hex: str, rssi: int):
        # Update best RSSI
        prev = self.scan_items.get(uuid_hex)
        if prev is None or rssi > prev:
            self.scan_items[uuid_hex] = rssi
        # Rebuild listbox display (simple)
        self.list_scan.delete(0, "end")
        # Sort by strongest first
        for u, r in sorted(self.scan_items.items(), key=lambda kv: kv[1], reverse=True):
            self.list_scan.insert("end", f"{u} | {r}")

    def _get_selected_uuid(self) -> Optional[str]:
        try:
            idx = self.list_scan.curselection()
            if not idx:
                return None
            line = self.list_scan.get(idx[0])
            return line.split("|", 1)[0].strip().lower()
        except Exception:
            return None

    # ---------- Actions (wrap controller in threads so GUI never blocks) ----------
    def _do_threaded(self, func, label: str):
        def run():
            ok, msg = False, f"{label}: (no result)"
            try:
                ok, msg = func()
            except Exception as e:
                ok, msg = False, f"{label} exception: {e}"
            self._post_log(msg)
            self.var_status.set(f"Status: {msg}")
        threading.Thread(target=run, daemon=True).start()

    def _do_create(self):
        self._do_threaded(self.ctrl.create_network, "CreateNetwork")

    def _do_attach(self):
        self._do_threaded(self.ctrl.attach, "Attach")

    def _do_detach(self):
        self._do_threaded(self.ctrl.detach_local, "Detach")

    def _do_leave(self):
        if messagebox.askyesno("Confirm Leave", "This will delete your local mesh node from the daemon.\nProceed?"):
            self._do_threaded(self.ctrl.leave_network, "Leave")

    def _do_scan_start(self):
        try:
            secs = int(self.ent_secs.get().strip())
        except Exception:
            secs = None
        # Clear current list so the user sees fresh results
        self.scan_items.clear()
        self.list_scan.delete(0, "end")
        self._do_threaded(lambda: self.ctrl.scan_start(secs), "UnprovisionedScan")

    def _do_scan_stop(self):
        self._do_threaded(self.ctrl.scan_stop, "UnprovisionedScanCancel")

    def _do_provision_selected(self):
        uuid_hex = self._get_selected_uuid()
        if not uuid_hex:
            messagebox.showwarning("Provision", "Select a device from the list first.")
            return
        self._do_threaded(lambda: self.ctrl.provision_uuid(uuid_hex), "AddNode")

    def _do_provision_uuid(self):
        uuid_hex = self.ent_uuid.get().strip().lower().replace("-", "")
        if len(uuid_hex) != 32:
            messagebox.showwarning("Provision", "UUID must be 16 bytes (32 hex chars).")
            return
        self._do_threaded(lambda: self.ctrl.provision_uuid(uuid_hex), "AddNode")

    def _do_reset(self):
        dst = self.ent_unicast.get().strip()
        if not dst:
            messagebox.showwarning("Reset", "Enter a unicast address, e.g. 00aa or 0x00aa")
            return
        self._do_threaded(lambda: self.ctrl.reset_remote_node(dst), "ConfigNodeReset")

    def _on_close(self):
        # Just exit; controller threads are daemonic.
        self.root.destroy()


def main():
    root = tk.Tk()
    # Use a modern ttk theme when available
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    app = VespGUI(root)
    root.minsize(820, 620)
    root.mainloop()


if __name__ == "__main__":
    main()

