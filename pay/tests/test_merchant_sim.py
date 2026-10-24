"""Offline-only MerchantSim tests. Every approval is produced by ApprovalService; charger is a test double."""
import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.approval import ApprovalService
from pay.mandate import new_mandate
from pay.merchant_sim import MerchantSim, StripeTestCharger, _whole_cents, receipt_keys_from_env
from pay.replay import NonceStore
from pay.tap import keyring, sign_request
from shield.receipt import sign_allow_receipt

NOW = datetime.now(timezone.utc).replace(microsecond=0)
URL = "https://merchant.sim.test/v1/charge"
BUYER = "buyer-agent-1"
PAYEE = "seller-agent-1"


class FakeStripe:
    def __init__(self, timeout_first=False):
        self.calls, self.by_key, self.timeout_first = [], {}, timeout_first

    def charge(self, *, amount_cents, currency, idempotency_key, metadata):
        args = {"amount_cents": amount_cents, "currency": currency, "key": idempotency_key, "metadata": dict(metadata)}
        self.calls.append(args)
        if self.timeout_first and len(self.calls) == 1:
            raise TimeoutError("connection lost after submit")
        if idempotency_key not in self.by_key:
            self.by_key[idempotency_key] = {"id": f"pi_test_{len(self.by_key) + 1}", "status": "succeeded"}
        return self.by_key[idempotency_key]


@pytest.fixture
def world(tmp_path):
    tap_private = Ed25519PrivateKey.generate()
    receipt_private = Ed25519PrivateKey.generate()
    mandate = new_mandate(deal_id="deal-A", buyer_id=BUYER, goal_id="goal-1", amount=749.0,
                          payee=PAYEE, now=NOW)
    approvals = ApprovalService("throwaway-test-secret-0123456789")
    session, code = approvals.issue(mandate, channel="phone", now=NOW)
    session.start_call(now=NOW)
    session.begin_listening(now=NOW)
    session.recording_ref = "cartesia:ac_test"  # call evidence, as voice_cartesia records it
    decision = session.approve(code + " approve", now=NOW + timedelta(seconds=1))
    assert decision.approved and decision.record
    transaction = {"deal_id": "deal-A", "buyer_id": BUYER, "goal_id": "goal-1", "need_id": "need-1",
        "bid_id": "bid-1", "phase": "approved", "deal": {"id": "deal-A", "goal_id": "goal-1",
        "need_id": "need-1", "bid_id": "bid-1", "amount": 749.0, "payee": PAYEE}, "order": None,
        "advocate_card": {"need_id": "need-1", "bid_id": "bid-1", "warnings": [],
        "recommendation": "buy", "wait_until": "", "call_reason": {"rule_id": "advocate.ok",
        "summary": "No problems found in the checks", "source_url": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/checks.py"},
        "rule_id": "advocate.ok", "reason": "No problems found in the checks",
        "source_url": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/checks.py"},
        "mandate": dict(mandate), "voice_approval": decision.record}
    stripe = FakeStripe()
    store_path = str(tmp_path / "merchant.sqlite")
    sim = MerchantSim(keys=keyring(tap_private.public_key()), receipt_keys=keyring(receipt_private.public_key()),
        store=NonceStore(store_path), approvals=lambda deal_id, buyer_id: transaction
        if (deal_id, buyer_id) == ("deal-A", BUYER) else None, charger=stripe)
    return tap_private, receipt_private, mandate, transaction, sim, stripe


def request_body(mandate):
    return json.dumps({"accepted_funds": [{"amount": "749.00", "currency": "USD", "payment_method": "stripe"}],
        "recipient": mandate["payee"], "deadline_seconds": 600, "reference": mandate["hash"],
        "description": "deal " + mandate["deal_id"]}, separators=(",", ":")).encode()


def signed(priv, receipt_priv, mandate, body=None, *, message_id=None, now=NOW):
    body = body or request_body(mandate)
    request_json = body.decode("utf-8")
    message_id = message_id or "req:" + hashlib.sha256(mandate["buyer_id"].encode() + b"\n" + body).hexdigest()
    receipt = sign_allow_receipt(private_key=receipt_priv, message_id=message_id, request_json=request_json,
        deal_id=mandate["deal_id"], mandate_hash=mandate["hash"], amount_cents=74900, currency="USD",
        payee=mandate["payee"], now=now)
    return {"method": "POST", "url": URL, "body": body, "receipt": receipt,
            "message_id": message_id, "buyer_id": mandate["buyer_id"],
            "headers": sign_request(method="POST", url=URL, body=body, mandate=mandate,
                                    private_key=priv, now=now)}


def test_valid_approved_payment_charges_once(world):
    priv, receipt_priv, mandate, _, sim, stripe = world
    out = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert out["status"] == "charged" and out["charge_id"] == "pi_test_1" and out["origin"] == "SIM"
    assert stripe.calls == [{"amount_cents": 74900, "currency": "USD", "key": "mandate:" + mandate["hash"],
                             "metadata": {"deal_id": "deal-A", "mandate_hash": mandate["hash"], "origin": "SIM"}}]


@pytest.mark.parametrize("receipt_change", [None, "bad", "missing_key"])
def test_missing_or_invalid_receipt_fails_before_charger(world, receipt_change):
    priv, receipt_priv, mandate, _, sim, stripe = world
    req = signed(priv, receipt_priv, mandate)
    if receipt_change == "bad":
        req["receipt"]["verdict"] = "block"
    elif receipt_change == "missing_key":
        sim.receipt_keys = {}
    else:
        req["receipt"] = None
    out = sim.handle(**req, now=NOW)
    assert out["status"] == "refused" and not stripe.calls


def test_replayed_signed_request_is_refused(world):
    priv, receipt_priv, mandate, _, sim, stripe = world
    req = signed(priv, receipt_priv, mandate)
    assert sim.handle(**req, now=NOW)["status"] == "charged"
    replay = sim.handle(**req, now=NOW)
    assert replay["status"] == "refused" and not replay.get("charge_id") and len(stripe.calls) == 1


def test_stale_request_cannot_charge_after_atomic_unsubmitted_retirement(world):
    priv, receipt_priv, mandate, _, sim, stripe = world
    req = signed(priv, receipt_priv, mandate)
    body = req["body"]
    attempt = sim.store.retirement_attempt(mandate_hash=mandate["hash"], buyer_id=BUYER,
        deal_id=mandate["deal_id"], request_body=body, amount_cents=74900, currency="USD", payee=PAYEE)
    assert sim.store.retire_unsubmitted_attempt(attempt, mandate["nonce"]) is True
    stale = sim.handle(**req, now=NOW)
    assert stale["status"] == "refused" and not stripe.calls


def test_wrong_buyer_or_request_amount_is_refused(world):
    priv, receipt_priv, mandate, _, sim, stripe = world
    req = signed(priv, receipt_priv, mandate)
    req["buyer_id"] = "another-buyer"
    assert sim.handle(**req, now=NOW)["status"] == "refused"
    changed_body = request_body(mandate).replace(b"749.00", b"7.49")
    assert sim.handle(**signed(priv, receipt_priv, mandate, changed_body, message_id="req:changed"), now=NOW)["status"] == "refused"
    assert not stripe.calls


@pytest.mark.parametrize("field", ["recipient", "reference", "amount"])
def test_merchant_refuses_duplicate_json_keys_before_charging(world, field):
    priv, receipt_priv, mandate, _, sim, stripe = world
    body = request_body(mandate)
    originals = {"recipient": '"recipient":"seller-agent-1"', "reference": f'"reference":"{mandate["hash"]}"',
                 "amount": '"amount":"749.00"'}
    replacements = {"recipient": '"recipient":"attacker","recipient":"seller-agent-1"',
                    "reference": f'"reference":"wrong","reference":"{mandate["hash"]}"',
                    "amount": '"amount":"1.00","amount":"749.00"'}
    body = body.replace(originals[field].encode(), replacements[field].encode())
    result = sim.handle(**signed(priv, receipt_priv, mandate, body), now=NOW)
    assert result["status"] == "refused" and not stripe.calls


@pytest.mark.parametrize("amount", [" 749.00 ", "7.499E+2"])
def test_merchant_refuses_noncanonical_wire_amount(world, amount):
    priv, receipt_priv, mandate, _, sim, stripe = world
    body = request_body(mandate).replace(b"749.00", amount.encode())
    result = sim.handle(**signed(priv, receipt_priv, mandate, body), now=NOW)
    assert result["status"] == "refused" and not stripe.calls


def test_timeout_is_uncertain_and_only_local_reconcile_retries_identically(world):
    priv, receipt_priv, mandate, _, sim, stripe = world
    stripe.timeout_first = True
    req = signed(priv, receipt_priv, mandate)
    out = sim.handle(**req, now=NOW)
    assert out["status"] == "uncertain" and out["charge_id"] is None
    attempt = sim.store.get_payment_attempt(mandate["hash"])
    assert attempt["phase"] == "uncertain" and sim.store.seen("mandate", mandate["nonce"])
    retry = signed(priv, receipt_priv, mandate, now=NOW + timedelta(seconds=2))
    assert sim.handle(**retry, now=NOW + timedelta(seconds=2))["status"] == "refused"
    assert len(stripe.calls) == 1
    recovered = sim.reconcile(deal_id="deal-A", buyer_id=BUYER, mandate_hash=mandate["hash"])
    assert recovered["status"] == "charged" and recovered["charge_id"] == "pi_test_1"
    assert len(stripe.calls) == 2 and stripe.calls[0] == stripe.calls[1]


def test_charged_readback_returns_saved_result_without_charger(world):
    priv, receipt_priv, mandate, _, sim, stripe = world
    assert sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)["status"] == "charged"
    calls = len(stripe.calls)
    result = sim.reconcile(deal_id="deal-A", buyer_id=BUYER, mandate_hash=mandate["hash"])
    assert result["status"] == "charged" and result["charge_id"] == "pi_test_1"
    assert len(stripe.calls) == calls


@pytest.mark.parametrize("field,value", [
    ("id", "apr_wrong"), ("amount_read_back", 1), ("payee_read_back", "attacker"),
    ("decided_at", "2099-01-01T00:00:00Z"),
])
def test_voice_approval_must_bind_id_readback_and_decision_time(world, field, value):
    priv, receipt_priv, mandate, transaction, sim, stripe = world
    transaction["voice_approval"][field] = value
    result = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert result["status"] == "refused" and not stripe.calls


LIMITS = {"per_purchase_limit": 800.0, "period_limit": 1000.0, "spent_this_period": 0.0}


def test_allowance_is_a_distinct_stored_authorization_not_a_voice_approval(world):
    priv, receipt_priv, mandate, transaction, sim, stripe = world
    transaction["mandate"]["within_allowance"] = True
    mandate["within_allowance"] = True
    transaction["voice_approval"] = None
    stored_mandate = transaction["mandate"]
    transaction["allowance_authorization"] = {"id": stored_mandate["approval_id"], "mandate_hash": stored_mandate["hash"],
        "mandate_id": stored_mandate["id"], "deal_id": stored_mandate["deal_id"], "buyer_id": stored_mandate["buyer_id"],
        "goal_id": stored_mandate["goal_id"], "amount": stored_mandate["amount"], "payee": stored_mandate["payee"],
        "method": "allowance", "approved_at": NOW.isoformat(), **LIMITS}
    out = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert out["status"] == "charged", out
    assert transaction["voice_approval"] is None


def test_market_typed_approval_row_is_not_voice_or_allowance_authorization(world):
    priv, receipt_priv, mandate, transaction, sim, stripe = world
    transaction["voice_approval"] = None
    stored = transaction["mandate"]
    transaction["allowance_authorization"] = {"id": stored["approval_id"], "mandate_hash": stored["hash"],
        "mandate_id": stored["id"], "deal_id": stored["deal_id"], "buyer_id": stored["buyer_id"],
        "goal_id": stored["goal_id"], "amount": stored["amount"], "payee": stored["payee"],
        "method": "typed", "approved_at": NOW.isoformat()}
    result = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert result["status"] == "refused" and not stripe.calls


@pytest.mark.parametrize("field,value", [("id", "different"), ("amount", 1), ("payee", "attacker")])
def test_allowance_binding_mismatch_never_charges(world, field, value):
    priv, receipt_priv, mandate, transaction, sim, stripe = world
    transaction["mandate"]["within_allowance"] = True
    mandate["within_allowance"] = True
    transaction["voice_approval"] = None
    stored_mandate = transaction["mandate"]
    transaction["allowance_authorization"] = {"id": stored_mandate["approval_id"], "mandate_hash": stored_mandate["hash"],
        "mandate_id": stored_mandate["id"], "deal_id": stored_mandate["deal_id"], "buyer_id": stored_mandate["buyer_id"],
        "goal_id": stored_mandate["goal_id"], "amount": stored_mandate["amount"], "payee": stored_mandate["payee"],
        "method": "allowance", "approved_at": NOW.isoformat(), **LIMITS}
    transaction["allowance_authorization"][field] = value
    out = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert out["status"] == "refused" and not stripe.calls


def test_parallel_sims_share_one_atomic_mandate_claim(world):
    priv, receipt_priv, mandate, _, sim, stripe = world
    second = MerchantSim(keys=sim.keys, receipt_keys=sim.receipt_keys,
        store=NonceStore(sim.store._path), approvals=sim.approvals, charger=stripe)
    requests = [signed(priv, receipt_priv, mandate), signed(priv, receipt_priv, mandate)]
    barrier = threading.Barrier(2)
    results = [None, None]

    def submit(index, merchant):
        barrier.wait()
        results[index] = merchant.handle(**requests[index], now=NOW)

    threads = [threading.Thread(target=submit, args=(0, sim)),
               threading.Thread(target=submit, args=(1, second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert [result["status"] for result in results].count("charged") == 1
    assert len(stripe.calls) == 1


def test_constructing_second_sim_does_not_recover_inflight_submission(world):
    priv, receipt_priv, mandate, _, sim, stripe = world
    entered, release = threading.Event(), threading.Event()

    class BlockedStripe(FakeStripe):
        def charge(self, **kwargs):
            entered.set()
            assert release.wait(timeout=5)
            return super().charge(**kwargs)

    blocked = BlockedStripe()
    sim.charger = blocked
    req = signed(priv, receipt_priv, mandate)
    result = []
    worker = threading.Thread(target=lambda: result.append(sim.handle(**req, now=NOW)))
    worker.start()
    assert entered.wait(timeout=5)
    attempt = sim.store.get_payment_attempt(mandate["hash"])
    assert attempt["phase"] == "submitted"
    MerchantSim(keys=sim.keys, receipt_keys=sim.receipt_keys, store=NonceStore(sim.store._path),
        approvals=sim.approvals, charger=blocked)
    assert sim.store.get_payment_attempt(mandate["hash"])["phase"] == "submitted"
    release.set()
    worker.join(timeout=5)
    assert result[0]["status"] == "charged"


def test_expired_uncertain_attempt_is_not_resubmitted_and_settled_charge_cache_survives(world, monkeypatch):
    priv, receipt_priv, mandate, _, sim, stripe = world
    stripe.timeout_first = True
    result = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert result["status"] == "uncertain"
    monkeypatch.setattr("pay.merchant_sim.verify_mandate", lambda _mandate: False)
    calls = len(stripe.calls)
    expired = sim.reconcile(deal_id="deal-A", buyer_id=BUYER, mandate_hash=mandate["hash"])
    assert expired["status"] == "uncertain" and len(stripe.calls) == calls
    assert sim.store.claim_uncertain_attempt("deal-A", BUYER, mandate["hash"])
    assert sim.store.finish_payment_attempt(mandate["hash"], "charged", charge_id="pi_test_cached")
    _, _, _, transaction, _, _ = world
    transaction["phase"] = "settled"
    cached = sim.reconcile(deal_id="deal-A", buyer_id=BUYER, mandate_hash=mandate["hash"])
    assert cached["status"] == "charged" and cached["charge_id"] == "pi_test_cached"
    assert len(stripe.calls) == calls


def test_stripe_charger_rejects_live_or_missing_key():
    with pytest.raises(ValueError):
        StripeTestCharger(secret_key="sk_live_123")
    with pytest.raises(ValueError):
        StripeTestCharger(secret_key="")


def test_missing_receipt_keyring_is_not_a_compatibility_mode(monkeypatch):
    from pay.merchant_sim import MerchantSim
    with pytest.raises(ValueError, match="keyrings are required"):
        MerchantSim(keys={}, receipt_keys={}, store=NonceStore(), approvals=lambda deal, buyer: None, charger=FakeStripe())
    monkeypatch.delenv("SHIELD_RECEIPT_PUBKEYS", raising=False)
    assert receipt_keys_from_env() == {}
    monkeypatch.setenv("SHIELD_RECEIPT_PUBKEYS", "not-base64!")
    with pytest.raises(ValueError, match="SHIELD_RECEIPT_PUBKEYS is invalid"):
        receipt_keys_from_env()


@pytest.mark.parametrize("amount", ["sNaN", "1e999999"])
def test_merchant_amount_parser_rejects_nonfinite_and_unbounded_decimal(amount):
    assert _whole_cents(amount) is None


@pytest.mark.parametrize("channel", ["typed", "browser", None, "PHONE"])
def test_only_a_phone_call_approval_charges(world, channel):
    # #214: approval is by phone call only; a typed, browser, missing or odd-case channel never charges
    priv, receipt_priv, mandate, transaction, sim, stripe = world
    record = dict(transaction["voice_approval"])
    if channel is None:
        record.pop("channel")
    else:
        record["channel"] = channel
    transaction["voice_approval"] = record
    out = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert out["status"] == "refused" and not stripe.calls


@pytest.mark.parametrize("ref", [None, "", "typed", "cartesia:", "browser:ac_1", "cartesia:ac 1"])
def test_phone_approval_without_call_evidence_never_charges(world, ref):
    # #277: channel "phone" is only a label; a typed approve() on a phone session has no cartesia:<call_id>
    priv, receipt_priv, mandate, transaction, sim, stripe = world
    transaction["voice_approval"] = dict(transaction["voice_approval"], recording_ref=ref)
    out = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert out["status"] == "refused" and not stripe.calls


@pytest.mark.parametrize("limits", [
    {"per_purchase_limit": 700.0, "period_limit": 1000.0, "spent_this_period": 0.0},   # over the per-purchase limit
    {"per_purchase_limit": 800.0, "period_limit": 1000.0, "spent_this_period": 300.0},  # over the period remainder
    {"per_purchase_limit": 800.0, "period_limit": 1000.0},                              # spent unknown
    {},                                                                                 # allowance unknown
    {"per_purchase_limit": True, "period_limit": 1000.0, "spent_this_period": 0.0},     # not a number
])
def test_forged_within_allowance_above_the_limit_never_charges(world, limits):
    # #214: within_allowance alone is not proof; the amount must fit the allowance the record was checked against
    priv, receipt_priv, mandate, transaction, sim, stripe = world
    transaction["mandate"]["within_allowance"] = True
    mandate["within_allowance"] = True
    transaction["voice_approval"] = None
    stored = transaction["mandate"]
    transaction["allowance_authorization"] = {"id": stored["approval_id"], "mandate_hash": stored["hash"],
        "mandate_id": stored["id"], "deal_id": stored["deal_id"], "buyer_id": stored["buyer_id"],
        "goal_id": stored["goal_id"], "amount": stored["amount"], "payee": stored["payee"],
        "method": "allowance", "approved_at": NOW.isoformat(), **limits}
    out = sim.handle(**signed(priv, receipt_priv, mandate), now=NOW)
    assert out["status"] == "refused" and not stripe.calls
