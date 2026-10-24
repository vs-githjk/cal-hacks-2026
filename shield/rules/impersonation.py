"""shield.impersonation: a sender claiming to be the buyer, the advocate or Tech Bazaar itself."""
from shield.rules.base import BLOCK, Rule, rx

_ROLES = {
    "marketplace": r"(?:tech\s*bazaar|bazaar\s*shield|the\s+marketplace\s+(?:admin|operator|support)|marketplace\s+(?:admin|operator|support)|shield)",
    "advocate": r"(?:the\s+|your\s+)?advocate",
    "referee": r"(?:the\s+)?(?:tech\s*bazaar\s+)?(?:referee|arbiter|moderator|auditor)(?:\s+team)?",
    "buyer": r"(?:the\s+buyer'?s?\s+agent|the\s+buyer|your\s+buyer|your\s+owner|your\s+agent|the\s+owner)",
}
_LEAD = r"\b(?:this\s+is|i\s+am|i'?m|we\s+are|message\s+from|official(?:ly)?|speaking\s+as|on\s+behalf\s+of)\s+(?:the\s+)?(?:official\s+)?"
PATTERNS = {role: rx(_LEAD + body + r"\b") for role, body in _ROLES.items()}


def check(doc, ctx):
    sender_role = str((ctx or {}).get("sender_role") or "seller").lower()
    for role, p in PATTERNS.items():
        if role == sender_role:
            continue  # a buyer agent may say it is the buyer agent
        for m in p.finditer(doc.norm):
            yield doc.raw_span(m.start(), m.end())


RULE = Rule("shield.impersonation", BLOCK, "high",
            "sender claims a role it does not hold (buyer, advocate, Tech Bazaar)", check, fold=True)
