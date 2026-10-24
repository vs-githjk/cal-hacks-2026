"""Transport-free request handlers shared by the HTTP layer. Logs hashes and rule ids, never bodies."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from pay.replay import NonceStore
from pay.tap import keyring
from pay.tap import load_private_key
from pay.reasons import reason_for
from shield.receipt import sign_allow_receipt
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


def handle_screen_payment(payload: Any, registry: Registry, receipt_private_key=None) -> dict:
    """Screen the exact Payment Protocol JSON and, only on allow, optionally attest its binding."""
    p = payload if isinstance(payload, Mapping) else {}
    message_id, sender = p.get("message_id"), p.get("sender_agent")
    request_json, expected = p.get("request_json"), p.get("expected")
    try:
        if (not isinstance(message_id, str) or not message_id or not isinstance(sender, str) or not sender
                or not isinstance(request_json, str) or len(request_json.encode("utf-8")) > 32 * 1024
                or not isinstance(expected, Mapping)
                or set(expected) != {"deal_id", "mandate_hash", "amount_cents", "currency", "payee"}):
            raise ValueError("malformed payment-screen request")
        seller = registry.get(sender)
        if seller is None or seller.get("role") != "seller" or registry.is_denied(sender):
            raise ValueError("payment sender is not a registered seller")
        deal_id, mand_hash, amount_cents, currency, payee = (expected[k] for k in
            ("deal_id", "mandate_hash", "amount_cents", "currency", "payee"))
        if (not all(isinstance(x, str) and x for x in (deal_id, mand_hash, currency, payee))
                or isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents <= 0
                or currency != "USD" or payee != sender):
            raise ValueError("invalid expected payment binding")
        request = json.loads(request_json)
        if not isinstance(request, dict) or set(request) - {"accepted_funds", "recipient", "deadline_seconds", "reference", "description", "metadata"}:
            raise ValueError("malformed RequestPayment")
        funds = request.get("accepted_funds")
        if (not isinstance(funds, list) or len(funds) != 1 or not isinstance(funds[0], dict)
                or set(funds[0]) != {"amount", "currency", "payment_method"}):
            raise ValueError("RequestPayment must contain one complete accepted-funds entry")
        if not isinstance(funds[0].get("amount"), str):
            raise ValueError("RequestPayment amount must be a string")
        try:
            amount = Decimal(funds[0]["amount"])
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("invalid RequestPayment amount") from None
        if (not amount.is_finite() or amount <= 0 or amount * 100 != (amount * 100).to_integral_value()
                or int(amount * 100) != amount_cents or funds[0]["currency"] != currency
                or funds[0]["payment_method"] != "stripe" or request.get("recipient") != payee
                or request.get("reference") != mand_hash or request.get("description") != "deal " + deal_id
                or isinstance(request.get("deadline_seconds"), bool)
                or not isinstance(request.get("deadline_seconds"), int) or request["deadline_seconds"] <= 0):
            raise ValueError("RequestPayment does not match expected binding")
    except (ValueError, TypeError, UnicodeError, KeyError, json.JSONDecodeError):
        out = screen("invalid RequestPayment", {"request_id": str(message_id or "payment-screen")})
        out.update(verdict="block", rule_ids=["shield.payment.request_invalid"], severity="critical", evidence_spans=[])
        out = _legacy(out, p)
        out["reasons"] = out["rule_ids"]
        out["attack_type"] = "mandate"
        return out

    out = screen(request_json, {"sender_role": "seller", "payee_of_record": payee, "request_id": message_id})
    out = _legacy(out, p)
    if out["verdict"] == "allow" and receipt_private_key is not None:
        try:
            out["receipt"] = sign_allow_receipt(private_key=receipt_private_key, message_id=message_id,
                request_json=request_json, deal_id=deal_id, mandate_hash=mand_hash, amount_cents=amount_cents,
                currency=currency, payee=payee)
        except (TypeError, ValueError):
            log.error("payment-screen receipt signing failed")
    return out


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


def receipt_private_key_from_env():
    """Optional Shield-owned receipt signer; never fall back to the buyer's VISA TAP key."""
    path = os.environ.get("SHIELD_RECEIPT_PRIVATE_KEY_PATH")
    if not path:
        return None
    try:
        return load_private_key(path=path)
    except Exception as e:
        raise ValueError("SHIELD_RECEIPT_PRIVATE_KEY_PATH is not a valid Ed25519 key file") from e
