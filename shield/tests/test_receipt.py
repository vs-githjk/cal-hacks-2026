import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.tap import keyring
from shield.receipt import DOMAIN, _canonical, sign_allow_receipt, verify_allow_receipt


NOW = datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)
REQUEST = '{"deal_id":"deal-1","mandate_hash":"hash-1","amount_cents":74900}'
BINDING = dict(message_id="msg-1", request_json=REQUEST, deal_id="deal-1", mandate_hash="hash-1",
               amount_cents=74900, currency="USD", payee="seller-agent-1")


def make_receipt(private=None, **overrides):
    private = private or Ed25519PrivateKey.generate()
    receipt = sign_allow_receipt(private_key=private, **(BINDING | overrides), now=NOW)
    return receipt, private


def test_signed_allow_receipt_verifies_exact_binding():
    receipt, private = make_receipt()
    result = verify_allow_receipt(receipt, keyring(private.public_key()), **BINDING, now=NOW)
    assert result and result.reason == "ok"


def test_receipt_rejects_different_request_bytes_and_binding():
    receipt, private = make_receipt()
    keys = keyring(private.public_key())
    assert not verify_allow_receipt(receipt, keys, **(BINDING | {"request_json": REQUEST + " "}), now=NOW)
    assert not verify_allow_receipt(receipt, keys, **(BINDING | {"payee": "seller-agent-2"}), now=NOW)


def test_receipt_rejects_expired_or_overlong_lifetime():
    receipt, private = make_receipt()
    keys = keyring(private.public_key())
    assert not verify_allow_receipt(receipt, keys, **BINDING, now=NOW + timedelta(seconds=61))
    import pytest
    with pytest.raises(ValueError, match="ttl_seconds"):
        make_receipt(ttl_seconds=61)


def test_receipt_rejects_unknown_key_and_modified_signature_payload():
    receipt, private = make_receipt()
    assert not verify_allow_receipt(receipt, {}, **BINDING, now=NOW)
    assert not verify_allow_receipt(receipt, None, **BINDING, now=NOW)
    assert not verify_allow_receipt(receipt | {"verdict": "block"}, keyring(private.public_key()), **BINDING, now=NOW)


@pytest.mark.parametrize("field,value", [
    ("message_id", "other-message"), ("deal_id", "other-deal"), ("mandate_hash", "other-hash"),
    ("amount_cents", 1), ("currency", "CAD"), ("payee", "other-payee"),
])
def test_each_receipt_binding_mismatch_is_refused(field, value):
    receipt, private = make_receipt()
    assert not verify_allow_receipt(receipt, keyring(private.public_key()), **(BINDING | {field: value}), now=NOW)


def test_expected_cents_must_be_a_positive_integer():
    receipt, private = make_receipt()
    assert not verify_allow_receipt(receipt, keyring(private.public_key()),
        **(BINDING | {"amount_cents": 74900.0}), now=NOW)


def resign(receipt, private):
    payload = {k: v for k, v in receipt.items() if k != "signature"}
    return payload | {"signature": base64.b64encode(private.sign(DOMAIN + _canonical(payload))).decode("ascii")}


def test_receipt_rejects_missing_extra_fields_and_bad_base64():
    receipt, private = make_receipt()
    keys = keyring(private.public_key())
    assert not verify_allow_receipt({k: v for k, v in receipt.items() if k != "receipt_id"}, keys, **BINDING, now=NOW)
    assert not verify_allow_receipt(receipt | {"extra": "x"}, keys, **BINDING, now=NOW)
    assert not verify_allow_receipt(receipt | {"signature": "not-base64!"}, keys, **BINDING, now=NOW)


def test_receipt_rejects_signed_future_time_and_overlong_lifetime():
    receipt, private = make_receipt()
    keys = keyring(private.public_key())
    future = resign(receipt | {"issued_at": int((NOW + timedelta(seconds=31)).timestamp()),
                               "expires_at": int((NOW + timedelta(seconds=60)).timestamp())}, private)
    assert not verify_allow_receipt(future, keys, **BINDING, now=NOW)
    long_lived = resign(receipt | {"expires_at": receipt["issued_at"] + 61}, private)
    assert not verify_allow_receipt(long_lived, keys, **BINDING, now=NOW)


@pytest.mark.parametrize("field,value", [("amount_cents", True), ("issued_at", "1"), ("expires_at", False)])
def test_receipt_rejects_noninteger_or_boolean_numeric_fields(field, value):
    receipt, private = make_receipt()
    malformed = resign(receipt | {field: value}, private)
    assert not verify_allow_receipt(malformed, keyring(private.public_key()), **BINDING, now=NOW)


def test_request_digest_is_the_exact_utf8_bytes():
    receipt, private = make_receipt()
    assert receipt["request_sha256"] == hashlib.sha256(REQUEST.encode("utf-8")).hexdigest()
    assert not verify_allow_receipt(receipt, keyring(private.public_key()), **(BINDING | {"request_json": REQUEST + " "}), now=NOW)
