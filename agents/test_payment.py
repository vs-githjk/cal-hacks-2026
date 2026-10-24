import json
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from uagents_core.contrib.protocols.payment import Funds

import payment
from pay.approval import ApprovalService
from pay.mandate import new_mandate

NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def checkout():
    mandate = new_mandate(deal_id="deal-1", buyer_id="buyer-1", goal_id="goal-1", amount=79.99,
                          payee="seller-1", now=NOW)
    service = ApprovalService("test-secret-for-payment-commit")
    session, code = service.issue(mandate, now=NOW)
    session.start_call(now=NOW)
    session.begin_listening(now=NOW)
    voice = session.approve(code + " approve", now=NOW + timedelta(seconds=1)).record
    assert voice and voice["result"] == "approved"
    tx = {"deal_id": "deal-1", "buyer_id": "buyer-1", "goal_id": "goal-1", "need_id": "need-1",
          "bid_id": "bid-1", "phase": "submitted", "deal": {"id": "deal-1", "goal_id": "goal-1",
          "need_id": "need-1", "bid_id": "bid-1", "amount": 79.99, "payee": "seller-1"},
          "order": {"id": "order-1", "need_id": "need-1", "bid_id": "bid-1", "amount": 79.99,
                    "approved_by": "buyer-1", "approval_id": "approval-1", "limit_checked": True,
                    "idempotency_key": "mandate:" + mandate["hash"], "payment_ref": "", "status": "PENDING"},
          "advocate_card": {"need_id": "need-1", "bid_id": "bid-1", "warnings": [],
                            "recommendation": "buy", "wait_until": "", "call_reason": {"rule_id": "advocate.ok",
                            "summary": "No problems found in the checks", "source_url": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/checks.py"},
                            "rule_id": "advocate.ok", "reason": "No problems found in the checks",
                            "source_url": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/checks.py"},
          "mandate": mandate, "voice_approval": voice, "allowance_authorization": None,
          "settlement": None,
          "settlement_result": {"status": "charged", "charge_id": "pi_test_123", "mandate_hash": mandate["hash"], "origin": "SIM"},
          "payment_ref": "pi_test_123", "mode": "SIM"}
    req = payment.payment_request(mandate, "seller-1")
    body = req.model_dump_json().encode("utf-8")
    tx["settlement"] = {"message_id": "req:" + hashlib.sha256(b"buyer-1\n" + body).hexdigest(),
        "request_sha256": hashlib.sha256(body).hexdigest(), "mandate_hash": mandate["hash"],
        "deal_id": "deal-1", "buyer_id": "buyer-1", "amount_cents": 7999, "currency": "USD",
        "payee": "seller-1", "idempotency_key": "mandate:" + mandate["hash"], "receipt_keyid": "shield-test"}
    return tx, req


def test_commit_requires_real_approved_transaction_and_paid_stripe_result(checkout):
    tx, req = checkout
    result = payment.commit(req, tx, now=NOW)
    assert result.transaction_id == "pi_test_123"
    assert result.reference == tx["mandate"]["hash"]
    assert result.funds.amount == "79.99"


def test_commit_accepts_stored_allowance_authorization_without_fabricating_voice(checkout):
    tx, req = checkout
    tx["voice_approval"] = None
    tx["mandate"]["within_allowance"] = True
    tx["allowance_authorization"] = {"id": tx["mandate"]["approval_id"], "mandate_hash": tx["mandate"]["hash"],
        "mandate_id": tx["mandate"]["id"], "deal_id": tx["deal_id"], "buyer_id": tx["buyer_id"],
        "goal_id": tx["goal_id"], "amount": tx["mandate"]["amount"], "payee": tx["mandate"]["payee"],
        "method": "allowance", "approved_at": NOW.isoformat()}
    assert payment.commit(req, tx, now=NOW).transaction_id == "pi_test_123"
    assert tx["voice_approval"] is None


def test_commit_does_not_treat_market_typed_approval_as_voice_or_allowance(checkout):
    tx, req = checkout
    tx["voice_approval"] = None
    tx["mandate"]["within_allowance"] = True
    tx["allowance_authorization"] = {"id": tx["mandate"]["approval_id"],
        "mandate_hash": tx["mandate"]["hash"], "mandate_id": tx["mandate"]["id"],
        "deal_id": tx["deal_id"], "buyer_id": tx["buyer_id"], "goal_id": tx["goal_id"],
        "amount": tx["mandate"]["amount"], "payee": tx["mandate"]["payee"],
        "method": "typed", "approved_at": NOW.isoformat()}
    with pytest.raises(PermissionError):
        payment.commit(req, tx, now=NOW)


@pytest.mark.parametrize("mutate", [
    lambda tx: tx.update(voice_approval=None),
    lambda tx: tx["voice_approval"].update(result="denied"),
    lambda tx: tx["voice_approval"].update(mandate_hash="wrong"),
    lambda tx: tx.update(settlement_result={"status": "uncertain", "charge_id": None}),
    lambda tx: tx["settlement_result"].update(charge_id="mandate:" + tx["mandate"]["hash"]),
    lambda tx: tx["settlement_result"].update(mandate_hash="wrong"),
    lambda tx: tx["settlement"].update(request_sha256="wrong"),
    lambda tx: tx["settlement"].update(message_id="req:wrong"),
    lambda tx: tx.update(payment_ref="other"),
    lambda tx: tx.update(phase="approved"),
])
def test_commit_refuses_unapproved_or_unpaid_or_mismatched_transaction(checkout, mutate):
    tx, req = checkout
    tx = json.loads(json.dumps(tx))
    mutate(tx)
    with pytest.raises(PermissionError):
        payment.commit(req, tx, now=NOW)


@pytest.mark.parametrize("change", [
    {"recipient": "attacker"}, {"reference": "other"}, {"description": "deal other"},
    {"accepted_funds": []},
    {"accepted_funds": [Funds(amount="79.98", currency="USD", payment_method="stripe")]},
    {"accepted_funds": [Funds(amount="79.99", currency="EUR", payment_method="stripe")]},
])
def test_commit_refuses_payment_request_drift(checkout, change):
    tx, req = checkout
    values = req.model_dump()
    values.update(change)
    altered = type(req)(**values)
    with pytest.raises(PermissionError):
        payment.commit(altered, tx, now=NOW)


def test_commit_refuses_expired_or_corrupt_mandate(checkout):
    tx, req = checkout
    with pytest.raises(PermissionError):
        payment.commit(req, tx, now=NOW.replace(year=2027))
    tx["mandate"]["amount"] = 1
    with pytest.raises(PermissionError):
        payment.commit(req, tx, now=NOW)


def test_mandate_factory_delegates_to_canonical_builder(monkeypatch):
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return {"hash": "canonical"}

    monkeypatch.setattr(payment, "_new_mandate", fake)
    assert payment.make_mandate("d", 12.5, "s", "b", True, goal_id="g", now=NOW) == {"hash": "canonical"}
    assert seen["deal_id"] == "d" and seen["buyer_id"] == "b" and seen["goal_id"] == "g"


@pytest.mark.parametrize("amount", ["sNaN", "1e999999"])
def test_amount_parser_rejects_nonfinite_and_unbounded_decimal_without_crashing(amount):
    assert payment._cents(amount) is None
