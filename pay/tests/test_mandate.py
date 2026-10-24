"""d2 mandate tests: hash, expiry, single use, deal binding, charge guard."""
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from pay.mandate import (
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
    mark_used(m, store, now=NOW)
    assert m["status"] == "used"
    again = approved(dict(m))
    with pytest.raises(MandateError) as e:
        mark_used(again, store, now=NOW)
    assert e.value.reason == "replayed_mandate"


def test_mark_used_refuses_unverifiable_mandate():
    m = approved(make())
    m["amount"] = 2.0
    with pytest.raises(MandateError) as e:
        mark_used(m, NonceStore(), now=NOW)
    assert e.value.reason == "hash_mismatch"
    assert m["status"] == "approved"


def test_replayed_mandate_fails_can_charge_even_if_status_is_reset():
    store = NonceStore()
    m = approved(make())
    assert can_charge(m, NOW, store).ok
    mark_used(m, store, now=NOW)
    forged = approved(dict(m))  # attacker flips status back to approved
    r = can_charge(forged, NOW, store)
    assert not r.ok and r.reason == "replayed_mandate"


def test_idempotency_key_is_bound_to_hash():
    m = make()
    assert idempotency_key(m) == "mandate:" + m["hash"]


# ---------- deal binding ----------

def test_mandate_for_deal_a_cannot_authorize_deal_b():
    m = approved(make(deal_id="deal-A"))
    assert can_charge(m, NOW, deal_id="deal-A").ok
    r = can_charge(m, NOW, deal_id="deal-B")
    assert not r.ok and r.reason == "deal_mismatch"


def test_relabelling_mandate_to_deal_b_breaks_the_hash():
    m = approved(make(deal_id="deal-A"))
    m["deal_id"] = "deal-B"
    r = can_charge(m, NOW, deal_id="deal-B")
    assert not r.ok and r.reason == "hash_mismatch"


def test_amount_and_payee_expectations_are_enforced():
    m = approved(make())
    assert can_charge(m, NOW, amount=1119, payee="seller-x").ok
    assert can_charge(m, NOW, amount=1118.99).reason == "amount_mismatch"
    assert can_charge(m, NOW, payee="seller-z").reason == "payee_mismatch"


# ---------- charge guard ----------

def test_cannot_charge_without_approved_status_and_approval_id():
    now = NOW
    pending = make()
    assert can_charge(pending, now).reason == "not_approved"
    for status in ("denied", "expired", "used"):
        m = make()
        m["status"] = status
        m["approval_id"] = "appr-1"
        assert not can_charge(m, now).ok
    no_id = make()
    no_id["status"] = "approved"
    assert can_charge(no_id, now).reason == "no_approval_id"
    blank = make()
    blank["status"] = "approved"
    blank["approval_id"] = "  "
    assert can_charge(blank, now).reason == "no_approval_id"


def test_can_charge_ok_when_approved_with_id_and_fresh():
    m = approved(make())
    r = can_charge(m, NOW + timedelta(minutes=2))
    assert r.ok and r.reason == "ok"


def test_can_charge_refuses_expired_even_if_approved():
    m = approved(make())
    assert can_charge(m, NOW + timedelta(minutes=11)).reason == "expired"
