"""Hardened approval core (d3): a one-time word-pair code, a code-only intent check, default deny.

Voice is never the credential. The credential is a two-word code shown on the buyer's authenticated screen
and spoken on the phone call inside one session about one exact mandate. No model decides "approve": `approve`
passes only when the normalized transcript holds the exact word pair AND the token "approve" or "approved"
(nothing else counts: not "approves", "approval" or "disapprove"). Everything
else, including silence, a timeout, low speech-to-text confidence and anything unclear, denies.

Flow:
    svc = ApprovalService()                              # secret from env APPROVAL_SECRET (>= 16 chars)
    session, code = svc.issue(mandate)                   # show `code` on the review card; only its hash is kept
    script = script_for(mandate, advocate_reason)        # opening, deal read-back, why-not-cheaper answer
    session.start_call(); session.begin_listening()
    decision = session.approve(transcript_text)          # a phone call transcript; there is no typed path (#185)
    if decision.approved: record = decision.record       # VoiceApproval; mandate is now approved
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, Overflow
from typing import Any, Optional

from pay.callscript import CallScript, ScriptError, script_for  # noqa: F401  (re-exported)
from pay.mandate import _manual_check, format_ts, mandate_hash, verify
from pay.mandate import _now as _now_utc
from pay.replay import NonceStore
from pay.words import WORD_SET, WORDS

SECRET_ENV = "APPROVAL_SECRET"
MIN_SECRET_LENGTH = 16
NS_CODE = "approval_code"
CODE_TTL_SECONDS = 120
VOICE_CODE_TTL_SECONDS = 300
MAX_ATTEMPTS = 3
COOLDOWN_SECONDS = 30
LISTEN_WINDOW_SECONDS = 10
MAX_TOKENS = 12
# Consent is the code, "approve" or "approved", and filler, nothing else (#195, red team M1). Any digit, number word or
# money unit denies ("<code> approve $900", "nine ninety nine", "1.2k"), and so does any other word ("approve for seller
# z"): a spoken amount or payee is never consent to this mandate's. "two" counts as filler only in "two word(s)", as the
# real call of Oct 24 00:08 said ("the two words from my screen are ..."). The money control is still the signed mandate.
MONEY_UNITS = frozenset({"dollar", "dollars", "buck", "bucks", "cent", "cents", "usd", "grand", "k"})
NUMBER_WORDS = frozenset({
    "zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
    "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty",
    "fourty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "billion", "half",
    "quarter", "point", "percent", "dozen",
})
FILLER = frozenset({
    "okay", "ok", "uh", "um", "umm", "er", "erm", "hmm", "so", "yes", "yeah", "yep", "sure", "alright", "right", "well",
    "hello", "hi", "hey", "the", "a", "my", "code", "codes", "word", "words", "is", "are", "its", "it", "from", "on",
    "screen", "says", "i", "please", "and", "that", "thats", "this", "here",
    # #195 answer from the owner: "approve, thank you" and "okay go ahead, approve" pass; a number or another amount still denies
    "thanks", "thank", "you", "now", "go", "ahead", "good", "sounds",
})
MIN_CONFIDENCE = 0.6
APPROVE_TOKEN = "approve"
APPROVE_TOKENS = frozenset({APPROVE_TOKEN, "approved"})  # speech-to-text often hears "approve" as "approved"; exactly these two
# Any of these anywhere in the utterance means "no" (or "not sure"): deny.
NEGATIONS = frozenset({
    "no", "not", "nope", "nah", "dont", "never", "cant", "cannot", "wont", "didnt", "isnt", "wasnt",
    "shouldnt", "stop", "cancel", "deny", "denied", "decline", "reject", "wait", "hold", "should", "would",
    "could", "can", "if", "whether", "maybe", "unless", "refuse", "refused", "without", "nothing", "nor",
})

STATES = ("issued", "awaiting_code", "approved", "denied", "expired")
_TERMINAL = ("approved", "denied", "expired")
_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "contracts", "VoiceApproval.schema.json")


class ApprovalError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


# ---------- text and code ----------

def normalize(text: Any) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Apostrophes vanish ("don't" is "dont"); any other
    non-ASCII-alphanumeric character becomes a space, so look-alike letters never match a code word."""
    if not isinstance(text, str):
        return ""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"['’‘`]", "", t)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def code_hash(code: str) -> str:
    """sha256 hex of the normalized word pair, as the VoiceApproval contract defines code_hash."""
    return hashlib.sha256(normalize(code).encode("utf-8")).hexdigest()


def _within(a: str, b: str, limit: int = 2) -> bool:
    """True when the edit distance between a and b is at most `limit` (small inputs only)."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1] <= limit


def _as_code_word(token: str) -> str:
    """Map a heard token to the list word one edit away, so an accent or a speech-to-text spelling ("orchid's"
    normalizes to "orchids", "sunsat", "orchd") still counts. List words are at least 3 edits apart, so at most
    one is that close. The pair still has to be this deal's two words in order; two edits let ordinary words
    in ("zipper" is two from "copper"), so the limit stays at one."""
    if token in WORD_SET or len(token) < 4:
        return token
    near = [w for w in WORDS if _within(token, w, 1)]
    return near[0] if len(near) == 1 else token


def _code_like(token: str) -> bool:
    """A word of the list or a near miss of one (a misheard code word): used only to pick the deny reason."""
    return token in WORD_SET or (len(token) >= 4 and any(_within(token, w) for w in WORDS))


def derive_code(secret: str, mand_hash: str, nonce: str) -> str:
    """Two different words, chosen by HMAC-SHA256(secret, mandate_hash : nonce)."""
    digest = hmac.new(secret.encode("utf-8"), f"{mand_hash}:{nonce}".encode("utf-8"), hashlib.sha256).digest()
    n = len(WORDS)
    i = int.from_bytes(digest[0:4], "big") % n
    j = int.from_bytes(digest[4:8], "big") % (n - 1)
    if j >= i:
        j += 1
    return f"{WORDS[i]} {WORDS[j]}"


# ---------- contract ----------

def validate_record(rec: dict) -> list[str]:
    """Error strings (empty list means it matches contracts/VoiceApproval.schema.json)."""
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    try:
        import jsonschema
    except ImportError:
        return _manual_check(rec, schema)
    return sorted(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                  for e in jsonschema.Draft202012Validator(schema).iter_errors(rec))


def _approval_cents(value: Any) -> Optional[int]:
    try:
        amount = Decimal(str(value))
        if isinstance(value, bool) or not amount.is_finite() or amount <= 0 or amount.adjusted() > 11:
            return None
        cents = amount * 100
        if cents <= 0 or cents != cents.to_integral_value():
            return None
        return int(cents)
    except (InvalidOperation, Overflow, ValueError, TypeError):
        return None


def _approval_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def approved_voice_record_matches(record: Any, mandate: Any, *,
                                  now: Optional[datetime] = None) -> bool:
    """Pure approval gate shared by checkout, settlement, and MerchantSim.

    Browser approvals keep their 120-second issuance window; the voice adapter may use up to 300 seconds
    for ringing and read-back, still bounded by the exact mandate expiry.
    """
    if not isinstance(record, dict) or not isinstance(mandate, dict):
        return False
    if validate_record(record):
        return False
    # LOCKED rule (Vidyut, 08:40): approval is by phone call only; a typed or browser record never pays
    if (record.get("channel") != "phone" or record.get("result") != "approved" or record.get("id") != mandate.get("approval_id")
            or record.get("mandate_id") != mandate.get("id")
            or record.get("mandate_hash") != mandate.get("hash")
            or _approval_cents(record.get("amount_read_back")) != _approval_cents(mandate.get("amount"))
            or record.get("payee_read_back") != mandate.get("payee")):
        return False
    try:
        issued = _approval_time(record["code_issued_at"])
        expires = _approval_time(record["code_expires_at"])
        decided = _approval_time(record["decided_at"])
        mandate_created = _approval_time(mandate["created_at"])
        mandate_expires = _approval_time(mandate["expires_at"])
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            return False
        current = current.astimezone(timezone.utc)
        ttl = expires - issued
        return (issued <= decided <= expires and timedelta(0) < ttl <= timedelta(seconds=VOICE_CODE_TTL_SECONDS)
                and mandate_created <= issued <= expires <= mandate_expires
                and decided <= current + timedelta(seconds=5))
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return False


@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: Optional[str]          # a VoiceApproval deny_reason, None when approved
    state: str
    final: bool                    # True once the session is over
    record: Optional[dict] = None  # the VoiceApproval row, set when the session just ended

    def __bool__(self) -> bool:
        return self.approved


# ---------- service ----------

class ApprovalService:
    """Holds the server secret, the used-code store and the per-mandate counters shared by every session.

    Attempts and the deny cooldown are counted per mandate, not per session, so asking for a fresh code
    cannot reset the guess budget. Only code hashes are kept, never a code."""

    def __init__(self, secret: Optional[str] = None, store: Optional[NonceStore] = None, *,
                 code_ttl_seconds: int = CODE_TTL_SECONDS, cooldown_seconds: int = COOLDOWN_SECONDS,
                 max_attempts: int = MAX_ATTEMPTS):
        secret = secret if secret is not None else os.environ.get(SECRET_ENV, "")
        if not isinstance(secret, str) or len(secret) < MIN_SECRET_LENGTH:
            raise ApprovalError("no_secret", f"set {SECRET_ENV} to a random value of at least {MIN_SECRET_LENGTH} characters")
        if not 0 < max_attempts <= MAX_ATTEMPTS:
            raise ValueError(f"max_attempts must be 1..{MAX_ATTEMPTS}")
        self._secret = secret
        self.store = store if store is not None else NonceStore()
        self.code_ttl = timedelta(seconds=code_ttl_seconds)
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self.max_attempts = max_attempts
        self.lock = threading.RLock()
        self._codes: dict[str, str] = {}              # code_hash -> mandate_hash (every code ever issued)
        self._attempts: dict[str, int] = {}           # mandate_hash -> failed or spent tries
        self._cooldown_until: dict[str, datetime] = {}
        self._live: dict[str, "ApprovalSession"] = {}

    def attempts_used(self, mand_hash: str) -> int:
        return self._attempts.get(mand_hash, 0)

    def issue(self, mandate: dict, *, channel: str = "browser",
              now: Optional[datetime] = None) -> tuple["ApprovalSession", str]:
        """Start a session for one pending mandate. Returns (session, code): show the code on the buyer's
        authenticated screen. The service and the session keep only its hash."""
        if channel not in ("browser", "phone"):
            raise ValueError("channel must be browser or phone (typed is a per-attempt channel)")
        now = _now_utc(now).replace(microsecond=0)
        with self.lock:
            if self.attempts_used(str(mandate.get("hash"))) >= self.max_attempts:
                raise ApprovalError("max_attempts", "this deal used its attempts; it needs a new mandate")
            bad = verify(mandate, now)
            if not bad:
                raise ApprovalError(bad.reason, bad.detail)
            if mandate["status"] != "pending":
                raise ApprovalError("not_pending", "only a pending mandate can be approved")
            mh = mandate["hash"]
            old = self._live.get(mh)
            if old is not None and old.state not in _TERMINAL:
                old._finish(now, "expired", "expired", "expired")   # a new code retires the old one
            for _ in range(32):                                       # a collision with any past code is redrawn
                code = derive_code(self._secret, mh, secrets.token_hex(16))
                ch = code_hash(code)
                if ch not in self._codes and not self.store.seen(NS_CODE, ch):
                    break
            else:  # pragma: no cover
                raise ApprovalError("no_code_available", "could not draw an unused code")
            expires = min(now + self.code_ttl, _expiry_of(mandate))
            session = ApprovalSession(self, mandate, ch, now, expires, channel)
            self._codes[ch] = mh
            self._live[mh] = session
            return session, code


def _expiry_of(mandate: dict) -> datetime:
    from pay.mandate import parse_ts
    return parse_ts(mandate["expires_at"])


# ---------- session ----------

class ApprovalSession:
    """issued -> awaiting_code -> approved | denied | expired. Default is deny."""

    def __init__(self, service: ApprovalService, mandate: dict, chash: str, issued_at: datetime,
                 expires_at: datetime, channel: str):
        self._svc = service
        self.mandate = mandate
        self.mandate_hash: str = mandate["hash"]
        self.code_hash = chash
        self.issued_at = issued_at
        self.expires_at = expires_at
        self.channel = channel
        self.state = "issued"
        self.attempts = 0
        self.id = "apr_" + secrets.token_hex(8)
        self.result: Optional[str] = None
        self.deny_reason: Optional[str] = None
        self.decided_at: Optional[datetime] = None
        self.recording_ref: Optional[str] = None
        self._listen_deadline: Optional[datetime] = None

    # --- state ---

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL

    def start_call(self, now: Optional[datetime] = None) -> str:
        """issued -> awaiting_code. Attempts made before this move the session on by themselves."""
        if self.state == "issued":
            self.state = "awaiting_code"
        return self.state

    def begin_listening(self, now: Optional[datetime] = None) -> None:
        """The agent just finished speaking: a voice answer must arrive within 10 seconds."""
        self._listen_deadline = _now_utc(now) + timedelta(seconds=LISTEN_WINDOW_SECONDS)

    def tick(self, now: Optional[datetime] = None) -> str:
        """Expire the session if its code is past its time. Returns the state."""
        now = _now_utc(now)
        with self._svc.lock:
            if not self.terminal and now >= self.expires_at:
                self._finish(now, "expired", "expired", "expired")
            return self.state

    def silence(self, now: Optional[datetime] = None) -> Decision:
        """No answer (or a timeout): deny, result no_answer."""
        now = _now_utc(now)
        with self._svc.lock:
            if self.terminal:
                return self._repeat()
            return self._finish(now, "denied", "no_answer", "silence")

    # --- attempts ---

    def approve(self, transcript_text: Any, now: Optional[datetime] = None, *,
                confidence: Optional[float] = None) -> Decision:
        """One spoken attempt. Approves only on the exact word pair plus the token "approve" or "approved" in the same
        utterance. `confidence` is the speech-to-text confidence; below 0.6 counts as a mismatch."""
        return self._attempt(transcript_text, _now_utc(now), confidence, self._voice_channel())

    def _voice_channel(self) -> str:
        return self.channel

    def _attempt(self, text: Any, now: datetime, confidence: Optional[float], channel: str) -> Decision:
        svc = self._svc
        with svc.lock:
            if self.terminal:
                return self._repeat()
            if now >= self.expires_at:
                return self._finish(now, "expired", "expired", "expired")
            problem = self._mandate_problem(now)
            if problem is not None:
                return problem
            if self.state == "issued":
                self.state = "awaiting_code"
            if svc.attempts_used(self.mandate_hash) >= svc.max_attempts:
                return self._finish(now, "denied", "denied", "max_attempts")
            until = svc._cooldown_until.get(self.mandate_hash)
            if until is not None and now < until:
                return Decision(False, "cooldown", self.state, False)
            if self._listen_deadline is not None and now > self._listen_deadline:
                return self._finish(now, "denied", "no_answer", "silence")
            tokens = normalize(text).split()
            if not tokens:
                return self._finish(now, "denied", "no_answer", "silence")
            self._listen_deadline = None
            # speech-to-text never emits invisible format characters; text carrying them is an injection, and
            # the close-spelling match below must not glue a split word back together
            hidden = isinstance(text, str) and any(unicodedata.category(c) == "Cf" for c in text)
            # normalize() turns any other script into blanks; a non-ASCII digit, letter or symbol ("approve ٩٠٠", "€",
            # "九百") must deny, not vanish (#195)
            foreign = isinstance(text, str) and any(ord(c) > 127 and (c.isalnum() or unicodedata.category(c)[0] == "S")
                                                    for c in unicodedata.normalize("NFKC", text))
            reason = "wrong_code" if hidden else "no_code" if foreign else self._judge(tokens, confidence)
            svc._attempts[self.mandate_hash] = svc.attempts_used(self.mandate_hash) + 1
            self.attempts += 1
            if reason is None:
                self.channel = channel
                return self._approve(now)
            svc._cooldown_until[self.mandate_hash] = now + svc.cooldown
            if svc.attempts_used(self.mandate_hash) >= svc.max_attempts:
                self.mandate["status"] = "denied"
                final = self._finish(now, "denied", "denied", "max_attempts")
                return Decision(False, reason, final.state, True, final.record)
            return Decision(False, reason, self.state, False)

    def _judge(self, tokens: list[str], confidence: Optional[float]) -> Optional[str]:
        """None when the utterance is the right code plus "approve" or "approved"; else the deny reason."""
        svc = self._svc
        if confidence is not None and not (isinstance(confidence, (int, float)) and confidence >= MIN_CONFIDENCE):
            return "wrong_code"
        if len(tokens) > MAX_TOKENS:
            return "no_code"
        if NEGATIONS & set(tokens):
            return "no_code"
        two_words = {i for i, t in enumerate(tokens) if t == "two" and tokens[i + 1:i + 2] in (["words"], ["word"])}
        if any(any(c.isdigit() for c in t) for t in tokens) or MONEY_UNITS & set(tokens) or any(
                t in NUMBER_WORDS and i not in two_words for i, t in enumerate(tokens)):
            return "no_code"                   # a number was spoken; consent must be the code and "approve" only
        words = [_as_code_word(t) for t in tokens]
        pairs = [(k, hashlib.sha256(f"{a} {b}".encode("utf-8")).hexdigest())
                 for k, (a, b) in enumerate(zip(words, words[1:])) if a in WORD_SET and b in WORD_SET]
        pair_hashes = [h for _, h in pairs]
        own_at = [k for k, h in pairs if hmac.compare_digest(h, self.code_hash)]
        own = bool(own_at)
        if not own:
            for h in pair_hashes:
                owner = svc._codes.get(h)
                if owner is not None and owner != self.mandate_hash:
                    return "replay"            # a code issued for another deal
            return "wrong_code" if any(_code_like(t) for t in tokens) else "no_code"
        if not APPROVE_TOKENS & set(tokens):
            return "no_code"                   # the code alone is not consent
        # Outside this deal's pair (said once), every heard token must be approve or filler as heard: no other list word, no
        # repeat of the code, and no near miss mapped onto a list word ("rover", "apples" are not "river", "apple" here).
        if len(own_at) != 1 or any(t not in APPROVE_TOKENS and t not in FILLER and i not in two_words
                                   for i, t in enumerate(tokens) if i not in (own_at[0], own_at[0] + 1)):
            return "no_code"                   # any other word (a payee, a term, a condition) is not consent to this mandate
        if not svc.store.consume(NS_CODE, self.code_hash):
            return "replay"                    # single use
        return None

    def _mandate_problem(self, now: datetime) -> Optional[Decision]:
        m = self.mandate
        if m.get("status") != "pending":
            return self._finish(now, "denied", "denied", "replay")
        try:
            moved = mandate_hash(m) != self.mandate_hash or m.get("hash") != self.mandate_hash
        except (ValueError, TypeError):
            moved = True
        if moved:
            return self._finish(now, "denied", "denied", "replay")   # fields changed after the code was issued
        check = verify(m, now)
        if check:
            return None
        if check.reason == "expired":
            return self._finish(now, "expired", "expired", "expired")
        return self._finish(now, "denied", "denied", "replay")

    # --- outcomes ---

    def _repeat(self) -> Decision:
        """A further attempt on a finished session: deny again, change nothing."""
        reason = "replay" if self.state == "approved" else (self.deny_reason or "replay")
        return Decision(False, reason, self.state, True)

    def _approve(self, now: datetime) -> Decision:
        self.state, self.result, self.deny_reason, self.decided_at = "approved", "approved", None, now
        record = self.to_record()
        self.mandate["status"] = "approved"
        self.mandate["approval_id"] = record["id"]
        return Decision(True, None, "approved", True, record)

    def _finish(self, now: datetime, state: str, result: str, reason: str) -> Decision:
        if self.terminal:
            return self._repeat()
        self.state, self.result, self.deny_reason, self.decided_at = state, result, reason, now
        return Decision(False, reason, state, True, self.to_record())

    def to_record(self) -> dict:
        """The VoiceApproval row for a finished session (the code itself is never in it)."""
        if self.decided_at is None or self.result is None:
            raise ApprovalError("not_decided", "the session has no outcome yet")
        rec = {
            "id": self.id,
            "mandate_id": self.mandate["id"],
            "mandate_hash": self.mandate_hash,
            "channel": self.channel,
            "code_issued_at": format_ts(self.issued_at),
            "code_expires_at": format_ts(self.expires_at),
            "code_hash": self.code_hash,
            "attempts": self.attempts,
            "amount_read_back": self.mandate["amount"],
            "payee_read_back": self.mandate["payee"],
            "result": self.result,
            "deny_reason": self.deny_reason,
            "decided_at": format_ts(self.decided_at),
            "recording_ref": self.recording_ref,
        }
        errors = validate_record(rec)
        if errors:  # fail closed: never emit a row that breaks the contract
            raise ApprovalError("record_invalid", errors[0])
        return rec
