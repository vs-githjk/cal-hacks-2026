"""shield.money.approval: seller text that tells the buyer side to approve, skip a check or charge."""
from shield.rules.base import BLOCK, Rule, finditer_spans, rx

PATTERNS = [
    rx(r"\balready\s+(?:been\s+)?(?:approved|verified|authori[sz]ed|confirmed)\b"),
    rx(r"\bpre-?(?:approved|verified|authori[sz]ed)\b"),
    rx(r"\b(?:skip|bypass|waive|omit)\s+(?:the\s+|your\s+)?(?:advocate|call|phone|approval|verification|veto|checks?|confirmation|buyer)\b"),
    rx(r"\bwithout\s+(?:calling|asking|notifying|confirming\s+with|contacting|checking\s+with)\s+(?:the\s+|your\s+)?(?:buyer|owner|human|user)\b"),
    rx(r"\b(?:do\s+not|don'?t|never)\s+(?:call|ask|notify|contact|bother)\s+(?:the\s+|your\s+)?(?:buyer|owner|human|user)\b"),
    rx(r"\bcharge\s+(?:now|immediately|the\s+card|it\s+now|right\s+away)\b"),
    rx(r"\bauto-?approve\b"),
    rx(r"\bapprove\s+(?:this|the)\s+(?:deal|bid|payment|order|purchase)\s+(?:now|immediately|automatically|quietly)\b"),
    rx(r"\bmark\s+(?:every|all|each)\s+claims?\s+(?:as\s+)?verified\b"),
    rx(r"\brelease\s+(?:the\s+)?(?:payment|funds)\s+(?:now|immediately)\b"),
]


def check(doc, ctx):
    return finditer_spans(doc, PATTERNS)


RULE = Rule("shield.money.approval", BLOCK, "high",
            "seller text pushing the buyer agent to approve, skip a check or charge", check, fold=True)
