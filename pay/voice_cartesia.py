"""Two-way approval call over a Cartesia MANAGED agent (issue #13). Default deny stays in OUR code.

The managed agent only talks. It never decides: it reads one deal script, asks for the two-word code on the
buyer's screen, repeats back what it heard and hangs up. We place the call, wait for it to end, fetch the
transcript and feed every BUYER utterance to pay.approval.ApprovalSession.approve(). Only an approved session
sets mandate["status"] = "approved", which is what pay.mandate.can_charge needs. Silence, a hang-up, a failed
dial, voicemail, a timeout or a missing transcript all end in a denial.

    session, code = svc.issue(mandate, channel="phone")   # code goes to the buyer's screen only (on_code)
    place_call(...)  ->  wait_for_end(...)  ->  transcript(...)  ->  session.approve(text, confidence=None)

What the call carries (dynamic variables, filled from pay.callscript.script_for): buyer_name, deal_script,
why_answer. The code and any seller text are never sent: amount and payee are read from the mandate, and the
why-answer comes from the advocate's closed-schema reason. Calls go only to APPROVAL_CALL_TO.

Cartesia API used (all base https://api.cartesia.ai, header "Cartesia-Version: 2026-08-14", key sent as
"X-API-Key" as in the guide examples and as "Authorization: Bearer" as the OpenAPI security scheme says):
  1. POST /agents/calls  (Create Outbound Call)
       https://docs.cartesia.ai/line/integrations/telephony/outbound-dialing.md
       https://docs.cartesia.ai/api-reference/agents/calls/create-outbound-call.md
     body: {from_number_id, agent_id, ringing_timeout_seconds (5..80), max_call_duration_minutes,
            outbound_calls: [{to_number (E.164), dynamic_variables: {name: string|number|bool}}]}
     reply 200: {calls: [{number, agent_call_id} | {number, error}]}. Check every entry, not only the status.
  2. GET /agents/calls/{call_id}  (Get Call)
       https://docs.cartesia.ai/api-reference/agents/calls/get-call.md
     fields: status (created | started | completed | failed), end_reason (agent_hangup, client_hangup,
     dial_no_answer, dial_busy, dial_failed, dial_timeout, voicemail_detected, ...), start_time, end_time,
     zdr_enabled (true means no transcript is kept), transcript: [{role: user | assistant | system, text,
     start_timestamp, end_timestamp}] (seconds from call start). role "user" is the human who answered.
     There is NO separate transcript endpoint: the transcript is a field of Get Call.
  3. GET /agents/{agent_id}  (Get Agent), https://docs.cartesia.ai/api-reference/agents/agents/get.md
     fields: phone_numbers: [{id, number}]. Used for the read-only check and to find from_number_id (the
     "ap_..." id of the agent's Cartesia number) when CARTESIA_PHONE_NUMBER_ID is not set. The docs say an
     agent has at most one number. Fallback: GET /agents/phone-numbers?agent_id=... (List Phone Numbers).
  Dynamic variables: https://docs.cartesia.ai/agents/dynamic-variables.md ({{name}} in the greeting and prompt;
  every variable used in the welcome message must be supplied before the call starts).
  Index of all pages: https://docs.cartesia.ai/llms.txt (Get Call and the list/get-agent pages are linked from
  the guides but missing from that index).

UNDOCUMENTED, so we design around it (see README): (a) how long after status "completed" the transcript is
complete (we retry a few times when it is empty); (b) whether Get Call needs X-API-Key or Bearer (we send both);
(c) a call-cancel endpoint (DELETE /agents/calls/{id} is documented as "redact", not as hang-up), so a wait
timeout denies and the call may still be ringing, and anything said after the timeout is ignored.

Keys are read from the environment or an env file (names only: CARTESIA_API_KEY, CARTESIA_AGENT_ID,
APPROVAL_CALL_TO, optional APPROVAL_BUYER_NAME and CARTESIA_PHONE_NUMBER_ID (the "ap_..." id sent as from_number_id) and APPROVAL_SECRET). No value is ever printed or logged.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from pay.approval import (APPROVE_TOKENS, VOICE_CODE_TTL_SECONDS, ApprovalError, ApprovalService, Decision,
                          normalize)
from pay.callscript import CallScript, ScriptError, is_clean_name, script_for
from pay.words import WORD_SET

API_BASE = "https://api.cartesia.ai"
API_VERSION = "2026-08-14"
USER_AGENT = "tech-bazaar-lane-d/1.0"
SYSTEM_CA = "/etc/ssl/cert.pem"
KEY_ENV, AGENT_ENV, TO_ENV, FROM_ENV, SECRET_ENV, NAME_ENV = (
    "CARTESIA_API_KEY", "CARTESIA_AGENT_ID", "APPROVAL_CALL_TO", "CARTESIA_PHONE_NUMBER_ID", "APPROVAL_SECRET",
    "APPROVAL_BUYER_NAME")
# #449 item 1: who may be called (comma-separated E.164) and where the persisted rate cap lives
ALLOW_ENV, RATE_ENV = "APPROVAL_CALL_ALLOWLIST", "APPROVAL_CALL_RATE_FILE"
ENV_NAMES = (KEY_ENV, AGENT_ENV, TO_ENV, FROM_ENV, SECRET_ENV, NAME_ENV, ALLOW_ENV, RATE_ENV)
DEFAULT_RATE_FILE = Path(__file__).resolve().parents[1] / "agents" / ".state" / "approval_call_rate.json"   # agents/.state is gitignored
RATE_PER_NUMBER_S = 300
RATE_DAY_S = 24 * 3600
RATE_DAY_MAX = 20
DEFAULT_BUYER_NAME = "Vidyut"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / "lane-d" / ".env"   # main lane-d checkout, gitignored

RINGING_TIMEOUT_S = 30
MAX_CALL_MINUTES = 3
POLL_S = 2.0
MAX_WAIT_S = 180.0
TRANSCRIPT_RETRIES = 4
TRANSCRIPT_RETRY_S = 2.0
CALL_CODE_TTL_S = VOICE_CODE_TTL_SECONDS  # still capped by the mandate's own 10 minute expiry
TERMINAL = ("completed", "failed")
_E164 = re.compile(r"\+[1-9][0-9]{6,14}")
_NAME = re.compile(r"[A-Za-z][A-Za-z .'-]{0,39}")


class CartesiaError(Exception):
    """A Cartesia request failed. The message never holds the API key."""


class NumberNotAllowed(CartesiaError):
    """A call was requested to a number other than APPROVAL_CALL_TO."""


class CallLimited(CartesiaError):
    """#449 item 1: no call, by policy. `reason` is "beta_allowlist" (number not on APPROVAL_CALL_ALLOWLIST) or "rate_limited"
    (per-number or daily cap, or the rate file is unusable: fail closed). The message never holds the number."""

    def __init__(self, reason: str):
        super().__init__({"beta_allowlist": "approval calls are limited to the beta allowlist",
                          "rate_limited": "approval call rate limit reached"}.get(reason, reason))
        self.reason = reason


class NoPhone(CartesiaError):
    """The buyer has no phone number to approve on. Above the allowance that means no call and no approval: the phone call is the only way."""


# The buyer APPROVAL_CALL_TO belongs to (the id the demo's /buyer pairs with; demo/bridge.py DB_BUYER_ID, pinned by a test).
DEFAULT_APPROVAL_BUYER = "vidyut"


# The market view only the referee can read: one row per buyer with the phone they gave at sign-up (market/spacetimedb/src/schema.ts AgentBuyerContactRow).
BUYER_CONTACT_VIEW = "agent_buyer_contact"
_BUYER_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
PhoneLookup = Callable[[str], Optional[str]]


def valid_e164(number: Any) -> bool:
    return isinstance(number, str) and _E164.fullmatch(number) is not None


def parse_allowlist(raw: Any) -> Optional[frozenset]:
    """#449 item 1: the numbers in APPROVAL_CALL_ALLOWLIST (comma-separated, spaces stripped, non-E.164 entries ignored).
    None when it is unset or blank (no limit); a set (possibly empty, so nobody) as soon as anything is written there."""
    if not isinstance(raw, str) or not raw.strip(", \t\n"):
        return None
    return frozenset(p for p in (x.strip() for x in raw.split(",")) if valid_e164(p))


def on_allowlist(number: Any, allowlist: Optional[frozenset]) -> bool:
    return allowlist is None or number in allowlist


class CallRateLimiter:
    """#449 item 1: at most 1 call per number per 300 s and 20 per rolling 24 h across all numbers, in a small JSON file shared by
    the buyer agent, the Caller and the demo scripts. Numbers are stored as sha256 hex only. Writes are atomic (temp file +
    os.replace) under an flock on a sidecar lock file. A missing file is empty; an unreadable or corrupt one fails closed."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self.path, self._clock = Path(path), clock

    def _load(self) -> list:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        try:
            calls = json.loads(raw)["calls"]
            if not isinstance(calls, list) or not all(
                    isinstance(c, dict) and isinstance(c.get("h"), str) and isinstance(c.get("t"), (int, float))
                    and not isinstance(c.get("t"), bool) for c in calls):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise CallLimited("rate_limited") from None
        return calls

    def reserve(self, number: str) -> None:
        """Record one call for `number` now, or raise CallLimited("rate_limited") and record nothing."""
        key = hashlib.sha256(number.encode("utf-8")).hexdigest()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(str(self.path) + ".lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                now = self._clock()
                calls = self._load()
                recent = [c for c in calls if now - c["t"] < RATE_DAY_S]
                if len(recent) >= RATE_DAY_MAX or any(c["h"] == key and now - c["t"] < RATE_PER_NUMBER_S for c in recent):
                    raise CallLimited("rate_limited")
                tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
                tmp.write_text(json.dumps({"calls": recent + [{"h": key, "t": now}]}), encoding="utf-8")
                os.replace(tmp, self.path)
        except OSError:
            raise CallLimited("rate_limited") from None


def phone_lookup_from_sql(sql: Callable[[str], Any]) -> PhoneLookup:
    """A lookup for one buyer's own phone, from a referee-identity `sql(query)` (market/scripts/stdb.py Market.sql: positional rows
    [buyer_id, phone]; dict rows work too). Only a row whose own buyer_id equals the one asked for counts, so another buyer's row can
    never be returned. Any odd id or any failure is None (the caller then fails closed). The number is never logged or put in an error."""
    def lookup(buyer_id: str) -> Optional[str]:
        if not isinstance(buyer_id, str) or not _BUYER_ID.fullmatch(buyer_id):
            return None
        try:
            rows = sql(f"SELECT buyer_id, phone FROM {BUYER_CONTACT_VIEW} WHERE buyer_id = '{buyer_id}'")
            for row in rows or []:
                rid, phone = (row.get("buyer_id"), row.get("phone")) if isinstance(row, Mapping) else (row[0], row[1])
                if rid == buyer_id:
                    return phone if isinstance(phone, str) else None
        except Exception:
            return None
        return None
    return lookup


def name_lookup_from_sql(sql: Callable[[str], Any]) -> PhoneLookup:
    """Like phone_lookup_from_sql, for the buyer's own display_name from the same agent_buyer_contact view (rows [buyer_id, display_name]).
    Only the row whose own buyer_id matches counts; any odd id or failure is None."""
    def lookup(buyer_id: str) -> Optional[str]:
        if not isinstance(buyer_id, str) or not _BUYER_ID.fullmatch(buyer_id):
            return None
        try:
            rows = sql(f"SELECT buyer_id, display_name FROM {BUYER_CONTACT_VIEW} WHERE buyer_id = '{buyer_id}'")
            for row in rows or []:
                rid, name = (row.get("buyer_id"), row.get("display_name")) if isinstance(row, Mapping) else (row[0], row[1])
                if rid == buyer_id:
                    return name if isinstance(name, str) else None
        except Exception:
            return None
        return None
    return lookup


GENERIC_GREETING = "there"


def greeting_name(buyer_id: str, env: Mapping[str, str], name_lookup: Optional[PhoneLookup] = None,
                  default_buyer_id: str = DEFAULT_APPROVAL_BUYER) -> str:
    """The name the approval call greets this buyer by. APPROVAL_BUYER_NAME (else "Vidyut") is for the default buyer ONLY. Any other buyer
    is greeted by their own display_name, or "there" when it is missing, empty or not a plain name the call script accepts."""
    if buyer_id and buyer_id == default_buyer_id:
        return env.get(NAME_ENV) or DEFAULT_BUYER_NAME
    if not buyer_id or name_lookup is None:
        return GENERIC_GREETING
    try:
        name = (name_lookup(buyer_id) or "").strip()
    except Exception:
        return GENERIC_GREETING
    return name if _NAME.fullmatch(name) and is_clean_name(name) else GENERIC_GREETING   # #449 item 1: no steering words aloud


def approval_phone(buyer_id: str, env: Mapping[str, str], default_buyer_id: str = DEFAULT_APPROVAL_BUYER,
                   lookup: Optional[PhoneLookup] = None) -> Optional[str]:
    """The number the approval call rings for this buyer, or None when there is none. The default buyer gets the env-configured
    APPROVAL_CALL_TO (unchanged, the market is not asked). Any other buyer gets their OWN phone from `lookup` (the market's agent-only
    contact view), only when it is a valid E.164 number; with no lookup, no row, no phone or a bad number it is None. Never the default
    buyer's number and never another buyer's."""
    if buyer_id and buyer_id == default_buyer_id:
        return env.get(TO_ENV) or None
    if not buyer_id or lookup is None:
        return None
    try:
        phone = lookup(buyer_id)
    except Exception:
        return None
    return phone if valid_e164(phone) else None


def client_for_buyer(buyer_id: str, env: Mapping[str, str], lookup: Optional[PhoneLookup] = None, **kw) -> "CartesiaClient":
    """The Cartesia client whose only number is this buyer's approval phone. NoPhone for a buyer with none (never the default number);
    the default buyer's missing or bad setup is the same CartesiaError as before."""
    phone = approval_phone(buyer_id, env, lookup=lookup)
    if phone is None and buyer_id != DEFAULT_APPROVAL_BUYER:
        raise NoPhone(f"no approval phone number for buyer {buyer_id}")
    target = phone or env.get(TO_ENV)
    if target and not on_allowlist(target, parse_allowlist(env.get(ALLOW_ENV))):
        raise CallLimited("beta_allowlist")   # #449 item 1: early and friendly; create_call enforces it again
    return CartesiaClient.from_env({**env, TO_ENV: phone} if phone else env, **kw)


# ---------- config ----------

def load_env(path: Optional[Path] = None, environ: Optional[Mapping[str, str]] = None) -> dict:
    """The names in ENV_NAMES from the process environment, else from the env file. Nothing else is read."""
    environ = os.environ if environ is None else environ
    out = {k: environ[k] for k in ENV_NAMES if environ.get(k)}
    if path is not None:
        try:
            for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                k = k.strip()
                if k in ENV_NAMES and k not in out and v.strip():
                    out[k] = v.strip().strip('"').strip("'")
        except OSError:
            pass
    return out


def mask_number(n: str) -> str:
    return n[:2] + "*" * max(len(n) - 4, 0) + n[-2:] if len(n) > 4 else "***"


def _tls_context() -> ssl.SSLContext:
    """Normal certificate checking, never disabled. certifi when installed, else the system bundle on macOS."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    if not ssl.get_default_verify_paths().cafile and not ctx.cert_store_stats().get("x509_ca") and os.path.exists(SYSTEM_CA):
        ctx = ssl.create_default_context(cafile=SYSTEM_CA)
    return ctx


# ---------- client ----------

class CartesiaClient:
    """Thin stdlib client. `approval_call_to` is the ONLY number it will ever dial."""

    def __init__(self, api_key: str, agent_id: str, approval_call_to: str, from_number_id: Optional[str] = None, *,
                 opener: Optional[Callable] = None, base_url: str = API_BASE, timeout: float = 20.0,
                 allowlist: Optional[frozenset] = None, rate_file: Optional[Path] = None,
                 clock: Callable[[], float] = time.time):
        if not api_key or not agent_id:
            raise CartesiaError(f"{KEY_ENV} and {AGENT_ENV} are required")
        if not isinstance(approval_call_to, str) or not _E164.fullmatch(approval_call_to):
            raise CartesiaError(f"{TO_ENV} must be an E.164 number such as +14155550123")
        self._key = api_key
        self.agent_id = agent_id
        self.approval_call_to = approval_call_to
        self.from_number_id = from_number_id
        self._opener = opener or urllib.request.urlopen
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self.allowlist = allowlist   # #449 item 1: None = no limit; from_env sets both from the env
        self._limiter = CallRateLimiter(rate_file, clock) if rate_file else None

    @classmethod
    def from_env(cls, env: Mapping[str, str], **kw) -> "CartesiaClient":
        missing = [k for k in (KEY_ENV, AGENT_ENV, TO_ENV) if not env.get(k)]
        if missing:
            raise CartesiaError("missing " + ", ".join(missing))
        kw.setdefault("allowlist", parse_allowlist(env.get(ALLOW_ENV)))
        kw.setdefault("rate_file", Path(env.get(RATE_ENV) or DEFAULT_RATE_FILE))
        return cls(env[KEY_ENV], env[AGENT_ENV], env[TO_ENV], env.get(FROM_ENV) or None, **kw)

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self._base + path, data=data, method=method, headers={
            "X-API-Key": self._key, "Authorization": f"Bearer {self._key}", "Cartesia-Version": API_VERSION,
            "Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            with self._opener(req, timeout=self._timeout, context=_tls_context()) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise CartesiaError(f"{method} {path.split('?')[0]} -> HTTP {e.code} {self._why(e)}") from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise CartesiaError(f"{method} {path.split('?')[0]} failed ({type(e).__name__})") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise CartesiaError(f"{method} {path.split('?')[0]} returned non-JSON") from None

    def _why(self, e: urllib.error.HTTPError) -> str:
        try:
            msg = json.loads(e.read()).get("message") or ""
        except (ValueError, OSError, AttributeError):
            msg = ""
        return str(msg).replace(self._key, "***")[:120]

    def get_agent(self) -> dict:
        return self._request("GET", f"/agents/{self.agent_id}")

    def resolve_from_number_id(self) -> str:
        """CARTESIA_PHONE_NUMBER_ID, else the agent's own number id (Get Agent, then List Phone Numbers)."""
        if self.from_number_id:
            return self.from_number_id
        nums = (self.get_agent().get("phone_numbers")) or []
        if not nums:
            nums = (self._request("GET", f"/agents/phone-numbers?agent_id={self.agent_id}").get("data")) or []
        if not nums or not nums[0].get("id"):
            raise CartesiaError("the agent has no phone number (assign one in the Cartesia playground)")
        self.from_number_id = str(nums[0]["id"])
        return self.from_number_id

    def create_call(self, to_number: str, variables: Mapping[str, Any]) -> str:
        """Start ONE outbound call. Refuses any number but approval_call_to. Returns agent_call_id."""
        if to_number != self.approval_call_to:
            raise NumberNotAllowed(f"refusing to call {mask_number(str(to_number))}: only {TO_ENV} is allowed")
        # #449 item 1: the one choke point, before any HTTP request. Reserve (record) first, then send.
        if not on_allowlist(to_number, self.allowlist):
            raise CallLimited("beta_allowlist")
        if self._limiter is not None:
            self._limiter.reserve(to_number)
        body = {"from_number_id": self.resolve_from_number_id(), "agent_id": self.agent_id,
                "ringing_timeout_seconds": RINGING_TIMEOUT_S, "max_call_duration_minutes": MAX_CALL_MINUTES,
                "outbound_calls": [{"to_number": to_number, "dynamic_variables": dict(variables)}]}
        calls = self._request("POST", "/agents/calls", body).get("calls") or []
        if len(calls) != 1:
            raise CartesiaError("unexpected reply: expected one call entry")
        entry = calls[0]
        if "error" in entry or not entry.get("agent_call_id"):
            raise CartesiaError("call could not start: " + str(entry.get("error", "no agent_call_id"))[:160].replace(self._key, "***"))
        return str(entry["agent_call_id"])

    def get_call(self, call_id: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(call_id)):
            raise CartesiaError("bad call id")
        return self._request("GET", f"/agents/calls/{call_id}")


# ---------- the call ----------

def build_variables(script: CallScript, buyer_name: str) -> dict:
    """The only values sent to Cartesia. Amount and payee come from the mandate through script_for and the why
    answer from the advocate's closed-schema reason, so neither the code nor any seller text is in here."""
    if not isinstance(buyer_name, str) or not _NAME.fullmatch(buyer_name) or not is_clean_name(buyer_name):
        raise ScriptError("buyer_name must be a plain name")
    return {"buyer_name": buyer_name,
            "deal_script": f"{script.deal_line}. {script.opening}.",
            "why_answer": script.why_answer}


def assert_clean(variables: Mapping[str, Any], code: str) -> None:
    """Last line of defence: refuse to send a variable that contains the code (as a pair or in order)."""
    pair = normalize(code)
    for k, v in variables.items():
        if pair in normalize(str(v)):
            raise ScriptError(f"variable {k} would leak the approval code; refusing to call")


def place_call(client, variables: Mapping[str, Any], to: Optional[str] = None) -> str:
    """Place the approval call. `to` may only be the client's APPROVAL_CALL_TO (or omitted)."""
    target = client.approval_call_to
    if to is not None and to != target:
        raise NumberNotAllowed(f"refusing to call {mask_number(str(to))}: only {TO_ENV} is allowed")
    return client.create_call(target, variables)


def wait_for_end(client, call_id: str, *, max_wait: float = MAX_WAIT_S, poll: float = POLL_S,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> Optional[dict]:
    """Poll Get Call until status is completed or failed. Returns that call, or None on timeout (deny)."""
    deadline, errors = clock() + max_wait, 0
    while True:
        try:
            call = client.get_call(call_id)
            errors = 0
            if call.get("status") in TERMINAL:
                return call
        except CartesiaError:
            errors += 1
            if errors >= 4:
                return None
        if clock() >= deadline:
            return None
        sleep(poll)


def transcript(client, call_id: str, call: Optional[dict] = None, *, retries: int = TRANSCRIPT_RETRIES,
               retry_s: float = TRANSCRIPT_RETRY_S, sleep: Callable[[float], None] = time.sleep) -> tuple[list, dict]:
    """(entries, call). The transcript is a field of Get Call; an empty one right after the end is retried."""
    call = call if call is not None else client.get_call(call_id)
    for i in range(retries + 1):
        entries = call.get("transcript") or []
        if entries or call.get("zdr_enabled") or call.get("status") == "failed" or i == retries:
            return [e for e in entries if isinstance(e, dict)], call
        sleep(retry_s)
        try:
            call = client.get_call(call_id)
        except CartesiaError:
            pass
    return [], call  # pragma: no cover


def buyer_utterances(entries: list) -> list[tuple[float, str]]:
    """[(start_seconds, text)]: consecutive role "user" entries are one utterance; any other role ends it. Only
    the human who answered counts: the agent (role assistant) speaking a code word never does."""
    out: list[tuple[float, str]] = []
    cur: Optional[list] = None
    for e in entries:
        if e.get("role") == "user" and isinstance(e.get("text"), str) and e["text"].strip():
            if cur is None:
                cur = [_secs(e.get("start_timestamp")), []]
            cur[1].append(e["text"])
        elif e.get("role") != "user" and cur is not None:
            out.append((cur[0], " ".join(cur[1])))
            cur = None
    if cur is not None:
        out.append((cur[0], " ".join(cur[1])))
    return out


def _secs(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else 0.0


def _could_be_a_guess(text: str) -> bool:
    """False for "hello" or "why not the cheaper one": no code word and no "approve", so it cannot be an attempt
    and must not burn one of the three tries. Never makes anything pass; only skips counting."""
    tokens = set(normalize(text).split())
    return bool(tokens & WORD_SET) or bool(APPROVE_TOKENS & tokens)


def _parse_ts(s: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class VoiceResult:
    approved: bool
    reason: Optional[str]            # None when approved; else why it was denied
    call_id: Optional[str] = None
    end_reason: Optional[str] = None
    record: Optional[dict] = None    # the VoiceApproval row (code only as a hash)
    attempts: int = 0                # approval attempts that were judged
    trace: list = field(default_factory=list)   # outcomes only, never what was said

    @property
    def buyer_line(self) -> Optional[str]:
        """What the buyer is told when the call did not approve (screen and chat); None when it approved."""
        return None if self.approved else denial_line(self.reason)


# #185: approval is by phone call only, so every way a call can fail ends in one plain line that says nothing was paid.
_DENIAL_LINES = {
    "call_failed": "Call failed, nothing was paid.",
    "call_timeout": "The call timed out, nothing was paid.",
    "no_answer": "No answer on the call, nothing was paid.",
    "no_transcript": "Nobody spoke on the call, nothing was paid.",
    "no_buyer_speech": "Nobody spoke on the call, nothing was paid.",
    "silence": "Nobody spoke on the call, nothing was paid.",
    "expired": "The deal expired before it was approved, nothing was paid.",
    "not_configured": "The call could not be placed, nothing was paid.",
    "no_phone": "There is no phone number on file to approve this on, so no call was placed and nothing was paid.",
}
_NOT_APPROVED = ("wrong_code", "no_code", "max_attempts", "replay", "cooldown", "denied", "script_error")


def denial_line(reason: Optional[str]) -> str:
    """The buyer-facing line for a denied approval call. Never names the code or what was said."""
    key = str(reason or "").split(":", 1)[0].strip()
    if key in _DENIAL_LINES:
        return _DENIAL_LINES[key]
    if key in _NOT_APPROVED:
        return "Not approved on the call, nothing was paid."
    return "Not approved, nothing was paid."


def judge_call(session, call: Mapping[str, Any], placed_at: datetime) -> tuple[Optional[Decision], list, int]:
    """Feed every buyer utterance of an ended call to the session. Returns (last decision, trace, ignored count).
    Time is the call's own clock (start_time plus the entry offset), so the cooldown, code expiry and mandate
    expiry apply as they would have live. The 10 second listen window is not used: the call has ended."""
    start = _parse_ts(call.get("start_time")) or placed_at
    trace, last = [], None
    for offset, text in buyer_utterances(call.get("transcript") or []):
        if not _could_be_a_guess(text):
            trace.append({"at_s": round(offset, 1), "outcome": "ignored"})
            continue
        d = session.approve(text, start + timedelta(seconds=offset))   # no confidence: Get Call has none
        last = d
        trace.append({"at_s": round(offset, 1), "outcome": "approved" if d.approved else d.reason})
        if d.final:
            break
    return last, trace, sum(1 for t in trace if t["outcome"] == "ignored")


def run_approval_call(mandate: dict, advocate_reason: Any, client, service: ApprovalService, *,
                      deal: Any = None, buyer_name: str = DEFAULT_BUYER_NAME, on_code: Optional[Callable[[str], None]] = None,
                      max_wait: float = MAX_WAIT_S, poll: float = POLL_S,
                      sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                      now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> VoiceResult:
    """One approval call for one pending mandate. Approves only when ApprovalSession approves a buyer
    utterance. `on_code(code)` shows the code on the buyer's screen; it is the only place the code goes."""
    try:
        script = script_for(mandate, advocate_reason, deal)
        variables = build_variables(script, buyer_name)
        session, code = service.issue(mandate, channel="phone", now=now())
    except ScriptError:
        return VoiceResult(False, "script_error")
    except ApprovalError as e:
        return VoiceResult(False, e.reason)

    def no_voice_answer(reason: str, *, call_id: Optional[str] = None,
                        end_reason: Optional[str] = None, trace: Optional[list] = None) -> VoiceResult:
        current = now()
        decision = (session.approve("", now=current) if current >= session.expires_at
                    else session.silence(now=current))
        return VoiceResult(False, reason, call_id, end_reason,
                           decision.record, session.attempts, trace or [])

    try:
        assert_clean(variables, code)
        if on_code is not None:
            try:
                on_code(code)
            except Exception:
                session.silence(now=now())
                raise
        session.start_call(now=now())
        placed_at = now()
    except ScriptError as e:
        d = session.silence(now=now())
        return VoiceResult(False, "call_failed", record=d.record, trace=[{"outcome": type(e).__name__}])
    try:
        call_id = place_call(client, variables)
    except CartesiaError as e:
        return no_voice_answer("call_failed", trace=[{"outcome": type(e).__name__}])
    ended = wait_for_end(client, call_id, max_wait=max_wait, poll=poll, sleep=sleep, clock=clock)
    if ended is None:
        return no_voice_answer("call_timeout", call_id=call_id)
    end_reason = ended.get("end_reason")
    if ended.get("status") == "failed" or end_reason in ("voicemail_detected", "dial_no_answer", "dial_busy",
                                                         "dial_failed", "dial_timeout"):
        return no_voice_answer(f"no_answer:{end_reason or 'failed'}", call_id=call_id, end_reason=end_reason)
    try:
        entries, full = transcript(client, call_id, ended, sleep=sleep)
    except CartesiaError:
        entries, full = [], ended
    if not entries:
        return no_voice_answer("no_transcript", call_id=call_id, end_reason=end_reason)
    session.recording_ref = f"cartesia:{call_id}"
    last, trace, _ = judge_call(session, {**full, "transcript": entries}, placed_at)
    if last is not None and last.approved:
        return VoiceResult(True, None, call_id, end_reason, last.record, session.attempts, trace)
    if last is None:
        return no_voice_answer("no_buyer_speech", call_id=call_id, end_reason=end_reason, trace=trace)
    final = last if last.final else session.silence(now=now())
    return VoiceResult(False, last.reason, call_id, end_reason, final.record, session.attempts, trace)


# ---------- CLI ----------

def _demo_deal() -> dict:
    """Vidyut's mandate for the Best Buy deal, built exactly as demo/approval_flow.run_beat4 builds it."""
    from demo.common import Narrator
    from demo.run_demo import run_all
    from pay.mandate import new_mandate
    run = run_all({2}, say=Narrator(False))
    b1, b2 = run["beats"]["1"], run["beats"]["2"]
    bid, win = b2["winner_bid"], b2["winner"]
    seller = next(s for s in b2["sellers"] if s["id"] == win["seller_id"])
    amount, goal = float(win["landed"]), b1["goal"]
    mandate = new_mandate(deal_id=f"deal-{bid['id']}", buyer_id=goal["buyer_id"], amount=amount, payee=seller["payee"],
                          goal_id=goal["id"], within_allowance=False, origin=bid["origin"])
    reason = b2["veto_reason"] or {"rule_id": "advocate.ok", "summary": "No problems found in the checks",
                                   "source_url": bid["lines"][0]["listing_url"]}
    line = bid["lines"][0]
    facts = {"item": line.get("attrs", {}).get("chipset") or line["sku_spec"].upper(),
             "condition": win["condition"], "seller": seller["name"]}
    return {"mandate": mandate, "reason": reason, "seller": seller["name"], "amount": amount, "facts": facts}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Beat 4 over a real Cartesia phone call (calls only APPROVAL_CALL_TO)")
    ap.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="where the CARTESIA_* names are read from")
    ap.add_argument("--demo", action="store_true", help="place the real call for Vidyut's Best Buy mandate")
    ap.add_argument("--dry-run", action="store_true", help="print the variables that would be sent; no network, no call")
    ap.add_argument("--check", action="store_true", help="read-only: GET the agent and print the HTTP outcome")
    ap.add_argument("--buyer-name", default=None, help=f"default: {NAME_ENV} from the env file, else {DEFAULT_BUYER_NAME}")
    args = ap.parse_args(argv)
    env = load_env(args.env_file)
    args.buyer_name = args.buyer_name or env.get(NAME_ENV) or DEFAULT_BUYER_NAME
    if not (args.demo or args.dry_run or args.check):
        ap.error("pick --demo, --dry-run or --check")
    if args.check:
        try:
            agent = CartesiaClient.from_env(env).get_agent()
        except CartesiaError as e:
            print(f"check: FAILED ({e})")
            return 1
        nums = agent.get("phone_numbers") or []
        print(f"check: HTTP 200, agent found, {len(nums)} phone number(s), from_number_id "
              f"{'set in env' if env.get(FROM_ENV) else 'taken from the agent'}")
        return 0
    deal = _demo_deal()
    mandate = deal["mandate"]
    script = script_for(mandate, deal["reason"], deal["facts"])
    try:
        variables = build_variables(script, args.buyer_name)
    except ScriptError as e:
        print(f"STOPPED: {e}")
        return 2
    print(f"deal: {deal['seller']} {deal['amount']:.2f} USD, payee {mandate['payee']}, mandate {mandate['id']} (SIM buyer, MIRROR listing)")
    if args.dry_run:
        print("dry-run: no network, no call, no code issued. Variables that would be sent:")
        print(json.dumps(variables, indent=2))
        to = env.get(TO_ENV)
        print("call target: " + (mask_number(to) if to else f"({TO_ENV} not set)"))
        return 0
    try:
        client = CartesiaClient.from_env(env)
    except CartesiaError as e:
        print(f"STOPPED: {e}")
        return 2
    from pay.mandate import can_charge
    from pay.replay import NonceStore
    store = NonceStore()
    service = ApprovalService(secret=env.get(SECRET_ENV) or secrets.token_hex(16), store=store, code_ttl_seconds=CALL_CODE_TTL_S)
    chk = dict(deal_id=mandate["deal_id"], amount=mandate["amount"], payee=mandate["payee"], store=store)
    b = can_charge(mandate, **chk)
    print(f"can_charge before the call: {'PASS' if b else 'REFUSED'} ({b.reason})", flush=True)

    def show(code: str) -> None:
        print(f"SCREEN CODE: {code}   (stands in for the buyer screen; say it, then say approve)", flush=True)
        print(f"calling {mask_number(client.approval_call_to)} now ...", flush=True)

    res = run_approval_call(mandate, deal["reason"], client, service, deal=deal["facts"], buyer_name=args.buyer_name, on_code=show)
    print(f"result: {'APPROVED' if res.approved else 'DENIED'}" + ("" if res.approved else f" ({res.reason})"))
    print(f"call id: {res.call_id or 'none'}, end reason: {res.end_reason or 'n/a'}, judged attempts: {res.attempts}, "
          f"utterance outcomes: {[t['outcome'] for t in res.trace] or 'none'}")
    if res.record:
        print(f"VoiceApproval {res.record['id']}: result {res.record['result']}, attempts {res.record['attempts']}, "
              f"channel {res.record['channel']}, code stored only as a hash")
    a = can_charge(mandate, **chk)
    print(f"can_charge after the call: {'PASS' if a else 'REFUSED'} ({a.reason}); mandate status {mandate['status']}")
    return 0 if res.approved == bool(a) else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
