"""Private buyer state. Runtime contexts and untrusted request state never belong here."""
from __future__ import annotations

import json
import os
import sqlite3
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

DEFAULT_STATE_DIR = Path(__file__).resolve().parents[1] / ".state"
DEFAULT_DB_PATH = DEFAULT_STATE_DIR / "state.sqlite3"
LEGACY_DB_PATH = Path(__file__).resolve().parents[1] / ".state.sqlite3"
_CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
_GOAL_KEYS = {"id", "buyer_id", "type", "items", "cap", "deadline", "state", "reserved_amount",
              "po_number", "created_at", "notes", "parent_goal_id", "parent_part"}
_TRANSACTION_KEYS = {"deal_id", "buyer_id", "goal_id", "need_id", "bid_id", "phase", "deal", "order",
                     "advocate_card", "mandate", "voice_approval", "allowance_authorization",
                     "settlement", "settlement_result", "payment_ref", "mode", "market_mandate"}
_PHASES = {"pending_approval", "paused", "approved", "denied", "expired", "submitted", "uncertain",
           "settled", "refused", "failed"}
_FORBIDDEN_KEYS = {"context", "owner_context", "runtime_context", "code", "approval_code", "passcode",
                   "one_time_code", "otp", "credential", "credentials", "password", "secret", "api_key",
                   "private_key", "access_token", "auth_token", "transcript", "call_transcript",
                   "approval_session", "cartesia_client", "authorization_header"}


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _json_safe(value: Any, path: str = "state") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _json_safe(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} has a non-string key")
            normalized = key.lower().replace("-", "_")
            approved_voice_timestamp = path.endswith(".voice_approval") and normalized in {
                "code_issued_at", "code_expires_at"
            }
            approved_voice_hash = path.endswith(".voice_approval") and normalized == "code_hash"
            if (normalized in _FORBIDDEN_KEYS or "context" in normalized or "credential" in normalized
                    or "password" in normalized or "secret" in normalized or "api_key" in normalized
                    or "private_key" in normalized or "transcript" in normalized
                    or ("code" in normalized and not approved_voice_hash and not approved_voice_timestamp)):
                raise ValueError(f"{path} contains a private runtime or credential field")
            _json_safe(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} is not JSON-safe")


def _dump(value: dict) -> str:
    _json_safe(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as e:
        raise ValueError("state is not JSON-safe") from e


def _load(text: str) -> dict:
    def invalid_constant(value):
        raise ValueError(f"invalid JSON constant {value}")

    value = json.loads(text, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("stored state is not an object")
    _json_safe(value)
    return value


def _validate(contract: str, value: dict) -> None:
    schema = json.loads((_CONTRACTS / f"{contract}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value)


def _validate_owned(buyer_id: str, part: dict) -> str:
    _json_safe(part)
    if set(part) - {"id", "buyer_id", "sku_spec", "item_name", "condition", "acquired_on", "source", "attrs", "notes"}:
        raise ValueError("owned part contains an unsupported field")
    _validate("OwnedPart", part)
    if part["buyer_id"] != buyer_id:
        raise ValueError("owned part belongs to a different buyer")
    kind = part["sku_spec"].split()
    if not kind:
        raise ValueError("owned part sku_spec is empty")
    return kind[0]


def _validate_goal(goal: dict) -> tuple[str, str]:
    _json_safe(goal)
    if set(goal) - _GOAL_KEYS:
        raise ValueError("goal contains an unsupported field")
    _validate("Goal", goal)
    if bool(goal.get("parent_goal_id")) != bool(goal.get("parent_part")):
        raise ValueError("parent_goal_id and parent_part must be provided together")
    return _nonempty(goal["id"], "goal id"), _nonempty(goal["buyer_id"], "goal buyer_id")


def _validate_transaction(transaction: dict) -> tuple[str, str, str]:
    _json_safe(transaction)
    if set(transaction) - _TRANSACTION_KEYS:
        raise ValueError("transaction contains an unsupported field")
    deal_id = _nonempty(transaction.get("deal_id"), "deal_id")
    buyer_id = _nonempty(transaction.get("buyer_id"), "buyer_id")
    goal_id = _nonempty(transaction.get("goal_id"), "goal_id")
    need_id = _nonempty(transaction.get("need_id"), "need_id")
    bid_id = _nonempty(transaction.get("bid_id"), "bid_id")
    if transaction.get("phase") not in _PHASES:
        raise ValueError("transaction phase is invalid")
    mandate = transaction.get("mandate")
    if not isinstance(mandate, dict):
        raise ValueError("transaction mandate is required")
    _validate("Mandate", mandate)
    if mandate["deal_id"] != deal_id or mandate["buyer_id"] != buyer_id or mandate["goal_id"] != goal_id:
        raise ValueError("transaction and mandate IDs do not match")
    market = transaction.get("market_mandate")
    if market is not None:  # a chat purchase's second mandate: the one the market holds (owner_approval.py)
        if not isinstance(market, dict):
            raise ValueError("market_mandate must be an object")
        _validate("Mandate", market)
        if market["buyer_id"] != buyer_id or market["goal_id"] != goal_id:
            raise ValueError("market mandate does not match the transaction")
    deal = transaction.get("deal")
    if not isinstance(deal, dict):
        raise ValueError("transaction deal is required")
    for field, expected in (("id", deal_id), ("goal_id", goal_id), ("need_id", need_id), ("bid_id", bid_id)):
        if deal.get(field) != expected:
            raise ValueError(f"transaction deal {field} does not match")
    order = transaction.get("order")
    if order is not None:
        if not isinstance(order, dict):
            raise ValueError("transaction order must be an object or null")
        _validate("Order", order)
        if order["need_id"] != need_id or order["bid_id"] != bid_id:
            raise ValueError("transaction order does not match its need and bid")
    card = transaction.get("advocate_card")
    if not isinstance(card, dict):
        raise ValueError("a stored AdvocateCard is required for the transaction")
    _validate("AdvocateCard", card)
    if card["bid_id"] != bid_id:
        raise ValueError("AdvocateCard must be bound to the transaction bid")
    if card["need_id"] != need_id:
        raise ValueError("AdvocateCard is for a different need")
    approval = transaction.get("voice_approval")
    if approval is not None:
        if not isinstance(approval, dict):
            raise ValueError("voice_approval must be an object")
        _validate("VoiceApproval", approval)
        if approval["mandate_id"] != mandate["id"] or approval["mandate_hash"] != mandate["hash"]:
            raise ValueError("VoiceApproval does not match the mandate")
    return deal_id, buyer_id, goal_id


def _begin(db: sqlite3.Connection) -> None:
    db.execute("BEGIN IMMEDIATE")


def _create_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS owned_parts (
            buyer_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (buyer_id, kind)
        );
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            buyer_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            deal_id TEXT PRIMARY KEY,
            buyer_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS handled_goals (
            goal_id TEXT PRIMARY KEY,
            buyer_id TEXT NOT NULL,
            handled_at TEXT NOT NULL
        );
    """)


def _restrict_windows_acl(path: Path, *, directory: bool = False) -> None:
    """Restrict this state file to the current Windows user before opening it."""
    identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True,
                              text=True, check=True, timeout=5).stdout.strip()
    # whoami returns a CSV row: DOMAIN\\user,"S-1-...". Only the SID is used.
    import csv
    rows = list(csv.reader(identity.splitlines()))
    sid = rows[0][-1] if rows and rows[0] else ""
    if not sid.startswith("S-1-"):
        raise OSError("could not identify current Windows user for private state ACL")
    # Replace the DACL in one SetFileSecurity call. In particular, do not use
    # icacls /reset: on an existing database that briefly copies the parent's
    # potentially broad inherited ACL onto private budgets and approvals.
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                        ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    set_file_security = advapi32.SetFileSecurityW
    set_file_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    set_file_security.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    inherit_flags = "OICI" if directory else ""
    if not convert(f"D:P(A;{inherit_flags};FA;;;{sid})", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        dacl_and_protect = 0x00000004 | 0x80000000
        if not set_file_security(str(path), dacl_and_protect, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        local_free(descriptor)


def open_state(path: str | Path | None = None) -> sqlite3.Connection:
    """Open safe state without recovery; use this connection on its creating thread only.

    Callers doing blocking work in a worker thread must pass immutable snapshots and
    persist results back on the event-loop thread. The database must live in a
    dedicated `.state` directory; this directory is made private before SQLite
    creates the database or its journal/WAL sidecars.
    """
    uses_default = path is None or Path(path) == DEFAULT_DB_PATH
    path = Path(path or DEFAULT_DB_PATH)
    if path.parent.name != ".state":
        raise ValueError("buyer state must live in a dedicated .state directory")
    if path.parent.is_symlink():
        raise ValueError("buyer state directory must not be a symlink")
    if path.is_symlink():
        raise ValueError("buyer state file must not be a symlink")
    if uses_default and not path.exists() and LEGACY_DB_PATH.exists():
        raise ValueError(
            "legacy buyer state exists at agents/.state.sqlite3; manually migrate it into "
            "agents/.state/state.sqlite3 before startup"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    else:
        _restrict_windows_acl(path.parent, directory=True)
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.is_symlink():
            raise ValueError("buyer state sidecar must not be a symlink")
        if sidecar.exists():
            if os.name != "nt":
                os.chmod(sidecar, 0o600)
            else:
                _restrict_windows_acl(sidecar)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    if os.name != "nt":
        os.chmod(path, 0o600)
    else:
        _restrict_windows_acl(path)
    db = sqlite3.connect(path, timeout=30)
    try:
        check = db.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise ValueError("state database is corrupt")
        _create_tables(db)
        return db
    except (sqlite3.DatabaseError, OSError, ValueError) as e:
        db.close()
        raise ValueError("state database is corrupt or unavailable") from e


def load_owned_parts(db: sqlite3.Connection, buyer_id: str) -> list[dict]:
    buyer_id = _nonempty(buyer_id, "buyer_id")
    out = []
    for row_kind, payload in db.execute("SELECT kind, payload FROM owned_parts WHERE buyer_id=? ORDER BY kind", (buyer_id,)):
        part = _load(payload)
        if _validate_owned(buyer_id, part) != row_kind:
            raise ValueError("stored owned part kind does not match its row")
        out.append(part)
    return out


def remember_owned(db: sqlite3.Connection, buyer_id: str, parts: list[dict]) -> list[dict]:
    buyer_id = _nonempty(buyer_id, "buyer_id")
    if not isinstance(parts, list):
        raise ValueError("parts must be a list")
    checked = [(_validate_owned(buyer_id, part), _dump(part)) for part in parts]
    _begin(db)
    try:
        for kind, payload in checked:
            db.execute("INSERT INTO owned_parts (buyer_id, kind, payload) VALUES (?, ?, ?) "
                       "ON CONFLICT (buyer_id, kind) DO UPDATE SET payload=excluded.payload",
                       (buyer_id, kind, payload))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return load_owned_parts(db, buyer_id)


def mark_goal_handled(db: sqlite3.Connection, goal_id: str, buyer_id: str) -> None:
    goal_id, buyer_id = _nonempty(goal_id, "goal_id"), _nonempty(buyer_id, "buyer_id")
    try:
        db.execute("INSERT OR IGNORE INTO handled_goals (goal_id, buyer_id, handled_at) VALUES (?, ?, ?)",
                   (goal_id, buyer_id, datetime.now(timezone.utc).isoformat()))
        db.commit()
    except BaseException:
        db.rollback()
        raise


def goal_handled(db: sqlite3.Connection, goal_id: str) -> bool:
    return db.execute("SELECT 1 FROM handled_goals WHERE goal_id=?", (goal_id,)).fetchone() is not None


def goal_has_transaction(db: sqlite3.Connection, goal_id: str) -> bool:
    return db.execute("SELECT 1 FROM transactions WHERE json_extract(payload, '$.goal_id')=?", (goal_id,)).fetchone() is not None


def load_goal(db: sqlite3.Connection, goal_id: str, buyer_id: str) -> dict | None:
    goal_id, buyer_id = _nonempty(goal_id, "goal_id"), _nonempty(buyer_id, "buyer_id")
    row = db.execute("SELECT payload FROM goals WHERE id=? AND buyer_id=?", (goal_id, buyer_id)).fetchone()
    if not row:
        return None
    goal = _load(row[0])
    if _validate_goal(goal) != (goal_id, buyer_id):
        raise ValueError("stored goal IDs do not match its row")
    return goal


def save_goal(db: sqlite3.Connection, goal: dict) -> None:
    goal_id, buyer_id = _validate_goal(goal)
    payload = _dump(goal)
    _begin(db)
    try:
        row = db.execute("SELECT buyer_id FROM goals WHERE id=?", (goal_id,)).fetchone()
        if row and row[0] != buyer_id:
            raise ValueError("goal ID already belongs to another buyer")
        db.execute("INSERT INTO goals (id, buyer_id, payload) VALUES (?, ?, ?) "
                   "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                   (goal_id, buyer_id, payload))
        db.commit()
    except BaseException:
        db.rollback()
        raise


def load_transaction(db: sqlite3.Connection, deal_id: str, buyer_id: str) -> dict | None:
    deal_id, buyer_id = _nonempty(deal_id, "deal_id"), _nonempty(buyer_id, "buyer_id")
    row = db.execute("SELECT phase, payload FROM transactions WHERE deal_id=? AND buyer_id=?", (deal_id, buyer_id)).fetchone()
    if not row:
        return None
    phase, payload = row
    transaction = _load(payload)
    if _validate_transaction(transaction)[:2] != (deal_id, buyer_id) or transaction["phase"] != phase:
        raise ValueError("stored transaction IDs do not match its row")
    return transaction


def save_transaction(db: sqlite3.Connection, transaction: dict) -> None:
    deal_id, buyer_id, _ = _validate_transaction(transaction)
    payload = _dump(transaction)
    _begin(db)
    try:
        row = db.execute("SELECT buyer_id FROM transactions WHERE deal_id=?", (deal_id,)).fetchone()
        if row and row[0] != buyer_id:
            raise ValueError("deal ID already belongs to another buyer")
        db.execute("INSERT INTO transactions (deal_id, buyer_id, phase, payload) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(deal_id) DO UPDATE SET phase=excluded.phase, payload=excluded.payload",
                   (deal_id, buyer_id, transaction["phase"], payload))
        db.commit()
    except BaseException:
        db.rollback()
        raise


def recover_on_start(db: sqlite3.Connection) -> None:
    """Pause calls and mark submitted charges uncertain; invoke once during explicit process startup."""
    _begin(db)
    try:
        rows = db.execute("SELECT deal_id, buyer_id, phase, payload FROM transactions "
                          "WHERE phase IN ('pending_approval', 'submitted')").fetchall()
        for deal_id, buyer_id, phase, payload in rows:
            transaction = _load(payload)
            if _validate_transaction(transaction)[:2] != (deal_id, buyer_id) or transaction["phase"] != phase:
                raise ValueError("stored transaction IDs or phase do not match its row")
            transaction["phase"] = "paused" if phase == "pending_approval" else "uncertain"
            db.execute("UPDATE transactions SET phase=?, payload=? WHERE deal_id=? AND buyer_id=?",
                       (transaction["phase"], _dump(transaction), deal_id, buyer_id))
        db.commit()
    except BaseException:
        db.rollback()
        raise
