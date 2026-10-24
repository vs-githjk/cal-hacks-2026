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
from shield.classifier import UNAVAILABLE_RULE, default_classifier, run_classifier, run_secret_ask
from shield.rules import RULES
from shield.rules import secret_ask
from shield.rules.base import BLOCK, QUARANTINE, SEVERITY_ORDER
from shield.text import make_doc

ERROR_RULE = "shield.error"
MAX_SPANS = 32
MAX_EXCERPT = 80
MAX_CHARS = 20000  # longer messages are quarantined before any parsing (regex cost grows with size)
OVERSIZE_RULE = "shield.encoded.payload"
MAX_CANDIDATE_CHARS = 3900  # what one classifier call carries (shield.classifier.MAX_CHARS is 4000)
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


_BUYER_SIDE = frozenset({"buyer", "advocate", "marketplace"})


def _seller_side(ctx: Mapping) -> bool:
    """Secret asks are checked for every sender except the buyer's own side. The role is trimmed and lowercased; only
    buyer, advocate and marketplace skip the check, so "seller_agent", "vendor", "Seller " and a missing role get it."""
    return str((ctx or {}).get("sender_role") or "").strip().lower() not in _BUYER_SIDE


def _as_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, (bytes, bytearray)):
        return bytes(message).decode("utf-8")
    raise TypeError("message must be str")


def _secret_ask(clf: Any, text: str, doc, ctx: Mapping) -> Optional[tuple[str, list[dict]]]:
    """Seller text only. Candidate sentences (a state/name/tell/give verb and a secret noun) are asked of the
    classifier. Returns (rule id, spans) to quarantine, or None to carry on. No classifier means fail closed."""
    cands = secret_ask.candidates(doc)
    if not cands:
        return None
    spans = [{"rule_id": secret_ask.SECRET_ASK_RULE, "start": s, "end": e, "text": text[s:e][:MAX_EXCERPT]}
             for s, e in cands[:MAX_SPANS]]
    joined = "\n".join(text[s:e] for s, e in cands)
    if clf is None or len(joined) > MAX_CANDIDATE_CHARS:  # too much to judge in one call: fail closed as well
        rule_id = UNAVAILABLE_RULE
    else:
        rule_id = run_secret_ask(clf, joined, ctx)
        if rule_id is None:
            return None
    for s in spans:
        s["rule_id"] = rule_id
    return rule_id, spans


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
            if _seller_side(ctx):  # buyer-side text is never held for a secret ask
                asked = _secret_ask(clf, text, doc, ctx)
                if asked is not None:
                    rule_id, spans = asked
                    return _verdict(QUARANTINE, [rule_id], "high" if rule_id == secret_ask.SECRET_ASK_RULE else "medium",
                                    spans, started, request_id)
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
