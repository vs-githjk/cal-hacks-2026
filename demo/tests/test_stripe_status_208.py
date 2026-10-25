"""#208: a Stripe test answer counts as a test charge only when it succeeded; a market that refuses the payment row
after a Stripe test charge gets one console line naming the PaymentIntent."""
from __future__ import annotations

import pytest

from demo import bridge
from demo.approval_flow import charge_or_stub
from demo.common import Narrator
from demo.run_demo import run_all
from demo.tests.test_bridge import clients, stripe_parts

KEY = {"STRIPE_SECRET_KEY": "sk_test_FAKEKEY1234567890"}


def mandate():
    from pay.mandate import new_mandate
    return new_mandate(deal_id="deal-1", buyer_id="vidyut", amount=12.5, payee="best-buy", origin="MIRROR")


def intent(status):
    def fake(m, key):
        return {"mode": "Stripe test mode", "id": "pi_test_9", "object": "payment_intent", "amount_cents": 1250,
                "currency": "usd", "payment_method": "pm_card_visa (Stripe test card)", "status": status}
    return fake


@pytest.mark.parametrize("status", ["requires_action", "processing", "canceled", None])
def test_a_stripe_answer_that_did_not_succeed_is_uncertain_not_a_stub_and_says_why(status):
    # #449 item 4 RT-10: with a test key a stub would look paid, so the charge is "uncertain" and carries no id
    charge, note = charge_or_stub(mandate(), KEY, True, intent(status))
    assert charge["status"] == "uncertain" and charge["id"] is None and "pi_test_9" in note and "uncertain" in note


def test_a_succeeded_stripe_answer_is_the_test_charge():
    charge, note = charge_or_stub(mandate(), KEY, True, intent("succeeded"))
    assert charge["mode"] == "Stripe test mode" and charge["id"] == "pi_test_9" and note == ""


def test_a_refused_payment_row_after_a_stripe_charge_names_the_payment_intent():
    run = run_all(say=Narrator(False))
    gate, approver, charger, charged, _ = stripe_parts(run, lambda code: f"{code} approve")
    log, notes = [], []
    cl = clients(log, fail={"record_payment": ["record_payment failed (530): mandate already paid"]})
    with pytest.raises(RuntimeError):
        bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), cl, delay=0, say=lambda s: None,
                       sleep=lambda x: None, clock=lambda: 0.0, approver=approver, charger=charger, deal_gate=gate,
                       note=notes.append)
    assert charged and any("pi_test_1" in n and "Stripe test dashboard" in n for n in notes)
