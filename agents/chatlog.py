"""Structured chat lines for the floor's ASI:One chat tile (Lane D, served by scripts/agent_feed.py GET /chat).

    AGENT_CHAT at=<ISO utc> who=<token> kind=message|thinking|done [name=<json>] text=<json>

status.py logs fixed labels only ("reply to owner"); this is the real chat line, one log line per message, so the feed can show what the
agents actually said. Stdlib only and no sibling imports, so agents (import chatlog), the Pulse module and the feed (loaded by path) share it.

Privacy: every text is cleaned here before it is written and again by the feed. Any run of 6+ digits (single spaces or dashes allowed
between digits, so a phone number or a code of digits), phone-shaped numbers, payment ids, API keys and bearer tokens become "••••", and so
does every approval code word registered with hide() (the code words issue_approval_code takes) and anything after "code is" or "code:".
Text is cut to MAX_TEXT characters, and json.dumps(ensure_ascii=True) keeps the record on one physical line, so remote text can neither
add a line nor forge a field. Callers log only text they may show: the owner's own words, the agents' own replies, Smell Test rule ids."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

MASK = "••••"
MAX_TEXT = 400
BLOCK_ATTACK_MAX = 80   # a Smell Test line never carries more than this much of the blocked text itself
KINDS = ("message", "thinking", "done")

_DIGIT_RUN = re.compile(r"\d(?:[ \-]?\d){5,}")   # the same rule as web/src/lib/chatFeed.ts maskDigits
_PHONE = re.compile(r"(?:\+\d{1,2}[\s.\-])?(?:\(\d{3}\)\s?|\d{3}[\s.\-])\d{3}[\s.\-]?\d{4}")
_PAYMENT_ID = re.compile(r"\b(?:pi|ch|cs|pm|cus|re|sub|in|seti|src|tok|card|ba|acct|evt|txn|pay)_[A-Za-z0-9_]{4,}")
_KEY = re.compile(r"\b(?:sk|pk|rk|whsec)_[A-Za-z0-9_]{6,}|eyJ[A-Za-z0-9_\-]{10,}|Bearer\s+\S+|AKIA[0-9A-Z]{12,}"
                  r"|\bsk-[A-Za-z0-9_\-]{8,}|\bgh[pousr]_[A-Za-z0-9]{10,}|xox[abp]-[A-Za-z0-9\-]{8,}"
                  r"|[A-Za-z0-9_]*(?:api[_-]?key|secret|token)\s*[=:]\s*\S+", re.I)   # the last one also catches ANTHROPIC_API_KEY=... and "token: ..."
# "the code is amber falcon", "approval code: amber falcon" -> the words after it go; up to three words, as issue_approval_code's code is a phrase
_CODE_PHRASE = re.compile(r"\b((?:pass|approval|one[- ]time|secret|verification)?[ -]?code\b\s*(?:is|are|was|:|=)\s*)"
                          r"(?!(?:required|needed|expired|invalid|wrong|not|sent|will|has|have|must|to|for|and|or|from|in|on)\b)"
                          r"([A-Za-z0-9]+(?:[ \-][A-Za-z0-9]+){0,2})", re.I)
_TOKEN = re.compile(r"[a-z][a-z0-9_]{0,23}")
_LINE = re.compile(r"^(?:\w+:\s+)?(?:\[[^\]]+\]:\s+)?AGENT_CHAT (.*)$")   # anchored to the line start or the logger prefix
_FIELD = re.compile(r'(at|who|kind)=(\S+)')

_HIDDEN: list[str] = []   # approval code words of this process (memory only, never written anywhere)
_HIDDEN_MAX = 64


def hide(secret: str | None) -> None:
    """Register an approval code (or any other secret string) so clean() masks it wherever it appears, whatever the words around it."""
    s = " ".join(re.split(r"[\s\-_]+", str(secret or "").strip()))   # "amber-falcon-river" and "amber falcon river" are one code
    if len(s) < 3 or s in _HIDDEN:
        return
    if len(_HIDDEN) >= _HIDDEN_MAX:
        del _HIDDEN[0]
    _HIDDEN.append(s)


def clean(text: object, limit: int = MAX_TEXT) -> str:
    """The text with every private shape masked, whitespace collapsed, cut to `limit` characters."""
    t = " ".join(str(text if text is not None else "").split())
    for s in sorted(_HIDDEN, key=len, reverse=True):
        t = re.sub(r"[\s\-_]+".join(re.escape(w) for w in re.split(r"[\s\-_]+", s) if w), MASK, t, flags=re.I)
    t = _CODE_PHRASE.sub(lambda m: m.group(1) + MASK, t)
    t = _KEY.sub(MASK, t)
    t = _PAYMENT_ID.sub(MASK, t)
    t = _PHONE.sub(MASK, t)
    t = _DIGIT_RUN.sub(MASK, t)
    return t if len(t) <= limit else t[: max(0, limit - 3)].rstrip() + "..."


def chat_line(who: str, kind: str, text: object, name: str | None = None, at: datetime | None = None) -> str:
    """One AGENT_CHAT record. `who` is a lowercase token (owner, buyer, advocate, shield, pulse, caller, seller_1 ...)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    w = str(who).strip().lower()
    if not _TOKEN.fullmatch(w):
        raise ValueError(f"who must be one short token, got {who!r}")
    stamp = (at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    label = f" name={json.dumps(clean(name, 40), ensure_ascii=True)}" if name else ""
    return f"AGENT_CHAT at={stamp} who={w} kind={kind}{label} text={json.dumps(clean(text), ensure_ascii=True)}"


def emit(logger, who: str, kind: str, text: object, name: str | None = None) -> None:
    """Log one chat line. Never raises: a chat line is a courtesy for the screen and must not break an agent. `logger` is a ctx.logger or
    a logging.Logger; None prints (the agent's stdout is its run log)."""
    try:
        line = chat_line(who, kind, text, name)
        if logger is None:
            print(line, flush=True)
        else:
            logger.info(line)
    except Exception:  # noqa: BLE001
        pass


def block_text(rule_ids: list, reasons: list) -> str:
    """The Smell Test line for a blocked message: the rule ids, then the first reason cut to BLOCK_ATTACK_MAX. Never the blocked text."""
    ids = ", ".join(str(r) for r in (rule_ids or [])[:4])
    why = clean(str((reasons or [""])[0]), BLOCK_ATTACK_MAX)
    return f"Smell Test blocked a message ({ids}): {why}" if ids else f"Smell Test blocked a message: {why}"


def parse_line(line: str) -> dict | None:
    """For the feed: {at, who, kind, name, text} of one AGENT_CHAT record at the start of a log line (or after the logger prefix), else None.
    The text is cleaned again here, so a log written before a masking rule existed still goes out masked."""
    m = _LINE.match(line.strip())
    if not m:
        return None
    rest = m.group(1)
    head, sep, tail = rest.partition(" text=")
    if not sep:
        return None
    name = None
    nm = re.search(r' name=(".*")$', head)
    if nm:
        head = head[: nm.start()]
        try:
            name = clean(json.loads(nm.group(1)), 40)
        except ValueError:
            name = None
    fields = dict(_FIELD.findall(head))
    who, kind = fields.get("who", ""), fields.get("kind", "message")
    if not _TOKEN.fullmatch(who):
        return None
    try:
        text = json.loads(tail)
    except ValueError:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    return {"at": fields.get("at", ""), "who": who, "kind": kind if kind in KINDS else "message", "name": name, "text": clean(text)}
