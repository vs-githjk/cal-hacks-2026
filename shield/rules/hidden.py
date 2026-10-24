"""Hidden-text payloads: invisible characters, CSS-hidden elements and HTML comments.

shield.hidden.text: hidden content that carries no recognisable instruction (quarantine).
shield.hidden.instruction: hidden content or a comment that matches an instruction, money, exfil or
impersonation pattern, or addresses an agent directly (block).
"""
import re

from shield.rules import exfil, impersonation, money, override
from shield.rules.base import BLOCK, QUARANTINE, Rule, any_match, rx

ZERO_WIDTH_LIMIT = 3
_HIDDEN_STYLE = (r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])|opacity\s*:\s*0(?![.\d])"
                 r"|(?:left|top|text-indent)\s*:\s*-\d{3,}px")
_ELEMENT = re.compile(
    r"<(?P<tag>[a-z][\w-]*)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)\s*>", re.IGNORECASE | re.DOTALL)
_ATTR_HIDDEN = re.compile(r"style\s*=\s*[\"'][^\"']*(?:" + _HIDDEN_STYLE + r")|\shidden(?:\s|=|$)", re.IGNORECASE)
_COMMENT = re.compile(r"<!--(?P<body>.*?)-->", re.DOTALL)
_TAGS = re.compile(r"<[^>]*>")
_ADDRESS = rx(r"\b(?:agent|assistant|bot|ai|llm|model)s?\b[^a-z0-9]{0,3}\s*(?:please\s+)?"
              r"(?:approve|pay|skip|send|verify|ignore|mark|charge|trust|accept|do\s+not|don'?t)\b")
_SIGNALS = (override.PATTERNS + money.PATTERNS + list(impersonation.PATTERNS.values()) + [_ADDRESS])


def _has_signal(text):
    return any_match(text, _SIGNALS) or exfil.matches(text)


_SKIP_TAGS = {"style", "script", "template", "noscript"}


def _hidden_segments(doc):
    """Yield (norm_start, norm_end, text) for each hidden element body and each HTML comment."""
    for m in _ELEMENT.finditer(doc.norm):
        if m.group("tag") in _SKIP_TAGS or not _ATTR_HIDDEN.search(m.group("attrs")):
            continue
        text = _TAGS.sub(" ", m.group("body")).strip()
        if text:
            yield m.start(), m.end(), text
    for m in _COMMENT.finditer(doc.norm):
        text = m.group("body").strip()
        if text:
            yield m.start(), m.end(), text


def check_text(doc, ctx):
    if len(doc.invisible) >= ZERO_WIDTH_LIMIT:
        yield doc.invisible[0], doc.invisible[-1] + 1
    for s, e, text in _hidden_segments(doc):
        if not _has_signal(text):
            if not _COMMENT.fullmatch(doc.norm[s:e]):  # a plain comment is normal markup, not a payload
                yield doc.raw_span(s, e)


def check_instruction(doc, ctx):
    for s, e, text in _hidden_segments(doc):
        if _has_signal(text):
            yield doc.raw_span(s, e)


TEXT_RULE = Rule("shield.hidden.text", QUARANTINE, "medium",
                 "invisible characters or CSS-hidden text in a listing", check_text)
INSTRUCTION_RULE = Rule("shield.hidden.instruction", BLOCK, "critical",
                        "hidden text or comment that carries an instruction for an agent", check_instruction)
