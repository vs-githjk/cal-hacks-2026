"""#449 RT-25: no CRS profile file never makes a payee a SIM seller, and the unsigned cache file is never trusted.
SIM is an explicit label in the operator's private profile file (seller_type "sim" or "individual"); everything else is
a business payee that CRS must have checked. The cache is used only with a valid HMAC from CRS_CACHE_SECRET. Offline."""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import crs
import pytest
from pay.crs_gate import payee_ok

NOW = datetime(2026, 10, 24, 8, tzinfo=timezone.utc)
SECRET = "cache-secret-for-tests-0123456789"
BODY = {"firstName": "Synthetic"}
DIGEST = hashlib.sha256(json.dumps(BODY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in ("CRS_TEST_IDENTITIES_PATH", "CRS_SIGNAL_CACHE_PATH", "CRS_API_KEY", "CRS_USERNAME", "CRS_PASSWORD",
                 "CRS_CACHE_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(crs, "_payee_cache", {})
    monkeypatch.setattr(crs, "APPROVED_PERSONAS", {"official-a": DIGEST})
    monkeypatch.setattr(crs, "_request", lambda *a: (_ for _ in ()).throw(AssertionError("no CRS request expected")))


def profile_file(monkeypatch, tmp_path, sellers):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"sellers": sellers}), encoding="utf-8")
    monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(path))
    monkeypatch.setenv("CRS_SIGNAL_CACHE_PATH", str(tmp_path / "cache.json"))
    return path


BUSINESS = {"seller_type": "business", "consent": True, "persona_ref": "official-a", "request": BODY}


# ---- who is a SIM seller: only an explicit label -------------------------------------------------------------------
def test_no_profile_file_is_not_a_sim_seller():
    assert crs.sim_reason("seller_1") is None
    assert crs.is_business("seller_1") is True
    assert crs.sim_labelled("seller_1") is False


def test_a_profile_file_without_an_entry_is_not_a_sim_seller(monkeypatch, tmp_path):
    profile_file(monkeypatch, tmp_path, {"seller_2": BUSINESS})
    assert crs.sim_reason("seller_1") is None and crs.sim_labelled("seller_1") is False


@pytest.mark.parametrize("label", ["sim", "SIM", " Sim ", "individual", "Individual"])
def test_an_explicit_sim_or_individual_label_is_a_sim_seller(monkeypatch, tmp_path, label):
    profile_file(monkeypatch, tmp_path, {"seller_1": {"seller_type": label, "consent": True}})
    assert crs.sim_reason("seller_1") and "SIM" in crs.sim_reason("seller_1").upper() + "individual"
    assert crs.sim_labelled("seller_1") is True and crs.is_business("seller_1") is False


@pytest.mark.parametrize("label", ["business", "busines", "", None, "partner", "simulated", "sim seller", 5])
def test_any_other_seller_type_is_a_business_that_must_be_checked(monkeypatch, tmp_path, label):
    profile_file(monkeypatch, tmp_path, {"seller_1": {"seller_type": label, "consent": True}})
    assert crs.sim_reason("seller_1") is None and crs.sim_labelled("seller_1") is False


# ---- the payee gate: not configured is held, a labelled SIM seller passes -------------------------------------------
def test_check_payee_with_no_profile_file_is_not_configured_and_the_gate_holds():
    out = asyncio.run(crs.check_payee("seller_1", NOW))     # _request would raise: no request is made
    assert out["business"] is True and out["cached"] is False
    check = out["check"]
    assert check["origin"] == "NOT_CONFIGURED" and check["verified"] is False and check["reason_codes"] == ["CRS_NOT_CONFIGURED"]
    assert check["seller_id"] == "seller_1" and check["product"] == "tu_identity"
    verdict = payee_ok(check, business=out["business"], now=NOW, seller_id="seller_1")
    assert not verdict and verdict.reason == "crs_not_configured"
    assert "seller_1" not in crs._payee_cache


def test_check_payee_with_a_file_but_no_entry_for_the_payee_is_also_not_configured(monkeypatch, tmp_path):
    profile_file(monkeypatch, tmp_path, {"seller_2": BUSINESS})
    monkeypatch.setenv("CRS_USERNAME", "u")
    monkeypatch.setenv("CRS_PASSWORD", "p")
    out = asyncio.run(crs.check_payee("seller_1", NOW))
    assert out["business"] is True and out["check"]["origin"] == "NOT_CONFIGURED"
    verdict = payee_ok(out["check"], business=True, now=NOW, seller_id="seller_1")
    assert verdict.reason == "crs_not_configured"       # not "crs_not_verified": nothing was configured to check


@pytest.mark.parametrize("label", ["sim", "individual"])
def test_a_labelled_sim_payee_passes_with_no_request_and_says_so(monkeypatch, tmp_path, label):
    profile_file(monkeypatch, tmp_path, {"seller_1": {"seller_type": label, "consent": True}})
    out = asyncio.run(crs.check_payee("seller_1", NOW))
    assert out["business"] is False and out["check"] is None and out["sim_reason"]
    verdict = payee_ok(out["check"], business=out["business"], now=NOW, seller_id="seller_1")
    assert verdict and verdict.detail == "identity not checked: SIM seller"


def test_an_unreadable_profile_file_still_holds_never_sim(monkeypatch, tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("{not json")
    monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(path))
    with pytest.raises(crs.ProfilesUnreadable):
        asyncio.run(crs.check_payee("seller_1", NOW))


# ---- the buyer's eligibility ----------------------------------------------------------------------------------------
def test_an_unconfigured_payee_is_not_eligible_unless_labelled_sim(monkeypatch, tmp_path):
    empty = {"signal": None, "reason": crs.REASON_NOT_CONFIGURED}
    for check in (None, {}, empty):
        assert crs.eligible("seller_1", check, NOW) is False             # no profile file at all
    profile_file(monkeypatch, tmp_path, {"seller_1": BUSINESS})
    assert crs.eligible("seller_1", empty, NOW) is False                 # a business profile but no CRS credentials
    profile_file(monkeypatch, tmp_path, {"seller_1": {"seller_type": "sim"}})
    for check in (None, {}, empty):
        assert crs.eligible("seller_1", check, NOW) is True              # explicitly SIM: exempt
    profile_file(monkeypatch, tmp_path, {"seller_1": {"seller_type": "individual"}})
    assert crs.eligible("seller_1", None, NOW) is True
    assert crs.eligible("seller_9", None, NOW) is False                  # a seller the file does not name


def test_to_crs_check_still_reports_not_configured_for_the_buyers_notice():
    assert crs.to_crs_check("seller_1", {"signal": None, "reason": crs.REASON_NOT_CONFIGURED})["origin"] == "NOT_CONFIGURED"


# ---- the dry-run status ---------------------------------------------------------------------------------------------
def test_status_of_an_unlabelled_payee_is_held_not_sim(monkeypatch, tmp_path):
    out = crs.payee_status("seller_1", NOW)
    assert out["state"] == "not_configured" and "CRS_TEST_IDENTITIES_PATH" in out["reason"] and out["band"] is None
    profile_file(monkeypatch, tmp_path, {"seller_2": BUSINESS})
    out = crs.payee_status("seller_1", NOW)
    assert out["state"] == "not_configured" and "no CRS profile" in out["reason"]


def test_status_of_a_labelled_sim_payee_is_sim(monkeypatch, tmp_path):
    profile_file(monkeypatch, tmp_path, {"seller_1": {"seller_type": "sim"}})
    assert crs.payee_status("seller_1", NOW)["state"] == "sim"


# ---- the cache: used only with a valid HMAC -------------------------------------------------------------------------
def signal(band="verified_stable", at=NOW - timedelta(hours=1), supplier="seller_1"):
    return {"supplier_id": supplier, "stability": band, "checked_at": at.isoformat().replace("+00:00", "Z"), "source": "sandbox"}


def entry(band="verified_stable", persona="official-a", **kw):
    return {"persona_ref": persona, "signal": signal(band, **kw), "reason": crs._reason(band)}


def test_sign_and_verify_round_trip_and_every_part_is_covered(monkeypatch):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    signed = crs.sign_entry("seller_1", entry())
    assert isinstance(signed["mac"], str) and len(signed["mac"]) == 64 and crs.entry_verified("seller_1", signed)
    assert not crs.entry_verified("seller_2", signed)                                   # another supplier key
    assert not crs.entry_verified("seller_1", {**signed, "persona_ref": "official-b"})
    assert not crs.entry_verified("seller_1", {**signed, "signal": {**signed["signal"], "stability": "caution"}})
    assert not crs.entry_verified("seller_1", {**signed, "signal": {**signed["signal"], "checked_at": "2026-10-24T07:59:00Z"}})
    assert not crs.entry_verified("seller_1", {**signed, "reason": "forged"})
    assert not crs.entry_verified("seller_1", {k: v for k, v in signed.items() if k != "mac"})
    for bad in (None, "", "0" * 64, 5, ["x"], signed["mac"].upper() + "0"):
        assert not crs.entry_verified("seller_1", {**signed, "mac": bad})
    assert not crs.entry_verified("seller_1", "not an entry") and not crs.entry_verified("seller_1", None)


@pytest.mark.parametrize("secret", [None, "", "   ", "too-short"])
def test_without_a_usable_secret_nothing_verifies_and_nothing_is_signed(monkeypatch, secret):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    signed = crs.sign_entry("seller_1", entry())
    monkeypatch.delenv("CRS_CACHE_SECRET")
    if secret is not None:
        monkeypatch.setenv("CRS_CACHE_SECRET", secret)
    assert not crs.entry_verified("seller_1", signed)          # even a genuine tag: no secret, no trust
    assert "mac" not in crs.sign_entry("seller_1", entry())


def test_a_tag_made_with_another_secret_does_not_verify(monkeypatch):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    signed = crs.sign_entry("seller_1", entry())
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET + "-rotated")
    assert not crs.entry_verified("seller_1", signed)


def test_the_tag_is_compared_in_constant_time():
    import inspect
    assert "compare_digest" in inspect.getsource(crs)


def fallback(monkeypatch, tmp_path, cache):
    """A business profile whose sandbox call fails, with `cache` on disk: what check_sellers returns for it."""
    profile_file(monkeypatch, tmp_path, {"seller_1": BUSINESS})
    monkeypatch.setenv("CRS_API_KEY", "test-token")
    monkeypatch.setattr(crs, "_request", lambda *a: (_ for _ in ()).throw(OSError("transport down")))
    (tmp_path / "cache.json").write_text(json.dumps(cache), encoding="utf-8")
    return asyncio.run(crs.check_sellers(NOW))["seller_1"]


def test_a_signed_cache_entry_is_used_when_the_sandbox_is_down(monkeypatch, tmp_path):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    out = fallback(monkeypatch, tmp_path, {"seller_1": crs.sign_entry("seller_1", entry())})
    assert out["signal"]["source"] == "recorded" and out["signal"]["stability"] == "verified_stable"
    assert crs.eligible("seller_1", out, NOW) is True


def test_an_unsigned_cache_entry_is_ignored_even_with_a_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    out = fallback(monkeypatch, tmp_path, {"seller_1": entry()})
    assert out == {"signal": None, "reason": crs.REASON_UNAVAILABLE}
    assert crs.eligible("seller_1", out, NOW) is False


def test_a_forged_or_edited_cache_entry_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    genuine = crs.sign_entry("seller_1", entry("not_verified"))
    forged = {**genuine, "signal": {**genuine["signal"], "stability": "verified_stable"}, "reason": crs.REASON_VERIFIED}
    assert fallback(monkeypatch, tmp_path, {"seller_1": forged}) == {"signal": None, "reason": crs.REASON_UNAVAILABLE}
    guessed = {**entry(), "mac": "a" * 64}
    assert fallback(monkeypatch, tmp_path, {"seller_1": guessed}) == {"signal": None, "reason": crs.REASON_UNAVAILABLE}


def test_without_the_secret_even_a_signed_entry_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    signed = crs.sign_entry("seller_1", entry())
    monkeypatch.delenv("CRS_CACHE_SECRET")
    assert fallback(monkeypatch, tmp_path, {"seller_1": signed}) == {"signal": None, "reason": crs.REASON_UNAVAILABLE}


def test_an_entry_signed_for_another_seller_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    other = crs.sign_entry("seller_2", entry(supplier="seller_1"))      # tag made under another key, copied to seller_1
    assert fallback(monkeypatch, tmp_path, {"seller_1": other}) == {"signal": None, "reason": crs.REASON_UNAVAILABLE}


def test_a_fresh_sandbox_result_is_written_with_a_tag_that_verifies(monkeypatch, tmp_path):
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    profile_file(monkeypatch, tmp_path, {"seller_1": BUSINESS})
    monkeypatch.setenv("CRS_API_KEY", "test-token")
    monkeypatch.setattr(crs, "_request", lambda *a: {"addOnProducts": [{"idManagerVerification": {"messages": []}}]})
    out = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert out["signal"]["source"] == "sandbox"
    written = json.loads((tmp_path / "cache.json").read_text())["seller_1"]
    assert crs.entry_verified("seller_1", written) and written["signal"]["stability"] == "verified_stable"


def test_without_the_secret_a_fresh_result_is_written_untagged_and_never_used_later(monkeypatch, tmp_path):
    profile_file(monkeypatch, tmp_path, {"seller_1": BUSINESS})
    monkeypatch.setenv("CRS_API_KEY", "test-token")
    monkeypatch.setattr(crs, "_request", lambda *a: {"addOnProducts": [{"idManagerVerification": {"messages": []}}]})
    asyncio.run(crs.check_sellers(NOW))
    written = json.loads((tmp_path / "cache.json").read_text())["seller_1"]
    assert "mac" not in written
    monkeypatch.setattr(crs, "_request", lambda *a: (_ for _ in ()).throw(OSError("down")))
    assert asyncio.run(crs.check_sellers(NOW))["seller_1"] == {"signal": None, "reason": crs.REASON_UNAVAILABLE}


def test_the_dry_run_status_shows_a_recorded_band_only_for_a_signed_entry(monkeypatch, tmp_path):
    profile_file(monkeypatch, tmp_path, {"seller_1": BUSINESS})
    cache = tmp_path / "cache.json"
    monkeypatch.setenv("CRS_CACHE_SECRET", SECRET)
    cache.write_text(json.dumps({"seller_1": entry()}))
    assert crs.payee_status("seller_1", NOW)["band"] is None
    cache.write_text(json.dumps({"seller_1": crs.sign_entry("seller_1", entry())}))
    assert crs.payee_status("seller_1", NOW)["band"] == "verified_stable"
    monkeypatch.delenv("CRS_CACHE_SECRET")
    assert crs.payee_status("seller_1", NOW)["band"] is None
