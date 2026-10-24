"""Transport-free request handlers shared by the HTTP layer. Logs hashes and rule ids, never bodies."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any, Mapping, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from pay.replay import NonceStore
from pay.tap import keyring
from pay.reasons import reason_for
from shield.agent import verify_agent
from shield.core import screen
from shield.registry import Registry, load_registry
from shield.verify import verify_mandate

log = logging.getLogger("shield")

# Old field "attack_type" (contracts/ShieldVerdict.schema.json v0), kept so Lane A's agents keep working.
_ATTACK_TYPE = {
    "override": "instruction_override", "hidden": "hidden_payload", "payee": "payee_swap",
    "money": "approval_pressure", "price": "price_claim", "exfil": "exfiltration",
    "encoded": "encoded_payload", "impersonation": "impersonation", "mandate": "mandate_mismatch",
    "classifier": "classifier_flag", "error": "error", "agent": "agent_identity",
}


_INTENT_TYPE = {
    "approval_bypass": "approval_pressure", "override": "instruction_override", "payment_redirect": "payee_swap",
    "authority_claim": "impersonation", "agent_directed": "instruction_override",
}


def attack_type(rule_ids: list[str]) -> str:
    if not rule_ids:
        return "none"
    if rule_ids[0].startswith("shield.intent."):
        return _INTENT_TYPE.get(rule_ids[0].split(".", 2)[2], "other")
    family = rule_ids[0].split(".")[1] if "." in rule_ids[0] else "error"
    return _ATTACK_TYPE.get(family, "other")


def _legacy(out: dict, payload: Any) -> dict:
    p = payload if isinstance(payload, Mapping) else {}
    out.update({
        "message_id": str(p.get("message_id", out["request_id"])),
        "sender_agent": str(p.get("sender_agent", "unknown")),
        "reasons": list(out["rule_ids"]),
        "attack_type": attack_type(out["rule_ids"]),
    })
    return out


def handle_screen(payload: Any) -> dict:
    p = payload if isinstance(payload, Mapping) else {}
    text = p.get("text", p.get("message"))
    ctx = dict(p["context"]) if isinstance(p.get("context"), Mapping) else p.get("context")
    if isinstance(ctx, dict) and "sender_role" not in ctx and p.get("sender_role"):
        ctx["sender_role"] = p["sender_role"]
    out = screen(text, ctx)
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16] if isinstance(text, str) else "none"
    log.info("screen sha256=%s verdict=%s rules=%s latency_ms=%s", digest, out["verdict"],
             ",".join(out["rule_ids"]) or "-", out["latency_ms"])
    return _legacy(out, payload)


def handle_verify_mandate(payload: Any, keys: Optional[Mapping], store: Optional[NonceStore]) -> dict:
    # Keys come only from the server; a "keys" field in the payload is ignored on purpose.
    expected = payload.get("expected") if isinstance(payload, Mapping) else None
    out = verify_mandate(payload, keys=keys, store=store, expected=expected if isinstance(expected, Mapping) else None)
    log.info("verify-mandate verdict=%s rules=%s latency_ms=%s", out["verdict"],
             ",".join(out["rule_ids"]) or "-", out["latency_ms"])
    return _legacy(out, payload)


def handle_verify_agent(payload: Any, registry: Registry) -> dict:
    out = verify_agent(payload, registry)
    addr = payload.get("agent_address") if isinstance(payload, Mapping) else None
    digest = hashlib.sha256(addr.encode("utf-8", "replace")).hexdigest()[:16] if isinstance(addr, str) else "none"
    log.info("verify-agent sha256=%s verdict=%s rules=%s latency_ms=%s", digest, out["verdict"],
             ",".join(out["rule_ids"]) or "-", out["latency_ms"])
    return _legacy(out, {"sender_agent": addr if isinstance(addr, str) else "unknown", "message_id": out["request_id"]})


def handle_advocate_reason(payload: Any) -> dict:
    """a10: {rule_id, source_url} in, closed schema {rule_id, summary, source_url} out; summary from a template."""
    return reason_for(payload)


def registry_from_env() -> Registry:
    """SHIELD_REGISTRY: path of the registry JSON (default shield/registry.json). A bad file raises at startup."""
    return load_registry()


def keys_from_env() -> dict:
    """SHIELD_TAP_PUBKEYS: comma-separated base64 raw Ed25519 public keys. Empty means every request fails
    with unknown_key (fail closed)."""
    keys = []
    for item in filter(None, (s.strip() for s in os.environ.get("SHIELD_TAP_PUBKEYS", "").split(","))):
        keys.append(Ed25519PublicKey.from_public_bytes(base64.b64decode(item, validate=True)))
    return keyring(*keys)


def store_from_env() -> NonceStore:
    return NonceStore(os.environ.get("SHIELD_NONCE_DB") or None)
