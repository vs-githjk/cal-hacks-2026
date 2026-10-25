"""#284: our TAP signer against a faithful port of Visa's reference verifier (see visa_reference_port.py).

Reference: github.com/visa/trusted-agent-protocol @ 16d59bdf (cdn-proxy/server.js, tap-agent/agent_app.py).
"""
import json
import re
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pay.mandate import new_mandate
from pay.replay import NonceStore
from pay.tap import (PAYER_TAG, BROWSER_TAG, key_id, keyring, sign_request, tap_status, verify_request)
from pay.tests.visa_reference_port import ReferenceVerifier, parse_signature_input, reference_agent_headers

NOW = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())
URL = "https://merchant.example.com/v1/charge"
AUTHORITY, PATH = "merchant.example.com", "/v1/charge"


@pytest.fixture
def priv():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def registry(priv):
    return {key_id(priv.public_key()): priv.public_key()}


def mandate():
    m = new_mandate(deal_id="deal-A", buyer_id="b1", amount=1119, payee="seller-x", now=NOW)
    m["status"], m["approval_id"] = "approved", "appr-1"
    return m


def signed(priv, **kw):
    m = mandate()
    body = json.dumps({"mandate": m}, sort_keys=True).encode()
    return m, body, sign_request(method="POST", url=URL, body=body, mandate=m, private_key=priv, now=NOW, **kw)


def ref_check(registry, h, verifier=None, now=NOW_TS):
    verifier = verifier or ReferenceVerifier(registry)
    return verifier.verify(signature_input=h["Signature-Input"], signature=h["Signature"],
                           authority=AUTHORITY, path=PATH, now=now)


# ---------- the port itself accepts Visa's own agent (so a pass below means something) ----------

def test_port_accepts_the_reference_agent_format_and_refuses_a_bad_one(priv, registry):
    kid = key_id(priv.public_key())
    good = reference_agent_headers(priv, authority=AUTHORITY, path=PATH, key_id=kid, nonce="n-1",
                                   created=NOW_TS, expires=NOW_TS + 60, tag="agent-browser-auth")
    v = ReferenceVerifier(registry)
    assert v.verify(signature_input=good["signature-input"], signature=good["signature"],
                    authority=AUTHORITY, path=PATH, now=NOW_TS) == (True, "ok")
    lower = good["signature-input"].replace("keyId=", "keyid=")  # RFC spelling: the reference does not read it
    assert ReferenceVerifier(registry).verify(signature_input=lower, signature=good["signature"],
                                              authority=AUTHORITY, path=PATH, now=NOW_TS)[0] is False


# ---------- our signer, verified by the reference logic ----------

def test_our_signature_verifies_with_the_reference_verifier(priv, registry):
    _, _, h = signed(priv)
    assert ref_check(registry, h) == (True, "ok")


def test_payment_signature_uses_the_payer_tag_and_the_reference_shape(priv):
    _, _, h = signed(priv)
    si = h["Signature-Input"]
    assert re.fullmatch(r'sig2=\("@authority" "@path"\); created=\d+; expires=\d+; keyId="[A-Za-z0-9_-]+"; '
                        r'alg="ed25519"; nonce="[A-Za-z0-9_.-]+"; tag="agent-payer-auth"', si), si
    assert re.fullmatch(r"sig2=:[A-Za-z0-9+/=]+:", h["Signature"])
    assert PAYER_TAG == "agent-payer-auth" and BROWSER_TAG == "agent-browser-auth"
    parsed = parse_signature_input(si)
    assert parsed["params"] == ["@authority", "@path"] and parsed["algorithm"] == "ed25519"
    assert parsed["tag"] == PAYER_TAG and parsed["expires"] - parsed["created"] == 60


def test_signature_agent_header_is_a_quoted_https_url(priv):
    _, _, h = signed(priv)
    assert re.fullmatch(r'"https://[^"\s]+"', h["Signature-Agent"])
    # merchant-backend signature_verification.py:59 strips the quotes and looks the URL up
    assert h["Signature-Agent"].strip('"').startswith("https://")


def test_signature_agent_is_configurable(priv):
    _, _, h = signed(priv, signature_agent="https://agent.techbazaar.example/dir")
    assert h["Signature-Agent"] == '"https://agent.techbazaar.example/dir"'


def test_browser_tag_is_available_and_also_verifies_with_the_reference(priv, registry):
    _, _, h = signed(priv, tag=BROWSER_TAG)
    assert 'tag="agent-browser-auth"' in h["Signature-Input"]
    assert ref_check(registry, h)[0] is True


def test_unknown_tag_is_refused_at_signing(priv):
    with pytest.raises(ValueError):
        signed(priv, tag="agent-whatever")


def test_reference_refuses_a_signature_for_another_authority_or_path(priv, registry):
    _, _, h = signed(priv)
    v = ReferenceVerifier(registry)
    assert v.verify(signature_input=h["Signature-Input"], signature=h["Signature"],
                    authority="evil.example.com", path=PATH, now=NOW_TS) == (False, "bad_signature")
    assert ref_check(registry, h, now=NOW_TS + 61) == (False, "expired")


# ---------- replay: same nonce twice is refused by both verifiers ----------

def test_replay_is_refused_by_the_reference_verifier_too(priv, registry):
    _, _, h = signed(priv)
    v = ReferenceVerifier(registry)
    assert ref_check(registry, h, v)[0] is True
    assert ref_check(registry, h, v) == (False, "replay")


def test_replayed_request_is_refused_by_ours_and_the_status_says_so(priv, registry):
    m, body, h = signed(priv)
    keys, store = keyring(priv.public_key()), NonceStore()
    first = verify_request(method="POST", url=URL, headers=h, body=body, keys=keys, store=store, now=NOW)
    again = verify_request(method="POST", url=URL, headers=h, body=body, keys=keys, store=store, now=NOW)
    assert first.ok and not again.ok and again.reason == "replayed_nonce"
    assert tap_status(first) == {"ok": True, "label": "TAP signature verified", "reason": "ok",
                                 "verified_by": "merchant simulator (SIM), not by Visa"}
    s = tap_status(again)
    assert s["ok"] is False and s["label"] == "Replay refused" and s["reason"] == "replayed_nonce"


def test_a_spent_mandate_nonce_also_reads_as_replay_refused():
    from pay.tap import _no
    assert tap_status(_no("replayed_mandate"))["label"] == "Replay refused"


def test_other_refusals_get_a_plain_refused_label():
    from pay.tap import _no
    s = tap_status(_no("bad_signature", "x"))
    assert s["ok"] is False and s["label"] == "TAP signature refused" and s["reason"] == "bad_signature"


# ---------- our verifier keeps what the reference cannot see ----------

def test_payment_request_signed_with_the_browser_tag_cannot_authorize_a_charge(priv):
    m, body, h = signed(priv, tag=BROWSER_TAG)
    r = verify_request(method="POST", url=URL, headers=h, body=body, keys=keyring(priv.public_key()),
                       store=NonceStore(), now=NOW)
    assert not r.ok and r.reason == "bad_tag"


def test_mandate_binding_survives_the_slimmer_reference_signature(priv):
    """The reference signature covers only @authority and @path; method, query, body and mandate hash are
    bound through the nonce, so changing any of them fails even though the reference would accept it."""
    m, body, h = signed(priv)
    keys = keyring(priv.public_key())
    for kw in ({"method": "PUT"}, {"url": URL + "?x=1"}):
        args = dict(method="POST", url=URL, headers=h, body=body, keys=keys, store=NonceStore(), now=NOW)
        args.update(kw)
        r = verify_request(**args)
        assert not r.ok and r.reason == "bad_signature", kw
