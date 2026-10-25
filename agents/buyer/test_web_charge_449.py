"""#449 item 4: a web buyer's charge leaves a durable "charging" row first, is read back from the market before it runs,
retries the payment row and tells the operator when it cannot be recorded, and is looked up again (same idempotency key)
after a crash or an unknown Stripe outcome. A stub or a second charge is never the answer."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_runtime_checkout import Context, runtime  # noqa: F401
from test_any_buyer import (BID, _approval_row, _fake_stripe, _orders, _stored_phases, _web_approval)  # noqa: F401

UNRECORDED = "Payment taken in Stripe test mode but not recorded in the market; needs the operator"


@pytest.fixture
def napped(runtime, monkeypatch):  # noqa: F811
    buyer, db = runtime
    slept = []

    async def nap(seconds):
        slept.append(seconds)
    monkeypatch.setattr(buyer, "_sleep", nap)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    return buyer, db, slept


def test_charging_is_saved_before_stripe_is_called(napped, monkeypatch):
    buyer, db, _slept = napped
    from pay import merchant_sim
    events = []
    save = buyer.buyer_state.save_transaction   # _web_approval wraps this again; the spy sees what reaches the store
    monkeypatch.setattr(merchant_sim.StripeTestCharger, "charge",
                        lambda self, **kw: events.append("stripe") or {"id": "pi_test_1", "status": "succeeded"})
    monkeypatch.setattr(buyer.buyer_state, "save_transaction", lambda d, tx: events.append(tx["phase"]) or save(d, tx))
    _web_approval(buyer, monkeypatch)
    assert events.index("charging") < events.index("stripe") < events.index("settled")
    assert _stored_phases(db) == ["settled"]


def test_charging_and_uncertain_are_held_phases_the_store_accepts():
    import importlib
    from buyer import state
    assert {"charging", "uncertain"} <= state._PHASES
    sys.modules.get("buyer_agent") or importlib.import_module("buyer_agent")
    assert "charging" in sys.modules["buyer_agent"].HELD_PHASES


def test_a_payment_row_is_retried_and_the_second_try_is_enough(napped, monkeypatch, caplog):
    buyer, db, slept = napped
    _fake_stripe(monkeypatch)
    buyer.MARKET_REFEREE.record_payment.side_effect = [buyer.MarketBridgeError("down"), {"recorded": True}]
    with caplog.at_level("ERROR", logger="buyer_agent"):
        ctx, _u, _m = _web_approval(buyer, monkeypatch)
    assert buyer.MARKET_REFEREE.record_payment.call_count == 2 and len(slept) == 1
    assert not buyer.MARKET_REFEREE.record_agent_event.called and not caplog.records
    assert len(_orders(buyer, ctx)) == 1 and _stored_phases(db) == ["settled"]


def test_a_payment_row_that_never_records_logs_an_error_tells_the_operator_and_keeps_the_charge(napped, monkeypatch, caplog):
    buyer, db, slept = napped
    calls = _fake_stripe(monkeypatch)
    buyer.MARKET_REFEREE.record_payment.side_effect = buyer.MarketBridgeError("down")
    with caplog.at_level("ERROR", logger="buyer_agent"):
        ctx, _u, _m = _web_approval(buyer, monkeypatch)
    deal_id = buyer.ROUND["transaction"]["deal_id"]
    assert buyer.MARKET_REFEREE.record_payment.call_count == 3 and len(slept) == 2 and len(calls) == 1
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1 and BID in errors[0].getMessage() and deal_id in errors[0].getMessage()
    assert "sk_test_x" not in caplog.text and "pi_test_1" not in caplog.text
    kw = buyer.MARKET_REFEREE.record_agent_event.call_args.kwargs
    assert kw["text"] == UNRECORDED and kw["address"] == buyer.common.address("buyer")
    assert len(_orders(buyer, ctx)) == 1 and _stored_phases(db) == ["settled"]   # the charge stands and the order goes out


@pytest.mark.parametrize("error", [TimeoutError("slow"), ConnectionError("reset"), RuntimeError("http_503: busy"),
                                   ValueError("bad json")])
def test_a_stripe_call_that_may_have_reached_stripe_is_saved_uncertain_not_expired(napped, monkeypatch, error):
    buyer, db, _slept = napped
    _fake_stripe(monkeypatch, error=error)
    ctx, _u, _m = _web_approval(buyer, monkeypatch)
    assert _stored_phases(db) == ["uncertain"] and not _orders(buyer, ctx) and not buyer.MARKET_REFEREE.record_payment.called
    assert buyer.ROUND["phase"] == "done" and not buyer.ROUND.get("pending_hold") and buyer.ROUND.get("transaction") is None


def test_a_declined_card_is_still_expired(napped, monkeypatch):
    buyer, db, _slept = napped
    _fake_stripe(monkeypatch, error=RuntimeError("card_declined: no"))
    _web_approval(buyer, monkeypatch)
    assert _stored_phases(db) == ["expired"]


def _restart(buyer, monkeypatch, db):
    buyer.ROUND.clear()
    monkeypatch.setattr(buyer, "state_db", lambda: db)
    monkeypatch.setattr(buyer, "nonce_store", lambda: Mock(recover_submitted_attempts=lambda: 0))
    buyer.recover_buyer_state()
    assert not buyer.ROUND.get("pending_hold")   # a web charge never wedges the agent


@pytest.mark.parametrize("how", ["uncertain", "charging"])
def test_recovery_resends_the_same_idempotency_key_then_records_and_orders(napped, monkeypatch, how):
    buyer, db, _slept = napped
    first = _fake_stripe(monkeypatch, error=TimeoutError("slow"))
    _web_approval(buyer, monkeypatch)
    mandate = json.loads(db.execute("SELECT payload FROM transactions").fetchone()[0])["mandate"]
    if how == "charging":   # the process died mid-charge: the row is "charging", not "uncertain"
        tx = buyer.buyer_state.load_transaction(db, json.loads(db.execute("SELECT payload FROM transactions").fetchone()[0])["deal_id"], BID)
        tx["phase"] = "charging"
        buyer.buyer_state.save_transaction(db, tx)
    _restart(buyer, monkeypatch, db)
    again = _fake_stripe(monkeypatch)   # Stripe answers the repeated request with the original PaymentIntent
    ctx = Context()
    asyncio.run(buyer.recover_web_charges(ctx))
    assert len(first) == 1 and len(again) == 1
    assert again[0]["idempotency_key"] == first[0]["idempotency_key"] == "mandate:" + mandate["hash"]
    assert buyer.MARKET_REFEREE.record_payment.call_args.kwargs["payment_ref"] == "pi_test_1"
    (to, placed), = _orders(buyer, ctx)
    assert to == mandate["payee"] and json.loads(placed.order_json)["payment_ref"] == "pi_test_1"
    assert _stored_phases(db) == ["settled"]
    asyncio.run(buyer.recover_web_charges(Context()))   # a second pass finds nothing: never a second charge
    assert len(again) == 1


def test_recovery_that_still_cannot_reach_stripe_leaves_it_uncertain_and_logs(napped, monkeypatch, caplog):
    buyer, db, _slept = napped
    _fake_stripe(monkeypatch, error=TimeoutError("slow"))
    _web_approval(buyer, monkeypatch)
    _restart(buyer, monkeypatch, db)
    _fake_stripe(monkeypatch, error=TimeoutError("still slow"))
    ctx = Context()
    with caplog.at_level("WARNING", logger="buyer_agent"):
        asyncio.run(buyer.recover_web_charges(ctx))
    assert _stored_phases(db) == ["uncertain"] and not _orders(buyer, ctx) and not buyer.MARKET_REFEREE.record_payment.called
    assert BID in caplog.text and "sk_test_x" not in caplog.text


# ---- RT-12: read the approval back before charging

@pytest.mark.parametrize("row", [lambda h: None, lambda h: {}, _approval_row(method="typed"), _approval_row(buyer_id="b_other"),
                                 lambda h: {"mandateHash": "0" * 64, "method": "voice_code", "approvedBy": BID},
                                 Mock(side_effect=RuntimeError("down"))])
def test_a_missing_or_mismatched_approval_row_means_no_charge(napped, monkeypatch, caplog, row):
    buyer, db, _slept = napped
    calls = _fake_stripe(monkeypatch)
    with caplog.at_level("WARNING", logger="buyer_agent"):
        ctx, _u, _m = _web_approval(buyer, monkeypatch, approval_row=row)
    assert not calls and not buyer.MARKET_REFEREE.record_payment.called and not _orders(buyer, ctx)
    assert _stored_phases(db) == ["expired"] and BID in caplog.text


def test_the_approval_row_is_read_for_this_mandate_before_the_charge(napped, monkeypatch):
    buyer, db, _slept = napped
    from pay import merchant_sim
    order = []
    monkeypatch.setattr(merchant_sim.StripeTestCharger, "charge",
                        lambda self, **kw: order.append("charge") or {"id": "pi_test_1", "status": "succeeded"})
    _web_approval(buyer, monkeypatch, approval_row=lambda h: order.append(("row", h)) or _approval_row()(h))
    assert [o if o == "charge" else o[0] for o in order] == ["row", "charge"]
    assert order[0][1] == buyer.ROUND["mandate"]["hash"]


# ---- expired mandate: recovery may look a charge up, never create one

def _stuck_uncertain(buyer, monkeypatch, db):
    _fake_stripe(monkeypatch, error=TimeoutError("slow"))
    _web_approval(buyer, monkeypatch)
    _restart(buyer, monkeypatch, db)


def _expire(buyer, monkeypatch):
    later = buyer.business_now() + __import__("datetime").timedelta(hours=1)
    monkeypatch.setattr(buyer, "business_now", lambda: later)


def _lookup(monkeypatch, result=None, error=None):
    from pay import merchant_sim
    seen = []

    def find(self, mandate_hash, **kw):
        seen.append(mandate_hash)
        if error:
            raise error
        return result
    monkeypatch.setattr(merchant_sim.StripeTestCharger, "find_by_mandate_hash", find)
    return seen


def test_expired_mandate_with_no_match_never_charges_and_stays_uncertain_for_the_operator(napped, monkeypatch, caplog):
    # Stripe search can lag about a minute, so "no match" is not proof that no money moved: never forget the row.
    buyer, db, _slept = napped
    _stuck_uncertain(buyer, monkeypatch, db)
    _expire(buyer, monkeypatch)
    charges = _fake_stripe(monkeypatch)
    seen = _lookup(monkeypatch, result=None)
    deal = json.loads(db.execute("SELECT payload FROM transactions").fetchone()[0])["deal_id"]
    ctx = Context()
    with caplog.at_level("WARNING", logger="buyer_agent"):
        asyncio.run(buyer.recover_web_charges(ctx))
    assert not charges and len(seen) == 1 and _stored_phases(db) == ["uncertain"] and not _orders(buyer, ctx)
    assert not buyer.MARKET_REFEREE.record_payment.called
    assert BID in caplog.text and deal in caplog.text and "needs the operator" in caplog.text and "sk_test_x" not in caplog.text


def test_expired_mandate_with_a_match_settles_without_a_new_charge(napped, monkeypatch):
    buyer, db, _slept = napped
    _stuck_uncertain(buyer, monkeypatch, db)
    _expire(buyer, monkeypatch)
    charges = _fake_stripe(monkeypatch)
    _lookup(monkeypatch, result={"id": "pi_found", "status": "succeeded"})
    ctx = Context()
    asyncio.run(buyer.recover_web_charges(ctx))
    assert not charges and _stored_phases(db) == ["settled"] and len(_orders(buyer, ctx)) == 1
    assert buyer.MARKET_REFEREE.record_payment.call_args.kwargs["payment_ref"] == "pi_found"


def test_expired_mandate_match_whose_row_the_market_refuses_keeps_the_charge_and_alerts(napped, monkeypatch, caplog):
    buyer, db, _slept = napped
    _stuck_uncertain(buyer, monkeypatch, db)
    _expire(buyer, monkeypatch)
    _lookup(monkeypatch, result={"id": "pi_found", "status": "succeeded"})
    buyer.MARKET_REFEREE.record_payment.side_effect = buyer.MarketBridgeError("expired")
    with caplog.at_level("ERROR", logger="buyer_agent"):
        asyncio.run(buyer.recover_web_charges(Context()))
    assert _stored_phases(db) == ["settled"] and buyer.MARKET_REFEREE.record_agent_event.called and "needs the operator" in caplog.text


def test_expired_mandate_whose_lookup_fails_stays_uncertain(napped, monkeypatch):
    buyer, db, _slept = napped
    _stuck_uncertain(buyer, monkeypatch, db)
    _expire(buyer, monkeypatch)
    charges = _fake_stripe(monkeypatch)
    _lookup(monkeypatch, error=TimeoutError("search down"))
    asyncio.run(buyer.recover_web_charges(Context()))
    assert not charges and _stored_phases(db) == ["uncertain"]


def test_unexpired_mandate_still_replays_the_same_key_and_does_not_search(napped, monkeypatch):
    buyer, db, _slept = napped
    first = _fake_stripe(monkeypatch, error=TimeoutError("slow"))
    _web_approval(buyer, monkeypatch)
    _restart(buyer, monkeypatch, db)
    seen = _lookup(monkeypatch, result=None)
    again = _fake_stripe(monkeypatch)
    asyncio.run(buyer.recover_web_charges(Context()))
    assert not seen and len(again) == 1 and again[0]["idempotency_key"] == first[0]["idempotency_key"]
    assert _stored_phases(db) == ["settled"]
