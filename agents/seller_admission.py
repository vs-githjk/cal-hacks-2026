"""Verify an operator-enrolled seller identity without creating payment authority."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Mapping
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from pay.replay import NonceStore
from pay.tap import sign_agent_request, verify_agent_request
from shield.agent import verify_agent
from shield.registry import Registry

PROTOCOL = "techbazaar/seller-admission/v1"
MAX_BODY_BYTES = 64 * 1024
ORIGINS = {"LIVE", "MIRROR", "SIM"}
_BLOCK = {"admitted": False, "verdict": "block", "rule_ids": ["admission.invalid_request"],
          "agent_address": None, "origin": "SIM"}


def _result(verdict: str, rule_ids: list[str], address: str | None, origin: str) -> dict:
    return {"admitted": verdict == "allow", "verdict": verdict, "rule_ids": rule_ids,
            "agent_address": address, "origin": origin}


def _canonical_payload(body: bytes) -> dict | None:
    if not isinstance(body, bytes) or not body or len(body) > MAX_BODY_BYTES:
        return None

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def reject_constant(_value):
        raise ValueError("invalid JSON number")

    try:
        payload = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
        if not isinstance(payload, dict) or json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                                        ensure_ascii=False, allow_nan=False).encode("utf-8") != body:
            return None
        return payload
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return None


def _valid_mirror_evidence(payload: dict) -> bool:
    source_url, observed_at = payload.get("source_url"), payload.get("observed_at")
    if (not isinstance(source_url, str) or len(source_url) > 2048
            or not isinstance(observed_at, str) or len(observed_at) > 64):
        return False
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7f for char in source_url):
        return False
    try:
        source = urlsplit(source_url)
        _ = source.port
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        return (source.scheme in ("http", "https") and bool(source.hostname)
                and source.username is None and source.password is None and not source.fragment
                and observed.tzinfo is not None)
    except (ValueError, TypeError):
        return False


def verify_admission_request(
    *,
    body: bytes,
    method: str,
    url: str,
    headers: Mapping[str, str],
    actual_sender: str,
    registry: Registry,
    keys: Mapping[str, Ed25519PublicKey],
    replay_store: NonceStore,
    expected_audience: str,
    now: datetime | None = None,
) -> dict:
    """Authenticate exact signed seller data, then apply the operator registry and Shield policy."""
    if not isinstance(body, bytes) or not body or len(body) > MAX_BODY_BYTES:
        return dict(_BLOCK, rule_ids=["admission.payload_invalid"])
    origin = getattr(registry, "origin", None)
    if not isinstance(origin, str) or origin not in ORIGINS:
        return dict(_BLOCK, rule_ids=["admission.origin_untrusted"])
    if not isinstance(actual_sender, str) or not actual_sender:
        return _result("block", ["admission.sender_missing"], None, origin)
    try:
        if registry.is_denied(actual_sender):
            return _result("block", ["shield.agent.denylisted"], actual_sender, origin)
        entry = registry.get(actual_sender)
    except Exception:
        return _result("block", ["admission.registry_unavailable"], actual_sender, origin)
    if entry is None:
        return _result("quarantine", ["shield.agent.unregistered"], actual_sender, origin)
    if entry.get("role") != "seller":
        return _result("block", ["shield.agent.role_mismatch"], actual_sender, origin)
    keyid = entry.get("admission_key_id")
    if not isinstance(keyid, str) or not keyid or not isinstance(keys, Mapping):
        return _result("block", ["admission.key_unpinned"], actual_sender, origin)
    public_key = keys.get(keyid)
    if not isinstance(public_key, Ed25519PublicKey):
        return _result("block", ["admission.key_unpinned"], actual_sender, origin)

    signed = verify_agent_request(method=method, url=url, headers=headers, body=body,
                                  keys={keyid: public_key}, store=replay_store,
                                  actual_sender=actual_sender, expected_audience=expected_audience, now=now)
    if not signed:
        return _result("block", ["admission.signature_invalid"], actual_sender, origin)

    payload = _canonical_payload(body)
    if payload is None:
        return _result("block", ["admission.payload_invalid"], actual_sender, origin)
    expected_fields = {"protocol", "audience", "agent_address", "claimed_role", "seller_of_record",
                       "manifest", "origin"}
    if payload.get("origin") == "MIRROR":
        expected_fields |= {"source_url", "observed_at"}
    if (set(payload) != expected_fields or payload.get("protocol") != PROTOCOL
            or payload.get("audience") != expected_audience or payload.get("agent_address") != actual_sender
            or payload.get("claimed_role") != "seller" or payload.get("origin") != origin
            or payload.get("seller_of_record") != entry.get("seller_of_record")
            or not isinstance(payload.get("manifest"), dict)
            or (origin == "MIRROR" and not _valid_mirror_evidence(payload))):
        return _result("block", ["admission.payload_invalid"], actual_sender, origin)
    try:
        screened = verify_agent({"agent_address": actual_sender, "claimed_role": "seller",
                                 "seller_of_record": payload["seller_of_record"],
                                 "manifest": payload["manifest"]}, registry)
    except Exception:
        return _result("block", ["admission.shield_error"], actual_sender, origin)
    if (not isinstance(screened, dict) or screened.get("verdict") not in ("allow", "quarantine", "block")
            or not isinstance(screened.get("rule_ids"), list)
            or any(not isinstance(rule, str) for rule in screened["rule_ids"])):
        return _result("block", ["admission.shield_error"], actual_sender, origin)
    return _result(screened["verdict"], list(screened["rule_ids"]), actual_sender, origin)


def sign_admission_request(*, payload: Mapping[str, object], method: str, url: str,
                           agent_address: str, private_key: Ed25519PrivateKey,
                           now: datetime | None = None, ttl_seconds: int = 60,
                           nonce: str | None = None) -> tuple[bytes, dict[str, str]]:
    """Serialize the exact canonical payload and sign it with the admission-only TAP profile."""
    if not isinstance(payload, Mapping):
        raise ValueError("admission payload must be an object")
    try:
        body = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("admission payload is not serializable") from exc
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("admission payload is too large")
    audience = payload.get("audience")
    if not isinstance(audience, str):
        raise ValueError("admission audience is required")
    headers = sign_agent_request(method=method, url=url, body=body, agent_address=agent_address,
                                 audience=audience, private_key=private_key, now=now,
                                 ttl_seconds=ttl_seconds, nonce=nonce)
    return body, headers
