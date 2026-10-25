"""Small synchronous adapter between buyer-owned transaction state and trusted checkout services."""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator
from pay.approval import approved_voice_record_matches
from pay.mandate import mandate_hash, parse_ts, verify as verify_mandate
from pay.tap import attach_signature, sign_request
from pay.voice_cartesia import VoiceResult, run_approval_call

_CARD_SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "AdvocateCard.schema.json"


def _utc_now(value: datetime | None = None) -> datetime:
    current = datetime.now(timezone.utc) if value is None else value
    if (not isinstance(current, datetime) or current.tzinfo is None
            or current.utcoffset() != timedelta(0)):
        raise ValueError("business time must be timezone-aware UTC")
    return current.astimezone(timezone.utc)


def _clock_now(clock: Callable[[], datetime] | None) -> Callable[[], datetime]:
    source = (lambda: datetime.now(timezone.utc)) if clock is None else clock
    if not callable(source):
        raise ValueError("business clock must be callable")
    return lambda: _utc_now(source())


def _cents(value: Any) -> int | None:
    try:
        from decimal import Decimal, InvalidOperation, Overflow
        amount = Decimal(str(value))
        if isinstance(value, bool) or not amount.is_finite() or amount <= 0 or amount.adjusted() > 11:
            return None
        cents = amount * 100
        if cents <= 0 or cents != cents.to_integral_value():
            return None
        return int(cents)
    except (InvalidOperation, Overflow, OverflowError, ValueError, TypeError):
        return None


def _bound_transaction(transaction: Mapping[str, Any], *, approval_phase: bool,
                       now: datetime | None = None) -> tuple[dict, dict, dict]:
    now = _utc_now(now)
    if not isinstance(transaction, Mapping):
        raise ValueError("stored transaction is unavailable")
    tx = dict(transaction)
    mandate, deal, card = tx.get("mandate"), tx.get("deal"), tx.get("advocate_card")
    if not isinstance(mandate, Mapping) or not isinstance(deal, Mapping) or not isinstance(card, Mapping):
        raise ValueError("stored transaction evidence is incomplete")
    if (tx.get("phase") not in (("pending_approval",) if approval_phase else ("approved", "submitted"))
            or any(tx.get(key) != mandate.get(key) for key in ("deal_id", "buyer_id", "goal_id"))
            or deal.get("id") != tx.get("deal_id") or deal.get("goal_id") != tx.get("goal_id")
            or deal.get("need_id") != tx.get("need_id") or deal.get("bid_id") != tx.get("bid_id")
            or card.get("need_id") != tx.get("need_id") or card.get("bid_id") != tx.get("bid_id")
            or _cents(deal.get("amount")) != _cents(mandate.get("amount"))
            or deal.get("payee") != mandate.get("payee")):
        raise ValueError("stored transaction does not match mandate, deal and review card")
    call_reason = card.get("call_reason")
    if (not isinstance(call_reason, Mapping) or set(call_reason) != {"rule_id", "summary", "source_url"}
            or card.get("rule_id") != call_reason.get("rule_id")
            or card.get("reason") != call_reason.get("summary")
            or card.get("source_url") != call_reason.get("source_url")):
        raise ValueError("stored AdvocateCard reason is not canonical")
    try:
        schema = json.loads(_CARD_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(dict(card))
    except Exception:
        raise ValueError("stored AdvocateCard is invalid") from None
    try:
        if mandate_hash(mandate) != mandate.get("hash") or not verify_mandate(mandate, now=now):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("stored mandate is invalid or expired") from None
    if approval_phase and mandate.get("status") != "pending":
        raise ValueError("mandate is not pending a fresh owner approval")
    if not approval_phase:
        if mandate.get("status") != "approved" or not mandate.get("approval_id"):
            raise PermissionError("mandate has no trusted approval")
        voice = tx.get("voice_approval")
        if isinstance(voice, Mapping):
            if not approved_voice_record_matches(dict(voice), dict(mandate), now=now):
                raise PermissionError("VoiceApproval does not authorize this mandate")
        else:
            allow = tx.get("allowance_authorization")
            expected = {"id": mandate.get("approval_id"), "mandate_hash": mandate.get("hash"), "mandate_id": mandate.get("id"),
                "deal_id": tx.get("deal_id"), "buyer_id": tx.get("buyer_id"), "goal_id": tx.get("goal_id"),
                "amount": mandate.get("amount"), "payee": mandate.get("payee"), "method": "allowance"}
            try:
                approved_at = datetime.fromisoformat(allow["approved_at"].replace("Z", "+00:00"))
                allowance_time_ok = (approved_at.tzinfo is not None and parse_ts(mandate["created_at"]) <= approved_at
                    <= now + timedelta(seconds=5))
            except (AttributeError, KeyError, TypeError, ValueError):
                allowance_time_ok = False
            if (not isinstance(allow, Mapping) or mandate.get("within_allowance") is not True
                    or not allowance_time_ok or not all(allow.get(k) == v for k, v in expected.items())):
                raise PermissionError("no trusted approval record exists for this mandate")
    return tx, dict(mandate), dict(deal)


def _advocate_reason(card: Mapping[str, Any]) -> dict | None:
    reason = card.get("call_reason")
    if not isinstance(reason, Mapping):
        return None
    # Only the same stored closed-schema reason used by the canonical review enters script_for.
    return {"rule_id": reason.get("rule_id"), "summary": reason.get("summary"),
            "source_url": reason.get("source_url")}


def approve_offer(transaction: Mapping[str, Any], client: Any, service: Any, *,
                  on_code: Callable[[str], Any], buyer_name: str = "there",
                  now: Callable[[], datetime] | None = None) -> VoiceResult:
    """Run the existing real voice approval flow for one stored pending transaction.

    `on_code` must privately deliver to the authenticated owner/session bound by the caller. This
    adapter never logs or returns the code and refuses async callbacks that were not awaited.
    """
    business_clock = _clock_now(now)
    tx, mandate, deal = _bound_transaction(transaction, approval_phase=True, now=business_clock())
    if not callable(on_code):
        raise ValueError("private owner code delivery callback is required")

    def private_delivery(code: str) -> None:
        try:
            sent = on_code(code)
            if inspect.isawaitable(sent):
                close = getattr(sent, "close", None)
                if close:
                    close()
                raise RuntimeError
            if sent is False:
                raise RuntimeError
        except Exception:
            # Suppress callback exception text: it could contain the one-time code.
            raise PermissionError("private approval code delivery failed") from None

    result = run_approval_call(mandate, _advocate_reason(tx["advocate_card"]), client, service,
                               deal=deal, buyer_name=buyer_name, on_code=private_delivery,
                               now=business_clock)
    record = result.record
    if result.approved and not approved_voice_record_matches(record, mandate, now=business_clock()):
        return VoiceResult(False, "approval_record_mismatch", call_id=result.call_id,
                           end_reason=result.end_reason, attempts=result.attempts, trace=result.trace)
    return result


def settle_offer(transaction: Mapping[str, Any], request_payment: Any, merchant_sim: Any, *,
                 receipt: Mapping[str, Any], message_id: str, tap_private_key: Any,
                 merchant_url: str = "https://merchant.sim.test/v1/charge",
                 now: datetime | None = None) -> dict:
    """Submit exact protocol bytes to MerchantSim after validating the stored approval binding."""
    now = _utc_now(now)
    tx, mandate, _deal = _bound_transaction(transaction, approval_phase=False, now=now)
    if not isinstance(receipt, Mapping) or not receipt or not isinstance(message_id, str) or not message_id:
        raise PermissionError("a Shield allow receipt and stable message id are required")
    try:
        body = request_payment.model_dump_json().encode("utf-8")
        parsed = json.loads(body)
    except Exception:
        raise ValueError("RequestPayment cannot be serialized") from None
    funds = parsed.get("accepted_funds") if isinstance(parsed, dict) else None
    if (not isinstance(funds, list) or len(funds) != 1 or not isinstance(funds[0], dict)
            or set(funds[0]) != {"amount", "currency", "payment_method"}
            or funds[0].get("currency") != "USD" or funds[0].get("payment_method") != "stripe"
            or _cents(funds[0].get("amount")) != _cents(mandate.get("amount"))
            or parsed.get("recipient") != mandate.get("payee") or parsed.get("reference") != mandate.get("hash")
            or parsed.get("description") != "deal " + str(tx.get("deal_id"))):
        raise PermissionError("RequestPayment differs from approved deal, amount or payee")
    expected_id = "req:" + hashlib.sha256(tx["buyer_id"].encode("utf-8") + b"\n" + body).hexdigest()
    if message_id != expected_id:
        raise PermissionError("RequestPayment message id does not bind exact bytes and buyer")
    amount_cents = _cents(funds[0].get("amount"))
    settlement = {"message_id": message_id, "request_sha256": hashlib.sha256(body).hexdigest(),
        "mandate_hash": mandate["hash"], "deal_id": tx["deal_id"], "buyer_id": tx["buyer_id"],
        "amount_cents": amount_cents, "currency": funds[0]["currency"], "payee": parsed["recipient"],
        "idempotency_key": "mandate:" + mandate["hash"], "mode": tx.get("mode"),
        "receipt_keyid": receipt.get("keyid") if isinstance(receipt.get("keyid"), str) else ""}
    headers = sign_request(method="POST", url=merchant_url, body=body, mandate=mandate,
                           private_key=tap_private_key, now=now)
    signed_mandate = attach_signature(mandate, headers)
    outcome = merchant_sim.handle(method="POST", url=merchant_url, headers=headers, body=body,
        receipt=receipt, message_id=message_id, buyer_id=tx["buyer_id"], now=now)
    if not isinstance(outcome, Mapping):
        return {"mandate": signed_mandate, "settlement": settlement, "settlement_result": {
            "status": "uncertain", "reason": "merchant_result_unavailable", "charge_id": None,
            "mandate_hash": mandate["hash"], "origin": "SIM"}}
    result = {key: outcome.get(key) for key in ("status", "reason", "charge_id", "mandate_hash", "origin")}
    if result.get("status") == "charged" and (result.get("origin") != "SIM"
            or result.get("mandate_hash") != mandate.get("hash")
            or not isinstance(result.get("charge_id"), str)
            or not result["charge_id"].startswith(("pi_", "ch_"))):
        raise PermissionError("MerchantSim returned a mismatched paid result")
    return {"mandate": signed_mandate, "settlement": settlement, "settlement_result": result}


def format_settlement_result(envelope: Mapping[str, Any]) -> str:
    """Describe only the exact status and identifiers returned by checkout settlement."""
    settlement = envelope.get("settlement") if isinstance(envelope, Mapping) else None
    result = envelope.get("settlement_result") if isinstance(envelope, Mapping) else None
    if not isinstance(settlement, Mapping) or not isinstance(result, Mapping):
        return "Payment result unavailable; do not mark this purchase paid."
    mandate_hash = settlement.get("mandate_hash")
    deal_id = settlement.get("deal_id")
    cents = settlement.get("amount_cents")
    if (not isinstance(mandate_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", mandate_hash)
            or not isinstance(deal_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", deal_id)
            or isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0):
        return "Payment result unavailable; do not mark this purchase paid."
    prefix = mandate_hash[:12]
    if result.get("status") == "charged":
        charge_id = result.get("charge_id")
        origin = result.get("origin")
        mode = settlement.get("mode")
        if mode not in ("SIM", "stripe_test"):
            return "Payment mode unavailable; do not mark this purchase paid."
        if (result.get("mandate_hash") != mandate_hash or origin != "SIM"
                or not isinstance(charge_id, str)
                or not re.fullmatch(r"(?:pi|ch)_[A-Za-z0-9_]{1,128}", charge_id)):
            return "Payment result unavailable; do not mark this purchase paid."
        return (f"{mode} payment confirmed for deal {deal_id}: ${cents // 100}.{cents % 100:02d}, "
                f"reference {charge_id}, mandate {prefix}.")
    if result.get("status") == "refused" or result.get("status") == "uncertain":
        return f"Payment {result['status']} for deal {deal_id}; mandate {prefix}."
    return "Payment result unavailable; do not mark this purchase paid."
