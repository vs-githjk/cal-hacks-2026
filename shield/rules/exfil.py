"""shield.exfil.send: attempts to move private data (budget, card, owner details) to a URL, webhook or mailbox."""
import re

from shield.rules.base import QUARANTINE, Rule, rx

_VERB = rx(r"\b(?:e-?mail|send|forward|post|upload|transmit|leak|exfiltrate|share|submit|dm)\b"
           r"(?P<mid>[^.\n]{0,70}?)\b(?:to|via|through)\s+(?:the\s+|our\s+|my\s+|this\s+)?"
           r"(?:https?://|webhook|endpoint|server|url|[\w.+-]+@[\w-]+)")
_SENSITIVE = re.compile(
    r"budget|allowance|limit|card|detail|number|credential|password|token|\bkey|secret|owner|balance|"
    r"payment|account|mandate|data|conversation|prompt|instruction|history|info|allowance|address|cvv|ssn")
_IMG = rx(r"!\[[^\]]*\]\(https?://[^)\s]*\?[^)\s]*=")


def matches(text: str) -> bool:
    return any(_SENSITIVE.search(m.group("mid")) for m in _VERB.finditer(text)) or bool(_IMG.search(text))


def check(doc, ctx):
    for m in _VERB.finditer(doc.norm):
        if _SENSITIVE.search(m.group("mid")):
            yield doc.raw_span(m.start(), m.end())
    for m in _IMG.finditer(doc.norm):
        yield doc.raw_span(m.start(), m.end())


RULE = Rule("shield.exfil.send", QUARANTINE, "high",
            "attempt to send private data to a URL, webhook or mailbox", check)
