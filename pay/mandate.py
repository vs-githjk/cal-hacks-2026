"""Mandate: the one-deal, one-amount, one-payee, one-use authorization (contracts/Mandate.schema.json).

The hash binds deal_id, buyer_id, amount, currency, payee, tier_price, nonce and expires_at. Stripe charge and
TAP verification both check it. A charge needs status "approved" plus an approval_id (`can_charge`).
Every check returns a Verdict with a stable machine reason, never free text from a model.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from pay.replay import NS_MANDATE, NonceStore

HASH_FIELDS = ("deal_id", "buyer_id", "amount", "currency", "payee", "tier_price", "nonce", "expires_at")   # buyer_id: #186
# Hashed only when present, so a mandate without it hashes exactly as it did before (T8: CRS check binding).
OPTIONAL_HASH_FIELDS = ("crs_check_id",)
MAX_TTL_SECONDS = 600
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "contracts", "Mandate.schema.json")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


class MandateError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def _ok() -> Verdict:
    return Verdict(True, "ok")


def _no(reason: str, detail: str = "") -> Verdict:
    return Verdict(False, reason, detail)


# ---------- time ----------

def format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(TS_FORMAT)


def parse_ts(s: str) -> datetime:
    if not isinstance(s, str) or not s.endswith("Z"):
        raise ValueError(f"timestamp must be UTC and end in Z: {s!r}")
    return datetime.strptime(s, TS_FORMAT).replace(tzinfo=timezone.utc)


def _now(now: Optional[datetime]) -> datetime:
    return datetime.now(timezone.utc) if now is None else now


# ---------- hash ----------

def _norm_number(v: Any) -> Any:
    """Integral floats hash as ints (1119.0 and 1119 are the same amount, as JS would print them)."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"expected a number, got {v!r}")
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError("number must be finite")
        if v.is_integer():
            return int(v)
    return v


def canonical(m: Mapping[str, Any]) -> str:
    """Canonical JSON over HASH_FIELDS: sorted keys, no spaces. A missing tier_price counts as null.
    OPTIONAL_HASH_FIELDS join the body only when they are not None."""
    body = {k: m.get(k) for k in HASH_FIELDS}
    body.update({k: m[k] for k in OPTIONAL_HASH_FIELDS if m.get(k) is not None})
    body["amount"] = _norm_number(body["amount"])
    body["tier_price"] = _norm_number(body["tier_price"])
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def mandate_hash(m: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(m).encode("utf-8")).hexdigest()


def idempotency_key(m: Mapping[str, Any]) -> str:
    """Key for the Stripe charge: a second charge for the same mandate hash is the same request."""
    return "mandate:" + mandate_hash(m)


# ---------- schema ----------

_schema_cache: Optional[dict] = None


def _schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


_TYPES = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _manual_check(m: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    """Minimal fallback: required keys, no extra keys, types, enums. Used only without jsonschema."""
    errors: list[str] = []
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in m:
            errors.append(f"missing required field {key}")
    if schema.get("additionalProperties") is False:
        for key in m:
            if key not in props:
                errors.append(f"unknown field {key}")
    for key, spec in props.items():
        if key not in m:
            continue
        v = m[key]
        types = spec.get("type")
        if types is not None:
            types = [types] if isinstance(types, str) else types
            if not any(_TYPES[t](v) for t in types):
                errors.append(f"{key} has the wrong type")
                continue
        if "enum" in spec and v not in spec["enum"]:
            errors.append(f"{key} is not one of {spec['enum']}")
    return errors


def validate_schema(m: Mapping[str, Any]) -> list[str]:
    """Error strings (empty list means valid). Uses jsonschema if installed, else a minimal check."""
    schema = _schema()
    try:
        import jsonschema
    except ImportError:
        return _manual_check(m, schema)
    validator = jsonschema.Draft202012Validator(schema)
    return sorted(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                  for e in validator.iter_errors(dict(m)))


# ---------- build ----------

def new_mandate(
    *,
    deal_id: str,
    buyer_id: str,
    amount: float,
    payee: str,
    tier_price: Optional[float] = None,
    currency: str = "USD",
    goal_id: Optional[str] = None,
    within_allowance: bool = False,
    origin: str = "SIM",
    ttl_seconds: int = MAX_TTL_SECONDS,
    now: Optional[datetime] = None,
    mandate_id: Optional[str] = None,
    crs_check_id: Optional[str] = None,
) -> dict:
    """A pending mandate with a random 128-bit nonce, expiring at most 10 minutes out.
    `crs_check_id` (pay.crs_gate.check_id) binds the mandate to the CRS check that cleared a business payee."""
    if crs_check_id is not None and (not isinstance(crs_check_id, str) or not crs_check_id.strip()):
        raise ValueError("crs_check_id must be a non-empty string when given")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be 1..{MAX_TTL_SECONDS}")
    amt = _norm_number(amount)
    if amt is None or amt <= 0:
        raise ValueError("amount must be a positive number")
    _norm_number(tier_price)
    created = _now(now).astimezone(timezone.utc).replace(microsecond=0)
    m: dict[str, Any] = {
        "id": mandate_id or "mnd_" + secrets.token_hex(8),
        "deal_id": deal_id,
        "buyer_id": buyer_id,
        "amount": amount,
        "currency": currency,
        "payee": payee,
        "tier_price": tier_price,
        "nonce": secrets.token_hex(16),
        "created_at": format_ts(created),
        "expires_at": format_ts(created + timedelta(seconds=ttl_seconds)),
        "within_allowance": within_allowance,
        "status": "pending",
        "approval_id": None,
        "tap_signature": None,
        "origin": origin,
    }
    if goal_id is not None:
        m["goal_id"] = goal_id
    if crs_check_id is not None:
        m["crs_check_id"] = crs_check_id
    m["hash"] = mandate_hash(m)
    errors = validate_schema(m)
    if errors:
        raise ValueError("mandate violates contracts/Mandate.schema.json: " + "; ".join(errors))
    return m


# ---------- verify ----------

def _positive_amount(v: Any) -> Optional[Any]:
    """The amount normalized, or None when it is not a positive finite number (NaN, 0, negative, bool, str)."""
    try:
        n = _norm_number(v)
    except ValueError:
        return None
    return n if n is not None and n > 0 else None


def _integrity(m: Mapping[str, Any], now: datetime) -> Optional[Verdict]:
    """Schema, amount, hash and ttl cap. created_at is not hashed, so the cap is checked twice: expires_at
    minus created_at, and expires_at against the clock (an edited created_at cannot stretch the quote)."""
    errors = validate_schema(m)
    if errors:
        return _no("schema_invalid", errors[0])
    if _positive_amount(m["amount"]) is None:
        return _no("bad_amount", "amount must be a positive, finite number")
    if mandate_hash(m) != m["hash"]:
        return _no("hash_mismatch", "fields do not match the mandate hash")
    try:
        created, expires = parse_ts(m["created_at"]), parse_ts(m["expires_at"])
    except ValueError as e:
        return _no("schema_invalid", str(e))
    if expires - created > timedelta(seconds=MAX_TTL_SECONDS):
        return _no("ttl_too_long", "expires_at is more than 10 minutes after created_at")
    if expires - now > timedelta(seconds=MAX_TTL_SECONDS):
        return _no("ttl_too_long", "expires_at is more than 10 minutes from now")
    return None


def _status_and_expiry(m: Mapping[str, Any], now: datetime) -> Optional[Verdict]:
    status = m["status"]
    if status == "used":
        return _no("already_used", "mandate was already used")
    if status == "denied":
        return _no("denied", "buyer denied this mandate")
    if status == "expired" or now >= parse_ts(m["expires_at"]):
        return _no("expired", "mandate is past expires_at")
    return None


def verify(m: Mapping[str, Any], now: Optional[datetime] = None) -> Verdict:
    """Valid if the schema and hash hold, the ttl cap holds, and it is unexpired, unused and not denied.
    Says nothing about approval: use `can_charge` before moving money."""
    now = _now(now)
    bad = _integrity(m, now)
    if bad is not None:
        return bad
    bad = _status_and_expiry(m, now)
    return bad if bad is not None else _ok()


def _expectations(m: Mapping[str, Any], deal_id, amount, payee, buyer_id) -> Optional[Verdict]:
    expected_amount = _positive_amount(amount)
    if expected_amount is None:
        return _no("bad_amount", "expected amount must be a positive, finite number")
    if m["deal_id"] != deal_id:
        return _no("deal_mismatch", "mandate is for a different deal")
    if _norm_number(m["amount"]) != expected_amount:
        return _no("amount_mismatch", "mandate is for a different amount")
    if m["payee"] != payee:
        return _no("payee_mismatch", "mandate is for a different payee")
    if buyer_id is not None and m["buyer_id"] != buyer_id:
        return _no("buyer_mismatch", "mandate is for a different buyer")
    return None


def can_charge(
    m: Mapping[str, Any],
    now: Optional[datetime] = None,
    *,
    deal_id: str,
    amount: float,
    payee: str,
    store: NonceStore,
    buyer_id: Optional[str] = None,
) -> Verdict:
    """The guard in front of every charge. Needs a valid, unexpired mandate with status "approved" and
    an approval_id, matching the deal, amount and payee the caller expects (all required: a mandate for
    deal A must never pass without saying which deal is being paid), and an unused nonce in `store`.
    `buyer_id` is checked too when given.

    `m` must only be a mandate loaded from the server's own approval row. The hash does not cover
    `status` or `approval_id`, so a mandate taken from a request body proves nothing about approval."""
    now = _now(now)
    bad = _integrity(m, now)
    if bad is not None:
        return bad
    bad = _expectations(m, deal_id, amount, payee, buyer_id)
    if bad is not None:
        return bad
    bad = _status_and_expiry(m, now)
    if bad is not None:
        return bad
    if m["status"] != "approved":
        return _no("not_approved", "status must be approved before payment")
    approval_id = m.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        return _no("no_approval_id", "an approval_id is required before payment")
    if store.seen(NS_MANDATE, m["nonce"]):
        return _no("replayed_mandate", "this mandate nonce was already used")
    return _ok()


def mark_used(
    m: dict,
    *,
    deal_id: str,
    amount: float,
    payee: str,
    store: NonceStore,
    now: Optional[datetime] = None,
    buyer_id: Optional[str] = None,
) -> dict:
    """Spend the mandate once. Re-runs `can_charge` with the same expectations, records the nonce
    atomically, sets status "used". Raises MandateError (reason "replayed_mandate" on a second use).
    Mutates and returns `m`."""
    verdict = can_charge(m, now, deal_id=deal_id, amount=amount, payee=payee, store=store, buyer_id=buyer_id)
    if not verdict:
        raise MandateError(verdict.reason, verdict.detail)
    if not store.consume(NS_MANDATE, m["nonce"]):
        raise MandateError("replayed_mandate", "this mandate nonce was already used")
    m["status"] = "used"
    return m
