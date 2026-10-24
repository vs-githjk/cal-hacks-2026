"""shield.exfil.screen_code: a seller asking for the approval code shown on the buyer's screen (#196).

The code is the buyer's credential for one mandate, spoken only on the approval call. Nobody else ever needs it, so an
ask for it is an attack, not a mistake: block.
"""
from shield.rules.base import seller_side, BLOCK, Rule, finditer_spans, rx

_ASK = (r"(?:read|recite|tell|say|send|give|share|type|enter|repeat|spell|paste|text|dm|e-?mail|reply\s+with|respond\s+with"
        r"|what\s+(?:are|is|were|do|does)|what'?s|what'?re|show|forward|provide|confirm|post|drop|put|need|want)")
_GAP = r"[^.!?]{0,60}?"                     # one sentence: line breaks inside it do not end the ask
_DEVICE = r"(?:screen|display|device|phone|tablet|app|browser|monitor|laptop|computer)"
_THEIRS = r"(?:your|ur|the\s+buyer'?s?|their|his|her)"
_NOUN = r"(?:words?|codes?|digits|numbers?|letters|phrase|pair|pin)"
PATTERNS = [
    # the code's nouns near THE BUYER'S device, with or without a verb: "the two words on your screen please"
    rx(r"\b" + _NOUN + r"\b[^.!?]{0,40}?\b(?:on|from|in|of|shown\s+on|displayed\s+(?:on|in))\s+" + _THEIRS + r"\s+"
       r"(?:buyer\s+|owner\s+)?" + _DEVICE + r"\b"),
    # what the buyer's device says or shows: "tell me what your screen says", "the code your phone shows"
    rx(r"\b" + _THEIRS + r"\s+" + _DEVICE + r"\b[^.!?]{0,30}?\b(?:says|say|shows|showing|show|displays|displaying|reads|reading)\b"),
    rx(r"\bwhat(?:'?s|\s+is)\s+(?:on|in)\s+" + _THEIRS + r"\s+" + _DEVICE + r"\b"),
    # the code itself by name: "type the approval code", "read me the verification phrase", "tell me the magic words"
    rx(r"\b" + _ASK + r"\b" + _GAP + r"\b(?:approval|pairing|confirmation|verification|security|two[-\s]word|2[-\s]word"
       r"|one[-\s]time|magic|secret)\s+(?:codes?|words?|phrase|pair)\b"),
    rx(r"\b" + _ASK + r"\b" + _GAP + r"\bword\s+pair\b"),
    # "what are the 2 words", "tell me both words"
    rx(r"\b(?:what\s+are|what'?re|tell|read|recite|say|give|send|share)\b[^.!?]{0,20}?\b(?:the\s+)?(?:two|2|both)\s+words\b"
       r"(?!\s*:)"),
]


def check(doc, ctx):
    if seller_side(ctx):   # the buyer's own agent asks for the code on the approval call; a seller never may
        yield from finditer_spans(doc, PATTERNS)


RULE = Rule("shield.exfil.screen_code", BLOCK, "critical",
            "asks for the approval code shown on the buyer's screen", check, fold=True)
