"""Model phrasing for explanations. LOCKED: an LLM never decides a veto or a verdict.

A caller hands in a sentence that code already wrote (with its numbers and its verdict word). The model may reword
it in plainer language; the reply is accepted only if it keeps every number and every verdict word, adds no link,
and stays one short sentence. Any failure (no key, timeout, bad reply) returns the code's own sentence. The model
never sees seller text as an instruction: the input is a closed sentence we built, sent inside <sentence> tags.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from typing import Callable, Optional

MODEL = "claude-haiku-5-5"
API_URL = "https://api.anthropic.com/v1/messages"
TIMEOUT_S = 3.0
MAX_CHARS = 260
# Words that carry the decision. If the code's sentence has one, the model's sentence must keep it.
ANCHORS = ("veto", "vetoed", "caution", "approved", "block", "blocked", "quarantine", "quarantined", "allow", "not", "no",
           "fishy", "unverified", "fit", "fits")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD = re.compile(r"[a-z']+")
_SYSTEM = ("You rewrite one sentence for a shopper in plain, expert language. Keep every number and every decision "
           "word (veto, caution, approved, block, quarantine, allow, not, no, fishy, unverified) exactly as given. "
           "Add no new facts, no links, no advice to buy or skip. Reply with one sentence under 220 characters.")

Transport = Callable[[dict, float], dict]


def _post(body: dict, timeout: float) -> dict:
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST", headers={
        "content-type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def accepts(candidate: object, original: str) -> bool:
    """True when the model's sentence may replace the code's: same numbers, same decision words, one clean sentence."""
    if not isinstance(candidate, str):
        return False
    text = " ".join(candidate.split())
    if not text or len(text) > MAX_CHARS or "\n" in candidate.strip():
        return False
    if re.search(r"https?:|www\.|[\u2013\u2014]|<|>", text):
        return False
    if len(re.findall(r"[.!?](?:\s|$)", text)) > 1 or not text.endswith((".", "!", "?")):
        return False
    if {n.rstrip(",") for n in _NUMBER.findall(original)} - {n.rstrip(",") for n in _NUMBER.findall(text)}:
        return False
    need = {w for w in _WORD.findall(original.lower()) if w in ANCHORS}
    return need <= set(_WORD.findall(text.lower()))


def phrase(sentence: str, *, post: Optional[Transport] = None, timeout: float = TIMEOUT_S) -> str:
    """The sentence, reworded by the model when that is safe, else unchanged. Never raises."""
    if os.environ.get("PHRASING_LLM") == "0":
        return sentence
    if post is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return sentence
    body = {"model": os.environ.get("ADVOCATE_MODEL") or MODEL, "max_tokens": 120, "system": _SYSTEM,
            "messages": [{"role": "user", "content": f"<sentence>{sentence}</sentence>"}]}
    box: dict = {}

    def call():
        try:
            box["data"] = (post or _post)(body, timeout)
        except Exception:
            pass

    worker = threading.Thread(target=call, daemon=True)  # a hard deadline: urllib's timeout is per socket read
    worker.start()
    worker.join(timeout)
    data = box.get("data")
    if not isinstance(data, dict):
        return sentence
    try:
        text = next((b.get("text") for b in data.get("content", []) if b.get("type") == "text"), None)
    except Exception:
        return sentence
    return " ".join(text.split()) if accepts(text, sentence) else sentence
