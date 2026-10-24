"""verify_mandate(request): pay.tap.verify_request plus mandate expectation checks, as a Shield verdict.

A request that fails because its signed mandate, payee, amount or deal do not match what we expect is
QUARANTINED as "shield.mandate.mismatch" (held for the buyer, not paid). Any other failure (bad or replayed
signature, tampered body, unknown key, expired) is BLOCKED. Errors fail closed. Like a merchant, this check
CONSUMES the signed request's nonce on success, so presenting the same request twice blocks the second.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any, Mapping, Optional

from pay.mandate import _expectations
from pay.replay import NonceStore
from pay.tap import verify_request
from shield import VERSION

REQUIRED_EXPECTED = ("deal_id", "amount", "payee")
MISMATCH_REASONS = frozenset({
    "mandate_mismatch", "mandate_hash_mismatch", "hash_mismatch", "payee_mismatch", "amount_mismatch",
    "deal_mismatch", "buyer_mismatch",
})


def _verdict(verdict: str, rule_ids: list[str], severity: str, started: float, request_id: str) -> dict:
    return {
        "verdict": verdict, "rule_ids": rule_ids, "severity": severity, "evidence_spans": [],
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "request_id": request_id, "version": VERSION,
    }


def _from_reason(reason: str, started: float, request_id: str) -> dict:
    if reason in MISMATCH_REASONS:
        ids = ["shield.mandate.mismatch"]
        if reason != "mandate_mismatch":
            ids.append(f"shield.mandate.{reason}")
        return _verdict("quarantine", ids, "critical", started, request_id)
    return _verdict("block", [f"shield.mandate.{reason}"], "high", started, request_id)


def _mandate_of(request: Mapping) -> Optional[Mapping]:
    m = request.get("mandate")
    if isinstance(m, Mapping):
        return m
    try:
        body = json.loads(request["body"])
        m = body.get("mandate") if isinstance(body, dict) else None
    except (ValueError, TypeError, KeyError):
        return None
    return m if isinstance(m, Mapping) else None


def verify_mandate(request: Any, *, keys: Optional[Mapping], store: Optional[NonceStore],
                   now: Optional[datetime] = None, expected: Optional[Mapping] = None) -> dict:
    """`request`: {method, url, headers, body (str), mandate?, expected_mandate_hash?}.
    `keys`: the server's own keyring (never taken from the caller). `expected`: {deal_id, amount, payee,
    buyer_id?} the caller expects this payment to be for;
    deal_id, amount and payee are all required."""
    started = time.perf_counter()
    request_id = uuid.uuid4().hex
    try:
        if keys is None or store is None:
            raise ValueError("keys and store are required")
        if not isinstance(request, Mapping):
            raise TypeError("request must be an object")
        body = request["body"]
        body_bytes = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        mandate = _mandate_of(request)
        # All three expectations are required: a missing one must never mean "skip that check".
        if (not isinstance(expected, Mapping) or mandate is None
                or any(k not in expected for k in REQUIRED_EXPECTED)):
            return _verdict("block", ["shield.mandate.malformed_request"], "high", started, request_id)
        try:
            bad = _expectations(mandate, expected["deal_id"], expected["amount"], expected["payee"],
                                expected.get("buyer_id"))
        except KeyError:
            bad = None  # the MANDATE lacks a field: verify_request reports the precise reason
        if bad is not None:
            return _from_reason(bad.reason, started, request_id)
        result = verify_request(
            method=request["method"], url=request["url"], headers=request["headers"], body=body_bytes,
            keys=keys, store=store, now=now, mandate=request.get("mandate"),
            expected_mandate_hash=request.get("expected_mandate_hash"),
        )
        if result.ok:
            return _verdict("allow", [], "none", started, request_id)
        return _from_reason(result.reason, started, request_id)
    except KeyError:
        # a missing field in a well-formed object is a malformed request; anything else is an internal error
        rule = "shield.mandate.malformed_request" if isinstance(request, Mapping) else "shield.error"
        return _verdict("block", [rule], "high", started, request_id)
    except Exception:
        return _verdict("block", ["shield.error"], "critical", started, request_id)
