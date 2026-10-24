"""shield.exfil.buyer_private: a seller asking for the buyer's spending limit, budget or personal details (#196).

The cap and the allowance are sealed (sellers never see them) and the buyer's name, address and phone go only to the
merchant of record at checkout. A seller asking for them in a bid or a chat message is quarantined.
"""
from shield.rules.base import seller_side, QUARANTINE, Rule, finditer_spans, rx

_ASK = (r"(?:reply\s+with|respond\s+with|send|tell|give|share|provide|confirm|state|enter|type|include|post|dm|e-?mail"
        r"|let\s+(?:me|us)\s+know|what(?:'?s|\s+is|\s+are|\s+was)|disclose|reveal|list)")
_OWNER = r"(?:(?:your|ur|the\s+buyer'?s?|the\s+owner'?s?|your\s+owner'?s?|their)\s+)"   # not a bare "the": "confirm the approved budget with your owner" is the buyer's own line
_PRIVATE = (r"(?:spending\s+(?:limit|cap)|spend(?:ing)?\s+limit|budget|allowance|price\s+(?:cap|ceiling|limit)|max(?:imum)?\s+"
            r"(?:price|budget|spend|bid|offer)|(?:spending\s+)?cap|ceiling|limit|home\s+address|street\s+address|"
            r"full\s+name|legal\s+name|date\s+of\s+birth|phone\s+number|mobile\s+number|email\s+address)")
PATTERNS = [
    rx(r"\b" + _ASK + r"\b[^.!?\n]{0,50}?" + _OWNER + r"(?:\w+\s+){0,2}?" + _PRIVATE + r"\b"),
    rx(r"\bhow\s+much\s+(?:can|will|would|could|do)\s+(?:you|the\s+buyer|your\s+owner|they)\s+(?:spend|pay|afford|go\s+up\s+to)\b"),
]


def check(doc, ctx):
    if seller_side(ctx):   # the buyer's own agent asks for the code on the approval call; a seller never may
        yield from finditer_spans(doc, PATTERNS)


RULE = Rule("shield.exfil.buyer_private", QUARANTINE, "high",
            "asks for the buyer's sealed limit or personal details", check, fold=True)
