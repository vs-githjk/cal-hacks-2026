"""shield.payee.swap: a payee or payout address in the message that differs from the seller's agent of record.

Needs `context["payee_of_record"]`; with no record there is nothing to compare, so the rule stays silent
(the mandate check still binds the payee at payment time).
"""
import re

from shield.rules.base import QUARANTINE, Rule, rx

_VALUE = (r"(?P<v>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+|0x[0-9a-fA-F]{40}|https?://[^\s\"'<>]+|"
          r"(?:paypal\.me|venmo\.com/u|cash\.app/\$|revolut\.me|wise\.com/pay|ko-fi\.com|t\.me)/[\w.\-$]+|acct_[A-Za-z0-9]{6,})")
_GAP = r"(?:[\s:=\"'>]|<[^>]*>)*?"
PATTERNS = [
    rx(r"\b(?:pay(?:ment)?s?\s*(?:to|address)|payee|payout(?:\s+(?:to|address|account))?|remit(?:\s+to)?|"
       r"send\s+(?:the\s+)?(?:payment|money|funds)\s+to)\b" + _GAP + _VALUE),
    rx(r"[\"']payee[\"']\s*:\s*[\"']" + _VALUE),
    rx(r"[\"']payout[_a-z]*[\"']\s*:\s*[\"']" + _VALUE),
]


def check(doc, ctx):
    record = str((ctx or {}).get("payee_of_record") or "").strip().lower()
    if not record:
        return
    for p in PATTERNS:
        for m in p.finditer(doc.norm):
            if m.group("v").strip().rstrip(".,;)").lower() != record:
                yield doc.raw_span(m.start(), m.end())


RULE = Rule("shield.payee.swap", QUARANTINE, "critical",
            "payee or payout address differs from the seller agent of record", check)
