"""The chat purchase makes the MARKET's mandate through the referee, for the winner's own deal and market seller (not a
random deal id and an agent address), then approves and pays against that mandate. Role-enforcing fake market."""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common, market_bridge
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import owner_approval as OA
import state
from market_bridge import MarketBridge, MarketBridgeError
from test_owner_approval import OPTION_NONE
from test_runtime_checkout import (CodeCapturingContext, FakeVoiceClient, _wire_voice, ready_for_requote,  # noqa: F401
                                   runtime)

ROUND_ID, BID_ID, SELLER, LANDED = "round-need-1", "bid-1", "seller-a", 582.0
DEAL = f"deal-{ROUND_ID}:{BID_ID}"


class MarketWorld:
    """The published market's rules for the reducers this path uses (market.ts): create_mandate, issue_approval_code and
    record_approval are referee-only; a mandate exists only for the closed round's rank 1 bid, named by its deal id and paid
    to its market seller id at its landed price; one live mandate per deal; record_approval needs a mandate that exists."""

    def __init__(self, require_code=False, fail_issue=False):
        self.fail_issue = fail_issue
        self.require_code, self.mandates, self.issued, self.approvals, self.calls = require_code, {}, {}, {}, []
        self.goal_id = self.need_id = ""  # the market derives these from the round's need; wire() reads them from the buyer

    def client(self, role):
        world = self

        class Client:
            identity = f"identity-{role}"

            def call(self, reducer, **a):
                world.calls.append((role, reducer, dict(a)))
                if reducer in {"create_mandate", "issue_approval_code", "record_approval"} and role != "referee":
                    raise RuntimeError(f"{reducer} needs referee; caller is {role} vidyut")
                if reducer == "create_mandate":
                    if "goal_id" in a or "need_id" in a:  # the published create_mandate takes neither (#447)
                        raise RuntimeError("create_mandate takes no goal_id or need_id")
                    if a["deal_id"] != DEAL:
                        raise RuntimeError("a mandate needs the rank 1 bid of a closed round")
                    if a["payee"] != SELLER:
                        raise RuntimeError(f"payee must be the winning seller ({SELLER})")
                    if abs(a["amount"] - LANDED) > 1e-9:
                        raise RuntimeError("amount must equal the winning landed price")
                    if any(m["deal_id"] == a["deal_id"] for m in world.mandates.values()):
                        raise RuntimeError("these units are already held for this deal")
                    world.mandates[a["hash"]] = a
                elif reducer == "issue_approval_code":
                    if world.fail_issue:
                        raise RuntimeError("market unreachable")
                    if a["mandate_hash"] not in world.mandates:
                        raise RuntimeError("no mandate with that hash")
                    world.issued[a["mandate_hash"]] = a["code"]
                elif reducer == "record_approval":
                    if a["mandate_hash"] not in world.mandates:
                        raise RuntimeError("no mandate with that hash")
                    if world.require_code and a.get("code") != world.issued.get(a["mandate_hash"]):
                        raise RuntimeError("the code does not match the one issued")
                    world.approvals[a["mandate_hash"]] = a

            def sql(self, query):
                assert role == "buyer" and "my_purchase_status" in query
                h = re.search(r"mandate_hash = '([0-9a-f]+)'", query).group(1)
                m = world.mandates.get(h)
                if not m:
                    return []
                ok = h in world.approvals
                return [{"mandateHash": h, "mandateId": m["id"], "dealId": m["deal_id"], "goalId": world.goal_id,
                         "needId": world.need_id, "amount": m["amount"], "payee": m["payee"],
                         "expiry": "2099-01-01T00:00:00Z", "origin": m["origin"], "withinAllowance": False,
                         "retired": False, "reservationMatches": True, "settled": False,
                         "approvalMethod": {"some": "voice_code"} if ok else OPTION_NONE,
                         "approvedAt": {"some": "2026-10-25T10:00:00Z"} if ok else OPTION_NONE,
                         "paymentRef": OPTION_NONE, "paymentAmount": OPTION_NONE, "paymentMode": OPTION_NONE, "paidAt": OPTION_NONE}]
        return Client()

    def wire(self, buyer, referee_class=MarketBridge):
        self.goal_id, self.need_id = buyer.ROUND["goal"]["id"], buyer.ROUND["need"]["id"]
        buyer.MARKET_BUYER = MarketBridge("buyer", client=self.client("buyer"))
        buyer.MARKET_REFEREE = referee_class("referee", client=self.client("referee"))

    def roles(self, reducer):
        return [role for role, r, _ in self.calls if r == reducer]


@pytest.fixture(autouse=True)
def _clean_codes():
    OA.ISSUED_CODES.clear()
    yield
    OA.ISSUED_CODES.clear()


def _purchase(buyer, world, referee_class=MarketBridge):
    ready_for_requote(buyer)
    world.wire(buyer, referee_class)
    client = FakeVoiceClient()
    _wire_voice(buyer, client, "buyer-runtime-voice-approval-secret")
    ctx = CodeCapturingContext(client)
    asyncio.run(asyncio.wait_for(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])), timeout=10))
    return ctx, client


def test_the_chat_purchase_creates_the_markets_mandate_through_the_referee_for_the_winners_deal(runtime):
    buyer, db = runtime
    world = MarketWorld()
    ctx, client = _purchase(buyer, world)
    tx = buyer.ROUND["transaction"]
    (created,) = [a for role, r, a in world.calls if r == "create_mandate"]
    assert world.roles("create_mandate") == ["referee"]
    assert created["deal_id"] == DEAL and created["payee"] == SELLER and created["amount"] == LANDED  # not deal-<uuid>, not agent1q...
    assert tx["market_mandate"]["hash"] == created["hash"] and tx["market_mandate"]["payee"] == SELLER
    # the local mandate keeps the payment protocol's agent-address payee and its own hash: the phone gate is untouched
    assert tx["mandate"]["payee"].startswith("agent1q") and tx["mandate"]["hash"] != created["hash"]
    assert tx["mandate"]["amount"] == created["amount"] and tx["mandate"]["goal_id"] == world.goal_id
    assert "goal_id" not in created and "need_id" not in created  # the market takes the goal and need from the round, not the call
    assert client.calls == 1 and tx["phase"] == "approved"
    stored = state.load_transaction(db, tx["deal_id"], tx["buyer_id"])
    assert stored["market_mandate"]["hash"] == created["hash"]  # survives a restart
    assert any(isinstance(m, buyer.common.OrderPlaced) for _to, m in ctx.sent)


def test_the_code_is_issued_then_the_referee_records_the_approval_for_the_same_market_mandate_hash(runtime):
    buyer, _db = runtime
    world = MarketWorld()
    _purchase(buyer, world)
    market_hash = buyer.ROUND["transaction"]["market_mandate"]["hash"]
    order = [r for _role, r, _a in world.calls if r in {"create_mandate", "issue_approval_code", "record_approval"}]
    assert order == ["create_mandate", "issue_approval_code", "record_approval"]
    assert world.roles("issue_approval_code") == world.roles("record_approval") == ["referee"]
    assert list(world.issued) == [market_hash] and list(world.approvals) == [market_hash]
    assert world.approvals[market_hash]["approved_by"] == buyer.ROUND["transaction"]["buyer_id"]
    assert world.approvals[market_hash]["code"] == world.issued[market_hash]  # the referee bridge requires the issued code


def test_the_issued_code_travels_with_the_approval_and_the_market_checks_it(runtime):
    buyer, _db = runtime
    world = MarketWorld(require_code=True)
    _purchase(buyer, world)
    market_hash = buyer.ROUND["transaction"]["market_mandate"]["hash"]
    assert world.approvals[market_hash]["code"] == world.issued[market_hash] and buyer.ROUND["transaction"]["phase"] == "approved"


def test_a_chat_purchase_whose_code_cannot_be_put_on_the_market_never_dials(runtime):
    buyer, _db = runtime
    world = MarketWorld(require_code=True, fail_issue=True)
    ctx, client = _purchase(buyer, world)
    assert client.calls == 0  # no call is placed without the code on /buyer
    assert "record_approval" not in [r for _role, r, _a in world.calls] and not world.approvals
    assert not any(isinstance(m, buyer.common.OrderPlaced) for _to, m in ctx.sent)
    assert buyer.ROUND["transaction"]["phase"] != "approved"


def test_one_live_mandate_per_deal_a_second_attempt_never_creates_another(runtime):
    buyer, _db = runtime
    world = MarketWorld()
    _purchase(buyer, world)
    with pytest.raises(MarketBridgeError, match="market_mandate_already_created"):
        buyer._build_pending_transaction(1)
    buyer.ROUND["transaction"] = None  # even with the local record gone, the deal is marked: no blind retry
    with pytest.raises(MarketBridgeError, match="market_mandate_already_created"):
        buyer._create_pending_transaction(1)
    assert world.roles("create_mandate") == ["referee"]


def test_a_failed_create_is_not_retried_for_the_same_deal(runtime):
    buyer, _db = runtime
    world = MarketWorld()
    ready_for_requote(buyer)
    world.wire(buyer)
    buyer.ROUND["bids"][0]["total_landed_price"] = 1.0  # the market refuses: amount is not the landed price
    with pytest.raises(MarketBridgeError):
        buyer._create_pending_transaction(1)
    with pytest.raises(MarketBridgeError, match="market_mandate_already_created"):
        buyer._create_pending_transaction(1)
    assert world.roles("create_mandate") == ["referee"] and not world.mandates


@pytest.mark.parametrize("missing", ["market_seller_id", "wrong_seller"])
def test_a_winner_without_its_market_seller_id_makes_no_mandate_at_all(runtime, missing):
    buyer, _db = runtime
    world = MarketWorld()
    ready_for_requote(buyer)
    world.wire(buyer)
    if missing == "market_seller_id":
        buyer.ROUND["bids"][0].pop("market_seller_id")
    else:
        buyer.ROUND["bids"][0]["market_seller_id"] = "seller-b"  # belongs to seller_2, not this bid's seller_1
    with pytest.raises(MarketBridgeError, match="market_seller_missing"):
        buyer._create_pending_transaction(1)
    assert world.calls == []


def test_the_old_chat_call_shape_is_what_the_live_market_refuses():
    world = MarketWorld()
    buyer = MarketBridge("buyer", client=world.client("buyer"))
    from datetime import datetime, timezone
    from pay.mandate import new_mandate
    now = datetime.now(timezone.utc)
    old = new_mandate(deal_id="deal-" + "0" * 32, buyer_id="vidyut", goal_id="goal-1", amount=LANDED,
                      payee="agent1qseller", within_allowance=False, now=now)
    with pytest.raises(MarketBridgeError):  # buyer identity, random deal id, agent address: every one refused
        buyer.create_mandate(old, need_id="need-1", buyer_id="vidyut", now=now)
    referee = MarketBridge("referee", client=world.client("referee"))
    with pytest.raises(MarketBridgeError):  # even through the referee the old deal id and payee are refused
        referee.create_mandate(old, need_id="need-1", buyer_id="vidyut", now=now)
    assert not world.mandates


def test_payment_record_and_settlement_name_the_market_mandate_not_the_local_one(runtime):
    from uagents_core.contrib.protocols.payment import CompletePayment
    from test_runtime_checkout import Context, charged_transaction
    buyer, db = runtime
    tx, _charger = charged_transaction(buyer, db)
    market = dict(tx["mandate"], hash="d" * 64, id="mandate-market", deal_id=DEAL, payee=SELLER)
    assert market["hash"] != tx["mandate"]["hash"]
    state.save_transaction(db, dict(tx, market_mandate=market))
    buyer.ROUND["transaction"] = dict(tx, market_mandate=market)
    paid = {"approval_method": "voice_code", "retired": False, "reservation_matches": True, "payment_ref": "ch_simulated_runtime",
            "payment_mode": "sim", "payment_amount": 582.0}
    buyer.MARKET_BUYER.purchase_status.side_effect = [
        {"payment_ref": None, "payment_mode": None, "payment_amount": None}, paid]
    buyer.MARKET_BUYER.settle_goal.return_value = {"settled": True}
    asyncio.run(buyer.on_complete(Context(), tx["mandate"]["payee"], CompletePayment(transaction_id="ch_simulated_runtime")))
    assert [c.args[0] for c in buyer.MARKET_BUYER.purchase_status.call_args_list] == ["d" * 64, "d" * 64]
    assert buyer.MARKET_REFEREE.record_payment.call_args.kwargs["mandate_hash"] == "d" * 64
    assert buyer.MARKET_BUYER.settle_goal.call_args.kwargs["mandate_hash"] == "d" * 64
    assert state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["phase"] == "settled"
