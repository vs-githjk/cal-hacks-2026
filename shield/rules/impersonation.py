"""shield.impersonation: a sender claiming to be the buyer, the advocate or Tech Bazaar itself."""
from shield.rules.base import BLOCK, QUARANTINE, Rule, rx

_ROLES = {
    "marketplace": r"(?:tech\s*bazaar|bazaar\s*shield|the\s+marketplace\s+(?:admin|operator|support)|marketplace\s+(?:admin|operator|support)|shield)",
    "advocate": r"(?:the\s+|your\s+)?advocate",
    "buyer": r"(?:the\s+buyer'?s?\s+agent|the\s+buyer|your\s+buyer|your\s+owner|your\s+agent|the\s+owner)",
}
_LEAD = r"\b(?:this\s+is|i\s+am|i'?m|we\s+are|message\s+from|official(?:ly)?|speaking\s+as|on\s+behalf\s+of)\s+(?:the\s+)?(?:official\s+)?"
PATTERNS = {role: rx(_LEAD + body + r"\b") for role, body in _ROLES.items()}
# Text dressed as another party's verdict, with no "this is" lead (#196): "Advocate summary: ... recommend buy",
# "[Advocate] recommend buy", "Bazaar Shield: allow", "Referee says this bid won". A verdict word is required, so
# "customer advocate says our returns are easy" or "the EMI shield" stay allowed. A bare "shield" is never ours.
_VERDICT = r"(?:recommend\w*|buy|approv\w*|allow\w*|passed|verified|cleared|veto\w*|winner|won|safe|trusted)"
OUTPUT = {
    "advocate": rx(r"\b(?:the\s+|your\s+)?advocate(?:'s)?\b[^.!?\n]{0,40}?\b" + _VERDICT + r"\b"),
    "marketplace": rx(r"\b(?:referee|tech\s*bazaar|bazaar\s*shield)(?:'s)?\b[^.!?\n]{0,40}?\b" + _VERDICT + r"\b"),
}

def check(doc, ctx):
    sender_role = str((ctx or {}).get("sender_role") or "seller").lower()
    for role, p in PATTERNS.items():
        if role == sender_role:
            continue  # a buyer agent may say it is the buyer agent
        for m in p.finditer(doc.norm):
            yield doc.raw_span(m.start(), m.end())


RULE = Rule("shield.impersonation", BLOCK, "high",
            "sender claims a role it does not hold (buyer, advocate, Tech Bazaar)", check, fold=True)


def check_output(doc, ctx):
    sender_role = str((ctx or {}).get("sender_role") or "seller").strip().lower()
    for role, p in OUTPUT.items():
        if role == sender_role:
            continue  # the advocate may write its own verdict
        for m in p.finditer(doc.norm):
            yield doc.raw_span(m.start(), m.end())


OUTPUT_RULE = Rule("shield.impersonation.output", QUARANTINE, "high",
                   "text dressed as the advocate's, referee's or Tech Bazaar's own verdict", check_output, fold=True)
