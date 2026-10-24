"""shield.exfil.screen_code: a seller asking for the approval code shown on the buyer's screen (#196).

The code is the buyer's credential for one mandate, spoken only on the approval call. Nobody else ever needs it, so an
ask for it is an attack, not a mistake: block.
"""
from shield.rules.base import seller_side, BLOCK, Rule, finditer_spans, rx

_ASK = (r"(?:read|tell|say|send|give|share|type|enter|repeat|spell|paste|text|dm|e-?mail|reply\s+with|respond\s+with"
        r"|what\s+(?:are|is|were)|what'?s|show|forward|provide|confirm|post|drop|put)")
_GAP = r"[^.!?\n]{0,60}?"
PATTERNS = [
    # "read me the two words on your screen", "what are the 2 words shown on your screen", "the code in your app"
    rx(r"\b" + _ASK + r"\b" + _GAP + r"\b(?:words?|codes?|digits|numbers?|letters|phrase|pair|pin)\b"
       r"[^.!?\n]{0,30}?\b(?:on|from|in|shown\s+on|displayed\s+(?:on|in))\s+(?:your|the|their|his|her|my)\s+"
       r"(?:buyer\s+|owner\s+)?(?:screen|display|phone|app|browser|monitor|card\s+on\s+screen)\b"),
    # "type the approval code", "reply with the pairing code", "say the two-word code", "send the word pair"
    rx(r"\b" + _ASK + r"\b" + _GAP + r"\b(?:approval|pairing|confirmation|two[-\s]word|2[-\s]word|one[-\s]time)\s+(?:code|words?|phrase)\b"),
    rx(r"\b" + _ASK + r"\b" + _GAP + r"\bword\s+pair\b"),
]


def check(doc, ctx):
    if seller_side(ctx):   # the buyer's own agent asks for the code on the approval call; a seller never may
        yield from finditer_spans(doc, PATTERNS)


RULE = Rule("shield.exfil.screen_code", BLOCK, "critical",
            "asks for the approval code shown on the buyer's screen", check, fold=True)
