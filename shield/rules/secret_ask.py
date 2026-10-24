"""Secret-ask CANDIDATES: a cheap, deliberately broad filter. It decides nothing.

A sentence is a candidate when it holds an ask verb (state, name, tell, give, send, share, provide, enter, type,
reply, confirm, read, text, verify, reveal, submit, paste, in base, -s and -ing forms) or an ask pattern ("what's
your ...", "need your ...", "your ...?") and a secret noun (password, passcode, card number, CVV, seed phrase, OTP,
PIN, verification or security code, login, credentials, API key, private key, "the code we texted you"). Whether the sentence really ASKS for the secret
("State your password.") or only describes the item ("State: like new, no password set.") is the classifier's
job (shield.classifier.run_secret_ask), because wording alone cannot tell them apart. Broad on purpose: a
missed candidate is a missed ask, an extra candidate costs one model call.

Not a Rule: it never produces a verdict by itself and is not in RULES.
"""
from __future__ import annotations

import re

from shield.rules.base import rx

SECRET_ASK_RULE = "shield.classifier.secret_ask"
# Closed answer set of the classifier: {ask_for_secret: bool, reason_code: one of these}. Never free text.
REASON_CODES = ("requests_secret", "item_description", "condition_label", "other")

_VERB = rx(
    r"\b(?:stat(?:e|es|ing)|nam(?:e|es|ing)|tell(?:s|ing)?|giv(?:e|es|ing)|send(?:s|ing)?|shar(?:e|es|ing)"
    r"|provid(?:e|es|ing)|enter(?:s|ing)?|typ(?:e|es|ing)|repl(?:y|ies|ying)|confirm(?:s|ing)?|read(?:s|ing)?"
    r"|text(?:s|ing)?|verif(?:y|ies|ying)|reveal(?:s|ing)?|submit(?:s|ting)?|past(?:e|es|ing))\b"
)
# "pass word", "pass-word", "pass_word", "pass phrase": the parts may be split by blanks, dashes, dots or underscores
# (a raw "p a s s w o r d" is joined by the folded views).
_SECRET_SRC = (
    r"\bpass[\s._-]{0,12}(?:word|wd|code|phrase)s?\b"
    r"|\b(?:credit\s+|debit\s+|bank\s+|payment\s+)?card\s*(?:number|num|no\.?|#|digits?|details)\b"
    r"|\bcv[vc]2?\b|\bsecurity\s+code\b"
    r"|\b(?:seed|recovery|secret|backup|mnemonic)\s+(?:phrase|words?)\b"
    r"|\botp\b|\bone[-\s]?time\s+(?:pass(?:word|code)|code|pin)\b"
    r"|\b(?:verification|2fa|mfa|sms|auth(?:entication)?|login|log-?in|access|confirmation)\s+codes?\b"
    r"|\bpin\b(?:\s+(?:code|number))?"
    r"|\bapi[\s_-]?keys?\b|\b(?:private|secret|signing|access)\s+keys?\b"
    r"|\blog[\s-]?ins?\b|\bcredentials?\b"
    # "the code we texted you", "the code you just received"
    r"|\bcode\s+(?:that\s+)?(?:(?:we|i|they)\s+(?:just\s+)?(?:texted|sent|emailed|messaged)"
    r"|(?:was|were)\s+(?:just\s+)?(?:texted|sent|emailed|messaged)|(?:you\s+)?(?:just\s+)?(?:received|got|get))\b"
)
_SECRET = rx(_SECRET_SRC)
# Question and need forms that carry no verb from _VERB: "what's your PIN?", "we need your OTP", "Your password?"
_ASKING = rx(
    r"\bwhat(?:['\u2019`]?s|\s+is|\s+are|\s+was)\s+your\s+(?:" + _SECRET_SRC + r")"
    r"|\b(?:need|needs|needed|require|requires|required|want|wants)\s+(?:to\s+know\s+)?(?:your|the)\s+(?:" + _SECRET_SRC + r")"
    r"|\byour\s+(?:" + _SECRET_SRC + r")\s*\?"
)
# Honest hardware and label text that looks like a secret noun or a verb. Blanked (same length) before matching.
# A connector "pin" has a count in front: 8-pin, 16 pin, 6+2 pin, 6 + 2-pin, eight pin.
_CONNECTOR_PIN = rx(r"\b(?:\d+|four|six|eight|ten|twelve|sixteen)(?:\s*\+\s*\d+)?[\s-]*pins?\b")
# "name" as a noun, not the verb: brand name, model name, product name, user name, "name brand".
_NAME_NOUN = rx(r"\b(?:brand|model|product|user|item|company|trade|manufacturer)[\s-]+names?\b|\bname[\s-]+brand\b")
_SENTENCE = re.compile(r"(?:(?!\n\s*\n|\r\s*\r|\u2029)[^.!?;])+\??")
# Simple HTML tags and comment markers become blanks of the same length, so spans still map back to the raw text.
_MARKUP = re.compile(r"</?[a-z][^<>]{0,200}>|<!--|-->", re.IGNORECASE)


def _blank(m: "re.Match[str]") -> str:
    return " " * len(m.group(0))


def candidates(doc) -> list[tuple[int, int]]:
    """Raw-text spans (start, end) of every candidate sentence, on the message and on its folded views
    (leetspeak such as "pa55word"). Sorted, overlaps merged, empty when nothing is a candidate."""
    found: list[tuple[int, int]] = []
    for view in [doc, *doc.views()]:
        prose = _MARKUP.sub(_blank, view.norm)
        for m in _SENTENCE.finditer(prose):
            # the whole sentence goes to the classifier: a window around the match could cut the real ask
            seg = m.group(0)
            noun_text = _CONNECTOR_PIN.sub(_blank, seg)
            if _SECRET.search(noun_text) and (_VERB.search(_NAME_NOUN.sub(_blank, seg)) or _ASKING.search(noun_text)):
                found.append(view.raw_span(m.start(), m.end()))
    merged: list[tuple[int, int]] = []
    for s, e in sorted(found):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    return merged
