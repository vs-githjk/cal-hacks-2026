"""#449 item 4 RT-10: with an sk_test_ key a Stripe error never becomes a SIM stub (a stub would look paid). The charge is
"uncertain", it is never recorded as a payment and never reported as paid, and the note says where to check it."""
from __future__ import annotations

import io
import urllib.error

import pytest

from demo import approval_flow, bridge
from demo.approval_flow import charge_or_stub
from demo.common import Narrator
from demo.run_demo import run_all
from demo.tests.test_bridge import clients, live_parts
from demo.tests.test_build import ALLOW, FakeMarket, kinds, run_build

KEY = {"STRIPE_SECRET_KEY": "sk_test_FAKEKEY1234567890"}


def mandate():
    from pay.mandate import new_mandate
    return new_mandate(deal_id="deal-1", buyer_id="vidyut", amount=12.5, payee="best-buy", origin="MIRROR")


def refuse(code=402):
    def fake(m, key):
        raise urllib.error.HTTPError("https://api.stripe.com/v1/payment_intents", code, "no", {}, io.BytesIO(b'{"error":{"type":"x","code":"y"}}'))
    return fake


@pytest.mark.parametrize("fake", [refuse(), refuse(500), lambda m, k: (_ for _ in ()).throw(TimeoutError("slow")),
                                  lambda m, k: {"id": "pi_test_9", "status": "requires_action", "mode": "Stripe test mode"}])
def test_a_failed_stripe_call_with_a_test_key_is_uncertain_never_a_sim_stub(fake):
    m = mandate()
    charge, note = charge_or_stub(m, KEY, True, fake)
    assert charge["status"] == "uncertain" and charge["mode"] != "SIM stub" and not str(charge.get("id") or "").startswith("ch_sim_")
    assert charge.get("id") is None and charge["idempotency_key"] == "mandate:" + m["hash"]
    assert "uncertain" in note and "Stripe dashboard" in note and charge["idempotency_key"] in note
    assert KEY["STRIPE_SECRET_KEY"] not in note


def test_the_failed_call_is_retried_once_with_the_same_key_and_a_good_retry_is_the_charge():
    calls = []

    def flaky(m, key):
        calls.append((m["hash"], key))
        if len(calls) == 1:
            raise TimeoutError("slow")
        return {"mode": "Stripe test mode", "id": "pi_test_2", "status": "succeeded", "idempotency_key": "mandate:" + m["hash"]}
    m = mandate()
    charge, note = charge_or_stub(m, KEY, True, flaky)
    assert len(calls) == 2 and calls[0] == calls[1] and charge["id"] == "pi_test_2" and charge["status"] == "succeeded" and note == ""


def test_two_failures_make_exactly_two_calls():
    calls = []

    def down(m, key):
        calls.append(1)
        raise TimeoutError("slow")
    assert charge_or_stub(mandate(), KEY, True, down)[0]["status"] == "uncertain" and len(calls) == 2


def test_without_a_test_key_the_labelled_sim_stub_stays():
    charge, note = charge_or_stub(mandate(), {"STRIPE_SECRET_KEY": "sk_live_x"}, True, refuse())
    assert charge["mode"] == "SIM stub" and charge["id"].startswith("ch_sim_") and "SIM stub" in note


# ---- the callers

def uncertain_charger(run):
    gate, _client, _shown, approver = live_parts(run, lambda code: f"{code} approve")
    return gate, approver, bridge.make_charger(gate, KEY, use_stripe=True, stripe_test=refuse(500))


def test_bridge_never_records_or_reports_an_uncertain_charge_as_paid():
    run = run_all(say=Narrator(False))
    gate, approver, charger = uncertain_charger(run)
    log, notes, said = [], [], []
    cl = clients(log)
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), cl, delay=0, say=said.append,
                              sleep=lambda x: None, clock=lambda: 0.0, approver=approver, charger=charger, deal_gate=gate,
                              note=notes.append)
    assert not [r for _, r, _ in log if r == "record_payment"]
    assert any("uncertain" in n and "Stripe dashboard" in n for n in notes)
    assert not any("payment recorded" in (s.say or "") for s in said if s.reducer == "record_payment")
    assert any(o.get("uncertain") for o in outcomes)


def test_make_charger_marks_an_uncertain_charge_and_gives_it_no_payment_ref():
    run = run_all(say=Narrator(False))
    gate, _approver, charger = uncertain_charger(run)
    gate.mandate = mandate()
    out = charger(None)
    assert out["uncertain"] is True and "payment_ref" not in out["args"] and "Stripe dashboard" in out["note"]


def test_build_never_records_or_reports_an_uncertain_charge_as_paid(tmp_path):
    def down(m, key):
        raise TimeoutError("slow")
    r, out, m, _client, notes = run_build(FakeMarket(), tmp_path=tmp_path, allowance=dict(ALLOW), use_stripe=True,
                                          env=KEY, stripe_test=down)
    assert out["status"] == "uncertain" and out["status"] != "paid"
    assert "record_payment" not in kinds(m) and m.payments == {} and r.payments == []
    assert any("uncertain" in n and "Stripe dashboard" in n for n in notes)
    assert out["view"]["approval"]["state"] == "uncertain"
