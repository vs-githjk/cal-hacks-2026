"""#186 (audit M5-1): the money guard refuses every mandate that is not approved, with or without an approval_id.

The checks run on can_charge, on mark_used and on the MerchantSim charge path. A mutation that lets "pending" through
(can_charge accepting status pending) must fail many tests here, not two.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.mandate import HASH_FIELDS, MandateError, can_charge, mandate_hash, mark_used, new_mandate
from pay.merchant_sim import MerchantSim
from pay.replay import NS_MANDATE, NonceStore
from pay.tap import keyring, sign_request

NOW = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)
URL = "https://merchant.sim.test/v1/charge"
DEAL, BUYER, AMOUNT, PAYEE = "deal-A", "vidyut", 1299.99, "best-buy@pay.example.test"
EXPECT = {"deal_id": DEAL, "amount": AMOUNT, "payee": PAYEE}

# (state, how the mandate gets there). The hash covers neither status nor approval_id, so each stays self-consistent.
STATES = ["pending", "denied", "expired_status", "expired_clock", "used", "approved_nonce_spent"]
APPROVAL_IDS = [None, "", "   ", "appr-1", "voice-7f3a"]
BUYERS = [None, BUYER]
# Every (state, approval_id) that must be refused: each non-approved state with every approval_id, plus "approved" with a
# missing or blank approval_id (the one state that reaches the approval_id check).
CASES = [(s, a) for s in STATES for a in APPROVAL_IDS] + [("approved", a) for a in (None, "", "   ")]
REASON = {"pending": "not_approved", "denied": "denied", "expired_status": "expired", "expired_clock": "expired",
          "used": "already_used", "approved_nonce_spent": "replayed_mandate", "approved": "no_approval_id"}


def expected_reason(state, approval_id):
    blank = approval_id is None or not approval_id.strip()
    return "no_approval_id" if state == "approved_nonce_spent" and blank else REASON[state]


def mandate_in(state, approval_id):
    m = new_mandate(deal_id=DEAL, buyer_id=BUYER, amount=AMOUNT, payee=PAYEE, now=NOW)
    status = {"expired_status": "expired", "expired_clock": "approved", "approved_nonce_spent": "approved"}.get(state, state)
    m["status"] = status
    if approval_id is None:
        m.pop("approval_id", None)
    else:
        m["approval_id"] = approval_id
    store = NonceStore()
    if state == "approved_nonce_spent":
        store.consume(NS_MANDATE, m["nonce"])
    when = NOW + timedelta(minutes=11) if state == "expired_clock" else NOW
    return m, store, when


@pytest.mark.parametrize("buyer", BUYERS)
@pytest.mark.parametrize("state, approval_id", CASES)
def test_can_charge_refuses_every_state_that_is_not_approved(state, approval_id, buyer):
    m, store, when = mandate_in(state, approval_id)
    v = can_charge(m, when, store=store, buyer_id=buyer, **EXPECT)
    assert not v and v.reason == expected_reason(state, approval_id), (state, approval_id, v.reason)


@pytest.mark.parametrize("state, approval_id", CASES)
def test_mark_used_refuses_and_spends_nothing(state, approval_id):
    m, store, when = mandate_in(state, approval_id)
    spent_before = store.seen(NS_MANDATE, m["nonce"])
    with pytest.raises(MandateError):
        mark_used(m, now=when, store=store, buyer_id=BUYER, **EXPECT)
    assert store.seen(NS_MANDATE, m["nonce"]) == spent_before
    if state != "used":
        assert m["status"] != "used"


@pytest.mark.parametrize("approval_id", ["appr-1", "voice-7f3a"])
def test_pending_with_an_approval_id_is_still_not_approved(approval_id):
    """The case a status mutation would let through: pending, yet carrying an approval_id."""
    m, store, when = mandate_in("pending", approval_id)
    assert can_charge(m, when, store=store, **EXPECT).reason == "not_approved"


class FakeStripe:
    def __init__(self):
        self.calls = []

    def charge(self, *, amount_cents, currency, idempotency_key, metadata):
        self.calls.append(amount_cents)
        return {"id": f"pi_test_{len(self.calls)}", "status": "succeeded"}


def sim_handle(m, store, when):
    """A validly signed charge request for `m` through MerchantSim; returns (result, stripe calls)."""
    priv = Ed25519PrivateKey.generate()
    stripe = FakeStripe()
    sim = MerchantSim(keys=keyring(priv.public_key()), store=store, approvals={DEAL: dict(m)}.get, charger=stripe)
    body = json.dumps({"deal_id": DEAL, "mandate": m}).encode()
    headers = sign_request(method="POST", url=URL, body=body, mandate=m, private_key=priv, now=when)
    return sim.handle(method="POST", url=URL, headers=headers, body=body, now=when), stripe.calls


@pytest.mark.parametrize("state, approval_id", CASES)
def test_the_merchant_sim_never_charges_a_mandate_that_is_not_approved(state, approval_id):
    m, store, when = mandate_in(state, approval_id)
    out, calls = sim_handle(m, store, when)
    # refused for the state itself, not for a broken signature (verify_request sees a spent nonce before can_charge does)
    want = "replayed_mandate" if state == "approved_nonce_spent" else expected_reason(state, approval_id)
    assert out["status"] == "refused" and out["reason"] == want and calls == [], out


def test_an_approved_mandate_with_an_approval_id_still_charges():
    """The positive controls: the refusals above are about the state, not a broken fixture."""
    m, store, when = mandate_in("approved_nonce_spent", "appr-1")
    assert not can_charge(m, when, store=store, **EXPECT)
    assert can_charge(m, when, store=NonceStore(), buyer_id=BUYER, **EXPECT)
    out, calls = sim_handle(m, NonceStore(), when)
    assert out["status"] == "charged" and calls == [129999]


# ---------- buyer_id is bound by the hash ----------

def test_buyer_id_is_a_hash_field():
    assert "buyer_id" in HASH_FIELDS


def test_changing_the_buyer_changes_the_hash_and_fails_the_guard():
    m = new_mandate(deal_id=DEAL, buyer_id=BUYER, amount=AMOUNT, payee=PAYEE, now=NOW)
    m["status"], m["approval_id"] = "approved", "appr-1"
    assert can_charge(m, NOW, store=NonceStore(), buyer_id=BUYER, **EXPECT)
    other = dict(m, buyer_id="mallory")
    assert mandate_hash(other) != m["hash"]
    assert can_charge(other, NOW, store=NonceStore(), **EXPECT).reason == "hash_mismatch"
    assert can_charge(m, NOW, store=NonceStore(), buyer_id="mallory", **EXPECT).reason == "buyer_mismatch"
