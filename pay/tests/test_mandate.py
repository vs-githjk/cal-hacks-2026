"""d2 mandate tests: hash, expiry, single use, deal binding, charge guard."""
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from pay.mandate import (
    format_ts,
    HASH_FIELDS,
    MandateError,
    can_charge,
    canonical,
    idempotency_key,
    mandate_hash,
    mark_used,
    new_mandate,
    validate_schema,
    verify,
)
from pay.replay import NonceStore

NOW = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)


def make(**kw):
    args = dict(
        deal_id="deal-A",
        buyer_id="buyer-1",
        amount=1119.0,
        payee="seller-x",
        tier_price=1099.5,
        now=NOW,
    )
    args.update(kw)
    return new_mandate(**args)


def approved(m, approval_id="appr-1"):
    m["status"] = "approved"
    m["approval_id"] = approval_id
    return m


def guard(m, now=NOW, **kw):
    """can_charge with the expectations the merchant would hold for the default mandate."""
    args = dict(deal_id="deal-A", amount=1119.0, payee="seller-x", store=NonceStore())
    args.update(kw)
    return can_charge(m, now, **args)


# ---------- hash ----------

def test_canonical_is_sorted_no_spaces_and_only_hash_fields():
    m = {
        "deal_id": "d1", "amount": 10, "currency": "USD", "payee": "p",
        "tier_price": None, "nonce": "ab", "expires_at": "2026-10-24T01:10:00Z",
        "status": "pending", "buyer_id": "b",
    }
    assert canonical(m) == (
        '{"amount":10,"currency":"USD","deal_id":"d1","expires_at":"2026-10-24T01:10:00Z",'
        '"nonce":"ab","payee":"p","tier_price":null}'
    )


def test_hash_is_sha256_hex_of_canonical_and_stable():
    m = make()
    expected = hashlib.sha256(canonical(m).encode()).hexdigest()
    assert mandate_hash(m) == expected == m["hash"]
    assert len(expected) == 64
    assert mandate_hash(m) == mandate_hash(dict(m))


def test_hash_matches_independent_golden_value():
    m = {
        "deal_id": "d1", "amount": 10, "currency": "USD", "payee": "p",
        "tier_price": None, "nonce": "ab", "expires_at": "2026-10-24T01:10:00Z",
    }
    literal = (
        '{"amount":10,"currency":"USD","deal_id":"d1","expires_at":"2026-10-24T01:10:00Z",'
        '"nonce":"ab","payee":"p","tier_price":null}'
    )
    assert mandate_hash(m) == hashlib.sha256(literal.encode()).hexdigest()
    json.loads(literal)  # the literal is valid JSON


def test_hash_is_key_order_independent_and_ignores_other_fields():
    m = make()
    items = list(m.items())
    random.Random(7).shuffle(items)
    shuffled = dict(items)
    assert mandate_hash(shuffled) == m["hash"]
    other = dict(m, status="approved", approval_id="x", tap_signature="sig", buyer_id="zzz")
    assert mandate_hash(other) == m["hash"]


def test_integral_float_and_int_amount_hash_the_same():
    a = make(amount=1119, tier_price=None)
    b = dict(a, amount=1119.0)
    assert mandate_hash(a) == mandate_hash(b)


@pytest.mark.parametrize("field,value", [
    ("deal_id", "deal-B"),
    ("amount", 1119.01),
    ("currency", "EUR"),
    ("payee", "seller-y"),
    ("tier_price", 1000),
    ("nonce", "0" * 32),
    ("expires_at", "2026-10-24T01:09:59Z"),
])
def test_any_hash_field_change_changes_hash(field, value):
    m = make()
    assert field in HASH_FIELDS
    changed = dict(m, **{field: value})
    assert mandate_hash(changed) != m["hash"]


def test_tier_price_none_differs_from_zero():
    m = make(tier_price=None)
    assert mandate_hash(dict(m, tier_price=0)) != m["hash"]


# ---------- new_mandate ----------

def test_new_mandate_shape_nonce_and_ttl():
    m = make()
    assert len(m["nonce"]) == 32 and int(m["nonce"], 16) >= 0
    assert make()["nonce"] != make()["nonce"]
    created = datetime.strptime(m["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    expires = datetime.strptime(m["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert expires - created <= timedelta(minutes=10)
    assert m["status"] == "pending" and m["approval_id"] is None and m["tap_signature"] is None
    assert m["currency"] == "USD" and m["within_allowance"] is False
    assert validate_schema(m) == []


def test_new_mandate_refuses_ttl_over_ten_minutes_or_nonpositive():
    with pytest.raises(ValueError):
        make(ttl_seconds=601)
    with pytest.raises(ValueError):
        make(ttl_seconds=0)
    assert make(ttl_seconds=600)["status"] == "pending"


@pytest.mark.parametrize("amount", [0, -5, True, float("nan"), float("inf"), "10"])
def test_new_mandate_refuses_bad_amount(amount):
    with pytest.raises(ValueError):
        make(amount=amount)


def test_schema_check_flags_unknown_field_and_bad_enum():
    m = make()
    assert validate_schema(dict(m, extra=1))
    assert validate_schema(dict(m, status="maybe"))
    bad = dict(m)
    del bad["payee"]
    assert validate_schema(bad)


# ---------- verify ----------

def test_verify_ok_for_fresh_mandate():
    r = verify(make(), NOW + timedelta(minutes=1))
    assert r.ok and bool(r) and r.reason == "ok"


def test_verify_detects_tampered_amount():
    m = make()
    m["amount"] = 1.0
    r = verify(m, NOW)
    assert not r.ok and r.reason == "hash_mismatch"


def test_expired_mandate_fails():
    m = make()
    r = verify(m, NOW + timedelta(minutes=10, seconds=1))
    assert not r.ok and r.reason == "expired"
    assert verify(m, NOW + timedelta(minutes=10)).reason == "expired"  # boundary is exclusive


def test_used_mandate_fails_on_status():
    m = make()
    m["status"] = "used"
    r = verify(m, NOW)
    assert not r.ok and r.reason == "already_used"


@pytest.mark.parametrize("status,reason", [("denied", "denied"), ("expired", "expired")])
def test_denied_or_expired_status_fails(status, reason):
    m = make()
    m["status"] = status
    r = verify(m, NOW)
    assert not r.ok and r.reason == reason


def test_rehashed_forged_long_ttl_mandate_fails():
    m = make()
    m["expires_at"] = (NOW + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    m["hash"] = mandate_hash(m)
    r = verify(m, NOW)
    assert not r.ok and r.reason == "ttl_too_long"


def test_verify_rejects_schema_violation():
    m = make()
    m["extra"] = True
    assert verify(m, NOW).reason == "schema_invalid"


# ---------- single use ----------

def test_mark_used_is_single_use():
    store = NonceStore()
    m = approved(make())
    mark_used(m, store=store, deal_id="deal-A", amount=1119.0, payee="seller-x", now=NOW)
    assert m["status"] == "used"
    again = approved(dict(m))
    with pytest.raises(MandateError) as e:
        mark_used(again, store=store, deal_id="deal-A", amount=1119.0, payee="seller-x", now=NOW)
    assert e.value.reason == "replayed_mandate"


def test_mark_used_refuses_unverifiable_mandate():
    m = approved(make())
    m["amount"] = 2.0
    with pytest.raises(MandateError) as e:
        mark_used(m, store=NonceStore(), deal_id="deal-A", amount=2.0, payee="seller-x", now=NOW)
    assert e.value.reason == "hash_mismatch"
    assert m["status"] == "approved"


def test_replayed_mandate_fails_can_charge_even_if_status_is_reset():
    store = NonceStore()
    m = approved(make())
    assert guard(m, store=store).ok
    mark_used(m, store=store, deal_id="deal-A", amount=1119.0, payee="seller-x", now=NOW)
    forged = approved(dict(m))  # attacker flips status back to approved
    r = guard(forged, store=store)
    assert not r.ok and r.reason == "replayed_mandate"


def test_idempotency_key_is_bound_to_hash():
    m = make()
    assert idempotency_key(m) == "mandate:" + m["hash"]


# ---------- deal binding ----------

def test_mandate_for_deal_a_cannot_authorize_deal_b():
    m = approved(make(deal_id="deal-A"))
    assert guard(m, deal_id="deal-A").ok
    r = guard(m, deal_id="deal-B")
    assert not r.ok and r.reason == "deal_mismatch"


def test_relabelling_mandate_to_deal_b_breaks_the_hash():
    m = approved(make(deal_id="deal-A"))
    m["deal_id"] = "deal-B"
    r = guard(m, deal_id="deal-B")
    assert not r.ok and r.reason == "hash_mismatch"


def test_amount_and_payee_expectations_are_enforced():
    m = approved(make())
    assert guard(m, amount=1119, payee="seller-x").ok
    assert guard(m, amount=1118.99).reason == "amount_mismatch"
    assert guard(m, payee="seller-z").reason == "payee_mismatch"


# ---------- charge guard ----------

def test_cannot_charge_without_approved_status_and_approval_id():
    now = NOW
    pending = make()
    assert guard(pending, now).reason == "not_approved"
    for status in ("denied", "expired", "used"):
        m = make()
        m["status"] = status
        m["approval_id"] = "appr-1"
        assert not guard(m, now).ok
    no_id = make()
    no_id["status"] = "approved"
    assert guard(no_id, now).reason == "no_approval_id"
    blank = make()
    blank["status"] = "approved"
    blank["approval_id"] = "  "
    assert guard(blank, now).reason == "no_approval_id"


def test_can_charge_ok_when_approved_with_id_and_fresh():
    m = approved(make())
    r = guard(m, NOW + timedelta(minutes=2))
    assert r.ok and r.reason == "ok"


def test_can_charge_refuses_expired_even_if_approved():
    m = approved(make())
    assert guard(m, NOW + timedelta(minutes=11)).reason == "expired"


# ---------- fix 1: required expectations, bad amounts, buyer ----------

def test_can_charge_and_mark_used_require_deal_amount_payee_and_store_keywords():
    m = approved(make())
    with pytest.raises(TypeError):
        can_charge(m, NOW)  # a deal-A mandate must never pass with no expectations
    for missing in ("deal_id", "amount", "payee", "store"):
        kw = dict(deal_id="deal-A", amount=1119.0, payee="seller-x", store=NonceStore())
        del kw[missing]
        with pytest.raises(TypeError):
            can_charge(m, NOW, **kw)
        kw2 = dict(kw, now=NOW)
        with pytest.raises(TypeError):
            mark_used(m, **kw2)


@pytest.mark.parametrize("bad", [0, -1, -0.01, float("nan"), float("inf"), True, "10"])
def test_expected_amount_that_is_not_positive_finite_is_a_verdict_not_a_raise(bad):
    m = approved(make())
    r = guard(m, amount=bad)
    assert not r.ok and r.reason == "bad_amount"


@pytest.mark.parametrize("bad", [0, -5, float("nan")])
def test_mandate_with_nonpositive_or_nan_amount_is_refused_with_a_verdict(bad):
    m = approved(make())
    m["amount"] = bad
    m["hash"] = "0" * 64  # an attacker can recompute this; the guard must not rely on it
    r = guard(m, amount=1119.0)
    assert not r.ok and r.reason == "bad_amount"
    assert verify(m, NOW).reason == "bad_amount"


def test_buyer_id_expectation():
    m = approved(make(buyer_id="buyer-1"))
    assert guard(m, buyer_id="buyer-1").ok
    r = guard(m, buyer_id="buyer-2")
    assert not r.ok and r.reason == "buyer_mismatch"


# ---------- fix 5: expires_at is capped against the clock, not only against created_at ----------

def _long_lived(created_offset_min=55, ttl_min=60):
    """A mandate whose expires_at is an hour out, with created_at edited (it is not hashed) so the
    created-to-expires gap looks like 5 minutes."""
    m = make()
    m["expires_at"] = format_ts(NOW + timedelta(minutes=ttl_min))
    m["created_at"] = format_ts(NOW + timedelta(minutes=created_offset_min))
    m["hash"] = mandate_hash(m)
    return approved(m)


def test_editing_created_at_cannot_bypass_the_ttl_cap():
    m = _long_lived()
    assert verify(m, NOW).reason == "ttl_too_long"
    assert guard(m, NOW).reason == "ttl_too_long"


def test_expires_at_exactly_ten_minutes_out_is_allowed_and_one_second_more_is_not():
    m = make()  # created NOW, expires NOW + 10 min
    assert verify(m, NOW).ok
    assert verify(m, NOW - timedelta(seconds=1)).reason == "ttl_too_long"
