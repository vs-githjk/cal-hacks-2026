import asyncio
import hashlib
import json
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import crs
import pytest
from buyer import hunt


NOW = datetime(2026, 10, 24, 8, tzinfo=timezone.utc)


@pytest.fixture
def tmp_path():
    cache = Path(__file__).resolve().parents[1] / ".cache"
    cache.mkdir(exist_ok=True)
    path = cache / f"crs-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        if path.resolve().parent == cache.resolve():
            shutil.rmtree(path)


def response(codes=()):
    return {"addOnProducts": [{"idManagerVerification": {"messages": [{"code": c} for c in codes]}}]}


def test_normalize_bands_and_rejects_bad_responses():
    assert crs.normalize("seller_1", response(), NOW.isoformat())["stability"] == "verified_stable"
    assert crs.normalize("seller_1", response(["2401"]), NOW.isoformat())["stability"] == "caution"
    for codes in (["2101"], ["2401", "2101"], ["9999"]):
        assert crs.normalize("seller_1", response(codes), NOW.isoformat())["stability"] == "not_verified"
    for malformed in ({}, {"addOnProducts": [{"idManagerVerification": {}}]},
                      {"addOnProducts": [{"idManagerVerification": {"messages": ""}}]}):
        assert crs.normalize("seller_1", malformed, NOW.isoformat())["stability"] == "not_verified"


def test_normalize_has_only_contract_fields_and_no_provider_data():
    raw = response()
    raw["privateCanary"] = "secret-name-123"
    signal = crs.normalize("seller_1", raw, NOW.isoformat())
    assert set(signal) == {"supplier_id", "stability", "checked_at", "source"}
    assert "secret-name-123" not in json.dumps(signal)
    assert crs.normalize("seller_1", {**response(), "errorMessages": ["private"]}, NOW.isoformat())["stability"] == "not_verified"
    assert crs.normalize("seller_1", {**response(), "messages": ["private"]}, NOW.isoformat())["stability"] == "not_verified"


def setup_profile(monkeypatch, tmp_path, *, seller_type="business", consent=True, persona="official-a", body=None,
                  auth_stub=True):
    body = body or {"firstName": "Synthetic"}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    profile_path = tmp_path / "private.json"
    profile_path.write_text(json.dumps({"sellers": {"seller_1": {
        "seller_type": seller_type, "consent": consent, "persona_ref": persona,
        "request": body,
    }}}), encoding="utf-8")
    monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(profile_path))
    monkeypatch.setenv("CRS_USERNAME", "test-user")
    monkeypatch.setenv("CRS_PASSWORD", "test-password")
    if auth_stub:
        monkeypatch.setattr(crs, "_get_token", lambda: "test-token")
    monkeypatch.setattr(crs, "_paths", lambda: (profile_path, tmp_path / "cache.json"))
    monkeypatch.setattr(crs, "APPROVED_PERSONAS", {"official-a": digest})
    return body


def test_unapproved_or_unconsented_profiles_make_no_request(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("CRS_API_KEY", "test-token")
    monkeypatch.setattr(crs, "_request", lambda *args: calls.append(args))
    body = {"firstName": "Synthetic"}
    for values in ({"consent": False}, {"seller_type": "individual"}, {"persona": "unknown"}):
        opts = {"seller_type": "business", "consent": True, "persona": "official-a", "body": body}
        opts.update(values)
        setup_profile(monkeypatch, tmp_path, **opts)
        asyncio.run(crs.check_sellers(NOW))
    setup_profile(monkeypatch, tmp_path, body=body)
    profile_path = tmp_path / "private.json"
    profile = json.loads(profile_path.read_text())
    profile["sellers"]["seller_1"]["request"] = {"firstName": "changed"}
    profile_path.write_text(json.dumps(profile))
    asyncio.run(crs.check_sellers(NOW))
    assert calls == []


def test_malformed_profile_file_and_unhashable_persona_fail_closed(monkeypatch, tmp_path):
    path = tmp_path / "private.json"
    path.write_text("[]")
    monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(path))
    monkeypatch.setattr(crs, "_paths", lambda: (path, tmp_path / "cache.json"))
    assert asyncio.run(crs.check_sellers(NOW)) == {}
    setup_profile(monkeypatch, tmp_path)
    profile = json.loads(path.read_text())
    profile["sellers"]["seller_1"]["persona_ref"] = []
    path.write_text(json.dumps(profile))
    assert asyncio.run(crs.check_sellers(NOW))["seller_1"]["signal"] is None


def test_missing_token_returns_safe_unavailable_without_request(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    monkeypatch.delenv("CRS_API_KEY", raising=False)
    monkeypatch.delenv("CRS_USERNAME", raising=False)
    monkeypatch.delenv("CRS_PASSWORD", raising=False)
    monkeypatch.setattr(crs, "_request", lambda *args: (_ for _ in ()).throw(AssertionError("called")))
    result = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert result == {"signal": None, "reason": crs.REASON_NOT_CONFIGURED}
    assert crs.eligible("seller_1", result, NOW)


def test_request_uses_fixed_sandbox_endpoint_and_requires_http_200(monkeypatch):
    class Reply:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(response()).encode()

    calls = []
    def opened(req, timeout):
        calls.append((req.full_url, req.get_method(), req.get_header("Authorization"), timeout))
        return Reply()

    monkeypatch.setattr(crs, "urlopen", opened)
    assert crs._request({"firstName": "Synthetic"}, "token") == response()
    assert calls == [(crs.ENDPOINT, "POST", "Bearer token", 4)]

    class ErrorReply(Reply):
        status = 201

    monkeypatch.setattr(crs, "urlopen", lambda *args, **kwargs: ErrorReply())
    with pytest.raises(ValueError):
        crs._request({"firstName": "Synthetic"}, "token")


def test_live_response_and_cached_fallback_preserve_original_time(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    monkeypatch.setenv("CRS_API_KEY", "private-token-canary")
    monkeypatch.setattr(crs, "_request", lambda body, token: response())
    fresh = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert fresh["signal"]["source"] == "sandbox"
    assert crs.eligible("seller_1", fresh, NOW)
    monkeypatch.delenv("CRS_API_KEY")
    monkeypatch.setattr(crs, "_get_token", lambda: (_ for _ in ()).throw(crs.CrsAuthError("failed")))
    monkeypatch.setattr(crs, "_request", lambda *args: (_ for _ in ()).throw(OSError("private provider text")))
    old = asyncio.run(crs.check_sellers(NOW + timedelta(hours=1)))["seller_1"]
    assert old["signal"]["source"] == "recorded"
    assert old["signal"]["checked_at"] == fresh["signal"]["checked_at"]
    assert crs.eligible("seller_1", old, NOW + timedelta(hours=1))
    assert "private-token-canary" not in json.dumps(old)
    assert "private provider text" not in json.dumps(old)


def test_invalid_cache_entries_never_grant_fallback(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    monkeypatch.delenv("CRS_API_KEY", raising=False)
    cache_path = tmp_path / "cache.json"
    valid = {"persona_ref": "official-a", "signal": {
        "supplier_id": "seller_1", "stability": "verified_stable",
        "checked_at": NOW.isoformat(), "source": "sandbox"}, "reason": crs.REASON_VERIFIED}
    variants = [None, "{broken", {**valid, "persona_ref": "official-b"},
                {**valid, "signal": {**valid["signal"], "checked_at": (NOW - timedelta(hours=25)).isoformat()}},
                {**valid, "signal": {**valid["signal"], "checked_at": (NOW + timedelta(seconds=1)).isoformat()}}]
    for entry in variants:
        cache_path.write_text("{bad" if entry == "{broken" else json.dumps({"seller_1": entry}) if entry else "{}")
        result = asyncio.run(crs.check_sellers(NOW))["seller_1"]
        assert result["signal"] is None


def test_invalid_cache_is_never_eligible(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    monkeypatch.setenv("CRS_API_KEY", "test-token")
    monkeypatch.setattr(crs, "_request", lambda *args: response())
    expired = asyncio.run(crs.check_sellers(NOW - timedelta(hours=25)))["seller_1"]
    assert not crs.eligible("seller_1", expired, NOW)
    future = asyncio.run(crs.check_sellers(NOW + timedelta(seconds=1)))["seller_1"]
    assert not crs.eligible("seller_1", future, NOW)
    fresh = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    fresh["signal"]["supplier_id"] = "seller_2"
    assert not crs.eligible("seller_1", fresh, NOW)


def test_simulated_fixture_never_grants_eligibility(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    signal = json.loads((Path(crs.__file__).parent / "fixtures" / "crs_signals.json").read_text())[0]
    result = {"signal": signal, "reason": crs.REASON_VERIFIED}
    assert not crs.eligible("seller_1", result, NOW)


def test_eligibility_rejects_persona_remap(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    monkeypatch.setenv("CRS_API_KEY", "test-token")
    monkeypatch.setattr(crs, "_request", lambda *args: response())
    check = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert crs.eligible("seller_1", check, NOW)
    profile_path = tmp_path / "private.json"
    profile = json.loads(profile_path.read_text())
    second_body = {"firstName": "Another synthetic profile"}
    second_digest = hashlib.sha256(json.dumps(second_body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    monkeypatch.setattr(crs, "APPROVED_PERSONAS", {"official-a": crs._canonical_hash({"firstName": "Synthetic"}),
                                                     "official-b": second_digest})
    profile["sellers"]["seller_1"]["persona_ref"] = "official-b"
    profile["sellers"]["seller_1"]["request"] = second_body
    profile_path.write_text(json.dumps(profile))
    assert not crs.eligible("seller_1", check, NOW)


def test_trusted_individual_is_exempt_without_crs_call(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path, seller_type="individual")
    monkeypatch.setenv("CRS_API_KEY", "test-token")
    calls = []
    monkeypatch.setattr(crs, "_request", lambda *args: calls.append(args))
    result = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert result["signal"] is None
    assert crs.eligible("seller_1", result, NOW)
    assert calls == []


def test_failed_check_preserves_old_cache_but_fresh_adverse_replaces(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    monkeypatch.setenv("CRS_API_KEY", "token")
    monkeypatch.setattr(crs, "_request", lambda *args: response())
    old = asyncio.run(crs.check_sellers(NOW))["seller_1"]["signal"]
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(crs, "_request", lambda *args: (_ for _ in ()).throw(OSError("secret")))
    asyncio.run(crs.check_sellers(NOW + timedelta(minutes=2)))
    assert json.loads(cache_path.read_text())["seller_1"]["signal"] == old
    monkeypatch.setattr(crs, "_request", lambda *args: response(["2101"]))
    adverse = asyncio.run(crs.check_sellers(NOW + timedelta(minutes=3)))["seller_1"]["signal"]
    assert adverse["stability"] == "not_verified"
    assert json.loads(cache_path.read_text())["seller_1"]["signal"] == adverse


def test_http_200_error_payload_is_unavailable_and_does_not_replace_cache(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    monkeypatch.setenv("CRS_API_KEY", "token")
    monkeypatch.setattr(crs, "_request", lambda *args: response())
    good = asyncio.run(crs.check_sellers(NOW))["seller_1"]["signal"]
    for field in ("errorMessages", "messages"):
        monkeypatch.setattr(crs, "_request", lambda *args: {field: ["private vendor detail"], **response()})
        result = asyncio.run(crs.check_sellers(NOW + timedelta(minutes=1)))["seller_1"]
        assert result["signal"]["source"] == "recorded"
        assert json.loads((tmp_path / "cache.json").read_text())["seller_1"]["signal"] == good
        assert "private vendor detail" not in json.dumps(result)


def test_cache_write_failure_keeps_fresh_signal_and_emits_fixed_warning(monkeypatch, tmp_path, capsys):
    setup_profile(monkeypatch, tmp_path)
    monkeypatch.setenv("CRS_API_KEY", "token-canary")
    monkeypatch.setattr(crs, "_request", lambda *args: response())
    monkeypatch.setattr(crs, "_cache_write", lambda *args: (_ for _ in ()).throw(OSError("secret")))
    result = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert result["signal"]["source"] == "sandbox"
    warning = capsys.readouterr().err
    assert warning.strip() == "CRS result cache could not be saved."
    assert "secret" not in warning and "token-canary" not in warning

class _Reply:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_missing_credentials_overrides_existing_cache_without_http(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path)
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"seller_1": {"persona_ref": "official-a", "signal": {
        "supplier_id": "seller_1", "stability": "verified_stable",
        "checked_at": NOW.isoformat(), "source": "sandbox"},
        "reason": crs.REASON_VERIFIED}}), encoding="utf-8")
    monkeypatch.delenv("CRS_USERNAME", raising=False)
    monkeypatch.delenv("CRS_PASSWORD", raising=False)
    calls = []
    monkeypatch.setattr(crs, "_open_request", lambda request: calls.append(request))
    result = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert result == {"signal": None, "reason": crs.REASON_NOT_CONFIGURED}
    assert calls == []


def test_preissued_token_skips_login(monkeypatch):
    crs._auth_state = crs._AuthState()
    monkeypatch.setenv("CRS_API_KEY", "preissued-token")
    monkeypatch.delenv("CRS_USERNAME", raising=False)
    monkeypatch.delenv("CRS_PASSWORD", raising=False)
    calls = []
    monkeypatch.setattr(crs, "_open_request", lambda request: calls.append(request))
    assert crs._get_token() == "preissued-token"
    assert calls == []


def test_to_crs_check_has_flat_sanitized_shape():
    check = {"signal": {"supplier_id": "seller_1", "stability": "verified_stable",
                         "checked_at": NOW.isoformat(), "source": "sandbox"}}
    assert crs.to_crs_check("seller_1", check) == {
        "seller_id": "seller_1", "product": "tu_identity", "verified": True,
        "reason_codes": ["CRS_IDENTITY_VERIFIED"], "origin": "SANDBOX",
        "checked_at": NOW.isoformat(),
    }
    not_configured = crs.to_crs_check("seller_1", {"signal": None, "reason": crs.REASON_NOT_CONFIGURED})
    assert not_configured["seller_id"] == "seller_1"
    assert not_configured["product"] == "tu_identity"
    assert not_configured["verified"] is False
    assert not_configured["reason_codes"] == ["CRS_NOT_CONFIGURED"]
    assert not_configured["origin"] == "NOT_CONFIGURED"
    assert datetime.fromisoformat(not_configured["checked_at"].replace("Z", "+00:00"))
    unavailable = crs.to_crs_check("seller_1", {"signal": None, "reason": crs.REASON_UNAVAILABLE})
    assert unavailable["seller_id"] == "seller_1"
    assert unavailable["origin"] == "SANDBOX"
    assert unavailable["reason_codes"] == ["CRS_UNAVAILABLE"]
    assert unavailable["verified"] is False
    assert datetime.fromisoformat(unavailable["checked_at"].replace("Z", "+00:00"))
    invalid = crs.to_crs_check("seller_1", {"signal": {"supplier_id": "other",
        "stability": "verified_stable", "checked_at": NOW.isoformat(), "source": "sandbox"}})
    assert invalid["reason_codes"] == ["CRS_INVALID"]
    assert invalid["verified"] is False
    absent = crs.to_crs_check("seller_1", None)
    assert absent["origin"] == "NOT_CONFIGURED"
    assert absent["reason_codes"] == ["CRS_NOT_CONFIGURED"]


def test_configured_profile_empty_not_configured_is_not_absence(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path, auth_stub=False)
    projected = crs.to_crs_check("seller_1", {"signal": None, "reason": crs.REASON_NOT_CONFIGURED})
    assert projected["origin"] == "SANDBOX"
    assert projected["reason_codes"] == ["CRS_INVALID"]


@pytest.mark.parametrize("malformed", [[], False, 0, {"signal": {}}])
def test_malformed_empty_check_never_looks_not_configured(monkeypatch, tmp_path, malformed):
    setup_profile(monkeypatch, tmp_path, auth_stub=False)
    projected = crs.to_crs_check("seller_1", malformed)
    assert projected["origin"] == "SANDBOX"
    assert projected["reason_codes"] == ["CRS_INVALID"]


def test_absent_crs_config_is_nonblocking_but_adverse_check_denies(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path, auth_stub=False)
    monkeypatch.delenv("CRS_API_KEY", raising=False)
    monkeypatch.delenv("CRS_USERNAME", raising=False)
    monkeypatch.delenv("CRS_PASSWORD", raising=False)
    check = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    eligible_suppliers = {"seller_1"} if crs.eligible("seller_1", check, NOW) else set()
    assert eligible_suppliers == {"seller_1"}
    bids = [{"id": "cheap", "supplier_id": "seller_1", "total_landed_price": 10}]
    assert hunt.pick_best(bids, {"cheap": {"recommendation": "buy"}}, eligible_suppliers) == 1
    monkeypatch.setenv("CRS_USERNAME", "configured-user")
    monkeypatch.setenv("CRS_PASSWORD", "configured-password")
    assert not crs.eligible("seller_1", check, NOW)
    monkeypatch.setattr(crs, "_paths", lambda: (None, tmp_path / "cache.json"))
    assert crs.eligible("seller_1", None, NOW)
    adverse = {"signal": {"supplier_id": "seller_1", "stability": "not_verified",
                           "checked_at": NOW.isoformat(), "source": "sandbox"}}
    assert not crs.eligible("seller_1", adverse, NOW)


def test_missing_consent_skips_auth_request(monkeypatch, tmp_path):
    setup_profile(monkeypatch, tmp_path, consent=False, auth_stub=False)
    calls = []
    monkeypatch.setattr(crs, "_open_request", lambda request: calls.append(request))
    result = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert result["reason"] == crs.REASON_CONSENT
    assert calls == []


@pytest.mark.parametrize("base,expected", [
    (None, "https://api-sandbox.stitchcredit.com/api/users/login"),
    ("", "https://api-sandbox.stitchcredit.com/api/users/login"),
    ("https://example.test/api/", "https://example.test/api/users/login"),
])
def test_login_uses_default_or_runtime_base_url(monkeypatch, base, expected):
    crs._auth_state = crs._AuthState()
    monkeypatch.setenv("CRS_USERNAME", "user")
    monkeypatch.setenv("CRS_PASSWORD", "password")
    if base is None:
        monkeypatch.delenv("CRS_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("CRS_BASE_URL", base)
    seen = []

    def opened(request):
        seen.append(request.full_url)
        return _Reply(200, {"token": "token-123"})

    monkeypatch.setattr(crs, "_open_request", opened)
    assert crs._get_token() == "token-123"
    assert seen == [expected]


def test_successful_login_is_cached_for_concurrent_checks(monkeypatch):
    crs._auth_state = crs._AuthState()
    monkeypatch.setenv("CRS_USERNAME", "user")
    monkeypatch.setenv("CRS_PASSWORD", "password")
    calls = []

    def opened(request):
        calls.append(request)
        return _Reply(200, {"token": "token-123"})

    monkeypatch.setattr(crs, "_open_request", opened)
    async def concurrent_tokens():
        return await asyncio.gather(asyncio.to_thread(crs._get_token), asyncio.to_thread(crs._get_token))

    tokens = asyncio.run(concurrent_tokens())
    assert tokens == ["token-123", "token-123"]
    assert len(calls) == 1


def test_login_failure_latches_and_never_retries(monkeypatch):
    crs._auth_state = crs._AuthState()
    monkeypatch.setenv("CRS_USERNAME", "user")
    monkeypatch.setenv("CRS_PASSWORD", "password")
    calls = []

    def opened(request):
        calls.append(request)
        return _Reply(401, {"error": "private"})

    monkeypatch.setattr(crs, "_open_request", opened)
    with pytest.raises(crs.CrsAuthError):
        crs._get_token()
    with pytest.raises(crs.CrsAuthError):
        crs._get_token()
    assert len(calls) == 1


def test_concurrent_failed_login_attempts_share_permanent_latch(monkeypatch):
    crs._auth_state = crs._AuthState()
    monkeypatch.setenv("CRS_USERNAME", "user")
    monkeypatch.setenv("CRS_PASSWORD", "password")
    calls = []
    monkeypatch.setattr(crs, "_open_request", lambda request: (calls.append(request) or _Reply(401, {})))

    async def concurrent_failures():
        return await asyncio.gather(
            asyncio.to_thread(crs._get_token), asyncio.to_thread(crs._get_token), return_exceptions=True)

    results = asyncio.run(concurrent_failures())
    assert all(isinstance(result, crs.CrsAuthError) for result in results)
    assert len(calls) == 1


def test_redirect_handler_rejects_redirect_target():
    assert crs._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.test") is None


def test_cli_missing_credentials_reports_not_configured_without_http(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["crs.py", "--live"])
    monkeypatch.setattr(crs, "_profiles", lambda: {"seller_1": {}})
    monkeypatch.delenv("CRS_USERNAME", raising=False)
    monkeypatch.delenv("CRS_PASSWORD", raising=False)
    calls = []
    monkeypatch.setattr(crs, "_open_request", lambda request: calls.append(request))
    assert crs.main() == 2
    assert json.loads(capsys.readouterr().out)["reason"] == crs.REASON_NOT_CONFIGURED
    assert calls == []


def test_cli_missing_profiles_reports_profile_without_http(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["crs.py", "--live"])
    monkeypatch.setattr(crs, "_profiles", lambda: {})
    monkeypatch.setenv("CRS_USERNAME", "user")
    monkeypatch.setenv("CRS_PASSWORD", "password")
    calls = []
    monkeypatch.setattr(crs, "_open_request", lambda request: calls.append(request))
    assert crs.main() == 2
    assert json.loads(capsys.readouterr().out)["reason"] == crs.REASON_PROFILE
    assert calls == []


@pytest.mark.parametrize("payload,status", [({"error": "private"}, 302), ({}, 200)])
def test_redirect_or_malformed_login_latches_after_one_attempt(monkeypatch, payload, status):
    crs._auth_state = crs._AuthState()
    monkeypatch.setenv("CRS_USERNAME", "user")
    monkeypatch.setenv("CRS_PASSWORD", "password")
    calls = []
    monkeypatch.setattr(crs, "_open_request", lambda request: (calls.append(request) or _Reply(status, payload)))
    for _ in range(2):
        with pytest.raises(crs.CrsAuthError):
            crs._get_token()
    assert len(calls) == 1


def test_configured_login_failure_can_use_fresh_cache_but_stays_latched(monkeypatch, tmp_path):
    crs._auth_state = crs._AuthState()
    setup_profile(monkeypatch, tmp_path, auth_stub=False)
    monkeypatch.setenv("CRS_USERNAME", "user")
    monkeypatch.setenv("CRS_PASSWORD", "password")
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"seller_1": {"persona_ref": "official-a", "signal": {
        "supplier_id": "seller_1", "stability": "verified_stable",
        "checked_at": NOW.isoformat(), "source": "sandbox"},
        "reason": crs.REASON_VERIFIED}}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(crs, "_open_request", lambda request: (calls.append(request) or _Reply(401, {})))
    result = asyncio.run(crs.check_sellers(NOW))["seller_1"]
    assert result["signal"]["source"] == "recorded"
    assert result["signal"]["checked_at"] == NOW.isoformat()
    assert len(calls) == 1
    with pytest.raises(crs.CrsAuthError):
        crs._get_token()
    assert len(calls) == 1


def test_login_redacts_credentials_token_and_provider_error(monkeypatch, caplog):
    crs._auth_state = crs._AuthState()
    monkeypatch.setenv("CRS_USERNAME", "private-user")
    monkeypatch.setenv("CRS_PASSWORD", "private-password")
    monkeypatch.setattr(crs, "_open_request", lambda request: (_ for _ in ()).throw(OSError("provider-secret")))
    with pytest.raises(crs.CrsAuthError):
        crs._get_token()
    output = " ".join(record.getMessage() for record in caplog.records)
    assert "private-user" not in output
    assert "private-password" not in output
    assert "provider-secret" not in output
    assert "token-123" not in output
