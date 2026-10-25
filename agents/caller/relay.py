"""The caller's one job (#259): place the approval phone call for a pending mandate and report the result.

It runs pay/'s existing call (pay.voice_cartesia.run_approval_call with a pay.approval.ApprovalService), so there is no
new approval path: it approves nothing itself and charges nothing; the buyer acts on the result. No call is placed when
the request is not from the buyer agent, the mandate does not verify, the same mandate was already called, there is
no screen to show the code on (the code goes only to the buyer's own screen), or Cartesia is not configured.
"""
from __future__ import annotations

import json
import os
import secrets as _secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

MAX_REQUEST_TTL_S = 600            # RT-24: a request may ask to live at most 10 minutes; a far-future expiry is no expiry
MAX_EXPIRES_CHARS = 40
MARKET_MODULE = Path(__file__).resolve().parents[2] / "market" / "spacetimedb" / "src" / "index.ts"
MAX_REQUEST_CHARS = 20000          # Shield's own cap: a longer request is refused, never screened in part
MAX_REQUEST_BODY_BYTES = 60 * 1024  # under Shield's 64 KB body cap, with room for the context (#298)
MIN_PRIVATE_BUYER_SEED = 16         # the same floor as common.MIN_PRIVATE_SEED (#449 PL-22)
_SEEN_LOCK = threading.Lock()       # on_call runs handle in worker threads: the one-call check and add are one step (#298)


def check_expiry(expires_at: Any, *, now: Optional[Callable[[], datetime]] = None, required: bool = True) -> Optional[str]:
    """RT-24: the refusal reason for a request's `expires_at`, or None when it is fresh. expires_at is ISO 8601 with an explicit
    zone ("2026-10-25T12:02:00Z"). Refused: missing (when required), not text or not a zone-aware ISO time (bad_expires_at,
    even when not required), already past or exactly now (request_expired), or more than MAX_REQUEST_TTL_S ahead
    (expires_too_far). An old request replayed later, or one that waited too long in a queue, never places a call."""
    if expires_at is None or expires_at == "":
        return "missing_expires_at" if required else None
    if not isinstance(expires_at, str) or len(expires_at) > MAX_EXPIRES_CHARS:
        return "bad_expires_at"
    try:
        when = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return "bad_expires_at"
    if when.tzinfo is None:
        return "bad_expires_at"
    current = (now or (lambda: datetime.now(timezone.utc)))()
    if when <= current:
        return "request_expired"
    if when - current > timedelta(seconds=MAX_REQUEST_TTL_S):
        return "expires_too_far"
    return None


def expiry_required_for_transport() -> bool:
    """The old VoiceTransportRequest has no deadline field (its schema digest is pinned, so a buyer on older code is still heard).
    It is refused as missing_expires_at only once the operator sets CALLER_REQUIRE_EXPIRES=1, i.e. when every buyer sends
    ExpiringVoiceTransportRequest, which is always checked."""
    return os.environ.get("CALLER_REQUIRE_EXPIRES", "").strip() == "1"


def precheck(sender: str, text: str, *, buyer_address: str, expires_at: Optional[str] = None,
             now: Optional[Callable[[], datetime]] = None, require_expiry: bool = True) -> Optional[str]:
    """The refusal reason before any Shield call, or None (#298). The sender is checked first, so a stranger costs no
    Shield call; then the request's expiry (RT-24; skipped when `expires_at` is None, i.e. not asked about). A request whose
    JSON body would pass Shield's 64 KB cap is too_large, not "shield_blocked": non-ASCII text is sent escaped, up to 12
    bytes a character."""
    if sender != buyer_address:
        return "not_the_buyer"
    if expires_at is not None and (why := check_expiry(expires_at, now=now, required=require_expiry)):
        return why
    if len(text) > MAX_REQUEST_CHARS or len(json.dumps(text)) > MAX_REQUEST_BODY_BYTES:
        return "too_large"
    return None


def buyer_seed_problem(seed: Optional[str]) -> Optional[str]:
    """#449 PL-22: the Caller trusts one sender, the address derived from BUYER_AGENT_SEED. A missing, short or public
    *-dev seed (common.SEEDS defaults are in the public repo) lets anyone sign as that buyer, so the Caller must not
    start on it. Returns the message to exit with, or None."""
    value = (seed or "").strip()
    if len(value) >= MIN_PRIVATE_BUYER_SEED and not value.endswith("-dev"):
        return None
    return ("Set BUYER_AGENT_SEED in agents/.env to a private seed (16+ characters, not a *-dev default) before starting "
            "the Caller: it only obeys the buyer agent's address, and a public seed would let anyone sign as the buyer.")


def market_has_typed_approval(module: Path = MARKET_MODULE) -> bool:
    """True while the market still exports approve_typed, or when that cannot be read (as demo/bridge.py decides): a code
    on /buyer would then arm a typed approval, which the phone-only rule forbids, so no code goes there and no call."""
    try:
        return "approve_typed" in module.read_text(encoding="utf-8")
    except OSError:
        return True


def _no(reason: str) -> dict:
    return {"approved": False, "reason": reason, "call_id": None, "voice_approval_id": None}


def handle(sender: str, request: Any, *, buyer_address: str, client: Any, show_code: Optional[Callable[[str], None]],
           seen: set, unconfigured: Optional[str] = None, secret: Optional[str] = None, buyer_name: str = "there",
           run: Optional[Callable] = None, expires_at: Optional[str] = None, now: Optional[Callable[[], datetime]] = None,
           require_expiry: bool = True, **timing) -> dict:
    """{approved, reason, call_id, voice_approval_id}. Every refusal places no call. With `expires_at` (RT-24) the request is
    checked again here, right before the dial, so one that went stale while it waited for Shield places no call and burns
    nothing."""
    from pay.approval import ApprovalService
    from pay.mandate import verify
    from pay.replay import NonceStore
    from pay.voice_cartesia import CALL_CODE_TTL_S, run_approval_call

    if sender != buyer_address:
        return _no("not_the_buyer")
    if not isinstance(request, dict) or not isinstance(request.get("mandate"), dict):
        return _no("bad_request")
    mandate = request["mandate"]
    ok = verify(mandate)
    if not ok:
        return _no(f"bad_mandate: {ok.reason}")
    if expires_at is not None and (why := check_expiry(expires_at, now=now, required=require_expiry)):
        return _no(why)
    with _SEEN_LOCK:
        if mandate["hash"] in seen:
            return _no("already_called")            # one call per mandate, ever
        if client is None:
            return _no(f"not_configured: {unconfigured or 'no Cartesia client'}")
        if show_code is None:
            return _no("no_screen: the code has nowhere safe to show")
        seen.add(mandate["hash"])                 # burned even if the call fails: never a second call for it
    service = ApprovalService(secret=secret or _secrets.token_hex(16), store=NonceStore(), code_ttl_seconds=CALL_CODE_TTL_S)
    try:
        res = (run or run_approval_call)(mandate, request.get("reason"), client, service, deal=request.get("deal"),
                                         buyer_name=buyer_name, on_code=show_code, **timing)
    except Exception as e:  # noqa: BLE001  (a screen that refused the code, a transport error: not approved, and said)
        return _no(f"call_error: {type(e).__name__}")
    if not res.approved:
        return {"approved": False, "reason": res.reason or "denied", "call_id": res.call_id, "voice_approval_id": None}
    voice_id = str((res.record or {}).get("id") or "").strip()
    if not voice_id:
        return {"approved": False, "reason": "no_voice_approval_id", "call_id": res.call_id, "voice_approval_id": None}
    return {"approved": True, "reason": None, "call_id": res.call_id, "voice_approval_id": voice_id}


TRANSPORT_KEYS = {"buyer_name", "deal_script", "why_answer"}


def transport(sender: str, request: Any, *, buyer_address: str, client: Any, seen: set,
              unconfigured: Optional[str] = None, expires_at: Optional[str] = None,
              now: Optional[Callable[[], datetime]] = None, require_expiry: bool = True, **timing) -> dict:
    """#398 item 3, voice only: place ONE call with the buyer's script variables and return the ended call with its
    transcript, {call_id, call, error}. It never sees a code or a secret, never judges what was said and never writes
    a record: the buyer verifies the utterance in its own ApprovalService. Additive: handle() is unchanged."""
    import re
    from pay.voice_cartesia import CartesiaError, place_call, transcript, wait_for_end

    def no(error: str) -> dict:
        return {"call_id": None, "call": None, "error": error}
    if sender != buyer_address:
        return no("not_the_buyer")
    if not isinstance(request, dict):
        return no("bad_request")
    mh, variables = request.get("mandate_hash"), request.get("variables")
    if not isinstance(mh, str) or not re.fullmatch(r"[0-9a-f]{64}", mh):
        return no("bad_request")
    if (not isinstance(variables, dict) or set(variables) != TRANSPORT_KEYS
            or not all(isinstance(v, str) and len(v) < 2000 for v in variables.values())):
        return no("bad_variables")
    if expires_at is not None and (why := check_expiry(expires_at, now=now, required=require_expiry)):
        return no(why)                              # stale while it waited: no call, nothing burned
    with _SEEN_LOCK:
        if ("transport", mh) in seen:
            return no("already_called")            # one voice call per mandate, ever
        if client is None:
            return no(f"not_configured: {unconfigured or 'no Cartesia client'}")
        seen.add(("transport", mh))
    try:
        call_id = place_call(client, variables)
        ended = wait_for_end(client, call_id, **{k: v for k, v in timing.items() if k in ("max_wait", "poll", "sleep", "clock")})
        if ended is None:
            return {"call_id": call_id, "call": None, "error": "call_timeout"}
        try:
            entries, full = transcript(client, call_id, ended, **({"sleep": timing["sleep"]} if "sleep" in timing else {}))
        except CartesiaError:
            entries, full = [], ended
        return {"call_id": call_id, "call": {**full, "transcript": entries}, "error": None}
    except Exception as e:  # noqa: BLE001  (a transport error: no call evidence, and said)
        return no(f"call_error: {type(e).__name__}")
