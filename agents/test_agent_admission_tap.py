import re
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.replay import NonceStore
from pay.tap import key_id, sign_agent_request, sign_request, verify_agent_request, verify_request
from pay.mandate import new_mandate


NOW = datetime(2026, 10, 24, 11, 0, tzinfo=timezone.utc)
URL = "https://seller.example/v1/admit?round=1"
SENDER = "agent1qseller"
AUDIENCE = "https://bazaar.example/v1/seller-admission"
BODY = b'{"protocol":"techbazaar/seller-admission/v1"}'


@pytest.fixture
def private_key():
    return Ed25519PrivateKey.generate()


def signed(key, *, body=BODY, now=NOW, nonce="admit-nonce", ttl_seconds=60):
    return sign_agent_request(method="POST", url=URL, body=body, agent_address=SENDER,
                              audience=AUDIENCE, private_key=key, now=now,
                              nonce=nonce, ttl_seconds=ttl_seconds)


def verify(headers, body=BODY, *, key=None, store=None, now=NOW, method="POST", url=URL,
           actual_sender=SENDER, expected_audience=AUDIENCE):
    keys = {key_id(key.public_key()): key.public_key()} if key else {}
    return verify_agent_request(method=method, url=url, headers=headers, body=body, keys=keys,
                                store=store or NonceStore(), actual_sender=actual_sender,
                                expected_audience=expected_audience, now=now)


def test_admission_signature_binds_body_sender_audience_and_accepts_pinned_key(private_key):
    headers = signed(private_key)
    assert set(headers) == {"Content-Digest", "Agent-Address", "Admission-Audience",
                            "Signature-Input", "Signature"}
    assert "Mandate-Hash" not in headers
    assert verify(headers, key=private_key).ok


@pytest.mark.parametrize("change", [
    {"method": "PUT"}, {"url": "https://elsewhere.example/v1/admit?round=1"},
    {"url": "https://seller.example/v1/other?round=1"},
    {"url": "https://seller.example/v1/admit?round=2"},
    {"actual_sender": "agent1qother"}, {"expected_audience": "https://elsewhere.example/admit"},
])
def test_changed_bindings_reject(private_key, change):
    assert not verify(signed(private_key), key=private_key, **change).ok


def test_body_tampering_and_forged_signature_do_not_burn_nonce(private_key):
    headers = signed(private_key)
    store = NonceStore()
    assert not verify(headers, BODY + b" ", key=private_key, store=store).ok
    assert not verify(headers, key=Ed25519PrivateKey.generate(), store=store).ok
    assert verify(headers, key=private_key, store=store).ok


def test_expiry_and_clock_skew(private_key):
    headers = signed(private_key, ttl_seconds=60)
    assert not verify(headers, key=private_key, now=NOW + timedelta(seconds=60)).ok
    future = signed(private_key, now=NOW + timedelta(seconds=31))
    assert not verify(future, key=private_key).ok


def test_replay_survives_reopening_shared_nonce_store(private_key, tmp_path):
    store_path = tmp_path / ".state" / "state.sqlite3"
    store_path.parent.mkdir()
    headers = signed(private_key)
    assert verify(headers, key=private_key, store=NonceStore(str(store_path))).ok
    assert not verify(headers, key=private_key, store=NonceStore(str(store_path))).ok


def test_case_colliding_headers_mandate_header_and_wrong_key_reject(private_key):
    headers = signed(private_key)
    duplicate = dict(headers, **{"agent-address": SENDER})
    assert not verify(duplicate, key=private_key).ok
    assert not verify(dict(headers, **{"Mandate-Hash": "not-used"}), key=private_key).ok
    assert not verify(headers, key=Ed25519PrivateKey.generate()).ok


@pytest.mark.parametrize("mutation", [
    lambda h: h.__setitem__("Signature-Input", h["Signature-Input"].replace('"@query"', '"@query" "@query"')),
    lambda h: h.__setitem__("Signature-Input", h["Signature-Input"].replace('"admission-audience"', '"unknown-component"')),
    lambda h: h.__setitem__("Signature-Input", h["Signature-Input"].replace(";expires=", ";unknown=1;expires=")),
    lambda h: h.__setitem__("Signature-Input", h["Signature-Input"].replace(";expires=", ";created=1;expires=")),
    lambda h: h.__setitem__("Signature-Input", h["Signature-Input"].replace("techbazaar-seller-admission-v1", "agent-browser-auth")),
])
def test_duplicate_unknown_and_wrong_purpose_signature_input_reject(private_key, mutation):
    headers = signed(private_key)
    mutation(headers)
    assert not verify(headers, key=private_key).ok


def test_payment_signature_cannot_verify_as_admission(private_key):
    mandate = new_mandate(deal_id="deal-a", buyer_id="buyer", amount=10, payee=SENDER, now=NOW)
    payment = sign_request(method="POST", url=URL, body=b"{}", mandate=mandate,
                           private_key=private_key, now=NOW)
    assert not verify(payment, body=b"{}", key=private_key).ok


def test_admission_signature_cannot_verify_as_payment(private_key):
    headers = signed(private_key)
    result = verify_request(method="POST", url=URL, headers=headers, body=BODY,
                            keys={key_id(private_key.public_key()): private_key.public_key()},
                            store=NonceStore(), now=NOW)
    assert not result.ok


def test_admission_nonce_namespace_is_separate_from_payment_tap(private_key):
    store = NonceStore()
    nonce = "same-nonce"
    assert store.consume("tap", f"{key_id(private_key.public_key())}:{nonce}")
    body, headers = BODY, signed(private_key, nonce=nonce)
    assert verify(headers, key=private_key, store=store).ok


def test_malformed_header_and_url_inputs_fail_without_burning_nonce(private_key):
    headers = signed(private_key)
    store = NonceStore()
    unicode_digest = dict(headers, **{"Content-Digest": "sha-256=:é:"})
    crlf_sender = dict(headers, **{"Agent-Address": SENDER + "\r\nX-Evil: yes"})
    oversized_numeric = dict(headers)
    oversized_numeric["Signature-Input"] = re.sub(
        r"created=\d+", "created=" + "9" * 5000, oversized_numeric["Signature-Input"])
    assert not verify(unicode_digest, key=private_key, store=store).ok
    assert not verify(crlf_sender, key=private_key, store=store).ok
    assert not verify(oversized_numeric, key=private_key, store=store).ok
    assert not verify(headers, key=private_key, store=store, url="https://seller.example\n/v1/admit?round=1").ok
    assert verify(headers, key=private_key, store=store).ok


def test_admission_signer_rejects_unsafe_binding_and_oversized_input(private_key):
    with pytest.raises(ValueError):
        sign_agent_request(method="POST", url="https://seller.example\n/v1/admit", body=BODY,
                           agent_address=SENDER, audience=AUDIENCE, private_key=private_key, now=NOW)
    with pytest.raises(ValueError):
        sign_agent_request(method="POST", url=URL, body=BODY, agent_address=SENDER + "\r\nX: y",
                           audience=AUDIENCE, private_key=private_key, now=NOW)
    with pytest.raises(ValueError):
        sign_agent_request(method="POST", url=URL, body=b"x" * (64 * 1024 + 1), agent_address=SENDER,
                           audience=AUDIENCE, private_key=private_key, now=NOW)


@pytest.mark.parametrize("url", ["https://seller.example:bad/v1/admit", "file:///v1/admit"])
def test_malformed_url_returns_denial_not_exception(private_key, url):
    headers = signed(private_key)
    assert not verify(headers, key=private_key, url=url).ok
