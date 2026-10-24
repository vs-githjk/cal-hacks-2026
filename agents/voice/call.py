"""The approval call, transport-agnostic: what to say and what to do with each heard utterance.
Wraps Lane D's pay.approval session and pay.callscript script; never decides approval itself.

A transport (Cartesia phone call, in-browser call, a test) drives one Call:
    call = Call(svc, mandate, advocate_reason)   # raises ScriptError -> do not place the call
    speak(call.start(now))                       # opening, deal, ask; listen window starts here
    for each FINAL transcript: speak(call.heard(text, confidence, now)); stop when call.done
    on silence or timeout: speak(call.silence(now)); a fresh code is in call.code for the buyer's screen
Rules kept here: seller text is never spoken (only script lines), the amount is never parsed from speech,
and the phone cannot approve without the code shown only on the buyer's screen."""
import re
from datetime import datetime

import common  # noqa: F401  (puts the repo root on sys.path for pay.*)
from pay.approval import ApprovalService
from pay.callscript import script_for

# A "why" question gets the advocate's closed-schema answer and is never sent to approve():
# every approve() call spends one of the deal's 3 attempts.
WHY = re.compile(r"\b(why|cheaper|reason|explain)\b", re.I)
RETRY_LINE = "That did not match. Say the two word code from your screen, then say approve"


class Call:
    def __init__(self, svc: ApprovalService, mandate: dict, advocate_reason: dict | None, channel: str = "phone"):
        self.svc, self.mandate, self.channel = svc, mandate, channel
        self.script = script_for(mandate, advocate_reason)  # ScriptError propagates: no call is placed
        self.session, self.code = svc.issue(mandate, channel=channel)  # code goes to the buyer's screen only
        self.decision = None

    @property
    def done(self) -> bool:
        return self.session.terminal

    def start(self, now: datetime | None = None) -> str:
        self.session.start_call(now)
        line = self.script.spoken()
        self.session.begin_listening(now)  # right after speaking: enforces the 10 s listen window
        return line

    def heard(self, text: str, confidence: float | None = None, now: datetime | None = None) -> str:
        """One FINAL speech-to-text transcript. Returns the line to speak next."""
        if self.done:
            return ""
        if WHY.search(text or "") and "approve" not in (text or "").lower():
            self.session.begin_listening(now)
            return self.script.why_answer
        self.decision = self.session.approve(text, now, confidence=confidence)
        if self.decision.approved:
            return self.script.approved_line
        if self.decision.final:
            return self.script.denied_line
        self.session.begin_listening(now)
        return RETRY_LINE

    def silence(self, now: datetime | None = None) -> str:
        """No answer in the listen window: deny this session, then issue a fresh code (the mandate stays
        pending) so the buyer can retry from the review card."""
        self.decision = self.session.silence(now)
        self.session, self.code = self.svc.issue(self.mandate, channel=self.channel, now=now)
        return self.script.denied_line


# Phone numbers the buyer registered in an earlier in-app step. The call goes only to one of these.
# ponytail: in-memory; Lane B's review card or the buyer agent calls register_number().
REGISTERED: dict[str, str] = {}


def register_number(buyer_id: str, e164: str) -> None:
    if not re.fullmatch(r"\+[1-9]\d{7,14}", e164 or ""):
        raise ValueError("phone number must be E.164, e.g. +14155550100")
    REGISTERED[buyer_id] = e164


def number_for(buyer_id: str) -> str:
    """The only number this buyer's call may go to. Raises if none was registered in-app."""
    if buyer_id not in REGISTERED:
        raise PermissionError("no phone number registered in-app for this buyer; use the in-browser call")
    return REGISTERED[buyer_id]
