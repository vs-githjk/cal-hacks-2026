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
    monkeypatch.setattr(buyer, "ALLOWANCE", 0)
    monkeypatch.setattr(buyer, "business_now", lambda: NOW)
    monkeypatch.setattr(buyer.crs, "eligible", lambda _supplier, check, _now: bool(check and check.get("eligible")))
    monkeypatch.setattr(buyer, "blocked_reasons", lambda *_args, **_kwargs: None)
    for name, value in {
        "ROUND": {}, "APPROVALS": {}, "APPROVAL_WAITERS": {}, "WEB_OUTBOX": [],
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


class ImmediateCodeContext(Context):
    def __init__(self, buyer):
        super().__init__()
        self.buyer = buyer

    async def send(self, to, message):
        self.sent.append((to, message))
        if to == "owner" and isinstance(message, self.buyer.ChatMessage):
            match = re.search(r"One-time approval code: ([a-z]+ [a-z]+)", message.text())
            if match:
                reply = self.buyer.ChatMessage(content=[self.buyer.TextContent(text=match.group(1))])
                await self.buyer.on_chat(self, "owner", reply)


def reviewed_card(need_id="need-1", bid_id="bid-1"):
    reason = CALL_SUMMARIES["advocate.ok"]
    source = "https://example.test/advocate"
    return {"need_id": need_id, "bid_id": bid_id, "warnings": [], "claim_checks": [],
            "recommendation": "buy", "wait_until": "",
            "call_reason": {"rule_id": "advocate.ok", "summary": reason, "source_url": source},
            "rule_id": "advocate.ok", "reason": reason, "source_url": source}


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
           "persona": "Seller", "source": "SIM", "origin": "SIM", "need_id": need["id"],
           "lines": [raw_line], "candidate_binding_hash": "c" * 64, "market_binding_hash": "c" * 64,
           "quoted_at": NOW.isoformat(), "expires_at": (NOW + timedelta(seconds=600)).isoformat(),
           "listing_hash": line_hash}
    buyer.MARKET_BUYER.create_mandate.side_effect = lambda mandate, **_kwargs: {
        "mandate_hash": mandate["hash"], "reservation_matches": True,
        "within_allowance": False, "retired": False}
    buyer.ROUND.update(owner="owner", owner_context=None, phase="requote", pick=1,
        deadline=NOW.timestamp() + 60, quoted_at=NOW.timestamp(), need=need, goal=goal,
        bids=[bid], cards={"bid-1": reviewed_card()}, reviewed=True,
        seller_checks={"seller_1": {"eligible": True}}, personas={}, owned=[], attempts=0,
        last_sent={}, market_round_id="round-need-1", order=None, transaction=None,
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
    assert not getattr(buyer, "APPROVALS", {})
    assert not any(isinstance(message, buyer.common.OrderPlaced) for _, message in ctx.sent)


def test_missing_owner_pin_prevents_creating_a_pending_purchase(runtime, monkeypatch):
    buyer, db = runtime
    monkeypatch.delenv("MARKET_BUYER_OWNER_SENDER")
    ready_for_requote(buyer)
    ctx = Context()

    asyncio.run(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])))

    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert not buyer.ROUND.get("transaction")
    assert not buyer.MARKET_BUYER.create_mandate.called
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
    referee.review_candidates.return_value = [{"round_id": "round-need-1", "need_id": "need-1",
        "bid_id": bid_id, "seller_id": "seller-a", "origin": raw["origin"],
        "lines": rows, "line_metadata": metadata, "binding_hash": candidate_hash}]
    referee.round_status.return_value = {"state": "closed"}
    chosen = raw["lines"]
    chosen_hash = metadata[0]["listingHash"]
    market.authoritative_winner.return_value = {"bid_id": bid_id, "seller_id": "seller-a",
        "binding_hash": candidate_hash, "landed": raw["total_landed_price"],
        "lines": [{"original_line_index": index, "sku_spec": line["sku_spec"],
            "unit_price": line["unit_price"], "listing_id": line["listing_id"],
            "listing_hash": metadata[index]["listingHash"], "quantity": line["quantity"],
            "shipping": line["shipping"]} for index, line in enumerate(chosen)]}
    buyer.MARKET_BUYER, buyer.MARKET_REFEREE = market, referee
    buyer.MARKET_BUYER.create_mandate.side_effect = lambda mandate, **_kwargs: {
        "mandate_hash": mandate["hash"], "reservation_matches": True,
        "within_allowance": False, "retired": False}
    state.save_goal(db, goal)
    buyer.ROUND.update(owner="owner", owner_context=None, phase="market_review_wait", pick=1,
        deadline=NOW.timestamp() + 60, quoted_at=NOW.timestamp(), need=need, goal=goal,
        bids=[raw], received_bids={bid_id: raw}, review_bids=[], cards={bid_id: reviewed_card("need-1", bid_id)},
        reviewed=True, seller_checks={"seller_1": {"eligible": True}}, personas={bid_id: "Seller One"},
        owned=[], attempts=0, last_sent={}, market_round_id="round-need-1", round_token="round-token",
        candidate_hashes={}, order=None, transaction=None)

    buyer.ROUND["review_bids"] = buyer._review_candidates(referee, "round-need-1")
    asyncio.run(buyer._finish_market_round(Context()))
    projected = buyer.ROUND["bids"][0]
    assert len(projected["lines"]) == 2
    assert buyer.ROUND["original_offer"] == raw
    assert projected["lines"][0].get("listing_hash") == chosen_hash

    buyer.ROUND.update(phase="requote", pick=1, deadline=NOW.timestamp() + 60,
                       quoted_at=NOW.timestamp())
    requote_ctx = Context()
    asyncio.run(buyer.on_requote(requote_ctx, dict(raw)))
    assert buyer.ROUND.get("transaction") and buyer.ROUND["transaction"]["phase"] == "pending_approval", repr(
        (buyer.ROUND.get("phase"), buyer.MARKET_BUYER.create_mandate.call_args_list,
         buyer.ROUND.get("original_offer") == raw, buyer.ROUND.get("candidate_hashes"),
         buyer.ROUND.get("market_winner"), requote_ctx.logger.warning.call_args_list,
         [message.text() for _, message in requote_ctx.sent if hasattr(message, "text")]))
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_actual_owner_typed_approval_uses_real_service_and_persists_before_order(runtime):
    buyer, db = runtime
    ready_for_requote(buyer)
    buyer.MARKET_BUYER.record_approval.return_value = {
        "approval_method": "typed_code", "approved_at": NOW.isoformat()}
    ctx = Context()
    asyncio.run(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])))
    transaction = buyer.ROUND.get("transaction")
    assert transaction and transaction["phase"] == "pending_approval"
    checkout._bound_transaction(transaction, approval_phase=True, now=NOW)
    buyer.NONCE_STORE = NonceStore(str(state.DEFAULT_DB_PATH))
    service = ApprovalService("buyer-runtime-typed-approval-secret", store=buyer.NONCE_STORE,
                              code_ttl_seconds=VOICE_CODE_TTL_SECONDS)
    buyer.APPROVAL_SERVICE = service
    buyer.APPROVAL_CALL_CLIENT = None

    async def foreign_owner_attempt():
        foreign = Context()
        msg = buyer.ChatMessage(content=[buyer.TextContent(text="APPROVE 1")])
        await buyer.on_chat(foreign, "foreign-owner", msg)
        assert not any("One-time approval code:" in message.text()
                       for _, message in foreign.sent if hasattr(message, "text"))
        unchanged = state.load_transaction(db, transaction["deal_id"], transaction["buyer_id"])
        assert unchanged["phase"] == "pending_approval" and unchanged["voice_approval"] is None
        assert service.attempts_used(transaction["mandate"]["hash"]) == 0
        assert not any(isinstance(message, buyer.common.OrderPlaced) for _, message in foreign.sent)

    asyncio.run(foreign_owner_attempt())

    async def approve_with_typed_code():
        async def incoming(text):
            message = buyer.ChatMessage(content=[buyer.TextContent(text=text)])
            await buyer.on_chat(ctx, "owner", message)

        task = asyncio.create_task(incoming("APPROVE 1"))
        code = None
        for _ in range(100):
            for _to, message in ctx.sent:
                if hasattr(message, "text"):
                    match = re.search(r"One-time approval code: ([a-z]+ [a-z]+)", message.text())
                    if match:
                        code = match.group(1)
                        break
            if code:
                break
            await asyncio.sleep(0.01)
        assert code, ([message.text() for _to, message in ctx.sent if hasattr(message, "text")],
                      ctx.logger.warning.call_args_list)
        before = state.load_transaction(db, transaction["deal_id"], transaction["buyer_id"])
        assert before["phase"] == "pending_approval" and before["voice_approval"] is None
        assert not any(isinstance(message, buyer.common.OrderPlaced) for _, message in ctx.sent)
        await incoming(code)
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(approve_with_typed_code())
    approved = state.load_transaction(db, transaction["deal_id"], transaction["buyer_id"])
    assert approved["phase"] == "approved"
    assert approved["order"]["id"] == approved["deal_id"]
    assert approved_voice_record_matches(approved["voice_approval"], approved["mandate"], now=NOW + timedelta(seconds=2))
    assert approved["mandate"]["status"] == "approved"


def test_immediate_owner_code_reply_is_not_lost_during_private_delivery(runtime):
    buyer, db = runtime
    ready_for_requote(buyer)
    buyer.MARKET_BUYER.record_approval.return_value = {
        "approval_method": "typed_code", "approved_at": NOW.isoformat()}
    ctx = ImmediateCodeContext(buyer)
    asyncio.run(buyer.on_requote(ctx, dict(buyer.ROUND["bids"][0])))
    transaction = buyer.ROUND["transaction"]
    buyer.NONCE_STORE = NonceStore(str(state.DEFAULT_DB_PATH))
    buyer.APPROVAL_SERVICE = ApprovalService("buyer-runtime-immediate-code-secret",
        store=buyer.NONCE_STORE, code_ttl_seconds=VOICE_CODE_TTL_SECONDS)

    asyncio.run(asyncio.wait_for(
        buyer.on_chat(ctx, "owner", buyer.ChatMessage(content=[buyer.TextContent(text="APPROVE 1")])),
        timeout=5))

    approved = state.load_transaction(db, transaction["deal_id"], transaction["buyer_id"])
    assert approved["phase"] == "approved"
    assert approved_voice_record_matches(approved["voice_approval"], approved["mandate"],
                                         now=NOW + timedelta(seconds=2))
    assert any(isinstance(message, buyer.common.OrderPlaced) for _, message in ctx.sent)


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
    session, code = service.issue(mandate, now=NOW)
    session.start_call(now=NOW)
    decision = session.approve_typed(code, now=NOW + timedelta(seconds=1))
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
        "approval_method": "typed_code", "retired": False, "reservation_matches": True,
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
        "approval_method": "typed_code", "retired": False, "reservation_matches": True,
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
    tx["order"]["payment_ref"] = tx["payment_ref"]
    tx["order"]["status"] = "charged"
    state.save_transaction(db, tx)
    buyer.ROUND.update(transaction=tx, pending_hold=True)
    buyer.MARKET_BUYER.purchase_status.return_value = {
        "approval_method": "typed_code", "retired": False, "reservation_matches": True,
        "payment_ref": "ch_simulated_runtime", "payment_mode": "sim", "payment_amount": 582.0}
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
    buyer.MARKET_REFEREE.record_payment.assert_called_once_with(
        mandate_hash=tx["mandate"]["hash"], payment_ref="ch_simulated_runtime",
        amount=tx["mandate"]["amount"], mode="sim")


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
    tx["order"]["payment_ref"] = tx["payment_ref"]
    tx["order"]["status"] = "charged"
    state.save_transaction(db, tx)
    assert charger.calls and buyer.NONCE_STORE.get_payment_attempt(tx["mandate"]["hash"])["phase"] == "charged"
    buyer.MARKET_BUYER.purchase_status.return_value = {
        "approval_method": "typed_code", "retired": False, "reservation_matches": True,
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


def test_final_owner_notice_failure_keeps_settlement_and_releases_goal(runtime):
    buyer, db = runtime
    tx, charger = charged_transaction(buyer, db)
    ctx = Context()
    original_send = ctx.send
    async def fail_final_notice(to, message):
        if to == "owner" and hasattr(message, "text") and message.text().startswith("Purchase "):
            raise ConnectionError("simulated final notification failure")
        await original_send(to, message)
    ctx.send = fail_final_notice

    asyncio.run(buyer.on_complete(ctx, tx["mandate"]["payee"],
        CompletePayment(transaction_id="ch_simulated_runtime")))

    settled = state.load_transaction(db, tx["deal_id"], tx["buyer_id"])
    assert settled["phase"] == "settled"
    assert state.load_goal(db, tx["goal_id"], "owner")["state"] == "DONE"
    assert buyer.ROUND.get("pending_hold") is False
    assert not any(isinstance(message, RejectPayment) for _, message in ctx.sent)
    assert len(charger.calls) == 1
    before = buyer.MARKET_BUYER.post_goal.call_count
    asyncio.run(buyer.handle_text(ctx, "owner", "a new GPU under $800 by Friday"))
    assert buyer.MARKET_BUYER.post_goal.call_count == before + 1
    assert buyer.ROUND.get("pending_hold") is not True


@pytest.mark.parametrize("settle_first", [False, True])
def test_tick_does_not_expire_charged_or_settled_goal(runtime, monkeypatch, settle_first):
    buyer, db = runtime
    tx, charger = charged_transaction(buyer, db)
    goal = state.load_goal(db, tx["goal_id"], "owner")
    goal["deadline"] = (NOW - timedelta(seconds=1)).isoformat()
    if settle_first:
        goal["state"] = "HOLD_FOR_CALL"
    state.save_goal(db, goal)
    buyer.ROUND.clear()
    if settle_first:
        ctx = Context()
        asyncio.run(buyer.buyer_startup(ctx))
        buyer.MARKET_BUYER.purchase_status.return_value = {
            "payment_ref": "ch_simulated_runtime", "payment_mode": "sim", "payment_amount": 582.0}
        buyer.MARKET_BUYER.settle_goal.return_value = {"settled": True}
        asyncio.run(buyer.on_complete(ctx, tx["mandate"]["payee"],
            CompletePayment(transaction_id="ch_simulated_runtime")))
    else:
        asyncio.run(buyer.buyer_startup(Context()))
    monkeypatch.setattr(buyer, "business_now", lambda: NOW + timedelta(days=2))
    ctx = Context()

    asyncio.run(buyer.tick(ctx))

    expected_goal_state = "DONE" if settle_first else "HOLD_FOR_CALL"
    expected_tx_phase = "settled" if settle_first else "uncertain"
    assert state.load_goal(db, tx["goal_id"], "owner")["state"] == expected_goal_state
    assert state.load_transaction(db, tx["deal_id"], tx["buyer_id"])["phase"] == expected_tx_phase
    assert not any("EXPIRED" in message.text() or "nothing ordered" in message.text().lower()
                   for _, message in ctx.sent if hasattr(message, "text"))
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
