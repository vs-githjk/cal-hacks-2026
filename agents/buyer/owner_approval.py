"""Recording a phone approval on the market: always through the REFEREE identity, then re-read through the BUYER's own view.

The market's record_approval reducer is referee-only (market.ts requireRole 'record_approval', ['referee']): the referee
relays what the phone call judged. The owner-chat path used to call it through the buyer client, which the live market
refuses ("record_approval needs referee; caller is buyer ..."), so an owner's approval in ASI:One could not be recorded.

Invariants kept here (nothing in this module approves anything; it only records a call result the caller already has):
  * it runs only after the call returned an approval record for this exact mandate (buyer_agent checks that first);
  * a payment still needs the market's own buyer-private row to show a voice_code approval for the same mandate hash,
    payee and amount, not retired (market_approval_matches), re-read through the buyer client after the referee writes.

Shape-compatible with the market bridge before and after #455: when record_approval takes a `code` (the word pair the
market issued for this call), the issued code is passed; when it does not, it is not. The code is kept in memory only,
never logged, printed or stored, and dropped once recorded.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from market_bridge import MarketBridgeError

METHOD = "voice_code"
ISSUED_CODES: dict[str, str] = {}  # mandate hash -> the code issued for its call. Memory only.


def remember_code(mandate_hash: str, code: str) -> None:
    if isinstance(mandate_hash, str) and isinstance(code, str) and code:
        if len(ISSUED_CODES) >= 64:  # a call lasts minutes: never grow without bound
            ISSUED_CODES.pop(next(iter(ISSUED_CODES)))
        ISSUED_CODES[mandate_hash] = code


def accepts_code(record_approval: Callable) -> bool:
    """True when the bridge's record_approval takes a `code` (or any keyword). Feature detection, not a version check."""
    try:
        params = inspect.signature(record_approval).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "code" or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


def referee_record(referee: Any, *, mandate_hash: str, buyer_id: str, voice_approval_id: str) -> Any:
    """The referee relays the call result. Passes the issued code only when the bridge takes one."""
    args = {"mandate_hash": mandate_hash, "method": METHOD, "approved_by": buyer_id, "voice_approval_id": voice_approval_id}
    code = ISSUED_CODES.get(mandate_hash)
    if code and accepts_code(referee.record_approval):
        args["code"] = code
    try:
        return referee.record_approval(**args)
    finally:
        ISSUED_CODES.pop(mandate_hash, None)  # one call, one code: never reused for another attempt


def record_owner_approval(referee: Any, buyer: Any, mandate: dict, buyer_id: str, voice_approval_id: str,
                          matches: Callable[[Any, dict], bool]) -> dict:
    """Owner chat: the referee records, the buyer re-reads. Raises MarketBridgeError unless the market's own row shows
    this exact mandate approved, so nothing downstream can pay on a failed or mismatched recording."""
    try:
        referee_record(referee, mandate_hash=mandate["hash"], buyer_id=buyer_id, voice_approval_id=voice_approval_id)
    except MarketBridgeError:
        # the write may have landed before the error (a retry): only the market's own row can say, and it must match
        status = buyer.purchase_status(mandate["hash"])
        if isinstance(status, dict) and status.get("approval_method") == METHOD and matches(status, mandate):
            return status
        raise
    status = buyer.purchase_status(mandate["hash"])
    if not isinstance(status, dict) or status.get("approval_method") != METHOD or not matches(status, mandate):
        raise MarketBridgeError("market_approval_readback_mismatch")
    return status
