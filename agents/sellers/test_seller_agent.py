import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from uagents_core.contrib.protocols.payment import CommitPayment, CompletePayment, Funds, RejectPayment

from agents.buyer import state
from agents.sellers import seller_agent
from pay.approval import ApprovalService
from pay.mandate import new_mandate
from pay.replay import NonceStore

BUYER_AGENT = "buyer-agent-registered"
SELLER_ADDR = "seller-agent-1"
BUYER_ID = "owner-chat-1"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


class FakeProtocol:
    def __init__(self, **_kwargs):
        self.handlers = {}

    def on_message(self, model):
        def register(handler):
            self.handlers[model] = handler
            return handler
        return register


class FakeAgent:
    def __init__(self, **_kwargs):
        self.address = SELLER_ADDR
        self.handlers = {}
        self.protocols = []

    def on_message(self, model):
        def register(handler):
            self.handlers[model] = handler
            return handler
        return register

    def include(self, protocol, **_kwargs):
        self.protocols.append(protocol)


class Context:
    session = "offline-session"

    def __init__(self):
        self.sent = []
        self.logs = []
        self.logger = self

    async def send(self, to, message):
        self.sent.append((to, message))

    def warning(self, message):
        self.logs.append(message)

    def info(self, message):
        self.logs.append(message)


def approved_transaction(*, expired=False, allowance=False):
    created = NOW - timedelta(hours=1) if expired else NOW
    mandate = new_mandate(deal_id="deal-seller", buyer_id=BUYER_ID, goal_id="goal-seller",
                          amount=79.99, payee=SELLER_ADDR, within_allowance=allowance, now=created)
    if allowance:
        record = None
        approval_id = "allowance-seller-1"
        mandate.update(status="approved", approval_id=approval_id)
        allowance_authorization = {"id": approval_id, "mandate_hash": mandate["hash"],
            "mandate_id": mandate["id"], "deal_id": mandate["deal_id"], "buyer_id": BUYER_ID,
            "goal_id": mandate["goal_id"], "amount": mandate["amount"], "payee": SELLER_ADDR,
            "method": "allowance", "approved_at": created.isoformat()}
    else:
        approval_service = ApprovalService("seller-agent-test-secret-123456", store=NonceStore())
        session, code = approval_service.issue(mandate, now=created)
        session.start_call(now=created)
        session.begin_listening(now=created)
        record = session.approve(code + " approve", now=created + timedelta(seconds=1)).record
        approval_id = record["id"]
        mandate.update(status="approved", approval_id=approval_id)
        allowance_authorization = None
    order = {"id": "deal-seller", "need_id": "need-seller", "bid_id": "bid-seller", "amount": 79.99,
             "approved_by": "allowance" if allowance else "owner", "approval_id": approval_id, "limit_checked": True,
             "idempotency_key": "mandate:" + mandate["hash"], "payment_ref": "", "status": "PENDING"}
    card = {"need_id": "need-seller", "bid_id": "bid-seller", "warnings": [], "recommendation": "buy",
            "wait_until": "", "call_reason": {"rule_id": "advocate.ok", "summary": "No problems found",
            "source_url": "https://example.com/check"}, "rule_id": "advocate.ok", "reason": "No problems found",
            "source_url": "https://example.com/check"}
    return {"deal_id": "deal-seller", "buyer_id": BUYER_ID, "goal_id": "goal-seller",
            "need_id": "need-seller", "bid_id": "bid-seller", "phase": "approved",
            "deal": {"id": "deal-seller", "goal_id": "goal-seller", "need_id": "need-seller",
                     "bid_id": "bid-seller", "amount": 79.99, "payee": SELLER_ADDR},
            "order": order, "advocate_card": card, "mandate": mandate, "voice_approval": record,
            "allowance_authorization": allowance_authorization, "settlement": None, "settlement_result": None,
            "payment_ref": None, "mode": "SIM"}


@pytest.fixture
def seller(tmp_path, monkeypatch):
    db_path = tmp_path / ".state" / "state.sqlite3"
    monkeypatch.setattr(state, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(seller_agent, "Agent", FakeAgent)
    monkeypatch.setattr(seller_agent, "Protocol", FakeProtocol)
    monkeypatch.setattr(seller_agent.common, "agent_args", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(seller_agent.common, "include_profile_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(seller_agent.common, "address", lambda role: BUYER_AGENT if role == "buyer" else role)
    monkeypatch.setattr(seller_agent, "load_seller", lambda _name: {"name": "Seller", "archetype": "helpful",
                                                                      "claims": ["tested parts"]})
    monkeypatch.setattr(seller_agent.common, "screen", lambda *_args, **_kwargs: {"verdict": "allow", "reasons": []})
    app = seller_agent.build("seller_1")
    pay_protocol = next(protocol for protocol in app.protocols if CommitPayment in protocol.handlers)
    return {"app": app, "handlers": pay_protocol.handlers,
            "order_handler": app.handlers[seller_agent.common.OrderPlaced], "db_path": db_path}


def save_transaction(db_path, transaction):
    db = state.open_state(db_path)
    try:
        state.save_transaction(db, transaction)
    finally:
        db.close()


def load_transaction(db_path, deal_id, buyer_id):
    db = state.open_state(db_path)
    try:
        return state.load_transaction(db, deal_id, buyer_id)
    finally:
        db.close()


def make_commit(transaction, charge_id="pi_test_seller_1", **changes):
    mandate = transaction["mandate"]
    fields = {"funds": Funds(amount="79.99", currency="USD", payment_method="stripe"),
              "recipient": SELLER_ADDR, "transaction_id": charge_id, "reference": mandate["hash"],
              "description": f"deal {transaction['deal_id']}"}
    fields.update(changes)
    return CommitPayment(**fields)


def charge_transaction(db_path, transaction, *, phase="charged", wrong_request=False):
    request = seller_agent.payment.payment_request(transaction["mandate"], recipient=SELLER_ADDR)
    body = request.model_dump_json().encode("utf-8")
    request_hash = hashlib.sha256(body).hexdigest()
    message_id = "req:" + hashlib.sha256(BUYER_ID.encode("utf-8") + b"\n" + body).hexdigest()
    if wrong_request:
        request_hash = "0" * 64
        message_id = "req:" + "0" * 64
    store = NonceStore(str(db_path))
    try:
        attempt = {"mandate_hash": transaction["mandate"]["hash"], "buyer_id": BUYER_ID,
                   "deal_id": transaction["deal_id"], "request_sha256": request_hash,
                   "amount_cents": 7999, "currency": "USD", "payee": SELLER_ADDR,
                   "idempotency_key": "mandate:" + transaction["mandate"]["hash"],
                   "message_id": message_id, "receipt_keyid": "shield-test", "phase": "submitted"}
        assert store.start_payment_attempt(attempt, transaction["mandate"]["nonce"])
        charge_id = "pi_test_seller_1"
        if phase != "submitted":
            assert store.finish_payment_attempt(transaction["mandate"]["hash"], phase,
                charge_id=charge_id if phase == "charged" else None)
    finally:
        store._db.close()
    if phase == "charged":
        transaction["phase"] = "submitted"
        transaction["payment_ref"] = charge_id
        transaction["settlement"] = {"message_id": message_id, "request_sha256": request_hash,
            "mandate_hash": transaction["mandate"]["hash"], "deal_id": transaction["deal_id"],
            "buyer_id": BUYER_ID, "amount_cents": 7999, "currency": "USD", "payee": SELLER_ADDR,
            "idempotency_key": "mandate:" + transaction["mandate"]["hash"],
            "receipt_keyid": "shield-test", "mode": "SIM"}
        transaction["settlement_result"] = {"status": "charged", "reason": "ok", "charge_id": charge_id,
            "mandate_hash": transaction["mandate"]["hash"], "origin": "SIM"}
    else:
        transaction["phase"] = "uncertain"
        transaction["settlement"] = {"message_id": message_id, "request_sha256": request_hash,
            "mandate_hash": transaction["mandate"]["hash"], "deal_id": transaction["deal_id"],
            "buyer_id": BUYER_ID, "amount_cents": 7999, "currency": "USD", "payee": SELLER_ADDR,
            "idempotency_key": "mandate:" + transaction["mandate"]["hash"],
            "receipt_keyid": "shield-test", "mode": "SIM"}
        transaction["settlement_result"] = {"status": "uncertain", "reason": "unknown", "charge_id": None,
            "mandate_hash": transaction["mandate"]["hash"], "origin": "SIM"}
    save_transaction(db_path, transaction)
    return make_commit(transaction)


def test_registered_buyer_order_sends_payment_request_from_exact_persisted_approval(seller):
    transaction = approved_transaction()
    save_transaction(seller["db_path"], transaction)
    ctx = Context()
    order = seller_agent.common.OrderPlaced(order_json=json.dumps(transaction["order"]),
                                            mandate_json=json.dumps(transaction["mandate"]))
    asyncio.run(seller["order_handler"](ctx, BUYER_AGENT, order))
    assert len(ctx.sent) == 1 and ctx.sent[0][0] == BUYER_AGENT
    request = ctx.sent[0][1]
    assert request.reference == transaction["mandate"]["hash"]
    assert request.recipient == SELLER_ADDR and request.description == "deal deal-seller"
    assert request.accepted_funds[0].amount == "79.99"
    assert load_transaction(seller["db_path"], transaction["deal_id"], BUYER_ID) == transaction


def test_stored_allowance_authorization_can_request_only_its_bound_mandate(seller):
    transaction = approved_transaction(allowance=True)
    save_transaction(seller["db_path"], transaction)
    ctx = Context()
    order = seller_agent.common.OrderPlaced(order_json=json.dumps(transaction["order"]),
        mandate_json=json.dumps(transaction["mandate"]))
    asyncio.run(seller["order_handler"](ctx, BUYER_AGENT, order))
    assert len(ctx.sent) == 1 and ctx.sent[0][1].reference == transaction["mandate"]["hash"]


def test_unregistered_buyer_or_order_mismatch_never_gets_payment_request(seller):
    transaction = approved_transaction()
    save_transaction(seller["db_path"], transaction)
    valid_order = json.loads(json.dumps(transaction["order"]))
    cases = [("foreign-agent", valid_order, transaction["mandate"]),
             (BUYER_AGENT, {**valid_order, "amount": 1}, transaction["mandate"]),
             (BUYER_AGENT, valid_order, {**transaction["mandate"], "payee": "attacker"})]
    ctx = Context()
    handler = seller["order_handler"]
    for sender, order, mandate in cases:
        message = seller_agent.common.OrderPlaced(order_json=json.dumps(order), mandate_json=json.dumps(mandate))
        asyncio.run(handler(ctx, sender, message))
    assert not ctx.sent


def test_order_with_mismatched_mandate_hash_never_sends_request(seller):
    transaction = approved_transaction()
    changed = {**transaction["mandate"], "hash": "0" * 64}
    ctx = Context()
    message = seller_agent.common.OrderPlaced(order_json=json.dumps(transaction["order"]),
                                               mandate_json=json.dumps(changed))
    asyncio.run(seller["order_handler"](ctx, BUYER_AGENT, message))
    assert not ctx.sent


def test_order_with_nonapproved_persisted_voice_record_never_sends_request(seller):
    transaction = approved_transaction()
    transaction["mandate"]["status"] = "pending"
    save_transaction(seller["db_path"], transaction)
    ctx = Context()
    message = seller_agent.common.OrderPlaced(order_json=json.dumps(transaction["order"]),
        mandate_json=json.dumps(transaction["mandate"]))
    asyncio.run(seller["order_handler"](ctx, BUYER_AGENT, message))
    assert not ctx.sent


def test_order_rejects_duplicate_json_keys_and_shield_block(seller, monkeypatch):
    transaction = approved_transaction()
    save_transaction(seller["db_path"], transaction)
    ctx = Context()
    duplicate = seller_agent.common.OrderPlaced(
        order_json='{"id":"forged","id":"deal-seller"}',
        mandate_json=json.dumps(transaction["mandate"]))
    asyncio.run(seller["order_handler"](ctx, BUYER_AGENT, duplicate))
    assert not ctx.sent

    monkeypatch.setattr(seller_agent.common, "screen", lambda *_args, **_kwargs: {
        "verdict": "block", "reasons": ["hostile buyer payload"]})
    valid = seller_agent.common.OrderPlaced(order_json=json.dumps(transaction["order"]),
        mandate_json=json.dumps(transaction["mandate"]))
    asyncio.run(seller["order_handler"](ctx, BUYER_AGENT, valid))
    assert not ctx.sent


def test_charged_attempt_after_seller_restart_sends_exact_completion(seller):
    transaction = approved_transaction()
    save_transaction(seller["db_path"], transaction)
    first_ctx = Context()
    order = seller_agent.common.OrderPlaced(order_json=json.dumps(transaction["order"]),
                                            mandate_json=json.dumps(transaction["mandate"]))
    asyncio.run(seller["order_handler"](first_ctx, BUYER_AGENT, order))
    commit = charge_transaction(seller["db_path"], transaction)

    restarted = seller_agent.build("seller_1")
    pay_protocol = next(protocol for protocol in restarted.protocols if CommitPayment in protocol.handlers)
    commit_ctx = Context()
    asyncio.run(pay_protocol.handlers[CommitPayment](commit_ctx, BUYER_AGENT, commit))
    assert len(commit_ctx.sent) == 1 and commit_ctx.sent[0][0] == BUYER_AGENT
    assert isinstance(commit_ctx.sent[0][1], CompletePayment)
    assert commit_ctx.sent[0][1].transaction_id == "pi_test_seller_1"


def test_already_charged_attempt_still_acknowledges_after_mandate_expiry(seller):
    transaction = approved_transaction(expired=True)
    transaction["phase"] = "submitted"
    save_transaction(seller["db_path"], transaction)
    commit = charge_transaction(seller["db_path"], transaction)
    ctx = Context()
    asyncio.run(seller["handlers"][CommitPayment](ctx, BUYER_AGENT, commit))
    assert len(ctx.sent) == 1 and isinstance(ctx.sent[0][1], CompletePayment)


@pytest.mark.parametrize("changes", [
    {"transaction_id": "pi_other"}, {"reference": "other-hash"}, {"recipient": "attacker"},
    {"description": "deal other"},
    {"funds": Funds(amount="79.98", currency="USD", payment_method="stripe")},
    {"funds": Funds(amount="79.99", currency="EUR", payment_method="stripe")},
    {"funds": Funds(amount="79.99", currency="USD", payment_method="cash")},
])
def test_mismatched_commit_never_completes(seller, changes):
    transaction = approved_transaction()
    save_transaction(seller["db_path"], transaction)
    commit = charge_transaction(seller["db_path"], transaction)
    values = commit.model_dump()
    values.update(changes)
    changed = type(commit)(**values)
    ctx = Context()
    asyncio.run(seller["handlers"][CommitPayment](ctx, BUYER_AGENT, changed))
    assert not ctx.sent


def test_unregistered_commit_never_completes(seller):
    transaction = approved_transaction()
    save_transaction(seller["db_path"], transaction)
    commit = charge_transaction(seller["db_path"], transaction)
    ctx = Context()
    asyncio.run(seller["handlers"][CommitPayment](ctx, "foreign-agent", commit))
    assert not ctx.sent


def test_unknown_uncertain_or_request_mismatched_attempt_never_completes(seller):
    transaction = approved_transaction()
    save_transaction(seller["db_path"], transaction)
    unknown_ctx = Context()
    asyncio.run(seller["handlers"][CommitPayment](unknown_ctx, BUYER_AGENT, make_commit(transaction)))
    assert not unknown_ctx.sent

    uncertain = approved_transaction()
    save_transaction(seller["db_path"], uncertain)
    uncertain_commit = charge_transaction(seller["db_path"], uncertain, phase="uncertain")
    uncertain_ctx = Context()
    asyncio.run(seller["handlers"][CommitPayment](uncertain_ctx, BUYER_AGENT, uncertain_commit))
    assert not uncertain_ctx.sent

    mismatched = approved_transaction()
    save_transaction(seller["db_path"], mismatched)
    wrong_commit = charge_transaction(seller["db_path"], mismatched, wrong_request=True)
    mismatch_ctx = Context()
    asyncio.run(seller["handlers"][CommitPayment](mismatch_ctx, BUYER_AGENT, wrong_commit))
    assert not mismatch_ctx.sent


def test_reject_does_not_complete_or_log_untrusted_reason(seller):
    ctx = Context()
    event = RejectPayment(reason="secret raw buyer text")
    asyncio.run(seller["handlers"][RejectPayment](ctx, BUYER_AGENT, event))
    assert not ctx.sent
    assert all("secret raw buyer text" not in line for line in ctx.logs)

