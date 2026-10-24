"""Merchant simulator (Lane C, c5). SIM: our own merchant, not a real store.

Conformance, verified by our merchant simulator: it checks the buyer agent's TAP-style signed request
(pay.tap.verify_request, bound to the mandate hash in the merchant's own approval row), re-runs
pay.mandate.can_charge, spends the mandate once (mark_used), and only then runs a Stripe TEST charge on
Stripe's Visa test card. A replayed request, a replayed mandate or an altered amount is refused with the
reason. Nothing here settles money; Stripe test mode only.

    sim = MerchantSim(keys=keyring(pub), store=NonceStore(path), approvals=lookup, charger=StripeTestCharger())
    out = sim.handle(method="POST", url=url, headers=headers, body=body)
    # {"status": "charged"|"refused"|"charge_failed", "reason", "detail", "charge_id", "mandate_hash", "origin": "SIM"}

`approvals(deal_id)` must return the mandate from the server's own approval row (status and approval_id
are not hashed, so a mandate from the request body proves nothing about approval).
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
import os
import ssl
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable, Mapping, Optional

from pay.mandate import MandateError, can_charge, idempotency_key, mark_used
from pay.replay import NonceStore
from pay.tap import verify_request

STRIPE_API = "https://api.stripe.com/v1/payment_intents"
STRIPE_TEST_CARD = "pm_card_visa"  # Stripe's test PaymentMethod for the Visa test card 4242 4242 4242 4242


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


def _whole_cents(amount: Any) -> Optional[int]:
    """Exact cents, or None when the amount is not a positive whole number of cents (19.995 is refused)."""
    try:
        cents = Decimal(str(amount)) * 100
    except (InvalidOperation, ValueError, TypeError):
        return None
    if isinstance(amount, bool) or not cents.is_finite() or cents <= 0 or cents != cents.to_integral_value():
        return None
    return int(cents)


class MerchantSim:
    def __init__(self, *, keys: Mapping[str, Any], store: NonceStore,
                 approvals: Callable[[str], Optional[Mapping[str, Any]]], charger: Any):
        self.keys, self.store, self.approvals, self.charger = keys, store, approvals, charger

    def handle(self, *, method: str, url: str, headers: Mapping[str, str], body: bytes,
               now: Optional[datetime] = None) -> dict:
        out = {"status": "refused", "reason": None, "detail": "", "charge_id": None, "mandate_hash": None, "origin": "SIM"}

        def refuse(reason, detail=""):
            return {**out, "reason": reason, "detail": detail}

        try:
            req = json.loads(body)
            deal_id, req_mandate = req["deal_id"], req["mandate"]
            req_amount, req_payee = req_mandate["amount"], req_mandate["payee"]
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            return refuse("bad_body", "body must be JSON with deal_id and mandate")
        record = self.approvals(deal_id) if isinstance(deal_id, str) else None
        if not record:
            return refuse("no_approval_record", "the merchant holds no approved mandate for this deal")
        record = dict(record)
        out["mandate_hash"] = record.get("hash")

        verdict = verify_request(method=method, url=url, headers=headers, body=body, keys=self.keys,
                                 store=self.store, now=now, expected_mandate_hash=record.get("hash"))
        if not verdict:
            return refuse(verdict.reason, verdict.detail)
        cents = _whole_cents(record.get("amount"))
        if cents is None:
            return refuse("bad_amount", "amount must be a positive whole number of cents")
        # what the REQUEST asks to pay, checked against the merchant's own row (not the row against itself)
        expect = {"deal_id": deal_id, "amount": req_amount, "payee": req_payee, "store": self.store}
        verdict = can_charge(record, now, **expect)
        if not verdict:
            return refuse(verdict.reason, verdict.detail)
        try:  # spend first: the single INSERT decides a race, so two requests can never both charge
            mark_used(record, now=now, **expect)
        except MandateError as e:
            return refuse(e.reason, e.detail)

        try:
            charge = self.charger.charge(amount_cents=cents, currency=record["currency"],
                                         idempotency_key=idempotency_key(record),
                                         metadata={"deal_id": record["deal_id"], "mandate_hash": record["hash"], "origin": "SIM"})
        except Exception as e:  # mandate stays spent: a new approval is needed, never a silent retry
            return {**out, "status": "charge_failed", "reason": "charge_failed", "detail": str(e)}
        return {**out, "status": "charged", "reason": "ok", "charge_id": charge["id"]}
