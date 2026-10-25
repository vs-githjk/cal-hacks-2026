"""#398 item 3: the buyer delegates only the voice of the approval call to Bazaar Caller (BUYER_DELEGATE_CALL=1).

DelegatedVoiceClient stands where the Cartesia client stands in pay.voice_cartesia.run_approval_call, so the buyer's own
ApprovalService issues the code (shown only in the owner's private chat), judges the transcript and writes the record,
exactly as on the direct path. The Caller only dials and returns what was said; it never sees the code or the secret.
A reply that does not match this mandate, reuses a call id, or is not a finished call is refused (`refused`), and a
missing reply is `transport_failed`. Either way the buyer falls back to its own direct call once; a refused reply is
never retried through the Caller.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from pay.voice_cartesia import TERMINAL, CartesiaError

CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
DELEGATE_TIMEOUT_S = 240.0   # under the code's 300 s life, so a direct fallback call still fits


class DelegatedVoiceClient:
    approval_call_to = "bazaar-caller"   # place_call dials only this; the Caller dials its own APPROVAL_CALL_TO

    def __init__(self, mandate_hash: str, request: Callable[[str, dict], Any], used_call_ids: set):
        self.mandate_hash, self.request, self.used = mandate_hash, request, used_call_ids
        self.call: dict | None = None
        self.refused = self.transport_failed = False

    def create_call(self, to_number: str, variables) -> str:
        if to_number != self.approval_call_to:
            raise CartesiaError("delegated call to another number")
        try:
            reply = self.request(self.mandate_hash, dict(variables))
        except Exception:  # noqa: BLE001  (timeout, transport error)
            self.transport_failed = True
            raise CartesiaError("delegated_call_unavailable") from None
        problem = self._check(reply)
        if problem == "transport":
            self.transport_failed = True
        if problem:
            self.refused = self.refused or problem != "transport"
            raise CartesiaError(f"delegated_reply_{problem}")
        self.used.add(reply["call_id"])
        self.call = reply["call"]
        return reply["call_id"]

    def _check(self, reply) -> str | None:
        if not isinstance(reply, dict):
            return "invalid"
        if reply.get("error"):
            return "transport"
        call_id, call = reply.get("call_id"), reply.get("call")
        if reply.get("mandate_hash") != self.mandate_hash:
            return "wrong_mandate"
        if not isinstance(call_id, str) or not CALL_ID.fullmatch(call_id) or call_id in self.used:
            return "replayed_or_bad_call_id"
        if (not isinstance(call, dict) or call.get("status") not in TERMINAL or not isinstance(call.get("transcript"), list)
                or str(call.get("id") or call_id) != call_id):
            return "not_a_finished_call"
        return None

    def get_call(self, call_id: str) -> dict:
        if self.call is None or call_id not in self.used:
            raise CartesiaError("no delegated call")
        return dict(self.call)
