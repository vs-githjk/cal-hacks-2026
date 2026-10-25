"""Runtime checkout acceptance tests with fake provider I/O and real local approval/payment guards."""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from advocate.checks import CALL_SUMMARIES
from buyer import checkout, state
from owner_approval import market_view
from goal import need_from_goal, parse_goal
from payment import payment_request
from pay.approval import ApprovalService, VOICE_CODE_TTL_SECONDS, approved_voice_record_matches
from pay.merchant_sim import MerchantSim
from pay.mandate import new_mandate
from pay.replay import NonceStore
from pay.tap import keyring
from shield.receipt import sign_allow_receipt
from uagents_core.contrib.protocols.payment import CompletePayment, CommitPayment, RejectPayment

NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_BUYER_OWNER_SENDER", "owner")
    fake_agent = Mock()
    for decorator in ("on_message", "on_interval", "on_rest_post", "on_rest_get", "on_event"):
        getattr(fake_agent, decorator).side_effect = lambda *a, **k: lambda fn: fn
    path_exists = Path.exists
    with patch("uagents.Agent", return_value=fake_agent), patch.object(
            Path, "exists", lambda path: False if path.name == ".env" else path_exists(path)):
        buyer = importlib.import_module("buyer_agent")
    fake_agent.address = buyer.common.address("buyer")
    monkeypatch.setattr(buyer, "ALLOWANCE", 0)
    monkeypatch.setattr(buyer, "business_now", lambda: NOW)
    monkeypatch.setattr(buyer.crs, "eligible", lambda _supplier, check, _now: bool(check and check.get("eligible")))
    monkeypatch.setattr(buyer, "blocked_reasons", lambda *_args, **_kwargs: None)
    for name, value in {
        "ROUND": {}, "WEB_OUTBOX": [], "GOAL_ATTEMPTS": {},
        "APPROVAL_SERVICE": None, "APPROVAL_CALL_CLIENT": None, "MERCHANT_SIM": None,
        "TAP_PRIVATE_KEY": None, "SHIELD_RECEIPT_KEYS": None, "SHIELD_PAYMENT_SCREEN": None,
        "MARKET_BUYER": Mock(), "MARKET_REFEREE": Mock(), "STATE_DB": None, "NONCE_STORE": None,
    }.items():
        if hasattr(buyer, name):
            monkeypatch.setattr(buyer, name, value)
    db_path = tmp_path / ".state" / "state.sqlite3"
    monkeypatch.setattr(state, "DEFAULT_DB_PATH", db_path)
    db = state.open_state(db_path)
    monkeypatch.setattr(buyer, "STATE_DB", db)
    yield buyer, db
    db.close()


class Context:
    def __init__(self):
        self.logger = Mock()
        self.sent = []
        self.session = uuid4()

    async def send(self, to, message):
        self.sent.append((to, message))


def reviewed_card(need_id="need-1", bid_id="bid-1"):
    reason = CALL_SUMMARIES["advocate.ok"]
    source = "https://example.test/advocate"
    return {"need_id": need_id, "bid_id": bid_id, "warnings": [], "claim_checks": [],
            "recommendation": "buy", "wait_until": "",
            "call_reason": {"rule_id": "advocate.ok", "summary": reason, "source_url": source},
            "rule_id": "advocate.ok", "reason": reason, "source_url": source}


def _wire_market_mandates(buyer):
    """The market as it behaves: create_mandate only through the REFEREE (the buyer identity is refused), and the buyer's own
    purchase row then shows that pending mandate (market.ts requireRole create_mandate, ['referee'])."""
    created = {}

    def create(mandate, **_kwargs):
        created[mandate["hash"]] = mandate
        return {"mandate_hash": mandate["hash"]}

    def status(mandate_hash):
        m = created[mandate_hash]
        return {"mandate_hash": mandate_hash, "amount": m["amount"], "payee": m["payee"], "reservation_matches": True,
                "within_allowance": False, "retired": False, "settled": False, "approval_method": None, "approved_at": None}

    def refused(*_a, **_k):
        raise buyer.MarketBridgeError("market_reducer_failed")  # create_mandate needs referee; caller is buyer
    buyer.MARKET_REFEREE.create_mandate.side_effect = create
    buyer.MARKET_BUYER.purchase_status.side_effect = status
    buyer.MARKET_BUYER.create_mandate.side_effect = refused


def _readbacks(buyer, row_fn):
    """The first buyer-side read is create_mandate's own readback (the pending row from _wire_market_mandates); every later
    read is what the test wants the market to show."""
    pending, reads = buyer.MARKET_BUYER.purchase_status.side_effect, []

    def status(mandate_hash):
        reads.append(mandate_hash)
        return pending(mandate_hash) if len(reads) == 1 else row_fn(mandate_hash)
    buyer.MARKET_BUYER.purchase_status.side_effect = status


def ready_for_requote(buyer):
    goal, _ = parse_goal("a new GPU under $800 by Friday", "owner", now=NOW)
    state.save_goal(buyer.STATE_DB, goal)
    need = need_from_goal(goal)
    need.update(id="need-1", buyer_id="vidyut")
    raw_line = {"sku_spec": need["items"][0]["sku_spec"], "unit_price": 582.0, "quantity": 1,
                "condition": "new", "variant": "retail", "listing_id": "listing-1",
                "listing_url": "https://seller.example/listing-1", "shipping": 0.0}
    line_hash = hashlib.sha256(json.dumps(raw_line, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    bid = {"id": "bid-1", "supplier_id": "seller_1", "total_landed_price": 582.0,
           "persona": "Seller", "source": "SIM", "origin": "SIM", "need_id": need["id"], "market_seller_id": "seller-a",
           "lines": [raw_line], "candidate_binding_hash": "c" * 64, "market_binding_hash": "c" * 64,
           "quoted_at": NOW.isoformat(), "expires_at": (NOW + timedelta(seconds=600)).isoformat(),
           "listing_hash": line_hash}
    _wire_market_mandates(buyer)
    buyer.ROUND.update(owner="owner", owner_context=None, phase="requote", pick=1,
        deadline=NOW.timestamp() + 60, quoted_at=NOW.timestamp(), need=need, goal=goal,
        bids=[bid], cards={"bid-1": reviewed_card()}, reviewed=True,
        seller_checks={"seller_1": {"eligible": True}}, personas={}, owned=[], attempts=0,
        last_sent={}, market_buyer_id="vidyut", market_round_id="round-need-1", order=None, transaction=None,
        original_offer=dict(bid), candidate_hashes={"bid-1": "c" * 64},
        market_winner={"total_landed_price": bid["total_landed_price"]})


def test_requote_persists_pending_approval_without_ordering(runtime):
    buyer, db = runtime
    ready_for_requote(buyer)
    ctx = Context()

    asyncio.run(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])))

    rows = db.execute("SELECT phase, payload FROM transactions").fetchall()
    assert len(rows) == 1
    phase, payload = rows[0]
    transaction = json.loads(payload)
    assert phase == transaction["phase"] == "pending_approval"
    assert transaction["voice_approval"] is None
    assert not buyer.ROUND.get("order")
    assert buyer.ROUND["goal"]["state"] != "DONE"
    assert not any(isinstance(message, buyer.common.OrderPlaced) for _, message in ctx.sent)


def test_missing_owner_pin_prevents_creating_a_pending_purchase(runtime, monkeypatch):
    buyer, db = runtime
    monkeypatch.delenv("MARKET_BUYER_OWNER_SENDER")
    ready_for_requote(buyer)
    ctx = Context()

    asyncio.run(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])))

    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert not buyer.ROUND.get("transaction")
    assert not buyer.MARKET_REFEREE.create_mandate.called and not buyer.MARKET_BUYER.create_mandate.called
    assert not any(isinstance(message, buyer.common.OrderPlaced) for _, message in ctx.sent)


def test_raw_multi_alternative_bid_survives_market_projection_and_requote(runtime):
    from sellers.policy import make_bid

    buyer, db = runtime
    goal, _ = parse_goal("a new RTX 4070 SUPER GPU under $800 by Friday", "owner", now=NOW)
    need = need_from_goal(goal)
    need.update(id="need-1", buyer_id="vidyut", source="sim")
    sku = need["items"][0]["sku_spec"]
    second_sku = "psu 750w"
    need["items"].append({**need["items"][0], "sku_spec": second_sku})
    listings = {
        sku: {"price": 599.99, "floor": 550.0, "condition": "new", "page_condition": "new",
              "variant": "retail", "listing_url": "https://seller.example/gpu", "attrs": {"chipset": sku}},
        second_sku: {"price": 99.99, "floor": 80.0, "condition": "new", "page_condition": "new",
                     "variant": "retail", "listing_url": "https://seller.example/psu", "attrs": {"wattage": 750}},
    }
    raw = make_bid(need, {"id": "seller_1", "name": "Seller One", "discount": 0.0,
        "shipping": 0.0, "perks": [], "claims": [], "listings": listings,
        "mirror_listings": [], "mirror_inputs": {}}, now=NOW)
    assert raw and len(raw["lines"]) == 2

    bid_id = raw["id"]
    candidate_hash = "a" * 64
    rows, metadata = [], []
    for index, line in enumerate(raw["lines"]):
        line_hash = hashlib.sha256(json.dumps(line, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        rows.append({"line_index": index, "sku_spec": line["sku_spec"],
            "unit_price": line["unit_price"], "quantity": line["quantity"], "shipping": line["shipping"]})
        metadata.append({"lineIndex": index, "listingId": line["listing_id"], "listingHash": line_hash,
            "source": line["source"], "snapshotId": line.get("snapshot_id", ""),
            "provenance": {}, "attrs": line["attrs"]})
    referee, market = Mock(), Mock()
    referee.round_status.return_value = {"state": "closed"}
    chosen = raw["lines"]
    chosen_hash = metadata[0]["listingHash"]
    # #447: the published market's winner row has no line index, listing or binding hash: the buyer binds it locally
    market.authoritative_winner.return_value = {"bid_id": bid_id, "seller_id": "seller-a",
        "landed": raw["total_landed_price"],
        "lines": [{"sku_spec": line["sku_spec"], "unit_price": line["unit_price"], "quantity": line["quantity"],
                   "qty_available": line["quantity"], "offered_condition": "", "offered_spec": ""} for line in chosen]}
    buyer.MARKET_BUYER, buyer.MARKET_REFEREE = market, referee
    _wire_market_mandates(buyer)
    state.save_goal(db, goal)
    buyer.ROUND.update(owner="owner", owner_context=None, phase="market_review_wait", pick=1,
        deadline=NOW.timestamp() + 60, quoted_at=NOW.timestamp(), need=need, goal=goal,
        bids=[raw], received_bids={bid_id: raw}, review_bids=[], cards={bid_id: reviewed_card("need-1", bid_id)},
        reviewed=True, seller_checks={"seller_1": {"eligible": True}}, personas={bid_id: "Seller One"},
        owned=[], attempts=0, last_sent={}, market_buyer_id="vidyut", market_round_id="round-need-1", round_token="round-token",
        candidate_hashes={}, order=None, transaction=None)

    buyer.ROUND["review_bids"] = buyer._review_candidates()
    asyncio.run(buyer._finish_market_round(Context()))
    projected = buyer.ROUND["bids"][0]
    assert len(projected["lines"]) == 2
    assert buyer.ROUND["original_offer"] == raw
    assert projected["lines"][0].get("listing_hash") == chosen_hash
    assert projected["market_seller_id"] == "seller-a"  # the web mandate pays the market's own seller id (PL-1)

    buyer.ROUND.update(phase="requote", pick=1, deadline=NOW.timestamp() + 60,
                       quoted_at=NOW.timestamp())
    requote_ctx = Context()
    asyncio.run(buyer.on_requote(requote_ctx, dict(raw)))
    assert buyer.ROUND.get("transaction") and buyer.ROUND["transaction"]["phase"] == "pending_approval", repr(
        (buyer.ROUND.get("phase"), buyer.MARKET_REFEREE.create_mandate.call_args_list,
         buyer.ROUND.get("original_offer") == raw, buyer.ROUND.get("candidate_hashes"),
         buyer.ROUND.get("market_winner"), requote_ctx.logger.warning.call_args_list,
         [message.text() for _, message in requote_ctx.sent if hasattr(message, "text")]))
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


class FakeVoiceClient:
    """Stands in for the Cartesia client: the 'owner' speaks the code shown in chat, then says approve."""
    approval_call_to = "+14155550123"

    def __init__(self, transcript="approve"):
        self.transcript = transcript
        self.code = None
        self.calls = 0

    def create_call(self, _to, _variables):
        self.calls += 1
        return "call-runtime-test"

    def get_call(self, call_id):
        return {"id": call_id, "status": "completed", "end_reason": "agent_hangup",
                "start_time": (NOW + timedelta(seconds=1)).isoformat(), "transcript": [
                    {"role": "user", "text": f"{self.code} {self.transcript}", "start_timestamp": 1.0}]}


class CodeCapturingContext(Context):
    """Records the one-time code the buyer posts to the owner chat so the fake call can speak it."""

    def __init__(self, client):
        super().__init__()
        self.client = client

    async def send(self, to, message):
        self.sent.append((to, message))
        if hasattr(message, "text"):
            match = re.search(r"One-time approval code: ([a-z]+ [a-z]+)", message.text())
            if match:
                self.client.code = match.group(1)


def owner_texts(ctx):
    return [message.text() for _to, message in ctx.sent if hasattr(message, "text")]


def _wire_voice(buyer, client, secret):
    buyer.NONCE_STORE = NonceStore(str(state.DEFAULT_DB_PATH))
    buyer.APPROVAL_SERVICE = ApprovalService(secret, store=buyer.NONCE_STORE, code_ttl_seconds=VOICE_CODE_TTL_SECONDS)
    buyer.APPROVAL_CALL_CLIENT = client


def _market_shows_the_approval(buyer):
    """What the real market's buyer-private row shows once the referee has recorded the approval for this mandate."""
    def status(mandate_hash):
        m = market_view(buyer.ROUND["transaction"])
        return {"approval_method": "voice_code", "approved_at": NOW.isoformat(), "mandate_hash": mandate_hash,
                "amount": m["amount"], "payee": m["payee"], "retired": False}
    _readbacks(buyer, status)


def test_requote_starts_the_phone_call_on_its_own_and_only_once(runtime):
    buyer, db = runtime
    ready_for_requote(buyer)
    buyer.MARKET_REFEREE.record_approval.return_value = {"mandate_hash": "x", "approval_method": "voice_code"}
    _market_shows_the_approval(buyer)
    client = FakeVoiceClient()
    _wire_voice(buyer, client, "buyer-runtime-voice-approval-secret")
    owner_ctx = CodeCapturingContext(client)
    asyncio.run(asyncio.wait_for(buyer.on_requote(owner_ctx, dict(buyer.ROUND["bids"][0])), timeout=10))

    approved = state.load_transaction(db, buyer.ROUND["transaction"]["deal_id"], buyer.ROUND["transaction"]["buyer_id"])
    assert client.calls == 1
    assert approved["phase"] == "approved"
    assert approved["voice_approval"]["channel"] == "phone"
    assert approved["order"]["id"] == approved["deal_id"]
    assert approved_voice_record_matches(approved["voice_approval"], approved["mandate"], now=NOW + timedelta(seconds=2))
    assert approved["mandate"]["status"] == "approved"
    # the REFEREE relays the call result (market.ts record_approval is referee-only); the buyer only re-reads it
    assert buyer.MARKET_REFEREE.record_approval.call_args.kwargs["method"] == "voice_code"
    assert buyer.MARKET_REFEREE.record_approval.call_args.kwargs["approved_by"] == approved["buyer_id"]
    assert not buyer.MARKET_BUYER.record_approval.called and buyer.MARKET_BUYER.purchase_status.called
    assert any(isinstance(message, buyer.common.OrderPlaced) for _, message in owner_ctx.sent)
    texts = owner_texts(owner_ctx)
    assert any("Calling you now to approve" in text for text in texts)
    assert any("One-time approval code:" in text and "Calling your phone now" in text for text in texts)
    assert not any("APPROVE" in text for text in texts)

    # a repeat of the same offer, or any owner text, never starts a second call or a typed approval
    asyncio.run(buyer.on_requote(owner_ctx, dict(buyer.ROUND["bids"][0])))
    for text in ("APPROVE 1", "approve", "yes"):
        asyncio.run(buyer.on_chat(owner_ctx, "owner", buyer.ChatMessage(content=[buyer.TextContent(text=text)])))
    assert client.calls == 1 and buyer.MARKET_REFEREE.record_approval.call_count == 1


@pytest.mark.parametrize("failure", ["referee_refuses", "market_row_missing", "market_row_for_another_amount"])
def test_owner_chat_never_orders_unless_the_referee_recorded_this_exact_mandate(runtime, failure):
    buyer, db = runtime
    ready_for_requote(buyer)
    if failure == "referee_refuses":
        buyer.MARKET_REFEREE.record_approval.side_effect = buyer.MarketBridgeError("market_reducer_failed")
        _readbacks(buyer, lambda h: {"approval_method": None, "approved_at": None})
    else:
        buyer.MARKET_REFEREE.record_approval.return_value = {"approval_method": "voice_code"}

        def status(mandate_hash):
            m = market_view(buyer.ROUND["transaction"])
            row = {"approval_method": "voice_code", "approved_at": NOW.isoformat(), "mandate_hash": mandate_hash,
                   "amount": m["amount"], "payee": m["payee"], "retired": False}
            return {**row, "approval_method": None, "approved_at": None} if failure == "market_row_missing" else {**row, "amount": 1.0}
        _readbacks(buyer, status)
    client = FakeVoiceClient()
    _wire_voice(buyer, client, "buyer-runtime-voice-approval-secret")
    owner_ctx = CodeCapturingContext(client)
    asyncio.run(asyncio.wait_for(buyer.on_requote(owner_ctx, dict(buyer.ROUND["bids"][0])), timeout=10))
    assert client.calls == 1  # the call happened and was approved, but the market never recorded it
    assert not any(isinstance(message, buyer.common.OrderPlaced) for _, message in owner_ctx.sent)
    held = state.load_transaction(db, buyer.ROUND["transaction"]["deal_id"], buyer.ROUND["transaction"]["buyer_id"])
    assert held["phase"] == "uncertain" and buyer.ROUND["pending_hold"] is True and not buyer.ROUND.get("order")
    assert any("remains held" in text for text in owner_texts(owner_ctx))


def test_failed_call_says_nothing_was_paid_and_a_typed_code_never_approves(runtime):
    """A call that does not connect must not leave a typed route: the code is only ever spoken."""
    buyer, db = runtime
    ready_for_requote(buyer)

    class NoAnswerClient(FakeVoiceClient):
        def get_call(self, call_id):
            return {"id": call_id, "status": "failed", "end_reason": "dial_no_answer", "transcript": []}

    client = NoAnswerClient()
    _wire_voice(buyer, client, "buyer-runtime-no-typed-secret")
    owner_ctx = CodeCapturingContext(client)
    asyncio.run(asyncio.wait_for(buyer.on_requote(owner_ctx, dict(buyer.ROUND["bids"][0])), timeout=10))
    transaction = buyer.ROUND["transaction"]
    for text in ("APPROVE 1", client.code):  # typing the code afterwards is only ordinary chat text
        asyncio.run(buyer.on_chat(owner_ctx, "owner", buyer.ChatMessage(content=[buyer.TextContent(text=text)])))
    held = state.load_transaction(db, transaction["deal_id"], transaction["buyer_id"])
    assert held["phase"] in {"paused", "denied"} and held["voice_approval"] is None and held["order"] is None
    assert client.calls == 1
    assert not any(isinstance(message, buyer.common.OrderPlaced) for _, message in owner_ctx.sent)
    assert not buyer.MARKET_REFEREE.record_approval.called
    assert any("Nothing was paid" in text for text in owner_texts(owner_ctx))


def test_unconfigured_approval_call_fails_closed_with_a_clear_message(runtime, monkeypatch):
    buyer, db = runtime
    for name in ("CARTESIA_API_KEY", "CARTESIA_AGENT_ID", "APPROVAL_CALL_TO", "CARTESIA_PHONE_NUMBER_ID"):
        monkeypatch.delenv(name, raising=False)
    ready_for_requote(buyer)
    _wire_voice(buyer, None, "buyer-runtime-unconfigured-secret")
    owner_ctx = Context()
    asyncio.run(buyer.on_requote(owner_ctx, dict(buyer.ROUND["bids"][0])))
    transaction = buyer.ROUND["transaction"]
    for text in ("APPROVE 1", "yes", "approve 1"):
        asyncio.run(buyer.on_chat(owner_ctx, "owner", buyer.ChatMessage(content=[buyer.TextContent(text=text)])))

    unchanged = state.load_transaction(db, transaction["deal_id"], transaction["buyer_id"])
    assert unchanged["phase"] == "pending_approval" and unchanged["voice_approval"] is None
    assert unchanged["order"] is None and unchanged["mandate"]["status"] == "pending"
    assert not any(isinstance(message, buyer.common.OrderPlaced) for _, message in owner_ctx.sent)
    assert not buyer.MARKET_REFEREE.record_approval.called
    texts = owner_texts(owner_ctx)
    assert any("Phone approval is not set up" in text and "Nothing was approved" in text
               and "nothing was paid" in text for text in texts)
    assert not any("One-time approval code:" in text for text in texts)


def submitted_transaction(buyer):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    deal_id, buyer_id, goal_id, need_id, bid_id = "deal-restart", "vidyut", "goal-restart", "need-1", "bid-1"
    payee = buyer.common.address("seller_1")
    order = {"id": deal_id, "need_id": need_id, "bid_id": bid_id, "amount": 582.0,
             "approved_by": "owner", "approval_id": "approval-1", "limit_checked": True,
             "idempotency_key": "order-key-1", "payment_ref": "", "status": "approved"}
    mandate = new_mandate(deal_id=deal_id, buyer_id=buyer_id, goal_id=goal_id, amount=582.0,
                          payee=payee, within_allowance=False, now=now)
    mandate.update(status="approved", approval_id="approval-1")
    deal = {"id": deal_id, "goal_id": goal_id, "need_id": need_id, "bid_id": bid_id,
            "amount": 582.0, "payee": payee, "owner_sender": "old-owner"}
    return {"deal_id": deal_id, "buyer_id": buyer_id, "goal_id": goal_id, "need_id": need_id,
            "bid_id": bid_id, "phase": "submitted", "deal": deal, "order": order,
            "advocate_card": reviewed_card(), "mandate": mandate, "voice_approval": None,
            "allowance_authorization": None, "settlement": None, "settlement_result": None,
            "payment_ref": None, "mode": "SIM"}


def test_buyer_startup_keeps_uncertain_checkout_locked_for_a_new_goal(runtime, monkeypatch):
    buyer, db = runtime
    monkeypatch.setenv("MARKET_BUYER_OWNER_SENDER", "old-owner")
    transaction = submitted_transaction(buyer)
    state.save_goal(db, {"id": transaction["goal_id"], "buyer_id": "old-owner",
        "type": "budget_cap", "items": [], "cap": 800, "deadline": "2099-01-01T00:00:00Z",
        "state": "HOLD_FOR_CALL", "reserved_amount": 582, "po_number": transaction["deal_id"],
        "created_at": datetime.now(timezone.utc).isoformat()})
    state.save_transaction(db, transaction)
    store = NonceStore(str(state.DEFAULT_DB_PATH))
    attempt = {"mandate_hash": transaction["mandate"]["hash"], "buyer_id": transaction["buyer_id"],
        "deal_id": transaction["deal_id"], "request_sha256": "b" * 64, "amount_cents": 58200,
        "currency": "USD", "payee": transaction["mandate"]["payee"],
        "idempotency_key": "mandate:" + transaction["mandate"]["hash"], "message_id": "req:restart",
        "receipt_keyid": "receipt-key", "phase": "submitted"}
    assert store.start_payment_attempt(attempt, transaction["mandate"]["nonce"])
    buyer.NONCE_STORE = store
    buyer.MERCHANT_SIM = Mock()
    ctx = Context()

    asyncio.run(buyer.buyer_startup(ctx))
    before = buyer.MARKET_BUYER.post_goal.call_count
    asyncio.run(buyer.handle_text(ctx, "new-owner", "a new GPU under $800 by Friday"))

    recovered = state.load_transaction(db, transaction["deal_id"], transaction["buyer_id"])
    saved_attempt = store.get_payment_attempt(transaction["mandate"]["hash"])
    assert recovered["phase"] == "uncertain"
    assert saved_attempt["phase"] == "uncertain"
    assert buyer.ROUND.get("pending_hold") is True
    assert buyer.MARKET_BUYER.post_goal.call_count == before
    buyer.MERCHANT_SIM.handle.assert_not_called()


def approved_transaction(buyer, db):
    owner, buyer_id, goal_id, need_id, bid_id = "owner", "vidyut", "goal-pay-1", "need-1", "bid-1"
    payee = buyer.common.address("seller_1")
    mandate = new_mandate(deal_id="deal-pay-1", buyer_id=buyer_id, goal_id=goal_id, amount=582.0,
                          payee=payee, within_allowance=False, now=NOW)
    store = NonceStore(str(state.DEFAULT_DB_PATH))
    service = ApprovalService("runtime-checkout-approval-secret", store=store,
                              code_ttl_seconds=VOICE_CODE_TTL_SECONDS)
    session, code = service.issue(mandate, channel="phone", now=NOW)
    session.start_call(now=NOW)
    session.begin_listening(now=NOW)
    session.recording_ref = "cartesia:ac_test"  # call evidence, as voice_cartesia records it
    decision = session.approve(code + " approve", now=NOW + timedelta(seconds=1))
    assert decision.approved and decision.record
    order = {"id": mandate["deal_id"], "need_id": need_id, "bid_id": bid_id,
             "amount": mandate["amount"], "approved_by": "owner", "approval_id": decision.record["id"],
             "limit_checked": True, "idempotency_key": "order-key-pay-1", "payment_ref": "", "status": "approved"}
    tx = {"deal_id": mandate["deal_id"], "buyer_id": buyer_id, "goal_id": goal_id,
          "need_id": need_id, "bid_id": bid_id, "phase": "approved",
          "deal": {"id": mandate["deal_id"], "goal_id": goal_id, "need_id": need_id,
                   "bid_id": bid_id, "amount": mandate["amount"], "payee": payee, "owner_sender": owner},
          "order": order, "advocate_card": reviewed_card(need_id, bid_id), "mandate": mandate,
          "voice_approval": decision.record, "allowance_authorization": None, "settlement": None,
          "settlement_result": None, "payment_ref": None, "mode": "SIM"}
    state.save_transaction(db, tx)
    state.save_goal(db, {"id": goal_id, "buyer_id": owner, "type": "budget_cap", "items": [],
        "cap": 800, "deadline": "2099-01-01T00:00:00Z", "state": "HOLD_FOR_CALL",
        "reserved_amount": 582, "po_number": "", "created_at": NOW.isoformat()})
    buyer.NONCE_STORE = store
    buyer.MARKET_BUYER.purchase_status.return_value = {
        "approval_method": "voice_code", "retired": False, "reservation_matches": True,
        "payment_ref": None, "expiry": tx["mandate"]["expires_at"], "origin": "SIM"}
    buyer.ROUND.update(owner=owner, owner_context=None, goal=state.load_goal(db, goal_id, owner),
                       order=order, mandate=mandate, transaction=tx, pending_hold=True, phase="submitted")
    return tx, service


def payment_material(buyer, tx, now=NOW):
    request = payment_request(tx["mandate"], tx["mandate"]["payee"])
    body = request.model_dump_json().encode("utf-8")
    message_id = "req:" + hashlib.sha256(tx["buyer_id"].encode() + b"\n" + body).hexdigest()
    receipt_key = Ed25519PrivateKey.generate()
    receipt = sign_allow_receipt(private_key=receipt_key, message_id=message_id, request_json=body,
        deal_id=tx["deal_id"], mandate_hash=tx["mandate"]["hash"], amount_cents=58200,
        currency="USD", payee=tx["mandate"]["payee"], now=now)
    return request, body, message_id, receipt, receipt_key


class FakeCharger:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.calls = []

    def charge(self, **kwargs):
        self.calls.append(kwargs)
        self.events.append("charge")
        return {"id": "ch_simulated_runtime", "status": "succeeded"}


def configure_merchant(buyer, db, tx, receipt_key, charger):
    tap_key = Ed25519PrivateKey.generate()
    merchant = MerchantSim(keys=keyring(tap_key.public_key()), receipt_keys=keyring(receipt_key.public_key()),
        store=buyer.NONCE_STORE, approvals=lambda deal_id, buyer_id:
            tx if deal_id == tx["deal_id"] and buyer_id == tx["buyer_id"] else None, charger=charger)
    buyer.TAP_PRIVATE_KEY = tap_key
    buyer.SHIELD_RECEIPT_KEYS = keyring(receipt_key.public_key())
    buyer.MERCHANT_SIM = merchant
    return merchant, tap_key


def install_shield_screen(buyer, receipt, message_id):
    def screen(actual_message_id, sender, request_json, expected):
        body = request_json.encode("utf-8") if isinstance(request_json, str) else request_json
        exact_id = "req:" + hashlib.sha256(b"vidyut\n" + body).hexdigest()
        if (actual_message_id != exact_id or actual_message_id != message_id
                or not isinstance(sender, str) or not isinstance(expected, dict)):
            return {"verdict": "deny", "message_id": actual_message_id}
        return {"verdict": "allow", "receipt": receipt, "message_id": actual_message_id}
    buyer.SHIELD_PAYMENT_SCREEN = screen


def test_wrong_seller_and_request_drift_never_reach_charger(runtime):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    request, body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    charger = FakeCharger()
    configure_merchant(buyer, db, tx, receipt_key, charger)
    install_shield_screen(buyer, receipt, message_id)

    wrong_sender = Context()
    asyncio.run(buyer.on_request_payment(wrong_sender, buyer.common.address("seller_2"), request))

    altered_data = request.model_dump()
    altered_data["reference"] = "0" * 64
    altered = type(request)(**altered_data)
    bad_body = altered.model_dump_json().encode("utf-8")
    bad_message_id = "req:" + hashlib.sha256(tx["buyer_id"].encode() + b"\n" + bad_body).hexdigest()
    bad_receipt = sign_allow_receipt(private_key=receipt_key, message_id=bad_message_id,
        request_json=bad_body, deal_id=tx["deal_id"], mandate_hash=tx["mandate"]["hash"],
        amount_cents=58200, currency="USD", payee=tx["mandate"]["payee"], now=NOW)
    drift_ctx = Context()
    install_shield_screen(buyer, bad_receipt, bad_message_id)
    asyncio.run(buyer.on_request_payment(drift_ctx, tx["mandate"]["payee"], altered))

    assert not charger.calls
    assert any(isinstance(message, RejectPayment) for _, message in drift_ctx.sent)
    assert not any(isinstance(message, CommitPayment) for ctx in (wrong_sender, drift_ctx)
                   for _, message in ctx.sent)


@pytest.mark.parametrize("channel", ["typed", "browser"])
def test_stored_approved_transaction_with_non_phone_approval_is_rejected_and_never_charged(runtime, channel):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    tx["voice_approval"] = {**tx["voice_approval"], "channel": channel}
    state.save_transaction(db, tx)
    buyer.ROUND.update(transaction=tx)
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    charger = FakeCharger()
    configure_merchant(buyer, db, tx, receipt_key, charger)
    install_shield_screen(buyer, receipt, message_id)
    ctx = Context()

    asyncio.run(buyer.on_request_payment(ctx, tx["mandate"]["payee"], request))

    assert not charger.calls
    assert any(isinstance(message, RejectPayment) for _, message in ctx.sent)
    assert not any(isinstance(message, CommitPayment) for _, message in ctx.sent)


def test_invalid_shield_receipt_never_reaches_charger(runtime):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    charger = FakeCharger()
    configure_merchant(buyer, db, tx, receipt_key, charger)
    invalid_receipt = {**receipt, "signature": "invalid"}
    install_shield_screen(buyer, invalid_receipt, message_id)
    ctx = Context()

    asyncio.run(buyer.on_request_payment(ctx, tx["mandate"]["payee"], request))

    assert not charger.calls
    assert any(isinstance(message, RejectPayment) for _, message in ctx.sent)


def test_expired_market_purchase_status_blocks_locally_fresh_mandate(runtime):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    assert datetime.fromisoformat(tx["mandate"]["expires_at"].replace("Z", "+00:00")) > NOW
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    buyer.MARKET_BUYER.purchase_status.return_value = {
        "approval_method": "voice_code", "retired": False, "reservation_matches": True,
        "payment_ref": None, "expiry": (NOW - timedelta(seconds=1)).isoformat(), "origin": "SIM"}
    charger = FakeCharger()
    configure_merchant(buyer, db, tx, receipt_key, charger)
    screen_calls = []
    def screen(*args):
        screen_calls.append(args)
        return {"verdict": "allow", "receipt": receipt, "message_id": message_id}
    buyer.SHIELD_PAYMENT_SCREEN = screen
    ctx = Context()

    asyncio.run(buyer.on_request_payment(ctx, tx["mandate"]["payee"], request))

    assert not screen_calls
    assert not charger.calls
    assert state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["phase"] == "approved"
    assert not any(isinstance(message, CommitPayment) for _, message in ctx.sent)


def test_exact_request_persists_charge_before_commitpayment(runtime, monkeypatch):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    events = []
    charger = FakeCharger(events)
    configure_merchant(buyer, db, tx, receipt_key, charger)
    install_shield_screen(buyer, receipt, message_id)
    seen = {}
    original_sign = checkout.sign_request
    def capture_sign(**kwargs):
        headers = original_sign(**kwargs)
        seen.update(headers=headers)
        return headers
    monkeypatch.setattr(checkout, "sign_request", capture_sign)
    original_merchant_factory = buyer._merchant_sim_for
    def readback_before_worker(transaction):
        persisted = state.load_transaction(db, tx["deal_id"], tx["buyer_id"])
        assert persisted["phase"] == "submitted"
        assert persisted["voice_approval"] == tx["voice_approval"]
        return original_merchant_factory(transaction)
    monkeypatch.setattr(buyer, "_merchant_sim_for", readback_before_worker)
    ctx = Context()
    async def send(to, message):
        ctx.sent.append((to, message))
        if isinstance(message, CommitPayment):
            persisted = state.load_transaction(db, tx["deal_id"], tx["buyer_id"])
            assert persisted["settlement_result"]["status"] == "charged"
            assert persisted["payment_ref"] == "ch_simulated_runtime"
            assert persisted["mandate"]["tap_signature"] == seen["headers"]["Signature"]
            events.append("commit")
    ctx.send = send

    asyncio.run(buyer.on_request_payment(ctx, tx["mandate"]["payee"], request))

    assert events == ["charge", "commit"], (events, ctx.logger.warning.call_args_list,
        [getattr(message, "reason", None) for _, message in ctx.sent],
        state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["settlement_result"])
    assert len(charger.calls) == 1
    assert any(isinstance(message, CommitPayment) for _, message in ctx.sent)
    assert state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["mode"] == "SIM"
    assert state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["settlement_result"]["origin"] == "SIM"
    assert not any("Stripe" in message.text() for _, message in ctx.sent if hasattr(message, "text"))
    owner_lines = [message.text() for _, message in ctx.sent if isinstance(message, buyer.ChatMessage)]
    submitted = [t for t in owner_lines if "confirmed charge was submitted" in t]
    assert submitted and "SIM payment confirmed" in submitted[0], owner_lines   # #209 review: say SIM, amount, reference
    assert "ch_simulated_runtime" in submitted[0] and f"${tx['mandate']['amount']:.2f}" in submitted[0]


def test_on_request_payment_passes_the_stored_transaction_to_guarded_settle_without_typeerror(runtime, monkeypatch):
    """hunt.settle(req, transaction, now=None): the handler must hand it the stored transaction, never old globals."""
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    charger = FakeCharger()
    configure_merchant(buyer, db, tx, receipt_key, charger)
    install_shield_screen(buyer, receipt, message_id)
    seen = []
    real_settle = buyer.hunt.settle

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return real_settle(*args, **kwargs)

    monkeypatch.setattr(buyer.hunt, "settle", spy)
    assert not hasattr(buyer, "APPROVALS") and not hasattr(buyer, "USED")
    ctx = Context()

    asyncio.run(buyer.on_request_payment(ctx, tx["mandate"]["payee"], request))

    assert len(seen) == 1
    (req, stored), kwargs = seen[0]
    assert req is request and isinstance(stored, dict) and stored["deal_id"] == tx["deal_id"]
    assert stored["phase"] == "submitted" and stored["settlement_result"]["status"] == "charged"
    assert set(kwargs) <= {"now"}
    assert not any("TypeError" in str(call) for call in ctx.logger.warning.call_args_list)
    assert len(charger.calls) == 1
    assert any(isinstance(message, CommitPayment) for _, message in ctx.sent)
    assert not any(isinstance(message, RejectPayment) for _, message in ctx.sent)


def test_on_request_payment_rejects_wrong_payee_then_replay_never_charges_twice(runtime):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    charger = FakeCharger()
    configure_merchant(buyer, db, tx, receipt_key, charger)
    install_shield_screen(buyer, receipt, message_id)

    wrong_payee = Context()
    asyncio.run(buyer.on_request_payment(wrong_payee, buyer.common.address("seller_2"), request))
    assert not charger.calls and not any(isinstance(m, CommitPayment) for _, m in wrong_payee.sent)

    first = Context()
    asyncio.run(buyer.on_request_payment(first, tx["mandate"]["payee"], request))
    assert len(charger.calls) == 1 and any(isinstance(m, CommitPayment) for _, m in first.sent)

    replay = Context()
    asyncio.run(buyer.on_request_payment(replay, tx["mandate"]["payee"], request))
    assert len(charger.calls) == 1  # the replay never charges again
    assert not any(isinstance(m, CommitPayment) for _, m in replay.sent)


def test_on_request_payment_rejects_wrong_amount_before_any_charge(runtime):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    request, _body, _message_id, _receipt, receipt_key = payment_material(buyer, tx)
    charger = FakeCharger()
    configure_merchant(buyer, db, tx, receipt_key, charger)
    data = request.model_dump()
    data["accepted_funds"] = [{**data["accepted_funds"][0], "amount": "999.00"}]
    inflated = type(request)(**data)
    body = inflated.model_dump_json().encode("utf-8")
    inflated_id = "req:" + hashlib.sha256(tx["buyer_id"].encode() + b"\n" + body).hexdigest()
    inflated_receipt = sign_allow_receipt(private_key=receipt_key, message_id=inflated_id, request_json=body,
        deal_id=tx["deal_id"], mandate_hash=tx["mandate"]["hash"], amount_cents=58200,
        currency="USD", payee=tx["mandate"]["payee"], now=NOW)
    install_shield_screen(buyer, inflated_receipt, inflated_id)
    ctx = Context()

    asyncio.run(buyer.on_request_payment(ctx, tx["mandate"]["payee"], inflated))

    assert not charger.calls
    assert any(isinstance(m, RejectPayment) for _, m in ctx.sent)
    assert not any(isinstance(m, CommitPayment) for _, m in ctx.sent)


def test_completepayment_rejects_mismatch_then_accepts_exact_late_ack(runtime):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    charger = FakeCharger()
    merchant, tap_key = configure_merchant(buyer, db, tx, receipt_key, charger)
    envelope = checkout.settle_offer(tx, request, merchant, receipt=receipt, message_id=message_id,
        tap_private_key=tap_key, now=NOW)
    tx.update(phase="submitted", settlement=envelope["settlement"],
        mandate=envelope["mandate"], settlement_result=envelope["settlement_result"],
        payment_ref=envelope["settlement_result"]["charge_id"])
    tx["order"].update(status="charged", payment_ref=tx["payment_ref"])  # what on_request_payment persists
    state.save_transaction(db, tx)
    buyer.ROUND.update(transaction=tx, pending_hold=True)
    paid_status = {
        "approval_method": "voice_code", "retired": False, "reservation_matches": True,
        "payment_ref": "ch_simulated_runtime", "payment_mode": "sim", "payment_amount": 582.0}
    buyer.MARKET_BUYER.purchase_status.side_effect = [
        {"payment_ref": None, "payment_mode": None, "payment_amount": None}, paid_status]
    buyer.MARKET_BUYER.settle_goal.return_value = {"settled": True}
    buyer.business_now = lambda: NOW + timedelta(hours=1)
    wrong = Context()

    asyncio.run(buyer.on_complete(wrong, buyer.common.address("seller_2"),
        CompletePayment(transaction_id="ch_simulated_runtime")))
    asyncio.run(buyer.on_complete(wrong, tx["mandate"]["payee"], CompletePayment(transaction_id="pi_wrong")))
    assert state.load_goal(db, tx["goal_id"], "owner")["state"] == "HOLD_FOR_CALL"
    assert buyer.ROUND.get("pending_hold") is True

    exact = Context()
    asyncio.run(buyer.on_complete(exact, tx["mandate"]["payee"],
        CompletePayment(transaction_id="ch_simulated_runtime")))
    assert state.load_goal(db, tx["goal_id"], "owner")["state"] == "DONE"
    assert buyer.ROUND.get("pending_hold") is not True
    assert len(charger.calls) == 1
    done = [m.text() for _, m in exact.sent if isinstance(m, buyer.ChatMessage) and "settled and recorded" in m.text()]
    assert done and "SIM payment confirmed" in done[0] and "ch_simulated_runtime" in done[0], exact.sent   # the "I did this" receipt
    buyer.MARKET_REFEREE.record_payment.assert_called_once_with(
        mandate_hash=tx["mandate"]["hash"], payment_ref="ch_simulated_runtime",
        amount=tx["mandate"]["amount"], mode="sim")


def test_exact_ack_skips_duplicate_market_payment_record(runtime):
    buyer, db = runtime
    tx, charger = charged_transaction(buyer, db)

    asyncio.run(buyer.on_complete(Context(), tx["mandate"]["payee"],
        CompletePayment(transaction_id="ch_simulated_runtime")))

    assert state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["phase"] == "settled"
    buyer.MARKET_REFEREE.record_payment.assert_not_called()
    buyer.MARKET_BUYER.settle_goal.assert_called_once()
    assert len(charger.calls) == 1


@pytest.mark.parametrize(("initial", "expected", "transition_from", "final", "accepted"), [
    # #447: the published module goes open -> closed (it ranks at close); there is no review state
    ("open", "closed", "open", "closed", True),
    ("open", "closed", "open", "open", False),
])
def test_market_scheduler_races_require_confirmed_round_transition(
        runtime, initial, expected, transition_from, final, accepted):
    from market_bridge import MarketBridge, MarketBridgeError
    buyer, _db = runtime

    class RacingMarketClient:
        identity = "referee-test"
        state = initial

        def sql(self, _query):
            return [{"id": "round-1", "need_id": "need-1", "state": self.state, "deadline": None}]

        def call(self, _reducer, **_kwargs):
            self.state = final
            raise RuntimeError("scheduler changed round concurrently")

    referee = MarketBridge("referee", client=RacingMarketClient())
    if accepted:
        status = buyer._ensure_market_round_state(
            referee, "round-1", expected=expected, transition_from=transition_from)
        assert status["state"] == expected
    else:
        with pytest.raises(MarketBridgeError):
            buyer._ensure_market_round_state(
                referee, "round-1", expected=expected, transition_from=transition_from)


def charged_transaction(buyer, db):
    tx, _service = approved_transaction(buyer, db)
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    charger = FakeCharger()
    merchant, tap_key = configure_merchant(buyer, db, tx, receipt_key, charger)
    envelope = checkout.settle_offer(tx, request, merchant, receipt=receipt, message_id=message_id,
        tap_private_key=tap_key, now=NOW)
    tx.update(phase="submitted", settlement=envelope["settlement"],
        mandate=envelope["mandate"], settlement_result=envelope["settlement_result"],
        payment_ref=envelope["settlement_result"]["charge_id"])
    tx["order"].update(status="charged", payment_ref=tx["payment_ref"])  # what on_request_payment persists
    state.save_transaction(db, tx)
    assert charger.calls and buyer.NONCE_STORE.get_payment_attempt(tx["mandate"]["hash"])["phase"] == "charged"
    buyer.MARKET_BUYER.purchase_status.return_value = {
        "approval_method": "voice_code", "retired": False, "reservation_matches": True,
        "payment_ref": "ch_simulated_runtime", "payment_mode": "sim", "payment_amount": 582.0}
    buyer.MARKET_BUYER.settle_goal.return_value = {"settled": True}
    return tx, charger


def test_startup_charged_ledger_allows_exact_ack_without_recharge(runtime, monkeypatch):
    buyer, db = runtime
    monkeypatch.setenv("MARKET_BUYER_OWNER_SENDER", "owner")
    tx, charger = charged_transaction(buyer, db)
    buyer.ROUND.clear()
    asyncio.run(buyer.buyer_startup(Context()))
    assert buyer.ROUND["transaction"]["phase"] == "uncertain"

    ctx = Context()
    asyncio.run(buyer.on_complete(ctx, tx["mandate"]["payee"],
        CompletePayment(transaction_id="ch_simulated_runtime")))

    recovered = state.load_transaction(db, tx["deal_id"], tx["buyer_id"])
    assert recovered["phase"] == "settled"
    assert state.load_goal(db, tx["goal_id"], "owner")["state"] == "DONE"
    assert len(charger.calls) == 1
    buyer.MARKET_BUYER.settle_goal.assert_called_once()


def test_charged_attempt_with_wrong_request_binding_cannot_settle(runtime, monkeypatch):
    buyer, db = runtime
    monkeypatch.setenv("MARKET_BUYER_OWNER_SENDER", "owner")
    tx, charger = charged_transaction(buyer, db)
    buyer.NONCE_STORE._db.execute("UPDATE payment_attempt SET request_sha256=? WHERE mandate_hash=?",
        ("f" * 64, tx["mandate"]["hash"]))
    buyer.NONCE_STORE._db.commit()
    buyer.ROUND.clear()
    asyncio.run(buyer.buyer_startup(Context()))

    asyncio.run(buyer.on_complete(Context(), tx["mandate"]["payee"],
        CompletePayment(transaction_id="ch_simulated_runtime")))

    assert state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["phase"] == "uncertain"
    assert state.load_goal(db, tx["goal_id"], "owner")["state"] == "HOLD_FOR_CALL"
    buyer.MARKET_BUYER.settle_goal.assert_not_called()
    buyer.MARKET_REFEREE.record_payment.assert_not_called()
    assert len(charger.calls) == 1


@pytest.mark.parametrize("failure_point", ["commit", "owner_notice"])
def test_postcharge_delivery_failure_can_finish_from_durable_charge_on_exact_ack(runtime, failure_point):
    buyer, db = runtime
    tx, _service = approved_transaction(buyer, db)
    request, _body, message_id, receipt, receipt_key = payment_material(buyer, tx)
    events = []
    charger = FakeCharger(events)
    configure_merchant(buyer, db, tx, receipt_key, charger)
    install_shield_screen(buyer, receipt, message_id)
    ctx = Context()
    failed = False

    async def send(to, message):
        nonlocal failed
        if (failure_point == "commit" and isinstance(message, CommitPayment) and not failed
                or failure_point == "owner_notice" and isinstance(message, buyer.ChatMessage)
                and "confirmed charge was submitted" in message.text() and not failed):
            failed = True
            raise ConnectionError("simulated delivery failure")
        ctx.sent.append((to, message))

    ctx.send = send
    asyncio.run(buyer.on_request_payment(ctx, tx["mandate"]["payee"], request))
    charged = state.load_transaction(db, tx["deal_id"], tx["buyer_id"])
    assert charged["phase"] == "submitted"
    assert buyer.NONCE_STORE.get_payment_attempt(tx["mandate"]["hash"])["phase"] == "charged"
    buyer.MARKET_BUYER.purchase_status.return_value = {
        "payment_ref": "ch_simulated_runtime", "payment_mode": "sim", "payment_amount": 582.0}
    buyer.MARKET_BUYER.settle_goal.return_value = {"settled": True}

    asyncio.run(buyer.on_complete(ctx, tx["mandate"]["payee"],
        CompletePayment(transaction_id="ch_simulated_runtime")))

    assert state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["phase"] == "settled"
    assert len(charger.calls) == 1
    assert events.count("charge") == 1
    assert not any(isinstance(message, RejectPayment) for _, message in ctx.sent)


# ---- #398 item 3: Bazaar Caller carries the voice only, behind BUYER_DELEGATE_CALL (off by default) -----------------
class FakeCaller:
    """Stands in for Bazaar Caller over uAgents: returns what the owner 'said' on a call it placed. It never knows the
    code; the test hands it the code the owner saw, as a person on the phone would speak it."""

    def __init__(self, owner, *, says="approve", reply=None, raise_=None, call_id="caller-call-1"):
        self.owner, self.says, self.reply, self.raise_, self.call_id = owner, says, reply, raise_, call_id
        self.requests = []

    def __call__(self, mandate_hash, variables):
        self.requests.append((mandate_hash, variables))
        if self.raise_:
            raise self.raise_
        if self.reply is not None:
            return self.reply(mandate_hash)
        return {"mandate_hash": mandate_hash, "call_id": self.call_id, "error": "", "call": {
            "id": self.call_id, "status": "completed", "end_reason": "agent_hangup",
            "start_time": (NOW + timedelta(seconds=1)).isoformat(),
            "transcript": [{"role": "user", "text": f"{self.owner.code} {self.says}", "start_timestamp": 1.0}]}}


def _delegate(buyer, monkeypatch, caller, direct):
    monkeypatch.setenv("BUYER_DELEGATE_CALL", "1")
    monkeypatch.setattr(buyer, "USED_CALL_IDS", set())
    monkeypatch.setattr(buyer, "_transport_request", lambda ctx, loop: caller)
    _wire_voice(buyer, direct, "buyer-runtime-delegate-secret")
    buyer.MARKET_REFEREE.record_approval.return_value = {"approval_method": "voice_code", "approved_at": NOW.isoformat()}


def _market_row(buyer, **override):
    m = market_view(buyer.ROUND["transaction"])
    return {"approval_method": "voice_code", "approved_at": NOW.isoformat(), "mandate_hash": m["hash"],
            "amount": m["amount"], "payee": m["payee"], "retired": False, **override}


def _run(buyer, ctx):
    asyncio.run(asyncio.wait_for(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])), timeout=10))
    t = buyer.ROUND["transaction"]
    return state.load_transaction(buyer.STATE_DB, t["deal_id"], t["buyer_id"])


def test_delegation_is_off_by_default_and_today_s_direct_call_runs(runtime, monkeypatch):
    buyer, _db = runtime
    monkeypatch.delenv("BUYER_DELEGATE_CALL", raising=False)
    assert not buyer.delegate_call_enabled()
    ready_for_requote(buyer)
    buyer.MARKET_REFEREE.record_approval.return_value = {"mandate_hash": "x", "approval_method": "voice_code"}
    _market_shows_the_approval(buyer)
    client = FakeVoiceClient()
    _wire_voice(buyer, client, "buyer-runtime-voice-approval-secret")
    ctx = CodeCapturingContext(client)
    assert _run(buyer, ctx)["phase"] == "approved" and client.calls == 1
    assert not any(isinstance(m, buyer.common.VoiceTransportRequest) for _, m in ctx.sent)
    assert buyer.MARKET_REFEREE.record_approval.call_count == 1  # recorded by the referee, then re-read once by the buyer
    assert buyer.MARKET_BUYER.purchase_status.call_count == 2  # create_mandate's readback, then the approval's


def test_delegation_approves_on_the_spoken_code_verified_by_the_buyer_and_re_reads_the_market(runtime, monkeypatch):
    buyer, _db = runtime
    ready_for_requote(buyer)
    direct = FakeVoiceClient()
    ctx = CodeCapturingContext(direct)
    caller = FakeCaller(direct)
    _delegate(buyer, monkeypatch, caller, direct)
    _readbacks(buyer, lambda h: _market_row(buyer))
    approved = _run(buyer, ctx)
    assert approved["phase"] == "approved" and direct.calls == 0 and len(caller.requests) == 1
    assert approved["voice_approval"]["recording_ref"] == "cartesia:caller-call-1"
    assert approved_voice_record_matches(approved["voice_approval"], approved["mandate"], now=NOW + timedelta(seconds=2))
    hash_, variables = caller.requests[0]
    assert set(variables) == {"buyer_name", "deal_script", "why_answer"}
    assert direct.code not in json.dumps(variables)                       # the Caller never sees the code
    assert any(isinstance(m, buyer.common.OrderPlaced) for _, m in ctx.sent)


@pytest.mark.parametrize("forge", ["wrong_mandate", "replayed_call_id", "unfinished_call"])
def test_a_forged_caller_reply_never_approves_and_the_direct_call_decides(runtime, monkeypatch, forge):
    buyer, _db = runtime
    ready_for_requote(buyer)
    direct = FakeVoiceClient(transcript="no")       # the owner declines on the real direct call
    ctx = CodeCapturingContext(direct)
    good = FakeCaller(direct)
    replies = {
        "wrong_mandate": lambda h: {**good(h, {}), "mandate_hash": "f" * 64},
        "replayed_call_id": lambda h: good(h, {}),
        "unfinished_call": lambda h: {**good(h, {}), "call": {**good(h, {})["call"], "status": "in_progress"}},
    }
    caller = FakeCaller(direct, reply=replies[forge])
    _delegate(buyer, monkeypatch, caller, direct)
    if forge == "replayed_call_id":
        buyer.USED_CALL_IDS.add("caller-call-1")
    held = _run(buyer, ctx)
    assert held["phase"] != "approved" and held["order"] is None
    assert len(caller.requests) == 1                          # never retried through the Caller
    assert direct.calls == 1   # a refused reply (it fails the buyer's checks) falls back to its own direct call, once
    assert not any(isinstance(m, buyer.common.OrderPlaced) for _, m in ctx.sent)


@pytest.mark.parametrize("says", [
    "alpha bravo approve",                # a guessed code
    "{wrong_code} approve",               # the right shape, one word wrong
    "{code} no",                          # denied
    "no {code}",                          # denied, code after
    "{code}",                             # the code without approve
    "",                                   # connected, but the owner said nothing
])
def test_a_finished_delegated_call_that_is_not_an_approval_is_final_and_never_rings_again(runtime, monkeypatch, says):
    """A guessed code, a wrong code, a spoken no, the code without approve, or silence after the call connected: the call
    reached the owner and finished, so the answer stands. The buyer never rings again, through the Caller or directly,
    and nothing is paid (#405 review, #412 item 2)."""
    buyer, _db = runtime
    ready_for_requote(buyer)
    direct = FakeVoiceClient()
    ctx = CodeCapturingContext(direct)
    good = FakeCaller(direct)

    def reply(h):
        r = good(h, {})
        words = (direct.code or "").split()
        wrong_code = " ".join(["zulu"] + words[1:]) if words else "zulu"
        text = says.format(code=direct.code, wrong_code=wrong_code).strip()
        transcript = [{"role": "user", "text": text, "start_timestamp": 1.0}] if text else []
        return {**r, "call": {**r["call"], "transcript": transcript}}
    caller = FakeCaller(direct, reply=reply)
    _delegate(buyer, monkeypatch, caller, direct)
    held = _run(buyer, ctx)
    assert held["phase"] != "approved" and held["order"] is None
    assert len(caller.requests) == 1 and direct.calls == 0   # exactly one ring: no second call, direct or delegated
    assert not any(isinstance(m, buyer.common.OrderPlaced) for _, m in ctx.sent)
    assert not buyer.MARKET_REFEREE.record_approval.called


def test_a_caller_call_timeout_is_final_and_never_dials_a_second_call(runtime, monkeypatch):
    """The Caller dialled and the call rang out (call_timeout): the phone already rang, so the buyer neither dials
    directly nor asks the Caller again, and nothing is paid."""
    buyer, _db = runtime
    ready_for_requote(buyer)
    direct = FakeVoiceClient()
    ctx = CodeCapturingContext(direct)
    caller = FakeCaller(direct, reply=lambda h: {"mandate_hash": h, "call_id": "caller-call-1", "call": None, "error": "call_timeout"})
    _delegate(buyer, monkeypatch, caller, direct)
    held = _run(buyer, ctx)
    assert held["phase"] != "approved" and held["order"] is None
    assert len(caller.requests) == 1 and direct.calls == 0
    assert not any(isinstance(m, buyer.common.OrderPlaced) for _, m in ctx.sent)
    assert not buyer.MARKET_REFEREE.record_approval.called


def test_a_web_buyer_never_delegates_and_gets_the_direct_call(runtime, monkeypatch):
    buyer, _db = runtime
    ready_for_requote(buyer)
    buyer.ROUND["market_buyer_id"] = "b_web12345"   # the transaction's buyer_id comes from here
    direct = FakeVoiceClient()
    ctx = CodeCapturingContext(direct)
    caller = FakeCaller(direct)
    _delegate(buyer, monkeypatch, caller, direct)
    approved = _run(buyer, ctx)
    assert approved["buyer_id"] == "b_web12345"
    assert direct.calls == 1 and caller.requests == []   # the buyer's own direct call, never the Caller
    assert not any(isinstance(m, buyer.common.VoiceTransportRequest) for _, m in ctx.sent)


def test_only_a_non_web_buyer_may_delegate(runtime, monkeypatch):
    buyer, _db = runtime
    delegation_allowed = buyer.delegation_allowed
    monkeypatch.setenv("BUYER_DELEGATE_CALL", "1")
    assert delegation_allowed({"buyer_id": "vidyut"})
    assert not delegation_allowed({"buyer_id": "b_ab12cd34"})
    assert not delegation_allowed({})
    monkeypatch.delenv("BUYER_DELEGATE_CALL")
    assert not delegation_allowed({"buyer_id": "vidyut"})


def test_a_caller_timeout_falls_back_to_the_direct_call_once(runtime, monkeypatch):
    buyer, _db = runtime
    ready_for_requote(buyer)
    direct = FakeVoiceClient()
    ctx = CodeCapturingContext(direct)
    caller = FakeCaller(direct, raise_=TimeoutError())
    _delegate(buyer, monkeypatch, caller, direct)
    _readbacks(buyer, lambda h: _market_row(buyer))
    approved = _run(buyer, ctx)
    assert approved["phase"] == "approved" and direct.calls == 1 and len(caller.requests) == 1


@pytest.mark.parametrize("field,value", [("payee", "someone-else"), ("amount", 1.0), ("mandate_hash", "e" * 64),
                                         ("approval_method", None), ("retired", True)])
def test_a_market_re_read_mismatch_blocks_the_order_and_payment(runtime, monkeypatch, field, value):
    buyer, _db = runtime
    ready_for_requote(buyer)
    direct = FakeVoiceClient()
    ctx = CodeCapturingContext(direct)
    _delegate(buyer, monkeypatch, FakeCaller(direct), direct)
    _readbacks(buyer, lambda h: _market_row(buyer, **{field: value}))
    held = _run(buyer, ctx)
    assert held["phase"] == "uncertain"
    assert not any(isinstance(m, buyer.common.OrderPlaced) for _, m in ctx.sent)
    assert any("could not be confirmed safely" in t for t in owner_texts(ctx))


def test_only_the_caller_can_answer_a_delegated_call(runtime):
    import concurrent.futures
    buyer, _db = runtime
    fut = concurrent.futures.Future()
    buyer.PENDING_TRANSPORT["a" * 64] = fut
    msg = buyer.common.VoiceTransportResult(mandate_hash="a" * 64, call_id="x", call_json="{}")
    asyncio.run(buyer.on_voice_transport(Context(), "agent1someone-else", msg))
    assert not fut.done()
    asyncio.run(buyer.on_voice_transport(Context(), buyer.common.address("caller"), msg))
    assert fut.result()["call_id"] == "x"
    buyer.PENDING_TRANSPORT.clear()
