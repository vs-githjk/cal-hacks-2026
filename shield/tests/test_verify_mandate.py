"""d4 verify_mandate: wraps pay.tap.verify_request and returns the Shield verdict shape."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.mandate import new_mandate
from pay.replay import NonceStore
from pay.tap import keyring, sign_request
from shield.verify import verify_mandate

NOW = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)
URL = "https://merchant.example.com/v1/charge"
KEYS = {"verdict", "rule_ids", "severity", "evidence_spans", "latency_ms", "request_id", "version"}


@pytest.fixture
def priv():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def keys(priv):
    return keyring(priv.public_key())


def build(priv, **kw):
    m = new_mandate(deal_id="deal-A", buyer_id="b1", amount=1119, payee="shady-sam@pay.example.test", now=NOW, **kw)
    m["status"], m["approval_id"] = "approved", "appr-1"
    body = json.dumps({"mandate": m}, sort_keys=True)
    headers = sign_request(method="POST", url=URL, body=body.encode(), mandate=m, private_key=priv, now=NOW)
    return m, {"method": "POST", "url": URL, "headers": headers, "body": body}


GOOD_EXPECTED = {"deal_id": "deal-A", "amount": 1119, "payee": "shady-sam@pay.example.test"}


def run(keys, req, store=None, **kw):
    kw.setdefault("expected", dict(GOOD_EXPECTED))
    return verify_mandate(req, keys=keys, store=store or NonceStore(), now=NOW, **kw)


def test_good_request_is_allowed(priv, keys):
    m, req = build(priv)
    out = run(keys, req, expected={"deal_id": "deal-A", "amount": 1119, "payee": "shady-sam@pay.example.test"})
    assert set(out) == KEYS and out["verdict"] == "allow" and out["rule_ids"] == []


def test_payee_swap_is_quarantined_as_mandate_mismatch(priv, keys):
    m, req = build(priv)
    out = run(keys, req, expected={"deal_id": "deal-A", "amount": 1119, "payee": "honest-hal@pay.example.test"})
    assert out["verdict"] == "quarantine"
    assert out["rule_ids"][0] == "shield.mandate.mismatch" and "shield.mandate.payee_mismatch" in out["rule_ids"]


def test_amount_and_deal_mismatch(priv, keys):
    m, req = build(priv)
    out = run(keys, req, expected={"deal_id": "deal-A", "amount": 900, "payee": m["payee"]})
    assert out["verdict"] == "quarantine" and "shield.mandate.amount_mismatch" in out["rule_ids"]
    out = run(keys, req, expected={"deal_id": "deal-B", "amount": 1119, "payee": m["payee"]})
    assert "shield.mandate.deal_mismatch" in out["rule_ids"]


def test_expected_mandate_hash_mismatch_is_quarantined(priv, keys):
    m, req = build(priv)
    req["expected_mandate_hash"] = "0" * 64
    out = run(keys, req)
    assert out["verdict"] == "quarantine" and out["rule_ids"][0] == "shield.mandate.mismatch"


def test_tampered_body_blocks(priv, keys):
    m, req = build(priv)
    req["body"] = req["body"] + " "  # the mandate is unchanged, only the signed digest no longer matches
    out = run(keys, req)
    assert out["verdict"] == "block" and out["rule_ids"] == ["shield.mandate.digest_mismatch"]


def test_replay_blocks_second_time(priv, keys):
    m, req = build(priv)
    store = NonceStore()
    assert run(keys, req, store)["verdict"] == "allow"
    out = run(keys, req, store)
    assert out["verdict"] == "block" and out["rule_ids"] == ["shield.mandate.replayed_nonce"]


def test_unknown_key_and_missing_headers_block(priv):
    m, req = build(priv)
    assert run({}, req)["rule_ids"] == ["shield.mandate.unknown_key"]
    req["headers"] = {}
    assert run(keyring(priv.public_key()), req)["rule_ids"] == ["shield.mandate.missing_header"]


def test_expired_signature_blocks(priv, keys):
    m, req = build(priv)
    out = verify_mandate(req, keys=keys, store=NonceStore(), now=NOW + timedelta(hours=1),
                         expected=dict(GOOD_EXPECTED))
    assert out["verdict"] == "block"


@pytest.mark.parametrize("bad", [None, {}, {"method": "POST"}, {"method": "POST", "url": 1, "headers": 3, "body": 4}])
def test_malformed_request_fails_closed(keys, bad):
    out = verify_mandate(bad, keys=keys, store=NonceStore(), now=NOW)
    assert out["verdict"] == "block" and out["rule_ids"] and set(out) == KEYS


def test_missing_keys_or_store_fails_closed(priv):
    m, req = build(priv)
    out = verify_mandate(req, keys=None, store=NonceStore(), now=NOW)
    assert out["verdict"] == "block" and out["rule_ids"] == ["shield.error"]


@pytest.mark.parametrize("expected", [
    None, {}, {"deal_id": "deal-A"}, {"deal_id": "deal-A", "amount": 1119}, {"deal_id": "deal-A", "payee": "shady-sam@pay.example.test"},
    {"amount": 1119, "payee": "shady-sam@pay.example.test"}, "deal-A", ["deal-A"],
])
def test_missing_or_partial_expected_blocks_instead_of_skipping_the_checks(priv, keys, expected):
    m, req = build(priv)
    out = verify_mandate(req, keys=keys, store=NonceStore(), now=NOW, expected=expected)
    assert out["verdict"] == "block" and out["rule_ids"] == ["shield.mandate.malformed_request"]
    # the same signed request is fine once the caller states all three expectations
    assert run(keys, req)["verdict"] == "allow"


def test_malformed_request_blocks_via_the_api_when_expected_is_partial(priv, keys):
    from shield.service import handle_verify_mandate
    m, req = build(priv)
    req["expected"] = {"deal_id": "deal-A"}
    out = handle_verify_mandate(req, keys, NonceStore())
    assert out["verdict"] == "block" and out["rule_ids"] == ["shield.mandate.malformed_request"]


def test_unreadable_mandate_with_expected_blocks(priv, keys):
    m, req = build(priv)
    req["body"] = "{}"
    out = run(keys, req)
    assert out["verdict"] == "block" and out["rule_ids"] == ["shield.mandate.malformed_request"]
