# vesp/util.py
from __future__ import annotations
from pathlib import Path
from typing import Optional
import json
import re
import uuid

# ---------- app dirs / files ----------
APP_NAME = "vesp"
STATE_DIR = Path.home() / ".config" / APP_NAME
STATE_DIR.mkdir(parents=True, exist_ok=True)

TOKEN_FILE = STATE_DIR / "token.json"
LOG_DIR = STATE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

NODE_UUID_FILE = STATE_DIR / "node_uuid.json"


# ---------- token helpers ----------
def save_token(token: int) -> None:
    TOKEN_FILE.write_text(json.dumps({"token": int(token)}))


def load_token() -> Optional[int]:
    try:
        data = json.loads(TOKEN_FILE.read_text())
        t = int(data.get("token"))
        if t < 0:
            return None
        return t
    except Exception:
        return None


def clear_token() -> None:
    try:
        TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass


# ---------- UUID helpers ----------
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def default_node_uuid_bytes() -> bytes:
    """
    Return a persistent 16B UUID for this app:
      - If ~/.config/vesp/node_uuid.json exists, return it.
      - Else return a fresh RFC-4122 v4 UUID (do NOT persist yet).
        Controller will persist it on JoinComplete.
    Set VESP_FORCE_NEW_UUID=1 to ignore any persisted UUID for this run.
    """
    import os, json
    if os.environ.get("VESP_FORCE_NEW_UUID") == "1":
        return uuid.uuid4().bytes  # RFC-4122 v4

    try:
        if NODE_UUID_FILE.exists():
            obj = json.loads(NODE_UUID_FILE.read_text())
            hx = (obj.get("uuid_hex","") or "").lower()
            if len(hx) == 32:
                return bytes.fromhex(hx)
    except Exception:
        pass
    return uuid.uuid4().bytes  # RFC-4122 v4

def persist_node_uuid(u: bytes) -> None:
    try:
        NODE_UUID_FILE.write_text(json.dumps({"uuid_hex": u.hex()}))
    except Exception:
        pass

def normalize_uuid_hex(s: str) -> str:
    """
    Accepts: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' or 'aabb...'(32 hex)
    Returns lowercase 32 hex chars, raises ValueError if not 16 bytes.
    """
    x = s.strip().lower().replace("-", "")
    if not _HEX32.match(x):
        raise ValueError("UUID must be exactly 16 bytes (32 hex characters).")
    return x


# ---------- Mesh address parsing ----------
def parse_unicast_addr(s: str) -> int:
    """
    Accept '0x1201', '1201' (hex without 0x), or decimal '4609'.
    Valid unicast range: 0x0001..0x7FFF.
    """
    ss = s.strip().lower()
    try:
        if ss.startswith("0x"):
            val = int(ss, 16)
        elif all(c in "0123456789abcdef" for c in ss) and len(ss) <= 4:
            val = int(ss, 16)  # hex without 0x
        else:
            val = int(ss, 10)  # decimal
    except ValueError:
        raise ValueError("Unicast address must be hex (e.g. 0x1201 or 1201) or decimal.")
    if not (0x0001 <= val <= 0x7FFF):
        raise ValueError("Unicast address out of range (0x0001..0x7FFF).")
    return val


# ---------- ADV parsing (PB-ADV only; no GATT) ----------
def parse_unprov_uuid(adv: bytes) -> Optional[str]:
    """
    Extract the 16-byte Device UUID of an unprovisioned mesh node from ADV:
      * AD type 0x2B (Mesh Beacon):
          [len][0x2B][beacon_type=0x00][16B UUID]...
      * AD type 0x29 (Mesh Provisioning PDU over ADV bearer):
          [len][0x29][pdu_type][16B UUID]...
      * AD type 0x16 (Service Data) for 0x1827 (Mesh Provisioning Service):
          [len][0x16][0x27,0x18][pdu_type][16B UUID]...
    Returns lowercase 32-hex UUID string, or None if not found.
    """
    i, n = 0, len(adv)
    while i < n:
        if i + 1 > n:
            break
        length = adv[i]
        i += 1
        if length == 0 or i + length > n:
            break
        ad_type = adv[i]
        ad_data = adv[i + 1 : i + length]
        i += length

        # 0x2B: Mesh Beacon (Unprovisioned Device)
        if ad_type == 0x2B and len(ad_data) >= 1 + 16:
            if ad_data[0] == 0x00:
                return ad_data[1:17].hex()

        # 0x29: Mesh Provisioning PDU over ADV bearer
        if ad_type == 0x29 and len(ad_data) >= 1 + 16:
            return ad_data[1:17].hex()

        # 0x16: Service Data (16-bit UUID) – expect 0x1827 little-endian
        if ad_type == 0x16 and len(ad_data) >= 2:
            if ad_data[0] == 0x27 and ad_data[1] == 0x18:
                if len(ad_data) >= 2 + 1 + 16:
                    return ad_data[3 : 3 + 16].hex()
    return None

