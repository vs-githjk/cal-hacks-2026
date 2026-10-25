"""Owner chat: once the referee has recorded the phone approval for the MARKET mandate, the purchase is charged in Stripe
test mode (the TAP/MerchantSim checkout has no keys in production), keyed to the market mandate hash, recorded and settled on
the market, then the owner gets the receipt. Role-enforcing fake market and a fake Stripe, as in test_chat_mandate.py."""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common, market_bridge
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import state
from market_bridge import MarketBridge
from test_chat_mandate import (BID_ID, DEAL, LANDED, ROUND_ID, SELLER, MarketWorld, _clean_codes, _purchase)  # noqa: F401
from test_owner_approval import OPTION_NONE
from test_runtime_checkout import (CodeCapturingContext, FakeVoiceClient, _wire_voice, owner_texts, ready_for_requote,  # noqa: F401
                                   runtime)


class PayWorld(MarketWorld):
    """MarketWorld plus the payment reducers: record_payment is referee-only and writes the payment once, settle_goal is the
    buyer's and needs that payment; the buyer's own row then shows the payment and the settlement."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.payments, self.settled, self.skew_after_approval, self.fail_settle = {}, {}, False, False

    def client(self, role):
        base, world = super().client(role), self

        class Client:
            identity = base.identity

            def call(self, reducer, **a):
                if reducer == "record_payment":
                    world.calls.append((role, reducer, dict(a)))
                    if role != "referee":
                        raise RuntimeError(f"record_payment needs referee; caller is {role} vidyut")
                    if a["mandate_hash"] not in world.approvals:
                        raise RuntimeError("no approved mandate with that hash")
                    if a["mandate_hash"] in world.payments:
                        raise RuntimeError("this mandate is already paid")
                    world.payments[a["mandate_hash"]] = a
                elif reducer == "settle_goal":
                    world.calls.append((role, reducer, dict(a)))
                    if role != "buyer" or world.fail_settle or a["mandate_hash"] not in world.payments:
                        raise RuntimeError("settle_goal refused")
                    world.settled[a["mandate_hash"]] = a
                else:
                    base.call(reducer, **a)

            def sql(self, query):
                rows = base.sql(query)
                h = re.search(r"mandate_hash = '([0-9a-f]+)'", query).group(1)
                if rows and h in world.approvals and world.skew_after_approval:
                    rows[0]["amount"] = rows[0]["amount"] + 1.0  # the market's own row no longer matches the mandate
                if rows and h in world.payments:
                    p = world.payments[h]
                    rows[0].update(paymentRef={"some": p["payment_ref"]}, paymentAmount={"some": p["amount"]},
                                   paymentMode={"some": p["mode"]}, paidAt={"some": "2026-10-25T10:01:00Z"},
                                   settled=h in world.settled)
                return rows
        return Client()


class FakeStripe:
    """Stripe test mode: the same idempotency key returns the same PaymentIntent and never charges twice."""

    def __init__(self, fail=False):
        self.fail, self.requests, self.charged = fail, [], {}

    def charge(self, *, amount_cents, currency, idempotency_key, metadata):
        self.requests.append({"amount_cents": amount_cents, "currency": currency, "key": idempotency_key, "metadata": dict(metadata)})
        if self.fail:
            raise RuntimeError("card_declined: Your card was declined.")
        pi = self.charged.setdefault(idempotency_key, {"id": f"pi_test_{len(self.charged) + 1}", "status": "succeeded"})
        return dict(pi)


@pytest.fixture(autouse=True)
def _no_stripe_env(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)


def _approve_and_pay(buyer, world, stripe=None, transcript="approve"):
    stripe = stripe or FakeStripe()
    buyer.STRIPE_TEST_CHARGER = stripe
    ready_for_requote(buyer)
    world.wire(buyer)
    client = FakeVoiceClient(transcript=transcript)
    _wire_voice(buyer, client, "buyer-runtime-voice-approval-secret")
    ctx = CodeCapturingContext(client)
    asyncio.run(asyncio.wait_for(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])), timeout=10))
    return ctx, stripe


def _market_hash(buyer):
    return buyer.ROUND["transaction"]["market_mandate"]["hash"]


def test_approve_then_charge_then_receipt_in_chat(runtime):
    buyer, db = runtime
    world = PayWorld()
    ctx, stripe = _approve_and_pay(buyer, world)
    tx, h = buyer.ROUND["transaction"], _market_hash(buyer)
    # one Stripe test charge, for the landed price, keyed to the MARKET mandate hash (not the local mandate)
    (req,) = stripe.requests
    assert req["amount_cents"] == 58200 and req["currency"] == "USD" and req["key"] == "mandate:" + h
    assert req["metadata"] == {"deal_id": DEAL, "mandate_hash": h, "origin": "SIM"} and h != tx["mandate"]["hash"]
    # the market: approval first, then the payment recorded by the referee and the goal settled by the buyer
    names = [r for _role, r, _a in world.calls if r in {"record_approval", "record_payment", "settle_goal"}]
    assert names == ["record_approval", "record_payment", "settle_goal"]
    assert world.roles("record_payment") == ["referee"] and world.roles("settle_goal") == ["buyer"]
    assert world.payments[h]["payment_ref"] == "pi_test_1" and world.payments[h]["mode"] == "stripe_test"
    assert world.payments[h]["amount"] == LANDED and h in world.settled
    assert world.settled[h]["deal_id"] == tx["deal_id"] and world.settled[h]["payment_ref"] == "pi_test_1"
    # the durable state and the goal
    stored = state.load_transaction(db, tx["deal_id"], tx["buyer_id"])
    assert stored["phase"] == "settled" and stored["payment_ref"] == "pi_test_1" and stored["order"]["status"] == "paid"
    assert stored["settlement_result"]["mode"] == "stripe_test" and stored["settlement_result"]["mandate_hash"] == h
    assert state.load_goal(db, tx["goal_id"], "owner")["state"] == "DONE"
    assert buyer.ROUND["phase"] == "done" and buyer.ROUND["pending_hold"] is False
    # purchase memory records the settled payment
    (owned,) = state.load_owned_parts(db, "owner")
    assert owned["source"] == "bought_here" and owned["sku_spec"].split()[0] == "gpu"
    # the owner reads the receipt: part, landed price, winning seller
    texts = owner_texts(ctx)
    receipt = texts[-1]
    assert receipt.startswith("Approval recorded on the market.") and "Paid in Stripe test mode. Receipt pi_test_1." in receipt
    assert "Part: " in receipt and "Landed price: $582.00 from Seller." in receipt and "no real money moved" in receipt
    assert texts[0].startswith("Fresh quote saved for deal") and re.search(r"One-time approval code: [a-z]+ [a-z]+", texts[1])
    assert "Approval confirmed for deal" in texts[2] and len(texts) == 4  # quote, code, approval, then ONE receipt message (ASI:One 429s)
    assert any(isinstance(m, buyer.common.OrderPlaced) for _to, m in ctx.sent)


def test_a_denied_call_charges_nothing(runtime):
    buyer, db = runtime
    world = PayWorld()
    ctx, stripe = _approve_and_pay(buyer, world, transcript="no")
    assert stripe.requests == [] and not world.payments and not world.approvals
    assert buyer.ROUND["transaction"]["phase"] != "approved" and "Paid in Stripe" not in " ".join(owner_texts(ctx))
    assert state.load_owned_parts(db, "owner") == []


def test_a_market_readback_mismatch_charges_nothing(runtime):
    buyer, db = runtime
    world = PayWorld()
    world.skew_after_approval = True  # the buyer's own row disagrees with the mandate after the referee recorded
    ctx, stripe = _approve_and_pay(buyer, world)
    assert stripe.requests == [] and not world.payments and not world.settled
    assert buyer.ROUND["phase"] == "uncertain" and buyer.ROUND["pending_hold"] is True
    assert "Paid in Stripe" not in " ".join(owner_texts(ctx)) and state.load_owned_parts(db, "owner") == []


def test_no_recorded_approval_on_the_market_means_no_charge_even_if_called_directly(runtime):
    buyer, db = runtime
    world = PayWorld()
    stripe = FakeStripe()
    buyer.STRIPE_TEST_CHARGER = stripe
    ready_for_requote(buyer)
    world.wire(buyer)
    ctx = CodeCapturingContext(FakeVoiceClient())
    tx = buyer._create_pending_transaction(1)  # pending only: the market has no approval for it
    tx["phase"] = "approved"
    tx["voice_approval"] = {"id": "va-1", "result": "approved", "mandate_hash": tx["mandate"]["hash"], "mandate_id": tx["mandate"]["id"]}
    bid = buyer.ROUND["bids"][0]
    with pytest.raises(PermissionError, match="market_purchase_not_approved"):
        asyncio.run(buyer._pay_chat_purchase(ctx, tx, dict(tx["mandate"]), {"id": tx["deal_id"]}, bid))
    assert stripe.requests == [] and not world.payments


def test_a_retry_never_charges_twice(runtime):
    buyer, db = runtime
    world = PayWorld()
    ctx, stripe = _approve_and_pay(buyer, world)
    tx, h = buyer.ROUND["transaction"], _market_hash(buyer)
    bid, mandate = buyer.ROUND["bids"][0], dict(tx["mandate"])
    # 1) a second call on the settled purchase does nothing
    asyncio.run(buyer._pay_chat_purchase(ctx, tx, mandate, dict(tx["order"]), bid))
    assert len(stripe.requests) == 1
    # 2) even if the local record were lost and the transaction looked approved again, the market's own row shows the payment
    lost = dict(tx, phase="approved", payment_ref=None, settlement_result=None)
    with pytest.raises(PermissionError, match="market_purchase_not_approved"):
        asyncio.run(buyer._pay_chat_purchase(ctx, lost, mandate, dict(tx["order"]), bid))
    assert len(stripe.requests) == 1 and list(world.payments) == [h] and world.roles("record_payment") == ["referee"]
    # 3) and Stripe itself would give the same PaymentIntent for the same key
    assert stripe.charge(amount_cents=58200, currency="USD", idempotency_key="mandate:" + h, metadata={})["id"] == "pi_test_1"
    assert len(stripe.charged) == 1


def test_a_stripe_failure_gives_no_receipt_no_payment_record_and_no_memory(runtime):
    buyer, db = runtime
    world = PayWorld()
    ctx, stripe = _approve_and_pay(buyer, world, stripe=FakeStripe(fail=True))
    assert len(stripe.requests) == 1 and not world.payments and not world.settled
    assert buyer.ROUND["transaction"]["phase"] == "uncertain" and buyer.ROUND["pending_hold"] is True
    assert "no receipt exists" in owner_texts(ctx)[-1] and "Paid in Stripe" not in owner_texts(ctx)[-1]
    assert state.load_owned_parts(db, "owner") == [] and buyer.ROUND["transaction"].get("payment_ref") is None


def test_a_charged_purchase_the_market_cannot_settle_stays_held_and_is_not_remembered(runtime):
    buyer, db = runtime
    world = PayWorld()
    world.fail_settle = True
    ctx, stripe = _approve_and_pay(buyer, world)
    tx, h = buyer.ROUND["transaction"], _market_hash(buyer)
    assert len(stripe.requests) == 1 and tx["payment_ref"] == "pi_test_1" and h in world.payments and not world.settled
    assert buyer.ROUND["phase"] == "uncertain" and buyer.ROUND["pending_hold"] is True and tx["phase"] == "submitted"
    assert "Paid in Stripe test mode. Receipt pi_test_1." in owner_texts(ctx)[-1] and "stays held" in owner_texts(ctx)[-1]
    assert state.load_owned_parts(db, "owner") == []
    assert state.load_goal(db, tx["goal_id"], "owner")["state"] != "DONE"


def _full_keys(buyer):
    buyer.TAP_PRIVATE_KEY, buyer.MERCHANT_SIM, buyer.SHIELD_RECEIPT_KEYS = object(), object(), {"k": "v"}


def test_with_the_tap_keys_configured_the_full_checkout_path_is_used_and_stripe_is_not(runtime):
    buyer, db = runtime
    _full_keys(buyer)
    world = PayWorld()
    ctx, stripe = _approve_and_pay(buyer, world)
    assert stripe.requests == [] and not world.payments
    assert any(isinstance(m, buyer.common.OrderPlaced) for _to, m in ctx.sent)
    assert "The seller was asked to request payment" in owner_texts(ctx)[-1]
    assert buyer.ROUND["transaction"]["phase"] == "approved"


def test_a_half_configured_checkout_does_not_fall_back_to_stripe(runtime):
    buyer, db = runtime
    buyer.TAP_PRIVATE_KEY = object()
    world = PayWorld()
    _ctx, stripe = _approve_and_pay(buyer, world)
    assert stripe.requests == [] and not world.payments and buyer.ROUND["transaction"]["phase"] == "approved"


@pytest.mark.parametrize("key", ["", "sk_live_abc", "rk_test_abc", "rk_live_abc"])
def test_only_an_sk_test_key_ever_charges(runtime, monkeypatch, key):
    buyer, db = runtime
    monkeypatch.setenv("STRIPE_SECRET_KEY", key)
    buyer.STRIPE_TEST_CHARGER = None
    assert buyer._stripe_test_charger() is None and not buyer._stripe_test_checkout_applies()
    world = PayWorld()
    ready_for_requote(buyer)
    world.wire(buyer)
    client = FakeVoiceClient()
    _wire_voice(buyer, client, "buyer-runtime-voice-approval-secret")
    ctx = CodeCapturingContext(client)
    asyncio.run(asyncio.wait_for(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])), timeout=10))
    assert not world.payments and buyer.ROUND["transaction"]["phase"] == "approved"


def test_an_sk_test_key_builds_the_test_charger(runtime, monkeypatch):
    buyer, _db = runtime
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc123")
    buyer.STRIPE_TEST_CHARGER = None
    from pay import merchant_sim
    assert isinstance(buyer._stripe_test_charger(), merchant_sim.StripeTestCharger) and buyer._stripe_test_checkout_applies()


def test_the_amount_must_equal_the_market_mandate_and_the_bid(runtime):
    buyer, db = runtime
    world = PayWorld()
    stripe = FakeStripe()
    buyer.STRIPE_TEST_CHARGER = stripe
    ready_for_requote(buyer)
    world.wire(buyer)
    ctx = CodeCapturingContext(FakeVoiceClient())
    tx = buyer._create_pending_transaction(1)
    tx["phase"] = "approved"
    tx["voice_approval"] = {"id": "va-1", "result": "approved", "mandate_hash": tx["mandate"]["hash"], "mandate_id": tx["mandate"]["id"]}
    bid = dict(buyer.ROUND["bids"][0], total_landed_price=1.0)
    with pytest.raises(PermissionError, match="chat_amount_mismatch"):
        asyncio.run(buyer._pay_chat_purchase(ctx, tx, dict(tx["mandate"]), {"id": tx["deal_id"]}, bid))
    assert stripe.requests == []
