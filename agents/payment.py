"""Payment Protocol helpers. A CommitPayment exists only after verified local approval and charge."""
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, Overflow
from typing import Any, Mapping

from uagents_core.contrib.protocols.payment import CommitPayment, Funds, RequestPayment

from pay.approval import approved_voice_record_matches
from pay.mandate import MAX_TTL_SECONDS as TTL_S, new_mandate as _new_mandate
from pay.mandate import mandate_hash, parse_ts, verify as verify_mandate


def make_mandate(deal_id: str, amount: float, payee: str, buyer_id: str, within_allowance: bool,
                 goal_id: str | None = None, now: datetime | None = None) -> dict:
    """Use the shared canonical mandate builder and schema."""
    return _new_mandate(deal_id=deal_id, amount=amount, payee=payee, buyer_id=buyer_id,
                        within_allowance=within_allowance, goal_id=goal_id, now=now)


def payment_request(mandate: dict, recipient: str) -> RequestPayment:
    """Construct the seller request; MerchantSim still validates it against stored buyer state."""
    return RequestPayment(accepted_funds=[Funds(amount=f"{mandate['amount']:.2f}", currency="USD",
                                                payment_method="stripe")],
                          recipient=recipient, deadline_seconds=TTL_S, reference=mandate["hash"],
                          description=f"deal {mandate['deal_id']}")


def _cents(value: Any) -> int | None:
    try:
        amount = Decimal(str(value))
        if isinstance(value, bool) or not amount.is_finite() or amount <= 0 or amount.adjusted() > 11:
            return None
        cents = amount * 100
        if cents <= 0 or cents != cents.to_integral_value():
            return None
        return int(cents)
    except (InvalidOperation, Overflow, OverflowError, ValueError, TypeError):
        return None


def _authorized(transaction: Mapping[str, Any], mandate: Mapping[str, Any],
                now: datetime | None = None) -> bool:
    voice = transaction.get("voice_approval")
    if isinstance(voice, Mapping):
        return approved_voice_record_matches(dict(voice), dict(mandate), now=now)
    allowance = transaction.get("allowance_authorization")
    if not isinstance(allowance, Mapping) or mandate.get("within_allowance") is not True:
        return False
    expected = {"id": mandate.get("approval_id"), "mandate_hash": mandate.get("hash"), "mandate_id": mandate.get("id"),
                "deal_id": mandate.get("deal_id"), "buyer_id": mandate.get("buyer_id"),
                "goal_id": mandate.get("goal_id"), "amount": mandate.get("amount"),
                "payee": mandate.get("payee"), "method": "allowance"}
    try:
        approved_at = datetime.fromisoformat(allowance["approved_at"].replace("Z", "+00:00"))
        time_ok = (approved_at.tzinfo is not None and parse_ts(mandate["created_at"]) <= approved_at
                   <= datetime.now(timezone.utc) + timedelta(seconds=5))
    except (AttributeError, KeyError, TypeError, ValueError):
        time_ok = False
    return time_ok and all(allowance.get(key) == value for key, value in expected.items())


def commit(req: RequestPayment, transaction: Mapping[str, Any],
           now: datetime | None = None) -> CommitPayment:
    """Create the seller ACK only from a stored approval and a matching successful Stripe test result.

    The idempotency key and stable transaction id are the actual PI/charge id. This function has
    no caller-supplied approval map or replay set; identity-bound state and MerchantSim own those checks.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(transaction, Mapping):
        raise PermissionError("no stored approved transaction")
    mandate = transaction.get("mandate")
    deal = transaction.get("deal")
    card = transaction.get("advocate_card")
    if not isinstance(mandate, Mapping) or not isinstance(deal, Mapping) or not isinstance(card, Mapping):
        raise PermissionError("stored purchase evidence is incomplete")
    reason = card.get("call_reason")
    if (not isinstance(reason, Mapping) or set(reason) != {"rule_id", "summary", "source_url"}
            or card.get("rule_id") != reason.get("rule_id")
            or card.get("reason") != reason.get("summary")
            or card.get("source_url") != reason.get("source_url")):
        raise PermissionError("stored review reason is not canonical")
    try:
        valid = (mandate_hash(mandate) == mandate.get("hash") and bool(verify_mandate(mandate, now)))
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid or mandate.get("status") != "approved" or not mandate.get("approval_id"):
        raise PermissionError("mandate is not valid and approved")
    for key in ("deal_id", "buyer_id", "goal_id"):
        if transaction.get(key) != mandate.get(key):
            raise PermissionError("transaction identity does not match mandate")
    deal_id = transaction.get("deal_id")
    if (deal.get("id") != deal_id or deal.get("goal_id") != transaction.get("goal_id")
            or deal.get("need_id") != transaction.get("need_id")
            or deal.get("bid_id") != transaction.get("bid_id")
            or card.get("need_id") != transaction.get("need_id")
            or card.get("bid_id") != transaction.get("bid_id")
            or _cents(deal.get("amount")) != _cents(mandate.get("amount"))
            or deal.get("payee") != mandate.get("payee") or not _authorized(transaction, mandate, now=now)):
        raise PermissionError("stored approval does not match this deal")
    if transaction.get("phase") != "submitted":
        raise PermissionError("transaction is not awaiting payment acknowledgement")
    if (req.reference != mandate.get("hash") or req.recipient != mandate.get("payee")
            or req.description != f"deal {deal_id}" or not isinstance(req.accepted_funds, list)
            or len(req.accepted_funds) != 1):
        raise PermissionError("payment request does not match the approved deal")
    funds = req.accepted_funds[0]
    if (funds.currency != mandate.get("currency") or funds.currency != "USD"
            or getattr(funds, "payment_method", None) != "stripe"
            or _cents(funds.amount) != _cents(mandate.get("amount"))):
        raise PermissionError("payment amount or currency does not match")
    try:
        body = req.model_dump_json().encode("utf-8")
    except Exception:
        raise PermissionError("payment request cannot be bound to its stored settlement") from None
    settlement = transaction.get("settlement")
    expected_message_id = "req:" + hashlib.sha256(transaction["buyer_id"].encode("utf-8") + b"\n" + body).hexdigest()
    expected_settlement = {"message_id": expected_message_id, "request_sha256": hashlib.sha256(body).hexdigest(),
        "mandate_hash": mandate["hash"], "deal_id": transaction["deal_id"], "buyer_id": transaction["buyer_id"],
        "amount_cents": _cents(mandate["amount"]), "currency": mandate["currency"], "payee": mandate["payee"],
        "idempotency_key": "mandate:" + mandate["hash"]}
    if (not isinstance(settlement, Mapping) or set(settlement) != set(expected_settlement) | {"receipt_keyid"}
            or not isinstance(settlement.get("receipt_keyid"), str) or not settlement["receipt_keyid"]
            or settlement["receipt_keyid"] == "not-submitted"
            or any(settlement.get(key) != value for key, value in expected_settlement.items())):
        raise PermissionError("stored settlement does not bind this exact request and mandate")
    result = transaction.get("settlement_result")
    if (not isinstance(result, Mapping) or result.get("status") != "charged"
            or result.get("origin") != "SIM" or result.get("mandate_hash") != mandate.get("hash")
            or not isinstance(result.get("charge_id"), str)
            or not result["charge_id"].startswith(("pi_", "ch_"))
            or transaction.get("payment_ref") != result.get("charge_id")):
        raise PermissionError("a matching successful Stripe test result is required")
    return CommitPayment(funds=funds, recipient=mandate["payee"], transaction_id=result["charge_id"],
                         reference=mandate["hash"], description=req.description)
