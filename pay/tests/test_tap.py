"""d2 TAP-style signing tests (RFC 9421 HTTP Message Signatures, Ed25519)."""
import base64
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.mandate import mandate_hash, new_mandate
from pay.replay import NonceStore
from pay.tap import (
    KEY_ENV,
    TAG,
    TapKeyError,
    attach_signature,
    generate_keypair,
    key_id,
    keyring,
    load_private_key,
    sign_request,
    verify_request,
)

NOW = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)
URL = "https://merchant.example.com/v1/charge?x=1"


@pytest.fixture
def priv():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def keys(priv):
    return keyring(priv.public_key())


def mandate(**kw):
    args = dict(deal_id="deal-A", buyer_id="b1", amount=1119, payee="seller-x", now=NOW)
    args.update(kw)
    m = new_mandate(**args)
    m["status"], m["approval_id"] = "approved", "appr-1"
    return m


def body_for(m, **extra):
    return json.dumps(dict({"mandate": m, "amount": m["amount"], "payee": m["payee"]}, **extra),
                      sort_keys=True).encode()


def signed(priv, m=None, body=None, now=NOW, **kw):
    m = m or mandate()
    body = body if body is not None else body_for(m)
    headers = sign_request(method="POST", url=URL, body=body, mandate=m, private_key=priv, now=now, **kw)
    return m, body, headers


def check(keys, headers, body, store=None, now=NOW, method="POST", url=URL, **kw):
    return verify_request(method=method, url=url, headers=headers, body=body, keys=keys,
                          store=store if store is not None else NonceStore(), now=now, **kw)


# ---------- happy path and shape ----------

def test_signed_request_verifies(priv, keys):
    m, body, headers = signed(priv)
    r = check(keys, headers, body)
    assert r.ok and r.reason == "ok"


def test_headers_follow_rfc9421_shape(priv):
    m, body, h = signed(priv)
    assert h["Mandate-Hash"] == m["hash"] == mandate_hash(m)
    assert h["Content-Digest"] == "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"
    si = h["Signature-Input"]
    assert si.startswith('sig1=("@method" "@authority" "@path" "content-digest" "mandate-hash");')
    for param in ("created=", "expires=", 'keyid="', 'alg="ed25519"', 'nonce="', f'tag="{TAG}"'):
        assert param in si
    assert re.fullmatch(r"sig1=:[A-Za-z0-9+/=]+:", h["Signature"])
    assert TAG == "agent-browser-auth"


def test_signature_matches_an_independently_built_signature_base(priv):
    m, body, h = signed(priv)
    params = h["Signature-Input"][len("sig1="):]
    base = "\n".join([
        '"@method": POST',
        '"@authority": merchant.example.com',
        '"@path": /v1/charge',
        f'"content-digest": {h["Content-Digest"]}',
        f'"mandate-hash": {m["hash"]}',
        f'"@signature-params": {params}',
    ])
    sig = base64.b64decode(h["Signature"][len("sig1=:"):-1])
    priv.public_key().verify(sig, base.encode())  # raises InvalidSignature if wrong


def test_attach_signature_stores_header_on_mandate(priv):
    m, body, h = signed(priv)
    attach_signature(m, h)
    assert m["tap_signature"] == h["Signature"]
    assert mandate_hash(m) == m["hash"]  # not part of the hash


def test_sign_refuses_mandate_whose_hash_is_stale(priv):
    m = mandate()
    m["amount"] = 1.0
    with pytest.raises(ValueError):
        sign_request(method="POST", url=URL, body=b"{}", mandate=m, private_key=priv, now=NOW)


# ---------- tampering ----------

def test_tampered_amount_in_body_fails(priv, keys):
    m, body, h = signed(priv)
    forged = body.replace(b'"amount": 1119', b'"amount": 1')
    assert forged != body
    r = check(keys, h, forged)
    assert not r.ok and r.reason == "digest_mismatch"


def test_tampered_amount_with_recomputed_digest_fails_signature(priv, keys):
    m, body, h = signed(priv)
    forged = body.replace(b'"amount": 1119', b'"amount": 1')
    h2 = dict(h)
    h2["Content-Digest"] = "sha-256=:" + base64.b64encode(hashlib.sha256(forged).digest()).decode() + ":"
    r = check(keys, h2, forged)
    assert not r.ok and r.reason == "bad_signature"


@pytest.mark.parametrize("field,value", [
    ("method", "PUT"),
    ("url", "https://evil.example.com/v1/charge?x=1"),
    ("url", "https://merchant.example.com/v1/refund?x=1"),
])
def test_tampered_method_authority_or_path_fails(priv, keys, field, value):
    m, body, h = signed(priv)
    r = check(keys, h, body, **{field: value})
    assert not r.ok and r.reason == "bad_signature"


def test_swapped_mandate_hash_header_fails(priv, keys):
    m, body, h = signed(priv)
    other = mandate(deal_id="deal-B")
    h2 = dict(h, **{"Mandate-Hash": other["hash"]})
    r = check(keys, h2, body)
    assert not r.ok and r.reason == "bad_signature"


def test_body_mandate_with_altered_amount_fails_hash_check(priv, keys):
    m = mandate()
    forged = dict(m, amount=1.0)  # hash field left stale
    body = json.dumps({"mandate": forged}).encode()
    headers = sign_request(method="POST", url=URL, body=body, mandate=m, private_key=priv, now=NOW)
    r = check(keys, headers, body)
    assert not r.ok and r.reason == "mandate_hash_mismatch"


def test_mandate_for_deal_a_cannot_authorize_deal_b_at_the_merchant(priv, keys):
    m, body, h = signed(priv, mandate(deal_id="deal-A"))
    merchant_expects = mandate(deal_id="deal-B")["hash"]
    r = check(keys, h, body, expected_mandate_hash=merchant_expects)
    assert not r.ok and r.reason == "mandate_mismatch"
    assert check(keys, h, body, store=NonceStore(), expected_mandate_hash=m["hash"]).ok


def test_wrong_key_fails_and_unknown_keyid_fails(priv, keys):
    m, body, h = signed(Ed25519PrivateKey.generate())
    assert check(keys, h, body).reason == "unknown_key"
    attacker = Ed25519PrivateKey.generate()
    forged_keys = {key_id(priv.public_key()): attacker.public_key()}
    m, body, h = signed(priv)
    assert check(forged_keys, h, body).reason == "bad_signature"


# ---------- replay ----------

def test_replayed_request_fails_with_reason(priv, keys):
    m, body, h = signed(priv)
    store = NonceStore()
    assert check(keys, h, body, store).ok
    r = check(keys, h, body, store)
    assert not r.ok and r.reason == "replayed_nonce"


def test_forged_request_does_not_burn_the_real_nonce(priv, keys):
    m, body, h = signed(priv)
    store = NonceStore()
    forged = body.replace(b'"amount": 1119', b'"amount": 1')
    assert check(keys, h, forged, store).reason == "digest_mismatch"
    assert check(keys, h, body, store).ok


def test_replay_survives_restart_with_json_store(priv, keys, tmp_path):
    p = str(tmp_path / "n.json")
    m, body, h = signed(priv)
    assert check(keys, h, body, NonceStore(p)).ok
    assert check(keys, h, body, NonceStore(p)).reason == "replayed_nonce"


def test_each_signature_gets_a_fresh_nonce(priv):
    _, _, a = signed(priv)
    _, _, b = signed(priv)
    nonce = lambda h: re.search(r'nonce="([^"]+)"', h["Signature-Input"]).group(1)
    assert nonce(a) != nonce(b)


# ---------- time window ----------

def test_expired_signature_fails(priv, keys):
    m, body, h = signed(priv, ttl_seconds=60)
    r = check(keys, h, body, now=NOW + timedelta(seconds=61))
    assert not r.ok and r.reason == "signature_expired"


def test_signature_from_the_future_fails(priv, keys):
    m, body, h = signed(priv, now=NOW + timedelta(minutes=5))
    assert check(keys, h, body).reason == "signature_not_yet_valid"


def test_ttl_over_cap_is_refused_at_signing(priv, keys):
    with pytest.raises(ValueError):
        signed(priv, ttl_seconds=301)


# ---------- malformed input ----------

def test_missing_headers_fail(priv, keys):
    m, body, h = signed(priv)
    for name in ("Signature", "Signature-Input", "Content-Digest", "Mandate-Hash"):
        h2 = {k: v for k, v in h.items() if k != name}
        r = check(keys, h2, body)
        assert not r.ok and r.reason == "missing_header", name


def test_header_names_are_case_insensitive(priv, keys):
    m, body, h = signed(priv)
    assert check(keys, {k.lower(): v for k, v in h.items()}, body).ok


def test_signature_input_must_cover_required_components(priv, keys):
    m, body, h = signed(priv)
    h2 = dict(h)
    h2["Signature-Input"] = h["Signature-Input"].replace(' "content-digest"', "")
    r = check(keys, h2, body)
    assert not r.ok and r.reason == "bad_component_set"


@pytest.mark.parametrize("old,new,reason", [
    (f'tag="{TAG}"', 'tag="other"', "bad_tag"),
    ('alg="ed25519"', 'alg="rsa-v1_5-sha256"', "bad_alg"),
    ("sig1=(", "sig9=(", "bad_signature_input"),
])
def test_bad_params_fail(priv, keys, old, new, reason):
    m, body, h = signed(priv)
    h2 = dict(h, **{"Signature-Input": h["Signature-Input"].replace(old, new)})
    r = check(keys, h2, body)
    assert not r.ok and r.reason == reason


def test_garbage_headers_fail_cleanly(priv, keys):
    m, body, h = signed(priv)
    for sig_input in ("", "garbage", 'sig1=("@method");created=x'):
        r = check(keys, dict(h, **{"Signature-Input": sig_input}), body)
        assert not r.ok
    r = check(keys, dict(h, Signature="sig1=:!!!:"), body)
    assert not r.ok


# ---------- keys ----------

def test_key_loaded_from_env_var_path(tmp_path, monkeypatch):
    path = str(tmp_path / "tap.pem")
    pub = generate_keypair(path)
    monkeypatch.setenv(KEY_ENV, path)
    loaded = load_private_key()
    assert key_id(loaded.public_key()) == key_id(pub)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_missing_env_var_or_file_raises(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    with pytest.raises(TapKeyError):
        load_private_key()
    with pytest.raises(TapKeyError):
        load_private_key(str(tmp_path / "nope.pem"))


def test_non_ed25519_or_garbage_key_file_raises(tmp_path):
    bad = tmp_path / "bad.pem"
    bad.write_text("not a key")
    with pytest.raises(TapKeyError):
        load_private_key(str(bad))


def test_generate_keypair_never_overwrites(tmp_path):
    path = str(tmp_path / "tap.pem")
    generate_keypair(path)
    with pytest.raises(FileExistsError):
        generate_keypair(path)


def test_end_to_end_with_key_from_env(tmp_path, monkeypatch):
    path = str(tmp_path / "tap.pem")
    generate_keypair(path)
    monkeypatch.setenv(KEY_ENV, path)
    priv = load_private_key()
    m, body, h = signed(priv)
    assert check(keyring(priv.public_key()), h, body).ok
