"""The caller's one job (#259): place the approval phone call for a pending mandate and report the result.

It runs pay/'s existing call (pay.voice_cartesia.run_approval_call with a pay.approval.ApprovalService), so there is no
new approval path: it approves nothing itself and charges nothing; the buyer acts on the result. No call is placed when
the request is not from the buyer agent, the mandate does not verify, the same mandate was already called, there is
no screen to show the code on (the code goes only to the buyer's own screen), or Cartesia is not configured.
"""
from __future__ import annotations

import json
import secrets as _secrets
import threading
from pathlib import Path
from typing import Any, Callable, Optional

MARKET_MODULE = Path(__file__).resolve().parents[2] / "market" / "spacetimedb" / "src" / "index.ts"
MAX_REQUEST_CHARS = 20000          # Shield's own cap: a longer request is refused, never screened in part
MAX_REQUEST_BODY_BYTES = 60 * 1024  # under Shield's 64 KB body cap, with room for the context (#298)
_SEEN_LOCK = threading.Lock()       # on_call runs handle in worker threads: the one-call check and add are one step (#298)


def precheck(sender: str, text: str, *, buyer_address: str) -> Optional[str]:
    """The refusal reason before any Shield call, or None (#298). The sender is checked first, so a stranger costs no
    Shield call. A request whose JSON body would pass Shield's 64 KB cap is too_large, not "shield_blocked": non-ASCII
    text is sent escaped, up to 12 bytes a character."""
    if sender != buyer_address:
        return "not_the_buyer"
    if len(text) > MAX_REQUEST_CHARS or len(json.dumps(text)) > MAX_REQUEST_BODY_BYTES:
        return "too_large"
    return None


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
           seen: set, unconfigured: Optional[str] = None, secret: Optional[str] = None, buyer_name: str = "Vidyut",
           run: Optional[Callable] = None, **timing) -> dict:
    """{approved, reason, call_id, voice_approval_id}. Every refusal places no call."""
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
              unconfigured: Optional[str] = None, **timing) -> dict:
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
