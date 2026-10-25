import hashlib
import json
import copy
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agents.buyer import checkout
from agents.buyer.checkout import format_settlement_result
from agents.advocate.checks import CALL_SUMMARIES
from pay.approval import ApprovalService
from pay.mandate import new_mandate
from pay.tap import keyring, verify_request
from pay.replay import NonceStore
from agents.payment import _authorized, commit as commit_payment, payment_request
from pay.approval import VOICE_CODE_TTL_SECONDS
from pay.merchant_sim import MerchantSim
from shield.receipt import sign_allow_receipt

NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def tx():
    mandate = new_mandate(deal_id="deal-1", buyer_id="buyer-1", goal_id="goal-1", amount=79.99,
                          payee="seller-1", now=NOW)
    summary = CALL_SUMMARIES["advocate.ok"]
    return {"deal_id": "deal-1", "buyer_id": "buyer-1", "goal_id": "goal-1", "need_id": "need-1",
            "bid_id": "bid-1", "phase": "pending_approval", "deal": {"id": "deal-1", "goal_id": "goal-1",
            "need_id": "need-1", "bid_id": "bid-1", "amount": 79.99, "payee": "seller-1"},
            "order": None, "advocate_card": {"need_id": "need-1", "bid_id": "bid-1", "warnings": [],
            "claim_checks": [],
            "recommendation": "buy", "wait_until": "", "call_reason": {"rule_id": "advocate.ok",
            "summary": summary, "source_url": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/checks.py"},
            "rule_id": "advocate.ok", "reason": summary,
            "source_url": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/checks.py"},
            "mandate": mandate, "voice_approval": None,
            "allowance_authorization": None, "settlement": None, "settlement_result": None,
            "payment_ref": None, "mode": None}


def approved_record(tx):
    service = ApprovalService("checkout-test-secret-987654321", code_ttl_seconds=VOICE_CODE_TTL_SECONDS)
    session, code = service.issue(copy.deepcopy(tx["mandate"]), channel="phone", now=NOW)
    session.start_call(now=NOW)
    session.begin_listening(now=NOW)
    session.recording_ref = "cartesia:ac_test"  # call evidence, as voice_cartesia records it
    return session.approve(code + " approve", now=NOW + timedelta(seconds=1)).record


def set_approved(tx):
    record = approved_record(tx)
    tx["voice_approval"] = record
    tx["mandate"]["status"] = "approved"
    tx["mandate"]["approval_id"] = record["id"]
    tx["phase"] = "approved"


def test_approve_offer_rejects_falsey_non_callable_clock(tx):
    class Falsey:
        def __bool__(self):
            return False

    with pytest.raises(ValueError, match="callable"):
        checkout.approve_offer(tx, object(), object(), on_code=lambda _code: None, now=Falsey())


def test_approve_offer_uses_stored_transaction_reason_and_private_callback(monkeypatch, tx):
    seen = {}
    record = approved_record(tx)

    def runner(mandate, reason, client, service, **kwargs):
        seen.update(mandate=mandate, reason=reason, client=client, service=service)
        kwargs["on_code"]("one time code")
        mandate["approval_id"] = record["id"]
        mandate["status"] = "approved"
        from pay.voice_cartesia import VoiceResult
        return VoiceResult(True, None, record=record)

    monkeypatch.setattr(checkout, "run_approval_call", runner)
    sent = []
    service = object()
    result = checkout.approve_offer(tx, object(), service, on_code=sent.append)
    assert result.approved and sent == ["one time code"]
    assert seen["reason"] == {"rule_id": "advocate.ok", "summary": "No problems found in the checks",
                              "source_url": tx["advocate_card"]["source_url"]}
    assert seen["mandate"]["hash"] == tx["mandate"]["hash"]
    assert tx["mandate"]["status"] == "pending"  # adapter never mutates stored state


def test_approve_offer_threads_business_clock_to_voice_and_bound_checks(monkeypatch, tx):
    from pay.voice_cartesia import VoiceResult

    clock = lambda: NOW
    seen = {}

    def runner(_mandate, _reason, _client, _service, **kwargs):
        seen.update(kwargs)
        return VoiceResult(False, "no_answer")

    monkeypatch.setattr(checkout, "run_approval_call", runner)
    result = checkout.approve_offer(tx, object(), object(), on_code=lambda _code: None, now=clock)
    assert not result.approved
    assert callable(seen["now"]) and seen["now"]() == NOW


def test_bound_transaction_checks_mandate_at_injected_business_time(tx):
    expired = NOW + timedelta(hours=1)
    with pytest.raises(ValueError, match="expired"):
        checkout._bound_transaction(tx, approval_phase=True, now=expired)


def test_payment_allowance_authorization_uses_injected_business_time(tx):
    tx["mandate"]["within_allowance"] = True
    approved_at = NOW + timedelta(days=1)
    tx["allowance_authorization"] = {
        "id": "allowance-1", "mandate_hash": tx["mandate"]["hash"],
        "mandate_id": tx["mandate"]["id"], "deal_id": tx["deal_id"], "buyer_id": tx["buyer_id"],
        "goal_id": tx["goal_id"], "amount": tx["mandate"]["amount"], "payee": tx["mandate"]["payee"],
        "method": "allowance", "approved_at": approved_at.isoformat(),
    }
    tx["mandate"].update(status="approved", approval_id="allowance-1")
    assert _authorized(tx, tx["mandate"], now=approved_at + timedelta(seconds=1))


def test_settle_offer_uses_same_business_time_for_expiry_before_merchant(tx):
    set_approved(tx)
    called = []

    class Merchant:
        def handle(self, **_kwargs):
            called.append(True)
            return {}

    with pytest.raises(ValueError, match="expired"):
        checkout.settle_offer(tx, payment_request(tx["mandate"], "seller-1"), Merchant(),
            receipt={"receipt_id": "r", "keyid": "k"}, message_id="unused",
            tap_private_key=Ed25519PrivateKey.generate(), now=NOW + timedelta(hours=1))
    assert not called


@pytest.mark.parametrize("mutation", [
    lambda tx: tx.update(buyer_id="attacker"),
    lambda tx: tx["deal"].update(amount=1),
    lambda tx: tx.update(advocate_card={"need_id": "n", "bid_id": "other"}),
])
def test_approve_offer_fails_closed_on_mismatched_frozen_transaction(monkeypatch, tx, mutation):
    mutation(tx)
    monkeypatch.setattr(checkout, "run_approval_call", lambda *a, **k: pytest.fail("must not dial"))
    with pytest.raises((ValueError, PermissionError)):
        checkout.approve_offer(tx, object(), object(), on_code=lambda code: None)


def test_code_delivery_failure_prevents_call(monkeypatch, tx):
    def runner(*args, **kwargs):
        kwargs["on_code"]("private code")
        pytest.fail("must stop before call")

    monkeypatch.setattr(checkout, "run_approval_call", runner)
    def failed(_code):
        raise RuntimeError("private channel unavailable")
    with pytest.raises(PermissionError, match="private approval code delivery failed"):
        checkout.approve_offer(tx, object(), object(), on_code=failed)


def test_approve_offer_rejects_awaitable_delivery_callback(monkeypatch, tx):
    async def private_send(_code):
        return True
    def runner(*args, **kwargs):
        kwargs["on_code"]("private code")
        pytest.fail("must not dial")
    monkeypatch.setattr(checkout, "run_approval_call", runner)
    with pytest.raises(PermissionError, match="private approval code delivery failed"):
        checkout.approve_offer(tx, object(), object(), on_code=private_send)


@pytest.mark.parametrize("amount", ["sNaN", "1e999999"])
def test_checkout_cents_parser_rejects_nonfinite_and_unbounded_decimal(amount):
    assert checkout._cents(amount) is None


@pytest.mark.parametrize("mode", ["SIM", "stripe_test"])
def test_settle_offer_signs_and_submits_exact_bytes_and_binding(tx, mode):
    set_approved(tx)
    tx["mode"] = mode
    private = Ed25519PrivateKey.generate()
    req = payment_request(tx["mandate"], "seller-1")
    body = req.model_dump_json().encode("utf-8")
    message_id = "req:" + hashlib.sha256(b"buyer-1\n" + body).hexdigest()
    seen = {}

    class Merchant:
        def handle(self, **kwargs):
            seen.update(kwargs)
            return {"status": "charged", "reason": "ok", "charge_id": "pi_test_1",
                    "mandate_hash": tx["mandate"]["hash"], "origin": "SIM"}

    result = checkout.settle_offer(tx, req, Merchant(), receipt={"receipt_id": "r", "keyid": "k"},
        message_id=message_id, tap_private_key=private, merchant_url="https://merchant.test/pay", now=NOW)
    assert result["settlement_result"]["status"] == "charged"
    assert result["settlement_result"]["origin"] == "SIM"
    assert result["settlement"]["mode"] == mode
    assert format_settlement_result(result).startswith(f"{mode} payment confirmed")
    tx.update(phase="submitted", settlement=result["settlement"],
              settlement_result=result["settlement_result"], payment_ref=result["settlement_result"]["charge_id"])
    assert commit_payment(req, tx, now=NOW).transaction_id == result["settlement_result"]["charge_id"]
    assert seen["body"] == body and seen["message_id"] == message_id and seen["buyer_id"] == "buyer-1"
    verdict = verify_request(method=seen["method"], url=seen["url"], headers=seen["headers"], body=body,
        keys=keyring(private.public_key()), store=NonceStore(), now=NOW,
        expected_mandate_hash=tx["mandate"]["hash"], mandate=tx["mandate"])
    assert verdict


@pytest.mark.parametrize("change", [
    {"recipient": "attacker"}, {"reference": "wrong"}, {"description": "deal other"},
])
def test_settle_offer_rejects_request_drift_before_merchant(tx, change):
    set_approved(tx)
    values = payment_request(tx["mandate"], "seller-1").model_dump()
    values.update(change)
    req = type(payment_request(tx["mandate"], "seller-1"))(**values)
    called = []
    with pytest.raises(PermissionError):
        checkout.settle_offer(tx, req, object(), receipt={}, message_id="bad",
                              tap_private_key=Ed25519PrivateKey.generate())
    assert not called


def test_300_second_voice_approval_passes_adapter_merchant_and_commit(tx, tmp_path):
    tx["mode"] = "SIM"

    class FakeVoiceClient:
        approval_call_to = "+14155550123"

        def __init__(self):
            self.code = None
            self.started_at = None

        def create_call(self, _to_number, _variables):
            self.started_at = datetime.now(timezone.utc)
            return "call-test"

        def get_call(self, call_id):
            return {"id": call_id, "status": "completed", "end_reason": "agent_hangup",
                    "start_time": self.started_at.isoformat(), "transcript": [{"role": "user",
                    "text": f"{self.code} approve", "start_timestamp": 1.0, "end_timestamp": 3.0}]}

    voice_client = FakeVoiceClient()
    service = ApprovalService("checkout-integration-secret-12345", store=NonceStore(),
                              code_ttl_seconds=VOICE_CODE_TTL_SECONDS)
    private_code_screen = []

    def private_send(code):
        private_code_screen.append(code)
        voice_client.code = code

    voice = checkout.approve_offer(tx, voice_client, service, on_code=private_send)
    assert voice.approved and voice.record and len(private_code_screen) == 1
    issued = datetime.fromisoformat(voice.record["code_issued_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(voice.record["code_expires_at"].replace("Z", "+00:00"))
    assert (expires - issued).total_seconds() == 300

    tx["voice_approval"] = voice.record
    tx["mandate"]["status"] = "approved"
    tx["mandate"]["approval_id"] = voice.record["id"]
    tx["phase"] = "approved"
    req = payment_request(tx["mandate"], "seller-1")
    body = req.model_dump_json().encode("utf-8")
    message_id = "req:" + hashlib.sha256(b"buyer-1\n" + body).hexdigest()
    tap_private, receipt_private = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    current = datetime.now(timezone.utc)
    receipt = sign_allow_receipt(private_key=receipt_private, message_id=message_id,
        request_json=body.decode("utf-8"), deal_id="deal-1", mandate_hash=tx["mandate"]["hash"],
        amount_cents=7999, currency="USD", payee="seller-1", now=current)

    class FakeStripe:
        def charge(self, **_kwargs):
            return {"id": "pi_test_voice_300", "status": "succeeded"}

    store = NonceStore(str(tmp_path / "checkout.sqlite"))
    merchant = MerchantSim(keys=keyring(tap_private.public_key()), receipt_keys=keyring(receipt_private.public_key()),
        store=store, approvals=lambda deal_id, buyer_id: tx if (deal_id, buyer_id) == ("deal-1", "buyer-1") else None,
        charger=FakeStripe())
    settlement = checkout.settle_offer(tx, req, merchant, receipt=receipt, message_id=message_id,
        tap_private_key=tap_private, merchant_url="https://merchant.test/pay", now=current)
    assert settlement["settlement_result"]["status"] == "charged"
    tx.update(phase="submitted", settlement=settlement["settlement"],
              settlement_result=settlement["settlement_result"],
              payment_ref=settlement["settlement_result"]["charge_id"])
    committed = commit_payment(req, tx, now=current)
    assert committed.transaction_id == "pi_test_voice_300"


@pytest.mark.parametrize("uncertain", [False, True])
def test_settle_offer_returns_the_tap_signed_mandate_used_by_merchant(tx, tmp_path, uncertain):
    set_approved(tx)
    original_mandate = copy.deepcopy(tx["mandate"])
    req = payment_request(tx["mandate"], "seller-1")
    body = req.model_dump_json().encode("utf-8")
    message_id = "req:" + hashlib.sha256(b"buyer-1\n" + body).hexdigest()
    tap_private, receipt_private = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    now = datetime.now(timezone.utc)
    receipt = sign_allow_receipt(private_key=receipt_private, message_id=message_id,
        request_json=body, deal_id="deal-1", mandate_hash=tx["mandate"]["hash"],
        amount_cents=7999, currency="USD", payee="seller-1", now=now)

    class FakeStripe:
        def charge(self, **_kwargs):
            if uncertain:
                raise TimeoutError("test-only unknown outcome")
            return {"id": "pi_test_signed_mandate", "status": "succeeded"}

    merchant = MerchantSim(keys=keyring(tap_private.public_key()),
        receipt_keys=keyring(receipt_private.public_key()),
        store=NonceStore(str(tmp_path / "signed-mandate.sqlite")),
        approvals=lambda deal_id, buyer_id: tx if (deal_id, buyer_id) == ("deal-1", "buyer-1") else None,
        charger=FakeStripe())
    submitted = {}
    handle = merchant.handle

    def capture_request(**kwargs):
        submitted.update(kwargs)
        return handle(**kwargs)

    merchant.handle = capture_request
    envelope = checkout.settle_offer(tx, req, merchant, receipt=receipt, message_id=message_id,
        tap_private_key=tap_private, merchant_url="https://merchant.test/pay", now=now)
    assert envelope["settlement_result"]["status"] == ("uncertain" if uncertain else "charged")
    assert verify_request(method=submitted["method"], url=submitted["url"],
        headers=submitted["headers"], body=submitted["body"],
        keys=keyring(tap_private.public_key()), store=NonceStore(), now=now,
        expected_mandate_hash=tx["mandate"]["hash"], mandate=envelope["mandate"])
    assert envelope["mandate"]["tap_signature"] == submitted["headers"]["Signature"]
    assert tx["mandate"] == original_mandate
