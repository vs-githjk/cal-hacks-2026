"""shield.exfil.buyer_private: a seller asking for the buyer's spending limit, budget or personal details (#196).

The cap and the allowance are sealed (sellers never see them) and the buyer's name, address and phone go only to the
merchant of record at checkout. A seller asking for them in a bid or a chat message is quarantined.
"""
from shield.rules.base import seller_side, QUARANTINE, Rule, finditer_spans, rx

_ASK = (r"(?:reply\s+with|respond\s+with|send|tell|give|share|provide|confirm|state|enter|type|include|post|dm|e-?mail"
        r"|let\s+(?:me|us)\s+know|what(?:'?s|\s+is|\s+are|\s+was)|disclose|reveal|list)")
# Not a bare "the": "confirm the approved budget with your owner" is the buyer's own line (test_rules CLEAN).
_OWNER = r"(?:(?:your|ur|yr|(?:the\s+)?buyer'?s?|(?:the\s+)?owner'?s?|your\s+owner'?s?|their)\s+)"
# A fit question uses the same words: "your max GPU length", "your PSU wattage limit" (#273). The fit reading is used only
# when it is safe (see check): no money word anywhere in the message, and every fit phrase ends in a unit or the end of
# the sentence. Otherwise the rule reads every max and limit as the buyer's spending limit, exactly as before #273.
# "size", "power", "draw" and "capacity" also mean money ("your max size", "your buying power limit"), so they count
# only right after a part noun ("your max GPU size").
_PART = r"(?:gpu|card|cooler|radiator|rad|psu|case|ram|memory|cpu|fan|tower)"
_FIT = r"(?:length|height|clearance|width|depth|thickness|wattage|tdp|watts?|mm|temps?|temperature)"
_MAX_FIT = (r"(?!\s+(?:" + _PART + r"\s+)?" + _FIT + r"\b|\s+" + _PART + r"\s+(?:size|power|draw|capacity)\b)")
_LIMIT = r"(?<!length\s)(?<!height\s)(?<!clearance\s)(?<!width\s)(?<!depth\s)(?<!wattage\s)(?<!tdp\s)(?<!thermal\s)limit"
_MONEY = rx(r"[$\u20ac\u00a3\u00a5\u20b9]|\b(?:dollars?|usd|eur|euros?|pounds?|gbp|rupees?|rupiah|yen|yuan|pesos?|kr|cents?|bucks|grand"
            r"|quid|dough|bread|gold|cash|money|funds?|funding|currency|wallet|pockets?|stretch|spend\w*|pay\w*|budget\w*|price\w*"
            r"|cost\w*|afford\w*|amount|deal|offer|bid|\d+\s?k)\b|\bhow\s+much\b")
# a fit phrase, and what may follow it for the fit reading: a unit, then the end of the sentence or line
_FIT_PHRASE = rx(r"\bmax(?:imum)?\s+(?:" + _PART + r"\s+)?" + _FIT + r"\b|\bmax(?:imum)?\s+" + _PART + r"\s+(?:size|power|draw|capacity)\b"
                 r"|\b(?:length|height|clearance|width|depth|wattage|tdp|thermal)\s+limit\b")
_FIT_TAIL = rx(r"[ \t]{0,3}(?:(?:in[ \t]+)?(?:mm|cm|millimet\w*|inch(?:es)?|in|\"|w|watts?|c|\u00b0c|slots?))?[ \t]{0,3}(?:[?.!,;\n]|$)")
_PRIVATE_BASE = (r"(?:spending\s+(?:limit|cap)|spend(?:ing)?\s+limit|budget|allowance|price\s+(?:cap|ceiling|limit)|max(?:imum)?"
                 r"%s|(?:spending\s+)?cap|ceiling|%s|(?:home|street|shipping|mailing)\s+address"
                 r"|address|full\s+name|legal\s+name|name|date\s+of\s+birth|phone\s+number|mobile\s+number|email\s+address)")
_MAX_WORDS = r"\s+(?:price|budget|spend|bid|offer)"
_PRIVATE = _PRIVATE_BASE % ("(?:" + _MAX_WORDS + "|" + _MAX_FIT + ")", _LIMIT)   # the fit reading
_PRIVATE_STRICT = _PRIVATE_BASE % ("(?:" + _MAX_WORDS + ")?", "limit")         # every max and limit is the spending limit
_ASK_PRIVATE = r"\b" + _ASK + r"\b[^.!?\n]{0,50}?" + _OWNER + r"(?:\w+\s+){0,2}?"
STRICT = rx(_ASK_PRIVATE + _PRIVATE_STRICT + r"\b")
PATTERNS = [
    rx(_ASK_PRIVATE + _PRIVATE + r"\b"),
    rx(r"\bhow\s+(?:much|high|far)\s+(?:can|will|would|could|do)\s+(?:you|the\s+buyer|your\s+owner|they)\s+"
       r"(?:spend|pay|afford|go)\b"),
    rx(r"\bhow\s+much\s+(?:has|have|did)\s+(?:the\s+buyer|your\s+owner|you|they)\s+(?:approve|approved|authori[sz]ed?|set)\b"),
    rx(r"\bwhat\s+(?:are|is)\s+(?:you|the\s+buyer|your\s+owner|they)\s+willing\s+to\s+(?:pay|spend)\b"),
    rx(r"\bhow\s+much\s+(?:the\s+buyer|your\s+owner|you|they)\s+(?:has|have|had|can|will|would|could)\s+"
       r"(?:approved?|authori[sz]ed?|set|spend|pay|afford)\b"),
    rx(r"\b(?:what'?s|what\s+is|tell\s+me)\s+the\s+max(?:imum)?\s+(?:you|they|the\s+buyer)\s+(?:can|will|would)\b"),
    rx(r"\b(?:what(?:'?s|\s+is)|state|tell\s+me|give\s+me|share|reveal)\s+the\s+(?:limit|cap|ceiling|max(?:imum)?|budget|allowance)\b"),
    rx(r"(?:^|[\s,;:])(?:budget|allowance|spending\s+limit|max(?:imum)?\s+budget)\s*\?"),
    rx(r"\bhow\s+much\s+(?:do|would|did|will)\s+(?:you|they|the\s+buyer|your\s+owner)\s+(?:want|plan|intend|hope|wish|like)\s+to\s+"
       r"(?:spend|pay)\b"
       r"|\bhow\s+much\s+(?:are|is)\s+(?:you|they|the\s+buyer|your\s+owner)\s+(?:looking|hoping|planning|willing|able)\s+to\s+(?:spend|pay)\b"
       r"|\bwhat(?:'?s|\s+is)\s+" + _OWNER + r"(?:price\s+range|target\s+price|price\s+point)\b"),
    rx(r"\b(?:full\s+name|home\s+address|phone\s+number|shipping\s+address)\b[^.!?\n]{0,40}?\bplease\b"),
]


def _fit_reading_is_safe(text: str) -> bool:
    """True when no money word is anywhere in the message and every fit phrase ends in a unit and the end of the sentence
    ("your max GPU length?", "your PSU wattage limit in W."). "your max length in dollars", "your max length of wallet"
    and a money line further down all fall back to the strict reading (#273)."""
    if _MONEY.search(text):
        return False
    return all(_FIT_TAIL.match(text, m.end()) for m in _FIT_PHRASE.finditer(text))


def check(doc, ctx):
    if seller_side(ctx):   # the buyer's own agent asks for the code on the approval call; a seller never may
        yield from finditer_spans(doc, PATTERNS)
        if not _fit_reading_is_safe(doc.norm):
            yield from finditer_spans(doc, [STRICT])


RULE = Rule("shield.exfil.buyer_private", QUARANTINE, "high",
            "asks for the buyer's sealed limit or personal details", check, fold=True)
