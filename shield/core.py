"""screen(message, context): the pure Shield core.

Deterministic rules run first. An optional classifier can only ADD a quarantine; it can never lower a
rule's verdict. Any internal error returns block with rule "shield.error" (fail closed). The verdict holds
only rule ids, severities, spans of the caller's own text and numbers: no text written by a model.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Mapping, Optional

from shield import VERSION
from shield.classifier import default_classifier, run_classifier
from shield.rules import RULES
from shield.rules.base import BLOCK, QUARANTINE, SEVERITY_ORDER
from shield.text import make_doc

ERROR_RULE = "shield.error"
MAX_SPANS = 32
MAX_EXCERPT = 80
MAX_CHARS = 20000  # longer messages are quarantined before any parsing (regex cost grows with size)
OVERSIZE_RULE = "shield.encoded.payload"
_DEFAULT = object()


def _verdict(verdict: str, rule_ids: list[str], severity: str, spans: list[dict], started: float,
             request_id: str) -> dict:
    return {
        "verdict": verdict,
        "rule_ids": rule_ids,
        "severity": severity,
        "evidence_spans": spans,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "request_id": request_id,
        "version": VERSION,
    }


def _as_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, (bytes, bytearray)):
        return bytes(message).decode("utf-8")
    raise TypeError("message must be str")


def screen(message: Any, context: Optional[Mapping] = None, *, classifier: Any = _DEFAULT) -> dict:
    """Screen one message. `context` keys (all optional): payee_of_record, price_history, sender_role,
    request_id. Returns the stable verdict dict."""
    started = time.perf_counter()
    request_id = uuid.uuid4().hex
    try:
        ctx = {} if context is None else context
        if not isinstance(ctx, Mapping):
            raise TypeError("context must be a mapping")
        request_id = str(ctx.get("request_id") or request_id)
        text = _as_text(message)
        if len(text) > MAX_CHARS:
            span = {"rule_id": OVERSIZE_RULE, "start": 0, "end": MAX_EXCERPT, "text": text[:MAX_EXCERPT]}
            return _verdict(QUARANTINE, [OVERSIZE_RULE], "medium", [span], started, request_id)
        doc = make_doc(text)

        fired: dict[str, Any] = {}
        spans: list[dict] = []
        for rule in RULES:
            found = list(rule.check(doc, ctx))
            if rule.fold:  # same rule on the leetspeak / spacing / accent-folded views of the message
                for view in doc.views():
                    found.extend(rule.check(view, ctx))
            hits = sorted(set(found))
            if not hits:
                continue
            fired[rule.id] = rule
            for s, e in hits[:8]:
                spans.append({"rule_id": rule.id, "start": s, "end": e, "text": text[s:e][:MAX_EXCERPT]})

        if not fired:
            clf = default_classifier() if classifier is _DEFAULT else classifier
            if clf is not None:
                added = run_classifier(clf, text, ctx)
                if added is not None:
                    return _verdict(QUARANTINE, [added], "medium", [], started, request_id)
            return _verdict("allow", [], "none", [], started, request_id)

        verdict = BLOCK if any(r.action == BLOCK for r in fired.values()) else QUARANTINE
        severity = max((r.severity for r in fired.values()), key=SEVERITY_ORDER.index)
        spans.sort(key=lambda d: (d["start"], d["rule_id"]))
        return _verdict(verdict, sorted(fired), severity, spans[:MAX_SPANS], started, request_id)
    except Exception:  # fail closed: never let an error read as "allow"
        return _verdict(BLOCK, [ERROR_RULE], "critical", [], started, request_id)
