"""shield.exfil.screen_code: a seller asking for the approval code shown on the buyer's screen (#196).

The code is the buyer's credential for one mandate, spoken only on the approval call. Nobody else ever needs it, so an
ask for it is an attack, not a mistake: block. Wording varies endlessly, so one sentence is judged on what it holds
together, not on word order: a code noun, the buyer's screen or the approval, and an ask. Codes a seller may honestly
mention (error, POST, boot, promo, tracking, serial, model) are taken out first.
"""
import re

from shield.rules.base import BLOCK, Rule, rx, seller_side

_HONEST_CODE = rx(r"\b(?:error|fault|post|boot|beep|bios|qr|bar|promo|promotional|coupon|discount|tracking|zip|postal|area|"
                  r"product|model|serial|part|sku|order|reference|confirmation\s+number|color|colour|source|access\s+point)\s+"
                  r"(?:codes?|numbers?|words?)\b")
_NOUN = rx(r"\b(?:words?|codes?|phrase|passphrase|pass\s+phrase|pair|digits|numbers|letters|pin)\b")
_DEVICE = r"(?:screen|display|device|phone|tablet|app|browser|monitor|laptop|computer)"
_THEIRS = r"(?:your|ur|the\s+buyer'?s?|the\s+owner'?s?|their|his|her)"
_WHERE = rx(r"\b" + _THEIRS + r"\s+(?:\w+\s+){0,2}?" + _DEVICE + r"\b|\bon\s+(?:the\s+)?(?:screen|display)\b"
            r"|\bpopped\s+up\b|\b(?:you|they)\s+(?:see|saw|got|received)\b|\byour\s+owner\s+(?:got|sees|saw|received)\b"
            r"|\bthe\s+(?:two|2|both)\s+(?:of\s+the\s+)?words\b|\bapproval\b|\bverification\b|\bpairing\b|\bone[-\s]time\b|\btwo[-\s]word\b|\b2[-\s]word\b|\bmagic\b|\bsecret\b")
_ASK = rx(r"\?|\bplease\b|\b(?:read|recite|tell|say|send|give|share|type|enter|repeat|spell|paste|text|dm|e-?mail|reply|respond"
          r"|what|which|show|forward|provide|confirm|post|drop|put|need|want|let\s+(?:me|us)\s+know|aloud|out)\b")
# "tell me what your screen says", "what does the buyer's screen read": relaying the screen's text, no noun needed
_RELAY = rx(r"\b(?:what|tell\s+me|read\s+me|read\s+out)\b[^.!?]{0,30}?\b" + _THEIRS + r"\s+" + _DEVICE +
            r"\b[^.!?]{0,15}?\b(?:says?|reads?|reading|shows?\s+(?:as\s+)?(?:the\s+)?(?:code|words?))\b"
            r"|\bwhat(?:'?s|\s+is)\s+(?:on|in)\s+" + _THEIRS + r"\s+" + _DEVICE + r"\b")
_SENTENCE = re.compile(r"[^.!?]+[.!?]*")


def check(doc, ctx):
    if not seller_side(ctx):   # the buyer's own agent asks for the code on the approval call; a seller never may
        return
    text = _HONEST_CODE.sub(lambda m: " " * len(m.group(0)), doc.norm)
    for m in _SENTENCE.finditer(text):
        s = m.group(0)
        if (_NOUN.search(s) and _WHERE.search(s) and _ASK.search(s)) or _RELAY.search(s):
            start = m.start() + len(s) - len(s.lstrip())
            yield doc.raw_span(start, m.end())


RULE = Rule("shield.exfil.screen_code", BLOCK, "critical",
            "asks for the approval code shown on the buyer's screen", check, fold=True)
