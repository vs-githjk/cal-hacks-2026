"""CRS sandbox identity signals for approved synthetic representative requests only."""
import asyncio
import hashlib
import json
import logging
import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_BASE_URL = "https://api-sandbox.stitchcredit.com/api"
LOGIN_PATH = "/users/login"
ENDPOINT_PATH = "/transunion/identity-manager-verification/basic"
ENDPOINT = f"{DEFAULT_BASE_URL}{ENDPOINT_PATH}"
CACHE_MAX_AGE = timedelta(hours=24)
PAYEE_TTL = timedelta(minutes=10)   # #257: one check per payee at the payment gate, reused for this long
REASON_VERIFIED = "Synthetic representative identity verified by CRS sandbox."
REASON_CAUTION = "CRS sandbox returned a fraud alert; additional proof is required."
REASON_NOT_VERIFIED = "CRS sandbox could not verify the synthetic representative identity."
REASON_UNAVAILABLE = "CRS sandbox check unavailable; a current recorded result may be used."
REASON_CONSENT = "Seller consent is missing or withdrawn."
REASON_PROFILE = "Approved synthetic representative profile is unavailable."
REASON_NOT_CONFIGURED = "CRS not configured."
REASON_CODES = {
    "verified_stable": ("CRS_IDENTITY_VERIFIED",),
    "caution": ("CRS_STEP_UP_REQUIRED",),
    "not_verified": ("CRS_IDENTITY_NOT_VERIFIED",),
}
_LOG = logging.getLogger(__name__)


class CrsAuthError(RuntimeError):
    """Sanitized authentication failure; details never leave the adapter."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = build_opener(_NoRedirect())
urlopen = _NO_REDIRECT_OPENER.open


class _AuthState:
    def __init__(self):
        self.lock = threading.Lock()
        self.token = None
        self.failed = False


_auth_state = _AuthState()

# SHA-256 of canonical JSON request bodies from the official CRS 1.1.2 persona file.
# Bodies stay in the operator's private config; only these non-identifying pins are committed.
APPROVED_PERSONAS = {
    "P01": "3119001eef22b4039638c20c01ac34be165b0e875d83843ac3971fc1074ff345",
    "P02": "4430882b47119b5c9fdd8d5efa98dd43b232b279cbade9ae763d6bf9213d8dbe",
    "P12": "b1998038811ba4b59fc341c2ef78cb8d710af8ae2cc3917d62c114bad3e6ad15",
    "P16": "a3cf8876c366f93ddc7ada36db87ffdf05404ea7100044393a686bbbacc6d250",
}
_issued_personas = {}


def _canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("invalid timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs timezone")
    return parsed.astimezone(timezone.utc)


def _band(response):
    if not isinstance(response, dict) or any(key in response for key in ("errorMessages", "codes", "messages", "details")):
        return "not_verified"
    try:
        messages = response["addOnProducts"][0]["idManagerVerification"]["messages"]
        if not isinstance(messages, list):
            return "not_verified"
        if not messages:
            return "verified_stable"
        codes = {str(message["code"]) for message in messages if isinstance(message, dict) and "code" in message}
        if len(codes) != len(messages):
            return "not_verified"
        if codes == {"2401"}:
            return "caution"
        return "not_verified"
    except (KeyError, IndexError, TypeError):
        return "not_verified"


def normalize(supplier_id: str, response: dict, checked_at: str) -> dict:
    """Return only the four SupplierSignal fields; malformed/unknown responses fail closed."""
    try:
        checked = _utc(checked_at).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError):
        raise ValueError("invalid check timestamp") from None
    if not isinstance(supplier_id, str) or not supplier_id:
        raise ValueError("invalid supplier id")
    return {"supplier_id": supplier_id, "stability": _band(response), "checked_at": checked, "source": "sandbox"}


def _paths():
    profile = os.environ.get("CRS_TEST_IDENTITIES_PATH")
    return Path(profile) if profile else None, Path(__file__).resolve().parents[1] / ".cache" / "crs-signals.json"


def _profiles():
    profile_path, _ = _paths()
    if profile_path is None:
        return {}
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        sellers = data.get("sellers", {}) if isinstance(data, dict) else {}
        return sellers if isinstance(sellers, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _approved(profile):
    if not isinstance(profile, dict) or profile.get("seller_type") != "business":
        return None
    if profile.get("consent") is not True:
        return None
    ref, body = profile.get("persona_ref"), profile.get("request")
    if not isinstance(ref, str) or ref not in APPROVED_PERSONAS or not isinstance(body, dict):
        return None
    if _canonical_hash(body) != APPROVED_PERSONAS[ref]:
        return None
    return body


def _cache_read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _reason(stability):
    return {"verified_stable": REASON_VERIFIED, "caution": REASON_CAUTION,
            "not_verified": REASON_NOT_VERIFIED}.get(stability, REASON_UNAVAILABLE)


def _cached(supplier_id, profile, now, cache):
    entry = cache.get(supplier_id)
    if not isinstance(entry, dict) or entry.get("persona_ref") != profile.get("persona_ref"):
        return None
    signal = entry.get("signal")
    if not isinstance(signal, dict) or set(signal) != {"supplier_id", "stability", "checked_at", "source"}:
        return None
    if signal.get("supplier_id") != supplier_id or signal.get("source") not in {"sandbox", "recorded"}:
        return None
    if signal.get("stability") not in {"verified_stable", "caution", "not_verified"}:
        return None
    try:
        age = now - _utc(signal["checked_at"])
    except (ValueError, TypeError, OverflowError):
        return None
    if age < timedelta(0) or age > CACHE_MAX_AGE:
        return None
    recorded = dict(signal, source="recorded")
    return {"signal": recorded, "reason": _reason(recorded["stability"])}


def eligible(supplier_id: str, check: dict | None, now: datetime) -> bool:
    """Fail-closed gate using current trusted consent/profile and a fresh sandbox signal."""
    profiles = _profiles()
    profile = profiles.get(supplier_id)
    missing_auth = not _configured()
    empty_not_configured = _is_empty_not_configured(check)
    if (missing_auth or not profiles) and empty_not_configured:
        return True
    if isinstance(profile, dict) and profile.get("seller_type") == "individual":
        return True
    if not isinstance(profile, dict) or profile.get("consent") is not True or _approved(profile) is None:
        return False
    if not isinstance(check, dict):
        return False
    issued = _issued_personas.get(id(check))
    if not issued or issued[0] is not check or issued[1] != profile.get("persona_ref"):
        return False
    signal = check.get("signal")
    if not isinstance(signal, dict) or set(signal) != {"supplier_id", "stability", "checked_at", "source"}:
        return False
    if signal.get("supplier_id") != supplier_id or signal.get("stability") != "verified_stable":
        return False
    if _canonical_hash(signal) != issued[2]:
        return False
    if check.get("reason") != REASON_VERIFIED:
        return False
    if signal.get("source") not in {"sandbox", "recorded"}:
        return False
    try:
        age = now.astimezone(timezone.utc) - _utc(signal["checked_at"])
    except (ValueError, TypeError, OverflowError, AttributeError):
        return False
    return timedelta(0) <= age <= CACHE_MAX_AGE


def to_crs_check(supplier_id: str, check: dict | None) -> dict:
    """Project the legacy result into the issue #128 flat CRS check shape."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    signal = check.get("signal") if isinstance(check, dict) else None
    stability = signal.get("stability") if isinstance(signal, dict) else None
    reason = check.get("reason") if isinstance(check, dict) else None
    if not isinstance(stability, str) or stability not in REASON_CODES:
        not_configured = (_is_empty_not_configured(check) and
                          (not _configured() or not _profiles()))
        return {
            "seller_id": supplier_id,
            "product": "tu_identity",
            "verified": False,
            "reason_codes": ["CRS_NOT_CONFIGURED" if not_configured else
                             ("CRS_UNAVAILABLE" if reason == REASON_UNAVAILABLE else "CRS_INVALID")],
            "origin": "NOT_CONFIGURED" if not_configured else "SANDBOX",
            "checked_at": now,
        }
    source = signal.get("source")
    if (signal.get("supplier_id") != supplier_id or
            not isinstance(source, str) or source not in {"sandbox", "recorded"}):
        return {"seller_id": supplier_id, "product": "tu_identity", "verified": False,
                "reason_codes": ["CRS_INVALID"], "origin": "SANDBOX", "checked_at": now}
    try:
        _utc(signal["checked_at"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return {"seller_id": supplier_id, "product": "tu_identity", "verified": False,
                "reason_codes": ["CRS_INVALID"], "origin": "SANDBOX", "checked_at": now}
    origin = {"sandbox": "SANDBOX", "recorded": "CACHED"}.get(source, "NOT_CONFIGURED")
    result = {
        "seller_id": supplier_id,
        "product": "tu_identity",
        "verified": stability == "verified_stable",
        "reason_codes": list(REASON_CODES[stability]),
        "origin": origin,
        "checked_at": signal.get("checked_at"),
    }
    persona_id = check.get("persona_ref") if isinstance(check, dict) else None
    if isinstance(persona_id, str) and persona_id:
        result["persona_id"] = persona_id
    return result


def _is_empty_not_configured(check) -> bool:
    if check is None or check == {}:
        return True
    return (isinstance(check, dict) and set(check) == {"signal", "reason"} and
            check.get("signal") is None and check.get("reason") == REASON_NOT_CONFIGURED)


def _open_request(request):
    return urlopen(request, timeout=4)


def _base_url():
    return (os.environ.get("CRS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _configured():
    return bool(os.environ.get("CRS_API_KEY") or
                (os.environ.get("CRS_USERNAME") and os.environ.get("CRS_PASSWORD")))


def _login():
    username, password = os.environ.get("CRS_USERNAME"), os.environ.get("CRS_PASSWORD")
    if not username or not password:
        raise CrsAuthError(REASON_NOT_CONFIGURED)
    request = Request(f"{_base_url()}{LOGIN_PATH}", data=json.dumps({
        "username": username, "password": password}).encode("utf-8"), headers={
            "Content-Type": "application/json"}, method="POST")
    with _open_request(request) as result:
        if result.status != 200:
            raise CrsAuthError("CRS authentication failed")
        payload = json.loads(result.read())
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise CrsAuthError("CRS authentication failed")
    return token


def _get_token():
    """Return one cached process token, permanently latching failed login."""
    global _auth_state
    preissued = os.environ.get("CRS_API_KEY")
    if preissued:
        return preissued
    if not _configured():
        raise CrsAuthError(REASON_NOT_CONFIGURED)
    with _auth_state.lock:
        if _auth_state.token:
            return _auth_state.token
        if _auth_state.failed:
            raise CrsAuthError("CRS authentication failed")
        try:
            _auth_state.token = _login()
            return _auth_state.token
        except CrsAuthError:
            _auth_state.failed = True
            _LOG.warning("CRS authentication failed; using sanitized fallback if available")
            raise
        except Exception:
            _auth_state.failed = True
            _LOG.warning("CRS authentication failed; using sanitized fallback if available")
            raise CrsAuthError("CRS authentication failed") from None


def _request(body, token):
    req = Request(f"{_base_url()}{ENDPOINT_PATH}", data=json.dumps(body).encode("utf-8"), headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    with _open_request(req) as result:
        if result.status != 200:
            raise ValueError("CRS request failed")
        payload = json.loads(result.read())
    _validate_response(payload)
    return payload


def _validate_response(payload):
    if not isinstance(payload, dict) or any(key in payload for key in ("errorMessages", "codes", "messages", "details")):
        raise ValueError("CRS response invalid")
    try:
        messages = payload["addOnProducts"][0]["idManagerVerification"]["messages"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("CRS response invalid") from None
    if not isinstance(messages, list) or any(not isinstance(item, dict) or "code" not in item for item in messages):
        raise ValueError("CRS response invalid")


def _cache_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix="crs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


async def check_sellers(now: datetime, only: set[str] | None = None) -> dict[str, dict]:
    """Check only configured, consented, business profiles; cache contains sanitized signals only.
    `only` limits the check to these supplier ids (check_payee asks for one)."""
    _issued_personas.clear()
    _, cache_path = _paths()
    profiles, cache = _profiles(), _cache_read(cache_path)
    token = None
    auth_failed = False
    auth_attempted = False
    results = {}
    for supplier_id, profile in profiles.items():
        if not isinstance(supplier_id, str) or not supplier_id:
            continue
        if only is not None and supplier_id not in only:
            continue
        if not isinstance(profile, dict) or profile.get("seller_type") != "business":
            results[supplier_id] = {"signal": None, "reason": REASON_PROFILE}
            continue
        if profile.get("consent") is not True:
            results[supplier_id] = {"signal": None, "reason": REASON_CONSENT}
            continue
        body = _approved(profile)
        if body is None:
            results[supplier_id] = {"signal": None, "reason": REASON_PROFILE}
            continue
        if not _configured():
            results[supplier_id] = {"signal": None, "reason": REASON_NOT_CONFIGURED}
            continue
        if not auth_attempted:
            auth_attempted = True
            try:
                token = await asyncio.to_thread(_get_token)
            except CrsAuthError:
                auth_failed = True
        if token:
            try:
                raw = await asyncio.to_thread(_request, body, token)
                _validate_response(raw)
                signal = normalize(supplier_id, raw, now.astimezone(timezone.utc).isoformat())
                result = {"signal": signal, "reason": _reason(signal["stability"])}
                _issued_personas[id(result)] = (result, profile["persona_ref"], _canonical_hash(signal))
                # Fresh adverse results supersede old passes; transport/parse failures do not.
                cache[supplier_id] = {"persona_ref": profile["persona_ref"], **result}
                try:
                    _cache_write(cache_path, cache)
                except OSError:
                    print("CRS result cache could not be saved.", file=sys.stderr)
                results[supplier_id] = result
                continue
            except Exception:
                auth_failed = True
                pass
        cached = _cached(supplier_id, profile, now, cache) if auth_failed else None
        if cached is not None:
            _issued_personas[id(cached)] = (cached, profile["persona_ref"], _canonical_hash(cached["signal"]))
            results[supplier_id] = cached
        else:
            results[supplier_id] = {"signal": None, "reason": REASON_UNAVAILABLE}
    return results


_payee_cache: dict[str, tuple[datetime, dict]] = {}


class ProfilesUnreadable(RuntimeError):
    """CRS_TEST_IDENTITIES_PATH is set but the file is missing, unreadable or has no sellers: who is a business is unknown."""


def _payee_profile(supplier_id: str):
    """The seller's profile (ids and seller_type compared without case), None when there is none. When a profile file
    is configured but cannot be read, ProfilesUnreadable: an unreadable file never turns a business into a SIM seller."""
    profile_path, _ = _paths()
    if profile_path is None:
        return None                      # no profile file configured: no seller is a known business
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProfilesUnreadable(f"CRS profile file unreadable ({type(e).__name__})") from None
    sellers = data.get("sellers") if isinstance(data, dict) else None
    if not isinstance(sellers, dict) or not sellers:
        raise ProfilesUnreadable("CRS profile file has no sellers")
    want = str(supplier_id).strip().lower()
    hits = [v for k, v in sellers.items() if isinstance(k, str) and k.strip().lower() == want]
    if len(hits) > 1:
        raise ProfilesUnreadable("CRS profile file has two entries for this seller")
    if hits and not isinstance(hits[0], dict):
        raise ProfilesUnreadable("CRS profile entry for this seller is not an object")
    return hits[0] if hits else None


def sim_reason(supplier_id: str) -> str | None:
    """Why this payee is a SIM seller, or None when it must be checked as a business. Only no profile file, no profile
    for the seller, or a profile that says "individual" is SIM; any other profile (an odd or missing seller_type too) is
    checked, and check_sellers holds it if it is not an approved business. Raises ProfilesUnreadable."""
    if _paths()[0] is None:
        return "no CRS profile file is configured (CRS_TEST_IDENTITIES_PATH)"
    profile = _payee_profile(supplier_id)
    if profile is None:
        return "no business CRS profile for this seller"
    if str(profile.get("seller_type", "")).strip().lower() == "individual":
        return "its CRS profile is an individual seller"
    return None


def is_business(supplier_id: str) -> bool:
    return sim_reason(supplier_id) is None


async def check_payee(supplier_id: str, now: datetime) -> dict:
    """#257: one CRS check of the payee at the payment gate, cached per payee for PAYEE_TTL.
    Returns {"business", "check", "cached"}: `check` is the CrsCheck (pay.crs_gate judges it) for a business payee,
    None for a SIM seller (no business profile, so no request). A transport failure is never cached."""
    why_sim = sim_reason(supplier_id)            # read every time: a changed profile or consent is never cached over
    if why_sim is not None:
        _payee_cache.pop(supplier_id, None)
        return {"business": False, "check": None, "cached": False, "sim_reason": why_sim}
    hit = _payee_cache.get(supplier_id)
    consent = (_payee_profile(supplier_id) or {}).get("consent") is True
    if hit is not None and now < hit[0] and consent:
        return {**hit[1], "cached": True}
    key = next((k for k in _profiles() if isinstance(k, str) and k.strip().lower() == str(supplier_id).strip().lower()),
               supplier_id)
    legacy = (await check_sellers(now, only={key})).get(key)
    check = to_crs_check(key, legacy)
    check["seller_id"] = supplier_id          # the seller being paid; payee_ok matches it exactly
    outcome = {"business": True, "check": check}
    if check["verified"] and "CRS_UNAVAILABLE" not in check["reason_codes"]:
        _payee_cache[supplier_id] = (now + PAYEE_TTL, outcome)   # only a verified, fresh answer is reused
    else:
        _payee_cache.pop(supplier_id, None)
    return {**outcome, "cached": False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Explicit CRS sandbox synthetic representative check")
    parser.add_argument("--live", action="store_true", help="perform explicit sandbox requests")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required to make a sandbox request")
    import common  # existing agent module loads agents/.env without overriding process variables
    profiles = _profiles()
    if not profiles or not _configured():
        reason = REASON_NOT_CONFIGURED if not _configured() else REASON_PROFILE
        print(json.dumps({"status": "unavailable", "reason": reason}))
        return 2
    now = datetime.now(timezone.utc)
    results = asyncio.run(check_sellers(now))
    public = {key: value for key, value in results.items() if value["signal"] is not None}
    print(json.dumps(public, separators=(",", ":")))
    return 0 if any(value["signal"] and value["signal"]["source"] == "sandbox" for value in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
