"""Optional drafting of a plain-language explanation. Offline it returns the deterministic text; with HYPHENATE_DRAFT=1 and
ANTHROPIC_API_KEY set it may ask a model to rephrase it. A model never makes or changes a control decision, and the draft is
discarded unless every dollar amount and id in it already appears in the source explanation."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Callable, Optional

MODEL = os.environ.get("HYPHENATE_DRAFT_MODEL", "claude-haiku-4-5")  # unverified until a live call answers
_TOKENS = re.compile(r"\$[\d,]+(?:\.\d+)?|\b(?:dec|je|PO|INV|RCV|CM|PAY)[-_]\d+\b")


def _anthropic(prompt: str) -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or os.environ.get("HYPHENATE_DRAFT") != "1":
        return None
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", method="POST", headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                                 data=json.dumps({"model": MODEL, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}).encode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["content"][0]["text"]
    except Exception:
        return None


def draft_explanation(explained: dict, llm: Optional[Callable[[str], Optional[str]]] = None) -> dict:
    """Returns {"text", "source": "template"|"model"}. `explained` is the output of Engine.explain."""
    base = explained["text"]
    call = llm if llm is not None else _anthropic
    prompt = ("Rewrite this finance audit explanation for a busy controller in 3 sentences. Keep every dollar amount and every id exactly as written, "
              "add nothing, and do not give advice.\n\n" + json.dumps(explained["decision"], default=str) + "\n\n" + base)
    out = call(prompt)
    if not out or not out.strip():
        return {"text": base, "source": "template"}
    allowed = set(_TOKENS.findall(base)) | set(_TOKENS.findall(json.dumps(explained, default=str)))
    if any(t not in allowed for t in _TOKENS.findall(out)):
        return {"text": base, "source": "template"}
    return {"text": out.strip(), "source": "model"}
