"""T8: a business payee needs a fresh, verified CRS check, and the mandate can bind to that check.

No network anywhere: payee_ok reads a CrsCheck record (contracts/CrsCheck.schema.json), nothing more.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from pay.crs_gate import bound_ok, check_id, payee_ok, validate_check
from pay.mandate import can_charge, mandate_hash, new_mandate, validate_schema, verify
from pay.replay import NonceStore

NOW = datetime(2026, 10, 24, 9, 0, 0, tzinfo=timezone.utc)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def check(**kw):
    rec = {
        "seller_id": "seller-grace-nakamura",
        "verified": True,
        "reason_codes": [],
        "product": "fraud_finder",
        "persona_id": "P19",
        "checked_at": ts(NOW - timedelta(hours=1)),
        "request_id": "req-0001",
        "origin": "SANDBOX",
    }
    rec.update(kw)
    return rec


# CRS test personas only (plan/sponsor-needs.md section 3). Band output: no scores, no report fields.
P19_GRACE = check()
P13_KAYLA = check(
    seller_id="seller-kayla-brennan", verified=False, persona_id="P13", request_id="req-0013",
    reason_codes=["risk_score_high", "email_new", "phone_owner_no_match", "voip_prepaid", "identity_fail"],
)


def mandate(payee="seller-grace-nakamura", **kw):
    args = dict(deal_id="deal-crs", buyer_id="vidyut", amount=1299.99, payee=payee, now=NOW)
    args.update(kw)
    return new_mandate(**args)


# (a) fresh verified check
def test_a_business_payee_with_fresh_verified_check_is_allowed():
    v = payee_ok(P19_GRACE, business=True, now=NOW)
    assert v.ok and v.reason == "ok"


def test_a_mandate_with_crs_check_id_hashes_differently_and_validates():
    plain = mandate()
    bound = new_mandate(deal_id="deal-crs", buyer_id="vidyut", amount=1299.99, payee="seller-grace-nakamura",
                        now=NOW, crs_check_id=check_id(P19_GRACE))
    # same nonce and expiry so only crs_check_id can differ
    twin = dict(bound)
    twin.pop("crs_check_id")
    twin["hash"] = mandate_hash(twin)
    assert bound["crs_check_id"] == check_id(P19_GRACE)
    assert mandate_hash(bound) != mandate_hash(twin)
    assert bound["hash"] == mandate_hash(bound)
    assert validate_schema(bound) == []
    assert verify(bound, NOW).ok
    assert "crs_check_id" not in plain


def test_a_stripping_or_swapping_crs_check_id_breaks_the_hash():
    bound = mandate(crs_check_id=check_id(P19_GRACE))
    stripped = {k: v for k, v in bound.items() if k != "crs_check_id"}
    assert verify(stripped, NOW).reason == "hash_mismatch"
    swapped = dict(bound, crs_check_id=check_id(P13_KAYLA))
    assert verify(swapped, NOW).reason == "hash_mismatch"


def test_a_empty_crs_check_id_is_refused():
    with pytest.raises(ValueError):
        mandate(crs_check_id="")


# (b) verified false
def test_b_blocked_check_is_refused_with_the_reason_codes():
    v = payee_ok(P13_KAYLA, business=True, now=NOW)
    assert not v.ok and v.reason == "crs_not_verified"
    for code in P13_KAYLA["reason_codes"]:
        assert code in v.detail


def test_b_blocked_check_is_refused_even_for_a_non_business_payee():
    assert not payee_ok(P13_KAYLA, business=False, now=NOW).ok


# (c) no check
def test_c_business_payee_without_a_check_is_refused():
    v = payee_ok(None, business=True, now=NOW)
    assert not v.ok and v.reason == "crs_missing"
    assert v.detail == "identity not checked by CRS"


# (d) expiry
def test_d_check_older_than_24_hours_is_refused():
    old = check(checked_at=ts(NOW - timedelta(hours=24, seconds=1)))
    v = payee_ok(old, business=True, now=NOW)
    assert not v.ok and v.reason == "crs_expired" and v.detail == "CRS check expired"


def test_d_check_just_inside_24_hours_is_allowed():
    ok = check(checked_at=ts(NOW - timedelta(hours=24)))
    assert payee_ok(ok, business=True, now=NOW).ok


# crs.py normalize() writes datetime.isoformat() with the "+00:00" swapped for "Z", so a real check carries
# microseconds ("2026-10-24T07:59:12.345678Z"). That is the shape production emits and it must clear.
def test_d_a_real_check_with_a_microsecond_timestamp_is_allowed():
    real = check(checked_at=(NOW - timedelta(hours=1, microseconds=345678)).isoformat().replace("+00:00", "Z"))
    assert "." in real["checked_at"] and real["checked_at"].endswith("Z")
    v = payee_ok(real, business=True, now=NOW)
    assert v.ok and v.reason == "ok"


def test_d_microsecond_timestamps_still_expire_and_still_refuse_the_future():
    old = check(checked_at="2026-10-23T08:59:59.999999Z")
    assert payee_ok(old, business=True, now=NOW).reason == "crs_expired"
    future = check(checked_at="2026-10-24T11:00:00.000001Z")
    assert payee_ok(future, business=True, now=NOW).reason == "crs_future"


@pytest.mark.parametrize("bad", [
    "2026-10-24T08:00:00.Z",
    "2026-10-24T08:00:00.1234567890Z",
    "2026-10-24T08:00:00.123+00:00",
    "2026-10-24T08:00:00,123Z",
    "2026-10-24T08:00:00.12aZ",
    "2026-10-24T08:00:00.123456",
    "2026-10-24T08:00:00.123456Z\n",
])
def test_d_malformed_fractional_timestamps_are_still_refused(bad):
    v = payee_ok(check(checked_at=bad), business=True, now=NOW)
    assert not v.ok and v.reason == "crs_malformed"


def test_d_check_dated_in_the_future_is_refused():
    future = check(checked_at=ts(NOW + timedelta(hours=2)))
    v = payee_ok(future, business=True, now=NOW)
    assert not v.ok and v.reason == "crs_future"


# (e) SIM seller
def test_e_sim_seller_without_a_check_passes_with_the_reason():
    v = payee_ok(None, business=False, now=NOW)
    assert v.ok
    assert v.reason == "ok" and v.detail == "identity not checked: SIM seller"


# fail closed on anything odd
def test_not_configured_check_is_refused_even_if_it_claims_verified():
    v = payee_ok(check(origin="NOT_CONFIGURED"), business=True, now=NOW)
    assert not v.ok and v.reason == "crs_not_configured"


def test_cached_check_inside_24_hours_is_allowed():
    assert payee_ok(check(origin="CACHED"), business=True, now=NOW).ok


def test_check_for_a_different_seller_is_refused():
    v = payee_ok(P19_GRACE, business=True, now=NOW, seller_id="seller-someone-else")
    assert not v.ok and v.reason == "crs_seller_mismatch"
    assert payee_ok(P19_GRACE, business=True, now=NOW, seller_id="seller-grace-nakamura").ok


@pytest.mark.parametrize("bad", [
    {"verified": "yes"},
    {"verified": 1},
    {"reason_codes": "none"},
    {"reason_codes": ["Has Spaces And Free Text"]},
    {"product": "equifax"},
    {"origin": "LIVE"},
    {"checked_at": "yesterday"},
    {"checked_at": "2026-10-24T08:00:00+00:00"},
])
def test_malformed_check_is_refused(bad):
    v = payee_ok(check(**bad), business=True, now=NOW)
    assert not v.ok and v.reason == "crs_malformed"


# (a2) the adapter on main (agents/crs.py to_crs_check) emits UPPERCASE codes and sends one even when verified

def adapter_check(codes, verified=True, origin="SANDBOX", age=timedelta(hours=2)):
    """The dict main's agents/test_crs.py:314 builds for a verified_stable seller_1 (product tu_identity). checked_at is
    written the way crs.py normalize() writes it (ends in Z); the test there passes a +00:00 string, which the gate refuses."""
    return {"seller_id": "seller_1", "product": "tu_identity", "verified": verified, "reason_codes": codes,
            "origin": origin, "checked_at": ts(NOW - age)}


def test_a_the_adapters_verified_check_with_an_uppercase_code_clears_a_business_payee():
    c = adapter_check(["CRS_IDENTITY_VERIFIED"])
    assert validate_check(c) == []
    v = payee_ok(c, business=True, now=NOW, seller_id="seller_1")
    assert v.ok and v.reason == "ok"


def test_a_the_adapters_not_configured_check_is_refused_for_the_right_reason_not_as_malformed():
    c = adapter_check(["CRS_NOT_CONFIGURED"], verified=False, origin="NOT_CONFIGURED")
    assert validate_check(c) == []
    assert payee_ok(c, business=True, now=NOW, seller_id="seller_1").reason == "crs_not_configured"


def test_a_the_adapters_invalid_and_unavailable_checks_are_refused_as_not_verified():
    for code in ("CRS_INVALID", "CRS_UNAVAILABLE"):
        v = payee_ok(adapter_check([code], verified=False), business=True, now=NOW, seller_id="seller_1")
        assert not v.ok and v.reason == "crs_not_verified" and code in v.detail


def test_a_the_adapters_verified_check_binds_to_a_mandate():
    c = adapter_check(["CRS_IDENTITY_VERIFIED"])
    m = new_mandate(deal_id="deal-crs", buyer_id="vidyut", amount=1299.99, payee="seller-one", now=NOW, crs_check_id=check_id(c))
    assert bound_ok(m, c, business=True, seller_id="seller_1", now=NOW).ok


# (f) existing hashes unchanged
def test_f_mandate_without_crs_check_id_hashes_as_if_the_field_did_not_exist():
    m = {"deal_id": "deal-crs", "amount": 1299.99, "currency": "USD", "payee": "seller-grace-nakamura",
         "tier_price": None, "nonce": "00112233445566778899aabbccddeeff", "expires_at": "2026-10-24T09:10:00Z"}
    # value of the #186 hash format (buyer_id bound, here absent so null); the pre-T8 value was 84c5c04e...a427
    assert mandate_hash(m) == "2a2fd9daaeffdd2fd9ef43d6e781c0d94c2b9124b8e339ed16561852f7137893"
    assert mandate_hash(dict(m, crs_check_id=None)) == mandate_hash(m)


# binding: the mandate must name exactly the check that cleared the payee
def test_bound_ok_requires_the_mandate_to_name_this_check_for_a_business_payee():
    good = mandate(crs_check_id=check_id(P19_GRACE))
    assert bound_ok(good, P19_GRACE, business=True, seller_id="seller-grace-nakamura", now=NOW).ok
    unbound = mandate()
    v = bound_ok(unbound, P19_GRACE, business=True, seller_id="seller-grace-nakamura", now=NOW)
    assert not v.ok and v.reason == "crs_not_bound"
    other = check(request_id="req-9999")
    v = bound_ok(good, other, business=True, seller_id="seller-grace-nakamura", now=NOW)
    assert not v.ok and v.reason == "crs_not_bound"


def test_bound_ok_refuses_a_mandate_carrying_another_sellers_check_id():
    # seller A's verified check id on a mandate that pays seller B: the gate is told who is paid and refuses
    m = mandate(payee="seller-evil", crs_check_id=check_id(P19_GRACE))
    v = bound_ok(m, P19_GRACE, business=True, seller_id="seller-evil", now=NOW)
    assert not v.ok and v.reason == "crs_seller_mismatch"
    assert bound_ok(m, P19_GRACE, business=True, seller_id="seller-grace-nakamura", now=NOW).ok


def test_bound_ok_fails_closed_without_a_seller_id():
    m = mandate(payee="seller-evil", crs_check_id=check_id(P19_GRACE))
    with pytest.raises(TypeError):
        bound_ok(m, P19_GRACE, business=True, now=NOW)
    v = bound_ok(m, P19_GRACE, business=True, seller_id=None, now=NOW)
    assert not v.ok and v.reason == "crs_seller_mismatch"


def test_bound_ok_for_a_sim_seller_needs_no_binding():
    assert bound_ok(mandate(), None, business=False, seller_id="seller-sim", now=NOW).ok


def test_bound_ok_refuses_when_the_check_fails_before_looking_at_the_binding():
    m = mandate(crs_check_id=check_id(P13_KAYLA))
    v = bound_ok(m, P13_KAYLA, business=True, seller_id="seller-kayla-brennan", now=NOW)
    assert not v.ok and v.reason == "crs_not_verified"


def test_a_bound_mandate_still_passes_can_charge():
    m = mandate(crs_check_id=check_id(P19_GRACE))
    m["status"], m["approval_id"] = "approved", "appr-1"
    v = can_charge(m, NOW, deal_id="deal-crs", amount=1299.99, payee="seller-grace-nakamura", store=NonceStore())
    assert v.ok


def test_check_id_is_stable_and_changes_with_the_check():
    assert check_id(P19_GRACE) == check_id(dict(P19_GRACE))
    assert check_id(P19_GRACE) != check_id(P13_KAYLA)
    assert check_id(P19_GRACE) != check_id(check(checked_at=ts(NOW - timedelta(hours=2))))
    assert check_id(P19_GRACE).startswith("crs_") and len(check_id(P19_GRACE)) == 4 + 32


# (g) the contract
def _schema():
    with open(os.path.join(ROOT, "contracts", "CrsCheck.schema.json"), encoding="utf-8") as f:
        return json.load(f)


def test_g_contract_accepts_the_p19_and_p13_fixtures():
    assert validate_check(P19_GRACE) == []
    assert validate_check(P13_KAYLA) == []


def test_g_contract_rejects_raw_report_fields():
    for extra in ({"risk": {"score": 9}}, {"ssn": "000-00-0000"}, {"score": 9}, {"report": {}}):
        errors = validate_check(dict(P19_GRACE, **extra))
        assert errors, extra


def test_g_contract_is_closed_and_names_the_required_fields():
    s = _schema()
    assert s["additionalProperties"] is False
    assert set(s["required"]) == {"seller_id", "verified", "reason_codes", "product", "checked_at", "origin"}
    assert set(s["properties"]) == {"seller_id", "verified", "reason_codes", "product", "persona_id",
                                    "checked_at", "request_id", "origin"}
    assert s["properties"]["product"]["enum"] == ["fraud_finder", "tu_identity"]
    assert s["properties"]["origin"]["enum"] == ["SANDBOX", "CACHED", "NOT_CONFIGURED"]


def test_g_contract_requires_every_required_field():
    for key in _schema()["required"]:
        rec = dict(P19_GRACE)
        del rec[key]
        assert validate_check(rec), key


def test_the_manual_fallback_agrees_with_jsonschema(monkeypatch):
    """Without jsonschema installed the same records must pass and fail the same way."""
    import builtins
    real_import = builtins.__import__

    def no_jsonschema(name, *a, **k):
        if name == "jsonschema":
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_jsonschema)
    assert validate_check(P19_GRACE) == []
    assert validate_check(dict(P19_GRACE, ssn="x"))
    assert validate_check(dict(P19_GRACE, reason_codes=["Free Text"]))
    assert validate_check(dict(P19_GRACE, reason_codes=["CRS_IDENTITY_VERIFIED", "x" * 49]))
    assert validate_check(dict(P19_GRACE, reason_codes=["CRS_IDENTITY_VERIFIED", "risk_score_high"])) == []
    assert validate_check(dict(P19_GRACE, reason_codes="none"))
    assert validate_check(dict(P19_GRACE, verified="yes"))
