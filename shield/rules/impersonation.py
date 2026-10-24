"""shield.impersonation: a sender claiming to be the buyer, the advocate or Tech Bazaar itself."""
from shield.rules.base import BLOCK, Rule, rx

_ROLES = {
    "marketplace": r"(?:tech\s*bazaar|bazaar\s*shield|the\s+marketplace\s+(?:admin|operator|support)|marketplace\s+(?:admin|operator|support)|shield)",
    "advocate": r"(?:the\s+|your\s+)?advocate",
    "buyer": r"(?:the\s+buyer'?s?\s+agent|the\s+buyer|your\s+buyer|your\s+owner|your\s+agent|the\s+owner)",
}
_LEAD = r"\b(?:this\s+is|i\s+am|i'?m|we\s+are|message\s+from|official(?:ly)?|speaking\s+as|on\s+behalf\s+of)\s+(?:the\s+)?(?:official\s+)?"
PATTERNS = {role: rx(_LEAD + body + r"\b") for role, body in _ROLES.items()}
# Text dressed as another party's own output, with no "this is" lead (#196): "Advocate summary: ... recommend buy",
# "Referee note:", "Shield verdict: allow", "The advocate recommends this offer".
_OUTPUT = r"(?:\s+|\s*[:-]\s*)(?:summary|verdict|report|note|check|recommendation|decision|result|says|approved|approves)\b"   # a real gap: not "ShieldVerdict"
HEADERS = {
    "advocate": rx(r"\b(?:the\s+|your\s+)?advocate(?:'s)?" + _OUTPUT + r"|\b(?:the\s+)?advocate\s+recommends\b"),
    "marketplace": rx(r"\b(?:referee|tech\s*bazaar|bazaar\s*shield|shield)(?:'s)?" + _OUTPUT + r"|\breferee\s+recommends\b"),
}


def check(doc, ctx):
    sender_role = str((ctx or {}).get("sender_role") or "seller").lower()
    for role, p in PATTERNS.items():
        if role == sender_role:
            continue  # a buyer agent may say it is the buyer agent
        for m in p.finditer(doc.norm):
            yield doc.raw_span(m.start(), m.end())
    for role, p in HEADERS.items():
        if role == sender_role:
            continue  # the advocate may head its own summary
        for m in p.finditer(doc.norm):
            yield doc.raw_span(m.start(), m.end())


RULE = Rule("shield.impersonation", BLOCK, "high",
            "sender claims a role it does not hold (buyer, advocate, Tech Bazaar)", check, fold=True)
