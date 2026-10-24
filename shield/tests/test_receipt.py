from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.tap import keyring
from shield.receipt import sign_allow_receipt, verify_allow_receipt


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
    assert not verify_allow_receipt(receipt | {"verdict": "block"}, keyring(private.public_key()), **BINDING, now=NOW)
