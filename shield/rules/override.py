"""shield.override.instruction: text that tries to replace the reading agent's instructions."""
from shield.rules.base import BLOCK, Rule, finditer_spans, rx

PATTERNS = [
    rx(r"\bignore\s+(?:all\s+|any\s+|every\s+)?(?:of\s+)?(?:your\s+|the\s+|my\s+)?"
       r"(?:previous|prior|above|earlier|preceding|former)\s+"
       r"(?:instructions?|rules?|prompts?|directions?|guidelines?|messages?|context)"),
    rx(r"\b(?:disregard|forget|override|bypass)\s+(?:all\s+|any\s+)?(?:of\s+)?(?:your\s+|the\s+)?"
       r"(?:previous\s+|prior\s+|above\s+|earlier\s+|system\s+|safety\s+)?"
       r"(?:instructions?|rules?|prompts?|guidelines?|programming|safeguards?)"),
    rx(r"\bnew\s+instructions?\s*:"),
    rx(r"(?:^|[\n\r>\[\(\{\"'])\s*(?:system|assistant|developer)\s*(?:prompt|message|note|override)?\s*[:\]]"),
    rx(r"\byou\s+are\s+now\s+(?:a|an|the|in|my|acting|operating|unrestricted|free|dan|no\s+longer)\b"),
    rx(r"\bfrom\s+now\s+on,?\s+(?:you|ignore|always|only)\b"),
    rx(r"\bpretend\s+(?:to\s+be|you\s+are)\b"),
    rx(r"\b(?:jailbreak|developer\s+mode|dan\s+mode)\b"),
    rx(r"\bact\s+as\s+(?:if\s+you\s+(?:are|were)|an?\s+(?:unrestricted|different|new|system|admin))"),
    rx(r"\b(?:note|message|instructions?|attention|notice|memo)s?\s+(?:to|for)\s+(?:all\s+|the\s+)?"
       r"(?:shopping\s+|buyer\s+|seller\s+|ai\s+)?(?:agents?|assistants?|bots?|llms?|models?)\b"),
    rx(r"\bdo\s+not\s+(?:tell|mention|reveal|show)\s+(?:this|it)?\s*to\s+the\s+(?:buyer|owner|user|advocate)"),
    rx(r"\breveal\s+(?:your|the)\s+(?:system\s+)?prompt"),
]


def check(doc, ctx):
    return finditer_spans(doc, PATTERNS)


RULE = Rule("shield.override.instruction", BLOCK, "high",
            "instruction override aimed at the reading agent", check, fold=True)
