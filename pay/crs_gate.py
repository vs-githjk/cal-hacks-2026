"""CRS gate: a business payee is paid only after a fresh, verified CRS identity check (T8).

Pure logic, no network and no login: the check is a CrsCheck record (contracts/CrsCheck.schema.json) that
the CRS adapter (Lane A, #15) emits. This module refuses anything stale, unverified, missing, malformed or
from an unconfigured account, and binds the cleared check into the mandate hash (`crs_check_id`) so the
payment names the exact check that cleared the payee. Reasons are stable machine strings, as in pay.mandate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from pay.mandate import Verdict, parse_ts

MAX_CHECK_AGE = timedelta(hours=24)
FUTURE_SKEW = timedelta(minutes=5)
SIM_SELLER_NOTE = "identity not checked: SIM seller"
_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "contracts", "CrsCheck.schema.json")
_CODE = re.compile(r"^[A-Za-z0-9_]{1,48}$")
_schema_cache: Optional[dict] = None


def _ok(detail: str = "") -> Verdict:
    return Verdict(True, "ok", detail)


def _no(reason: str, detail: str = "") -> Verdict:
    return Verdict(False, reason, detail)


def _schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _manual_errors(rec: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    """The same rules as the schema, for when jsonschema is not installed. Fails closed on any odd type."""
    errors: list[str] = []
    props = schema["properties"]
    for key in schema["required"]:
        if key not in rec:
            errors.append(f"missing required field {key}")
    for key in rec:
        if key not in props:
            errors.append(f"unknown field {key}")
    for key, spec in props.items():
        if key not in rec:
            continue
        v = rec[key]
        kind = spec["type"]
        if kind == "string":
            if not _is_str(v) or len(v) < spec.get("minLength", 0):
                errors.append(f"{key} must be a string")
            elif "enum" in spec and v not in spec["enum"]:
                errors.append(f"{key} is not one of {spec['enum']}")
        elif kind == "boolean":
            if not isinstance(v, bool):
                errors.append(f"{key} must be true or false")
        elif kind == "array":
            if not isinstance(v, list) or len(v) > spec.get("maxItems", 1 << 30):
                errors.append(f"{key} must be a short list")
            elif not all(_is_str(c) and _CODE.match(c) for c in v):
                errors.append(f"{key} items must be short codes (letters, digits, underscore)")
    return errors


def validate_check(rec: Any) -> list[str]:
    """Error strings (empty list means valid). Uses jsonschema if installed, else the manual rules."""
    if not isinstance(rec, Mapping):
        return ["<root>: a CrsCheck must be an object"]
    schema = _schema()
    try:
        import jsonschema
    except ImportError:
        return _manual_errors(rec, schema)
    validator = jsonschema.Draft202012Validator(schema)
    return sorted(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                  for e in validator.iter_errors(dict(rec)))


def check_id(check: Mapping[str, Any]) -> str:
    """Stable id of one check: sha256 over the fields that identify it, cut to 32 hex. This is what a
    mandate carries as `crs_check_id`. A different check (new time, request, verdict) is a different id."""
    keys = ("seller_id", "product", "checked_at", "verified", "request_id", "origin")
    body = json.dumps({k: check.get(k) for k in keys}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "crs_" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def payee_ok(
    check: Optional[Mapping[str, Any]],
    *,
    business: bool,
    now: Optional[datetime] = None,
    seller_id: Optional[str] = None,
) -> Verdict:
    """May this payee be paid? A business payee needs a verified CrsCheck younger than 24 hours.
    A SIM (non-business) payee with no check passes, with the detail "identity not checked: SIM seller".
    Any check that is present is judged the same way for both: a blocked one never clears a payee.
    `seller_id`, when given, must match the check's seller (a check for seller A never pays seller B)."""
    now = datetime.now(timezone.utc) if now is None else now
    if check is None:
        if business:
            return _no("crs_missing", "identity not checked by CRS")
        return _ok(SIM_SELLER_NOTE)
    errors = validate_check(check)
    if errors:
        return _no("crs_malformed", errors[0])
    if check["origin"] == "NOT_CONFIGURED":
        return _no("crs_not_configured", "CRS is not configured, so no identity was checked")
    if seller_id is not None and check["seller_id"] != seller_id:
        return _no("crs_seller_mismatch", "the CRS check is for a different seller")
    if not check["verified"]:
        codes = ", ".join(check["reason_codes"]) or "no reason given"
        return _no("crs_not_verified", f"CRS did not verify this seller: {codes}")
    try:
        checked = parse_ts(check["checked_at"])
    except ValueError as e:
        return _no("crs_malformed", str(e))
    if checked - now > FUTURE_SKEW:
        return _no("crs_future", "the CRS check is dated in the future")
    if now - checked > MAX_CHECK_AGE:
        return _no("crs_expired", "CRS check expired")
    return _ok(f"CRS {check['product']} check verified ({check['origin'].lower()})")


def bound_ok(
    mandate: Mapping[str, Any],
    check: Optional[Mapping[str, Any]],
    *,
    business: bool,
    seller_id: Optional[str],
    now: Optional[datetime] = None,
) -> Verdict:
    """The payment-side gate: payee_ok, and for a business payee the mandate must carry this exact check's
    id (crs_check_id is inside the mandate hash, so it cannot be added or swapped after approval).
    `seller_id` is the seller being paid and has no default: a caller that forgets it gets a TypeError, and a
    business payee with None or a different seller than the check's is refused (crs_seller_mismatch)."""
    verdict = payee_ok(check, business=business, now=now, seller_id=seller_id)
    if not verdict.ok or not business:
        return verdict
    if seller_id is None or check["seller_id"] != seller_id:
        return _no("crs_seller_mismatch", "the CRS check is for a different seller")
    if mandate.get("crs_check_id") != check_id(check):
        return _no("crs_not_bound", "the mandate does not name the CRS check that cleared this payee")
    return verdict
