"""Buyer-authorized MerchantSim checkout for the local Stripe test-mode path.

The handler requires exact RequestPayment bytes, a signed Shield allow receipt, TAP verification, and a
buyer/deal-bound transaction returned by its private approval lookup. The durable attempt and mandate nonce
are claimed atomically before charger submission. It uses Stripe's Visa test payment method only; this module
is not evidence of a completed Stripe charge unless the result contains Stripe's actual `pi_`/`ch_` id.
"""
from __future__ import annotations

import json
import hashlib
import base64
import re
from decimal import Decimal, InvalidOperation, Overflow
import os
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from pay.approval import approved_voice_record_matches
from pay.mandate import can_charge, idempotency_key, parse_ts, verify as verify_mandate
from pay.replay import NonceStore
from pay.tap import keyring, tap_status, verify_request
from shield.receipt import parse_unique_json, verify_allow_receipt

STRIPE_API = "https://api.stripe.com/v1/payment_intents"
STRIPE_TEST_CARD = "pm_card_visa"  # Stripe's test PaymentMethod for the Visa test card 4242 4242 4242 4242


def receipt_keys_from_env() -> dict:
    """Read the Shield receipt public-key ring; absent or malformed config never enables a bypass."""
    values = [part.strip() for part in os.environ.get("SHIELD_RECEIPT_PUBKEYS", "").split(",") if part.strip()]
    if not values:
        return {}
    try:
        return keyring(*(Ed25519PublicKey.from_public_bytes(base64.b64decode(value, validate=True)) for value in values))
    except (ValueError, TypeError):
        raise ValueError("SHIELD_RECEIPT_PUBKEYS is invalid") from None


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class StripeTestCharger:
    """Stripe PaymentIntent in TEST mode only: refuses any key that is not sk_test_."""

    def __init__(self, secret_key: Optional[str] = None):
        key = secret_key if secret_key is not None else os.environ.get("STRIPE_SECRET_KEY", "")
        if not key.startswith("sk_test_"):
            raise ValueError("Stripe test mode only: STRIPE_SECRET_KEY must start with sk_test_")
        self._key = key

    def charge(self, *, amount_cents: int, currency: str, idempotency_key: str, metadata: Mapping[str, str]) -> dict:
        form = {"amount": str(amount_cents), "currency": currency.lower(), "payment_method": STRIPE_TEST_CARD,
                "automatic_payment_methods[enabled]": "true",
                "automatic_payment_methods[allow_redirects]": "never", "confirm": "true"}
        form.update({f"metadata[{k}]": str(v) for k, v in metadata.items()})
        req = urllib.request.Request(STRIPE_API, data=urllib.parse.urlencode(form).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self._key}", "Idempotency-Key": idempotency_key})
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r:
                pi = json.loads(r.read())
        except urllib.error.HTTPError as e:
            err = json.loads(e.read() or b"{}").get("error", {})
            raise RuntimeError(f"{err.get('code') or err.get('type') or f'http_{e.code}'}: {err.get('message', '')}") from None
        if pi.get("status") != "succeeded":
            raise RuntimeError(f"payment_intent_{pi.get('status')}")
        return {"id": pi["id"], "status": pi["status"]}

    def find_by_mandate_hash(self, mandate_hash: str, *, opener: Callable = urllib.request.urlopen) -> Optional[dict]:
        """#449 item 4 PL-10: a read-only GET search for a succeeded test PaymentIntent whose metadata carries this mandate hash.
        It can never create a charge. None when nothing succeeded matches; any transport or parse failure raises."""
        if not isinstance(mandate_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", mandate_hash):
            raise ValueError("mandate hash must be 64 lowercase hex characters")
        query = urllib.parse.urlencode({"query": f"metadata['mandate_hash']:'{mandate_hash}'", "limit": "10"})
        req = urllib.request.Request(STRIPE_API + "/search?" + query, method="GET", headers={"Authorization": f"Bearer {self._key}"})
        with opener(req, timeout=30, context=_ctx()) as r:
            body = json.loads(r.read())
        for pi in body.get("data") or []:
            if isinstance(pi, dict) and pi.get("status") == "succeeded" and isinstance(pi.get("id"), str):
                return {"id": pi["id"], "status": "succeeded"}
        return None


def _whole_cents(amount: Any) -> Optional[int]:
    """Exact cents, or None when the amount is not a positive whole number of cents (19.995 is refused)."""
    try:
        parsed = Decimal(str(amount))
        if isinstance(amount, bool) or not parsed.is_finite() or parsed <= 0 or parsed.adjusted() > 11:
            return None
        cents = parsed * 100
        if cents <= 0 or cents != cents.to_integral_value():
            return None
        return int(cents)
    except (InvalidOperation, Overflow, OverflowError, ValueError, TypeError):
        return None


class MerchantSim:
    def __init__(self, *, keys: Mapping[str, Any], receipt_keys: Mapping[str, Any], store: NonceStore,
                 approvals: Callable[[str, str], Optional[Mapping[str, Any]]], charger: Any):
        if not isinstance(keys, Mapping) or not keys or not isinstance(receipt_keys, Mapping) or not receipt_keys:
            raise ValueError("TAP and Shield receipt keyrings are required")
        self.keys, self.receipt_keys, self.store, self.approvals, self.charger = keys, receipt_keys, store, approvals, charger

    def handle(self, *, method: str, url: str, headers: Mapping[str, str], body: bytes,
               receipt: Mapping[str, Any], message_id: str, buyer_id: str,
               now: Optional[datetime] = None) -> dict:
        out = {"status": "refused", "reason": None, "detail": "", "charge_id": None, "mandate_hash": None, "origin": "SIM"}

        def refuse(reason, detail=""):
            return {**out, "reason": reason, "detail": detail}

        try:
            req = parse_unique_json(body)
            if not isinstance(req, dict) or set(req) - {"accepted_funds", "recipient", "deadline_seconds", "reference", "description", "metadata"}:
                raise ValueError("bad RequestPayment")
            desc = req["description"]
            if not isinstance(desc, str) or not desc.startswith("deal ") or not desc[5:]:
                raise ValueError("missing deal reference")
            deal_id = desc[5:]
            funds = req["accepted_funds"]
            if (not isinstance(funds, list) or len(funds) != 1 or not isinstance(funds[0], dict)
                    or set(funds[0]) != {"amount", "currency", "payment_method"}):
                raise ValueError("one complete funds entry required")
            if not isinstance(funds[0]["amount"], str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", funds[0]["amount"]):
                raise ValueError("noncanonical payment amount")
            req_cents = _whole_cents(funds[0]["amount"])
            if (req_cents is None or funds[0]["currency"] != "USD" or funds[0]["payment_method"] != "stripe"
                    or not isinstance(req.get("recipient"), str) or not req["recipient"]
                    or not isinstance(req.get("reference"), str) or not req["reference"]
                    or isinstance(req.get("deadline_seconds"), bool) or not isinstance(req.get("deadline_seconds"), int)
                    or req["deadline_seconds"] <= 0):
                raise ValueError("invalid RequestPayment fields")
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            return refuse("bad_request_payment", "body must be one complete Payment Protocol RequestPayment")
        if not isinstance(body, bytes) or not isinstance(buyer_id, str) or not buyer_id or not isinstance(message_id, str):
            return refuse("bad_request_binding")
        expected_message_id = "req:" + hashlib.sha256(buyer_id.encode("utf-8") + b"\n" + body).hexdigest()
        if message_id != expected_message_id:
            return refuse("message_id_mismatch")
        try:
            transaction = self.approvals(deal_id, buyer_id)
        except Exception:
            transaction = None
        if not isinstance(transaction, Mapping):
            return refuse("no_approval_record", "no identity-bound approved transaction exists")
        transaction = dict(transaction)
        record = transaction.get("mandate")
        if not isinstance(record, Mapping) or transaction.get("deal_id") != deal_id or transaction.get("buyer_id") != buyer_id:
            return refuse("transaction_mismatch")
        record = dict(record)
        out["mandate_hash"] = record.get("hash")
        if not self._approved_transaction(transaction, record, now=now):
            return refuse("no_trusted_approval")
        if (req.get("reference") != record.get("hash") or req.get("recipient") != record.get("payee")
                or req_cents != _whole_cents(record.get("amount"))):
            return refuse("request_mismatch")

        receipt_verdict = verify_allow_receipt(receipt, self.receipt_keys, message_id=message_id,
            request_json=body, deal_id=deal_id, mandate_hash=record.get("hash"), amount_cents=req_cents,
            currency=funds[0]["currency"], payee=req["recipient"], now=now)
        if not receipt_verdict:
            return refuse(receipt_verdict.reason)

        verdict = verify_request(method=method, url=url, headers=headers, body=body, keys=self.keys,
                                 store=self.store, now=now, expected_mandate_hash=record.get("hash"), mandate=record)
        out["tap"] = tap_status(verdict)  # the approval card shows tap["label"]
        if not verdict:
            return refuse(verdict.reason, verdict.detail)
        cents = _whole_cents(record.get("amount"))
        if cents is None:
            return refuse("bad_amount", "amount must be a positive whole number of cents")
        verdict = can_charge(record, now, deal_id=deal_id, amount=record["amount"], payee=record["payee"],
                             buyer_id=buyer_id, store=self.store)
        if not verdict:
            return refuse(verdict.reason, verdict.detail)
        receipt_id = receipt.get("receipt_id") if isinstance(receipt, Mapping) else None
        receipt_keyid = receipt.get("keyid") if isinstance(receipt, Mapping) else None
        if not isinstance(receipt_id, str) or not receipt_id or not isinstance(receipt_keyid, str) or not receipt_keyid:
            return refuse("receipt_invalid")
        attempt = {"mandate_hash": record["hash"], "buyer_id": buyer_id, "deal_id": deal_id,
            "request_sha256": hashlib.sha256(body).hexdigest(), "amount_cents": cents,
            "currency": record["currency"], "payee": record["payee"],
            "idempotency_key": idempotency_key(record), "message_id": message_id,
            "receipt_keyid": receipt_keyid, "phase": "submitted"}
        if not self.store.start_payment_attempt(attempt, record["nonce"]):
            return refuse("payment_attempt_replayed")
        return self._submit(out, record, attempt, self.charger)

    @staticmethod
    def _approved_transaction(transaction: Mapping[str, Any], mandate: Mapping[str, Any],
                               now: Optional[datetime] = None, allow_settled: bool = False) -> bool:
        allowed_phases = ("approved", "submitted", "uncertain", "settled") if allow_settled else ("approved", "submitted", "uncertain")
        if (transaction.get("phase") not in allowed_phases
                or mandate.get("status") != "approved" or not isinstance(mandate.get("approval_id"), str)
                or not mandate["approval_id"] or transaction.get("deal_id") != mandate.get("deal_id")
                or transaction.get("buyer_id") != mandate.get("buyer_id")
                or transaction.get("goal_id") != mandate.get("goal_id")):
            return False
        deal, card = transaction.get("deal"), transaction.get("advocate_card")
        if (not isinstance(deal, Mapping) or not isinstance(card, Mapping)
                or deal.get("id") != transaction.get("deal_id") or deal.get("goal_id") != transaction.get("goal_id")
                or deal.get("need_id") != transaction.get("need_id") or deal.get("bid_id") != transaction.get("bid_id")
                or card.get("need_id") != transaction.get("need_id") or card.get("bid_id") != transaction.get("bid_id")
                or card.get("recommendation") not in ("buy", "caution")
                or _whole_cents(deal.get("amount")) != _whole_cents(mandate.get("amount"))
                or deal.get("payee") != mandate.get("payee")):
            return False
        reason = card.get("call_reason")
        if (not isinstance(reason, Mapping) or set(reason) != {"rule_id", "summary", "source_url"}
                or card.get("rule_id") != reason.get("rule_id")
                or card.get("reason") != reason.get("summary")
                or card.get("source_url") != reason.get("source_url")):
            return False
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
            current = now or datetime.now(timezone.utc)
            time_ok = approved_at.tzinfo is not None and parse_ts(mandate["created_at"]) <= approved_at <= current + timedelta(seconds=5)
        except (AttributeError, KeyError, TypeError, ValueError):
            time_ok = False
        # within_allowance is not proof: the amount must fit the limits the record was checked against
        per, period = _whole_cents(allowance.get("per_purchase_limit")), _whole_cents(allowance.get("period_limit"))
        raw_spent, amount = allowance.get("spent_this_period"), _whole_cents(mandate.get("amount"))
        spent = 0 if raw_spent == 0 and not isinstance(raw_spent, bool) else _whole_cents(raw_spent)
        fits = None not in (per, period, spent, amount) and amount <= per and spent + amount <= period
        return time_ok and fits and all(allowance.get(k) == v for k, v in expected.items())

    def _submit(self, out, mandate, attempt, charger):
        metadata = {"deal_id": attempt["deal_id"], "mandate_hash": attempt["mandate_hash"], "origin": "SIM"}
        try:
            charge = charger.charge(amount_cents=attempt["amount_cents"], currency=attempt["currency"],
                idempotency_key=attempt["idempotency_key"], metadata=metadata)
        except Exception:
            self.store.finish_payment_attempt(attempt["mandate_hash"], "uncertain", reason="charger_outcome_unknown")
            return {**out, "status": "uncertain", "reason": "charger_outcome_unknown"}
        if (not isinstance(charge, Mapping) or charge.get("status") != "succeeded"
                or not isinstance(charge.get("id"), str) or not charge["id"].startswith(("pi_", "ch_"))):
            self.store.finish_payment_attempt(attempt["mandate_hash"], "uncertain", reason="charger_outcome_unknown")
            return {**out, "status": "uncertain", "reason": "charger_outcome_unknown"}
        if not self.store.finish_payment_attempt(attempt["mandate_hash"], "charged", charge_id=charge["id"]):
            return {**out, "status": "uncertain", "reason": "attempt_result_not_persisted"}
        return {**out, "status": "charged", "reason": "ok", "charge_id": charge["id"]}

    def reconcile(self, *, deal_id: str, buyer_id: str, mandate_hash: str) -> dict:
        """Trusted local recovery for one stored attempt; never accepts a TAP request or caller charge values."""
        try:
            transaction = self.approvals(deal_id, buyer_id)
        except Exception:
            transaction = None
        if not isinstance(transaction, Mapping) or transaction.get("deal_id") != deal_id or transaction.get("buyer_id") != buyer_id:
            return {"status": "refused", "reason": "no_approval_record", "charge_id": None, "origin": "SIM"}
        mandate = transaction.get("mandate")
        if (not isinstance(mandate, Mapping) or mandate.get("hash") != mandate_hash
                or not self._approved_transaction(transaction, mandate, allow_settled=True)):
            return {"status": "refused", "reason": "transaction_mismatch", "charge_id": None, "origin": "SIM"}
        attempt = self.store.get_payment_attempt(mandate_hash)
        if not attempt or attempt["buyer_id"] != buyer_id or attempt["deal_id"] != deal_id:
            return {"status": "refused", "reason": "no_attempt", "charge_id": None, "origin": "SIM"}
        if attempt["phase"] == "charged":
            return {"status": "charged", "reason": "ok", "charge_id": attempt["charge_id"],
                    "mandate_hash": mandate_hash, "origin": "SIM"}
        if transaction.get("phase") == "settled":
            return {"status": "refused", "reason": "settled_transaction_has_no_charged_attempt",
                    "charge_id": None, "mandate_hash": mandate_hash, "origin": "SIM"}
        if not verify_mandate(mandate):
            return {"status": "uncertain", "reason": "mandate_expired_manual_reconciliation_required",
                    "charge_id": None, "mandate_hash": mandate_hash, "origin": "SIM"}
        claimed = self.store.claim_uncertain_attempt(deal_id, buyer_id, mandate_hash)
        if not claimed:
            return {"status": "refused", "reason": "attempt_not_uncertain", "charge_id": None, "origin": "SIM"}
        if (claimed["amount_cents"] != _whole_cents(mandate.get("amount"))
                or claimed["currency"] != mandate.get("currency") or claimed["payee"] != mandate.get("payee")
                or claimed["idempotency_key"] != idempotency_key(mandate)):
            self.store.finish_payment_attempt(mandate_hash, "refused", reason="attempt_binding_mismatch")
            return {"status": "refused", "reason": "attempt_binding_mismatch", "charge_id": None, "origin": "SIM"}
        out = {"status": "uncertain", "reason": "charger_outcome_unknown", "charge_id": None,
               "mandate_hash": mandate_hash, "origin": "SIM"}
        return self._submit(out, mandate, claimed, self.charger)
