"""shield.exfil.buyer_private: a seller asking for the buyer's spending limit, budget or personal details (#196).

The cap and the allowance are sealed (sellers never see them) and the buyer's name, address and phone go only to the
merchant of record at checkout. A seller asking for them in a bid or a chat message is quarantined.
"""
from shield.rules.base import seller_side, QUARANTINE, Rule, finditer_spans, rx

_ASK = (r"(?:reply\s+with|respond\s+with|send|tell|give|share|provide|confirm|state|enter|type|include|post|dm|e-?mail"
        r"|let\s+(?:me|us)\s+know|what(?:'?s|\s+is|\s+are|\s+was)|disclose|reveal|list)")
# Not a bare "the": "confirm the approved budget with your owner" is the buyer's own line (test_rules CLEAN).
_OWNER = r"(?:(?:your|ur|yr|(?:the\s+)?buyer'?s?|(?:the\s+)?owner'?s?|your\s+owner'?s?|their)\s+)"
_PRIVATE = (r"(?:spending\s+(?:limit|cap)|spend(?:ing)?\s+limit|budget|allowance|price\s+(?:cap|ceiling|limit)|max(?:imum)?"
            r"(?:\s+(?:price|budget|spend|bid|offer))?|(?:spending\s+)?cap|ceiling|limit|(?:home|street|shipping|mailing)\s+address"
            r"|address|full\s+name|legal\s+name|name|date\s+of\s+birth|phone\s+number|mobile\s+number|email\s+address)")
PATTERNS = [
    rx(r"\b" + _ASK + r"\b[^.!?\n]{0,50}?" + _OWNER + r"(?:\w+\s+){0,2}?" + _PRIVATE + r"\b"),
    rx(r"\bhow\s+(?:much|high|far)\s+(?:can|will|would|could|do)\s+(?:you|the\s+buyer|your\s+owner|they)\s+"
       r"(?:spend|pay|afford|go)\b"),
    rx(r"\bhow\s+much\s+(?:has|have|did)\s+(?:the\s+buyer|your\s+owner|you|they)\s+(?:approve|approved|authori[sz]ed?|set)\b"),
    rx(r"\bwhat\s+(?:are|is)\s+(?:you|the\s+buyer|your\s+owner|they)\s+willing\s+to\s+(?:pay|spend)\b"),
    rx(r"\bhow\s+much\s+(?:the\s+buyer|your\s+owner|you|they)\s+(?:has|have|had|can|will|would|could)\s+"
       r"(?:approved?|authori[sz]ed?|set|spend|pay|afford)\b"),
    rx(r"\b(?:what'?s|what\s+is|tell\s+me)\s+the\s+max(?:imum)?\s+(?:you|they|the\s+buyer)\s+(?:can|will|would)\b"),
    rx(r"\b(?:what(?:'?s|\s+is)|state|tell\s+me|give\s+me|share|reveal)\s+the\s+(?:limit|cap|ceiling|max(?:imum)?|budget|allowance)\b"),
    rx(r"(?:^|[\s,;:])(?:budget|allowance|spending\s+limit|max(?:imum)?\s+budget)\s*\?"),
    rx(r"\b(?:full\s+name|home\s+address|phone\s+number|shipping\s+address)\b[^.!?\n]{0,40}?\bplease\b"),
]


def check(doc, ctx):
    if seller_side(ctx):   # the buyer's own agent asks for the code on the approval call; a seller never may
        yield from finditer_spans(doc, PATTERNS)


RULE = Rule("shield.exfil.buyer_private", QUARANTINE, "high",
            "asks for the buyer's sealed limit or personal details", check, fold=True)
