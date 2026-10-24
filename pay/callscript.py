"""The call script (d3): every spoken line is a code-filled template.

Amount and payee come ONLY from the mandate (never from speech and never from seller text). The amount is
read as words plus digits. "Why not the cheaper one?" is answered only from the advocate's closed-schema
reason (a dict with exactly rule_id, summary and source_url). Any other key is stripped, and any value that
does not pass a strict allowlist is dropped, so a seller string that leaked into a summary is never spoken.
The script never asks for, and never reads out, a card number.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

OPENING = "I will only ask for the code on your screen, never a card number"
ASK = "Please read me the two words on your screen, then say approve. Anything else cancels this deal"
SELLER_FALLBACK = "from the seller named on your screen"
CONDITIONS = {"new": "new", "open box": "open box", "open-box": "open box", "open_box": "open box",
              "refurbished": "refurbished", "used": "used"}
ADVOCATE_KEYS = ("rule_id", "summary", "source_url")

_RULE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_SUMMARY_RE = re.compile(r"[A-Za-z0-9 .,%'-]{1,160}")
_PAYEE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,79}")
_ITEM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .+/-]{0,59}")
_SELLER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .&'-]{0,39}")
_HOST_RE = re.compile(r"[a-z0-9][a-z0-9.-]{0,98}[a-z0-9]")
# Words a summary must not contain: they would steer the call, imitate the buyer or ask for secrets.
_SUMMARY_BLOCKED = frozenset({
    "approve", "approved", "approving", "approval", "code", "ignore", "instruction", "instructions",
    "system", "assistant", "prompt", "password", "cvv", "otp", "pin", "wire", "transfer", "user", "say",
    "pretend", "override", "pay", "paid", "payment", "payments", "payee", "send", "sent", "dollar",
    "dollars", "usd", "bucks", "cash", "refund",
})
# Item and seller text read aloud also must not steer the buyer (#197): "you already agreed to this", "official reseller".
_FACTS_BLOCKED = _SUMMARY_BLOCKED | frozenset({
    "you", "your", "yours", "agreed", "agree", "already", "official", "officially", "authorized", "authorised",
    "verified", "certified", "trusted", "guaranteed", "confirmed", "promised", "advocate", "shield", "bazaar", "buyer",
    "referee", "now", "urgent",
})


class ScriptError(ValueError):
    """The mandate cannot be read back safely (bad amount or payee). No call should be placed."""


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand"))


def number_to_words(n: int) -> str:
    """0 to 999,999,999,999 in plain words ("one thousand one hundred nineteen")."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 0 or n >= 10 ** 12:
        raise ScriptError("number out of range")
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " " + number_to_words(rest))
    for size, name in _SCALES:
        if n >= size:
            rest = n % size
            return number_to_words(n // size) + " " + name + ("" if rest == 0 else " " + number_to_words(rest))
    raise ScriptError("number out of range")  # unreachable


def _cents(amount: Any) -> int:
    """The amount in whole cents, or ScriptError when it is not a positive, finite, 2-decimal amount."""
    if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
        raise ScriptError("amount must be a number")
    if isinstance(amount, float) and not math.isfinite(amount):
        raise ScriptError("amount must be finite")
    try:
        d = Decimal(str(amount))
    except InvalidOperation as e:
        raise ScriptError("amount must be a number") from e
    if not d.is_finite() or d <= 0:
        raise ScriptError("amount must be positive")
    cents = d * 100
    if cents != cents.to_integral_value():
        raise ScriptError("amount must be a whole number of cents")
    return int(cents)


def amount_words(amount: Any) -> str:
    """"one thousand one hundred nineteen dollars" or "... dollars and fifty cents"."""
    cents = _cents(amount)
    dollars, c = divmod(cents, 100)
    unit = "dollar" if dollars == 1 else "dollars"
    out = f"{number_to_words(dollars)} {unit}"
    if c:
        out += f" and {number_to_words(c)} {'cent' if c == 1 else 'cents'}"
    return out


def amount_digits(amount: Any) -> str:
    """"1,119.00 dollars"."""
    cents = _cents(amount)
    return f"{cents // 100:,}.{cents % 100:02d} dollars"


def clean_payee(payee: Any) -> str:
    """The payee exactly as the mandate has it, or ScriptError when it is not a plain id."""
    if not isinstance(payee, str) or not _PAYEE_RE.fullmatch(payee):
        raise ScriptError("payee is not a plain merchant id; refusing to read it aloud")
    return payee


def clean_advocate_reason(reason: Any) -> tuple[dict[str, str], list[str]]:
    """Keep only the closed-schema fields that pass their allowlist. Returns (kept, dropped field names).
    `kept` has any of rule_id, summary and host (the source_url reduced to its host)."""
    kept: dict[str, str] = {}
    dropped: list[str] = []
    if not isinstance(reason, Mapping):
        return kept, ["reason"]
    dropped += [str(k) for k in reason if k not in ADVOCATE_KEYS]
    rid = reason.get("rule_id")
    if isinstance(rid, str) and _RULE_ID_RE.fullmatch(rid):
        kept["rule_id"] = rid
    elif "rule_id" in reason:
        dropped.append("rule_id")
    summ = reason.get("summary")
    if isinstance(summ, str) and _SUMMARY_RE.fullmatch(summ.strip()) and summ.strip():
        words = set(re.findall(r"[a-z]+", summ.lower()))
        if words & _SUMMARY_BLOCKED:
            dropped.append("summary")
        else:
            kept["summary"] = " ".join(summ.split()).rstrip(".")
    elif "summary" in reason:
        dropped.append("summary")
    url = reason.get("source_url")
    host = _host(url) if isinstance(url, str) else None
    if host:
        kept["host"] = host
    elif "source_url" in reason:
        dropped.append("source_url")
    return kept, dropped


def _speakable_host(host: str) -> bool:
    """A raw IP or a local test page means nothing read aloud; the link stays on the screen."""
    return not (host == "localhost" or host.endswith(".localhost") or re.fullmatch(r"[0-9.]+", host))


def _host(url: str) -> Optional[str]:
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not _HOST_RE.fullmatch(host) or ".." in host:
        return None
    return host[4:] if host.startswith("www.") else host


def _plain(value: Any, pattern: "re.Pattern[str]", blocked: frozenset = _SUMMARY_BLOCKED) -> Optional[str]:
    """The value when it is a short plain string that passes `pattern` and holds no steering word, else None."""
    if not isinstance(value, str):
        return None
    v = " ".join(value.split())
    if not pattern.fullmatch(v) or set(re.findall(r"[a-z]+", v.lower())) & blocked:
        return None
    return v


PRICE_LINES = {
    "live": "The price was checked live just now",
    "mirror": "The price is from a dated listing snapshot",
}


def clean_deal_facts(deal: Any) -> tuple[dict[str, str], list[str]]:
    """Context read aloud beside the amount: item, condition and the seller's NAME (never the payee id, which
    stays bound in the mandate). `deal` is {item, condition, seller} from our own market record of the winning
    bid. Each value must pass a strict allowlist; anything else is dropped and the script falls back to a
    fixed phrase. Returns (kept, dropped field names)."""
    kept: dict[str, str] = {}
    dropped: list[str] = []
    if deal is None:
        return kept, dropped
    if not isinstance(deal, Mapping):
        return kept, ["deal"]
    dropped += [str(k) for k in deal if k not in ("item", "condition", "seller", "price")]
    for key, pattern in (("item", _ITEM_RE), ("seller", _SELLER_RE)):
        if key in deal:
            v = _plain(deal[key], pattern, _FACTS_BLOCKED)
            if v is None:
                dropped.append(key)
            else:
                kept[key] = v
    if "price" in deal:   # our own Bright Data re-check (#269), a fixed phrase per value
        line = PRICE_LINES.get(deal["price"]) if isinstance(deal["price"], str) else None
        if line is None:
            dropped.append("price")
        else:
            kept["price"] = line
    if "condition" in deal:
        c = CONDITIONS.get(str(deal["condition"]).strip().lower()) if isinstance(deal["condition"], str) else None
        if c is None:
            dropped.append("condition")
        else:
            kept["condition"] = c
    return kept, dropped


@dataclass(frozen=True)
class CallScript:
    opening: str
    deal_line: str
    ask_line: str
    why_answer: str
    approved_line: str
    denied_line: str
    amount_read_back: Any
    payee_read_back: str
    stripped: tuple[str, ...] = field(default=())

    def spoken(self) -> str:
        """What the agent says before it listens: the deal first, then the no-card promise, then the ask."""
        return ". ".join((self.deal_line, self.opening, self.ask_line)) + "."

    def full_text(self) -> str:
        """Every line the script can say, for audits and tests."""
        return "\n".join((self.deal_line, self.opening, self.ask_line, self.why_answer,
                          self.approved_line, self.denied_line))


def script_for(mandate: Mapping[str, Any], advocate_reason: Any = None, deal: Any = None) -> CallScript:
    """Build the call script for one mandate. Raises ScriptError when the amount or payee cannot be read back
    safely. `advocate_reason` is the advocate's closed-schema dict; anything outside it is stripped. `deal` is
    optional {item, condition, seller name} for a natural read-back (see clean_deal_facts); the amount is read
    once, in words, from the mandate, and the payee id is validated but never spoken."""
    amount = mandate.get("amount")
    payee = clean_payee(mandate.get("payee"))
    words, digits = amount_words(amount), amount_digits(amount)
    facts, deal_dropped = clean_deal_facts(deal)
    deal_line = (f"One {facts['item']}" if "item" in facts else "One purchase")
    if "condition" in facts:
        deal_line += f", {facts['condition']}"
    deal_line += f", from {facts['seller']}" if "seller" in facts else f", {SELLER_FALLBACK}"
    deal_line += f", for {words}"
    if "price" in facts:
        deal_line += f". {facts['price']}"
    kept, dropped = clean_advocate_reason(advocate_reason)
    parts = []
    if "rule_id" in kept or "summary" in kept:
        parts.append("The advocate rejected the cheaper offer")
    else:
        parts.append("The advocate has no recorded reason for that")
    if "summary" in kept:
        parts.append(kept["summary"])
    if "host" in kept and _speakable_host(kept["host"]):
        parts.append(f"The source is {kept['host']}, and the link is on your screen")
    elif "host" in kept:
        parts.append("The source link is on your screen")
    else:
        parts.append("The source link is on your screen")
    why = ". ".join(parts) + ". Nothing is paid until you say the code and approve"
    return CallScript(
        opening=OPENING,
        deal_line=deal_line,
        ask_line=ASK,
        why_answer=why,
        approved_line=f"Approved. One payment of {words}, written {digits}, to {payee}. Nothing else is authorized",
        denied_line="Not approved. Nothing was paid",
        amount_read_back=amount,
        payee_read_back=payee,
        stripped=tuple(dropped + deal_dropped),
    )
