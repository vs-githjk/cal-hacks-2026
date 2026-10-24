"""c5 merchant simulator (Lane C): verifies the TAP-style signature and mandate, then runs a Stripe test charge."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.mandate import new_mandate
from pay.merchant_sim import MerchantSim, StripeTestCharger
from pay.replay import NonceStore
from pay.tap import keyring, sign_request

NOW = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)
URL = "https://merchant.sim.test/v1/charge"


class FakeStripe:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def charge(self, *, amount_cents, currency, idempotency_key, metadata):
        self.calls.append({"amount_cents": amount_cents, "currency": currency, "key": idempotency_key, **metadata})
        if self.fail:
            raise RuntimeError("card_declined")
        return {"id": f"pi_test_{len(self.calls)}", "status": "succeeded"}


@pytest.fixture
def world():
    priv = Ed25519PrivateKey.generate()
    m = new_mandate(deal_id="deal-A", buyer_id="b1", amount=749.0, payee="honest-hal", now=NOW)
    m["status"], m["approval_id"] = "approved", "appr-1"
    approvals = {"deal-A": dict(m)}  # the merchant's own approval row
    stripe = FakeStripe()
    sim = MerchantSim(keys=keyring(priv.public_key()), store=NonceStore(), approvals=approvals.get, charger=stripe)
    return priv, m, sim, stripe


def signed(priv, mandate, body_mandate=None, now=NOW):
    body = json.dumps({"deal_id": mandate["deal_id"], "mandate": body_mandate or mandate}).encode()
    return {"method": "POST", "url": URL, "body": body,
            "headers": sign_request(method="POST", url=URL, body=body, mandate=mandate, private_key=priv, now=now)}


def test_valid_mandate_charges_once(world):
    priv, m, sim, stripe = world
    out = sim.handle(**signed(priv, m), now=NOW)
    assert out["status"] == "charged" and out["charge_id"] == "pi_test_1" and out["origin"] == "SIM"
    assert stripe.calls[0]["amount_cents"] == 74900 and stripe.calls[0]["key"] == "mandate:" + m["hash"]


def test_replayed_request_fails_with_reason(world):
    priv, m, sim, stripe = world
    req = signed(priv, m)
    assert sim.handle(**req, now=NOW)["status"] == "charged"
    out = sim.handle(**req, now=NOW)
    assert out["status"] == "refused" and out["reason"] in ("replayed_nonce", "replayed_mandate") and len(stripe.calls) == 1


def test_replayed_mandate_with_fresh_signature_fails(world):
    priv, m, sim, stripe = world
    assert sim.handle(**signed(priv, m), now=NOW)["status"] == "charged"
    out = sim.handle(**signed(priv, m, now=NOW + timedelta(seconds=5)), now=NOW + timedelta(seconds=5))
    assert out["status"] == "refused" and out["reason"] == "replayed_mandate" and len(stripe.calls) == 1


def test_altered_amount_in_body_fails(world):
    priv, m, sim, stripe = world
    req = signed(priv, m)
    req["body"] = req["body"].replace(b"749.0", b"7.49")
    out = sim.handle(**req, now=NOW)
    assert out["status"] == "refused" and out["reason"] == "digest_mismatch" and not stripe.calls


def test_altered_mandate_signed_by_buyer_agent_fails(world):
    priv, m, sim, stripe = world
    altered = dict(m, amount=7.49)
    from pay.mandate import mandate_hash
    altered["hash"] = mandate_hash(altered)  # a self-consistent mandate the buyer never approved
    out = sim.handle(**signed(priv, altered), now=NOW)
    assert out["status"] == "refused" and out["reason"] == "mandate_mismatch" and not stripe.calls


def test_deal_without_approval_record_fails(world):
    priv, m, sim, stripe = world
    other = new_mandate(deal_id="deal-B", buyer_id="b1", amount=10, payee="honest-hal", now=NOW)
    out = sim.handle(**signed(priv, other), now=NOW)
    assert out["status"] == "refused" and out["reason"] == "no_approval_record"


def test_malformed_body_fails_closed(world):
    priv, m, sim, stripe = world
    req = signed(priv, m)
    req["body"] = b"not json"
    assert sim.handle(**req, now=NOW)["status"] == "refused"


def test_failed_charge_reports_and_spends_the_mandate(world):
    priv, m, sim, _ = world
    sim.charger = FakeStripe(fail=True)
    out = sim.handle(**signed(priv, m), now=NOW)
    assert out["status"] == "charge_failed" and "card_declined" in out["detail"]
    assert sim.handle(**signed(priv, m, now=NOW + timedelta(seconds=5)), now=NOW + timedelta(seconds=5))["reason"] == "replayed_mandate"


def test_stripe_charger_refuses_a_live_key():
    with pytest.raises(ValueError):
        StripeTestCharger(secret_key="sk_live_123")
    with pytest.raises(ValueError):
        StripeTestCharger(secret_key="")
