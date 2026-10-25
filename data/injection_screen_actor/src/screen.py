"""screen_text(text): a thin wrapper over Bazaar Shield's rules (shield.core.screen, owned by Lane D, unchanged).

The Shield classifier stays OFF here: screen() is always called with classifier=None, so no code path builds the
Claude classifier, reads ANTHROPIC_API_KEY or opens a network connection, whatever SHIELD_CLASSIFIER says.

Shield's verdicts map one to one: block -> "block", quarantine -> "flag" (Shield holds the text for a person to
read), allow -> "pass" (no rule fired; not proof the text is harmless). Excerpts are the caller's own text, cut to
80 characters by Shield, with long digit runs and key-shaped tokens hidden so no card, account number or key is
echoed back.
"""
from __future__ import annotations

import re

from shield import VERSION
from shield.classifier import UNAVAILABLE_RULE
from shield.core import ERROR_RULE, MAX_CHARS, screen
from shield.rules import RULES_BY_ID

VERDICTS = {"block": "block", "quarantine": "flag", "allow": "pass"}
SCREENER = f"{VERSION} rules only (classifier off)"
CONTEXT = {"sender_role": "seller"}  # listing text is seller text: Shield's seller-side checks apply

_REASONS = {
    UNAVAILABLE_RULE: ("A sentence names a secret (such as a password, PIN, card number or code). The rules cannot tell "
                       "a description from a request for it, and the classifier that would decide is off in this "
                       "Actor, so a person should read it."),
    ERROR_RULE: "Shield hit an internal error and failed closed (block). The text was not screened and is not charged.",
}
OVERSIZE_REASON = f"Longer than {MAX_CHARS:,} characters: Shield holds it without reading it. Not screened, not charged."

_DIGITS = re.compile(r"\d(?:[ .-]?\d){7,}")  # card, account, routing and phone numbers
_TOKEN = re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abpr]|AKIA)[-_]?[A-Za-z0-9_-]{8,}|[A-Za-z0-9+/_-]{32,}={0,2}")


def redact(text: str) -> str:
    """Hide anything that could be a secret: runs of 8 or more digits and key-shaped tokens."""
    return _TOKEN.sub("[hidden]", _DIGITS.sub("[number hidden]", text))


def reason(rule_id: str) -> str:
    if rule_id in _REASONS:
        return _REASONS[rule_id]
    rule = RULES_BY_ID.get(rule_id)
    return rule.describe[:1].upper() + rule.describe[1:] if rule else rule_id


def screen_text(text: str) -> dict:
    """Screen one text with Shield's rules. Returns verdict (block | flag | pass), shield_verdict (Shield's own word),
    severity, rule_ids, spans [{rule_id, start, end, excerpt}] in `text`, reasons {rule_id: reason} and screened (False
    when Shield did not read the text: too long, or an internal error; those are never charged)."""
    v = screen(text, CONTEXT, classifier=None)
    spans = [{"rule_id": s["rule_id"], "start": s["start"], "end": s["end"], "excerpt": redact(s["text"])}
             for s in v["evidence_spans"]]
    oversize = isinstance(text, str) and len(text) > MAX_CHARS
    reasons = {r: (OVERSIZE_REASON if oversize else reason(r)) for r in v["rule_ids"]}
    return {"verdict": VERDICTS.get(v["verdict"], "block"), "shield_verdict": v["verdict"], "severity": v["severity"],
            "rule_ids": list(v["rule_ids"]), "spans": spans, "reasons": reasons,
            "screened": not oversize and ERROR_RULE not in v["rule_ids"], "screener": SCREENER}
