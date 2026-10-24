"""Short-lived Ed25519 attestations that Shield allowed exact RequestPayment bytes."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from pay.mandate import Verdict
from pay.tap import key_id

DOMAIN = b"tech-bazaar/shield-allow-receipt/v1\n"
MAX_TTL_SECONDS = 60
CLOCK_SKEW_SECONDS = 30
_FIELDS = {"version", "receipt_id", "message_id", "request_sha256", "deal_id", "mandate_hash",
           "amount_cents", "currency", "payee", "verdict", "issued_at", "expires_at", "keyid", "alg",
           "signature"}


def parse_unique_json(value: str | bytes) -> Any:
    """Parse UTF-8 JSON while rejecting repeated keys at every nesting level."""
    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=unique_pairs)


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _request_bytes(value: str | bytes) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
    raise ValueError("request_json must be UTF-8 text or bytes")


def _now_seconds(now: datetime | None) -> int:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return int(current.timestamp())


def sign_allow_receipt(*, private_key: Ed25519PrivateKey, message_id: str,
                       request_json: str | bytes, deal_id: str, mandate_hash: str,
                       amount_cents: int, currency: str, payee: str,
                       now: datetime | None = None, ttl_seconds: int = MAX_TTL_SECONDS) -> dict:
    """Sign a closed, exact-byte binding. This proves screening only, not buyer approval."""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("private_key must be an Ed25519 private key")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be 1..{MAX_TTL_SECONDS}")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents <= 0:
        raise ValueError("amount_cents must be a positive integer")
    for name, value in (("message_id", message_id), ("deal_id", deal_id), ("mandate_hash", mandate_hash),
                        ("currency", currency), ("payee", payee)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    request = _request_bytes(request_json)
    issued = _now_seconds(now)
    payload = {"version": "1", "receipt_id": secrets.token_urlsafe(18), "message_id": message_id,
               "request_sha256": hashlib.sha256(request).hexdigest(), "deal_id": deal_id,
               "mandate_hash": mandate_hash, "amount_cents": amount_cents, "currency": currency,
               "payee": payee, "verdict": "allow", "issued_at": issued, "expires_at": issued + ttl_seconds,
               "keyid": key_id(private_key.public_key()), "alg": "ed25519"}
    payload["signature"] = base64.b64encode(private_key.sign(DOMAIN + _canonical(payload))).decode("ascii")
    return payload


def _no(reason: str) -> Verdict:
    return Verdict(False, reason)


def verify_allow_receipt(receipt: Any, keys: Mapping[str, Ed25519PublicKey], *, message_id: str,
                         request_json: str | bytes, deal_id: str, mandate_hash: str,
                         amount_cents: int, currency: str, payee: str,
                         now: datetime | None = None) -> Verdict:
    """Pure verification: no nonce store, I/O or caller-provided purchase authority."""
    if not isinstance(keys, Mapping) or not keys:
        return _no("receipt_unknown_key")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents <= 0:
        return _no("receipt_binding_mismatch")
    if not isinstance(receipt, Mapping) or set(receipt) != _FIELDS:
        return _no("receipt_schema_invalid")
    try:
        request = _request_bytes(request_json)
        if (receipt["version"] != "1" or receipt["verdict"] != "allow" or receipt["alg"] != "ed25519"
                or receipt["message_id"] != message_id or receipt["deal_id"] != deal_id
                or receipt["mandate_hash"] != mandate_hash or receipt["amount_cents"] != amount_cents
                or receipt["currency"] != currency or receipt["payee"] != payee
                or receipt["request_sha256"] != hashlib.sha256(request).hexdigest()):
            return _no("receipt_binding_mismatch")
        for name in ("receipt_id", "message_id", "deal_id", "mandate_hash", "currency", "payee", "keyid", "signature"):
            if not isinstance(receipt[name], str) or not receipt[name]:
                return _no("receipt_schema_invalid")
        issued, expires, cents = receipt["issued_at"], receipt["expires_at"], receipt["amount_cents"]
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (issued, expires, cents)) or cents <= 0:
            return _no("receipt_schema_invalid")
        if expires <= issued or expires - issued > MAX_TTL_SECONDS:
            return _no("receipt_ttl_invalid")
        now_ts = _now_seconds(now)
        if issued > now_ts + CLOCK_SKEW_SECONDS:
            return _no("receipt_not_yet_valid")
        if now_ts >= expires:
            return _no("receipt_expired")
        public_key = keys.get(receipt["keyid"])
        if not isinstance(public_key, Ed25519PublicKey):
            return _no("receipt_unknown_key")
        signature = base64.b64decode(receipt["signature"], validate=True)
        payload = {key: value for key, value in receipt.items() if key != "signature"}
        public_key.verify(signature, DOMAIN + _canonical(payload))
    except (InvalidSignature, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        return _no("receipt_signature_invalid")
    return Verdict(True, "ok")
