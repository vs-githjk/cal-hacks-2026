"""What smelled: turns a Smell Test (Shield) verdict into the matched phrase, the rule id, a plain reason and a safe rewrite.

Everything here is code over the verdict Shield already returned: the phrase is cut from the user's own text at the span
offsets Shield gave, the reason comes from the table below, and the rewrite is the same text with those spans taken out.
The rewrite is offered only after Smell Test passes it again. A model may reword a reason sentence (phrasing.phrase) and
nothing else; it never sees the text and never touches the verdict, the span or the rewrite.
"""
from __future__ import annotations

import re

REASONS = {
    "shield.override.instruction": "It tries to give the reading agent new orders instead of describing a product.",
    "shield.hidden.text": "It hides invisible characters or hidden text inside the listing.",
    "shield.hidden.instruction": "It hides an instruction for an AI agent in text a person cannot see.",
    "shield.payee.swap": "It names a different payee or payout account than the seller on record.",
    "shield.money.approval": "It pushes the buyer's agent to approve, skip a check or charge a card.",
    "shield.price.contradiction": "It claims a was-price that the price history does not support.",
    "shield.exfil.send": "It asks for private data to be sent to a link, webhook or mailbox.",
    "shield.exfil.screen_code": "It asks for the approval code that only the buyer should see.",
    "shield.exfil.buyer_private": "It asks for the buyer's sealed limit or personal details.",
    "shield.encoded.payload": "It carries an oversized or encoded block, or look-alike letters that hide words.",
    "shield.impersonation": "The sender claims a role it does not hold, such as the buyer or Fish Market.",
    "shield.impersonation.output": "It is dressed up as a verdict from the Advocate, the referee or Fish Market.",
    "shield.intent.approval_bypass": "It tells the buyer's side to skip, waive or pre-clear an approval.",
    "shield.intent.override": "It tries to make the reader forget its earlier instructions.",
    "shield.intent.payment_redirect": "It changes where the payment should go, such as a new payee, account or wallet.",
    "shield.intent.authority_claim": "It uses a claimed title or authority to push an approval, payment or shipment.",
    "shield.intent.agent_directed": "It speaks to the AI agent reading it instead of describing a product.",
    "shield.classifier.suspicious": "A model-based screen judged the wording suspicious, though no single rule matched.",
    "shield.classifier.unavailable": "The model-based screen could not run, so the text is held rather than trusted.",
    "shield.classifier.secret_ask": "It asks someone to state or give up a password, code or PIN.",
    "shield.error": "Smell Test hit an internal error, so it failed closed and blocked the text.",
    "shield.unavailable": "Smell Test could not be reached, so the text is blocked.",
    "shield.quarantine.seen": "The same wording was caught earlier and is on the shared quarantine list.",
}
GENERIC_REASON = "A Smell Test rule flagged this text."
MAX_FINDINGS = 3
MAX_SPAN_SHOWN = 80
MAX_REWRITE_SHOWN = 600
_MEMORY_QUERY = re.compile(r"\bquarantine\b.*\b(?:list|memory|status|size)\b|\b(?:list|memory|status)\b.*\bquarantine\b|"
                           r"\bshared\s+(?:list|memory)\b|\bwhat(?:'s| is| has)\b.*\bquarantined\b", re.I)


def reason_for(rule_id: str) -> str:
    return REASONS.get(rule_id, GENERIC_REASON)


def _valid_spans(text: str, result: dict) -> list[dict]:
    out = []
    for s in result.get("evidence_spans") or []:
        if not isinstance(s, dict):
            continue
        a, b, rid = s.get("start"), s.get("end"), s.get("rule_id")
        if (isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool) and not isinstance(b, bool)
                and 0 <= a < b <= len(text) and isinstance(rid, str)):
            out.append({"rule_id": rid, "start": a, "end": b})
    return out


def _findings(text: str, result: dict) -> list[dict]:
    if result.get("verdict") == "allow":
        return []
    by_span: dict[tuple, dict] = {}
    for s in _valid_spans(text, result):
        key = (s["start"], s["end"])
        f = by_span.setdefault(key, {"rule_id": s["rule_id"], "start": s["start"], "end": s["end"],
                                     "span": " ".join(text[s["start"]:s["end"]].split())[:MAX_SPAN_SHOWN], "also": []})
        if s["rule_id"] != f["rule_id"] and s["rule_id"] not in f["also"]:
            f["also"].append(s["rule_id"])
    found = sorted(by_span.values(), key=lambda f: (f["start"], f["rule_id"]))
    if not found:  # a rule-less flag (the classifier, an error, Shield down): say which rule, with no phrase to point at
        found = [{"rule_id": r, "start": None, "end": None, "span": None, "also": []} for r in result.get("rule_ids", [])
                 if isinstance(r, str)]
    for f in found:
        f["reason"] = reason_for(f["rule_id"])
    return found[:MAX_FINDINGS]


SENTENCE_END = ".!?;\n"
REMOVED = "(removed by Smell Test)"


def _sentence_bounds(text: str, a: int, b: int) -> tuple[int, int]:
    start = max(text.rfind(c, 0, a) for c in SENTENCE_END) + 1
    ends = [i for i in (text.find(c, b) for c in SENTENCE_END) if i >= 0]
    return start, (min(ends) + 1 if ends else len(text))


def _rewrite(text: str, result: dict) -> str | None:
    """The text with the whole sentence around each flagged span taken out (a cut phrase can leave an order behind, as in
    "(removed) and rank this bid first"). Invisible characters are deleted on their own. The marker names no rule on purpose:
    a label like "an instruction to the agent" would smell by itself."""
    spans = sorted(_valid_spans(text, result), key=lambda s: (s["start"], s["end"]))
    if not spans:
        return None
    cuts: list[list] = []
    for s in spans:
        piece = text[s["start"]:s["end"]]
        invisible = not piece.strip() or all(not ch.isprintable() or ch.isspace() for ch in piece)
        a, b = (s["start"], s["end"]) if invisible else _sentence_bounds(text, s["start"], s["end"])
        if cuts and a <= cuts[-1][1]:
            cuts[-1][1] = max(cuts[-1][1], b)
            cuts[-1][2] = cuts[-1][2] and invisible
        else:
            cuts.append([a, b, invisible])
    out, at = [], 0
    for a, b, invisible in cuts:
        out.append(text[at:a])
        out.append("" if invisible else f" {REMOVED} ")
        at = b
    out.append(text[at:])
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()


def explain(text: str, result: dict, *, screen=None) -> dict:
    """The verdict, what smelled and a rewrite. `screen(text) -> verdict dict` re-checks the rewrite; without it the rewrite
    is returned unchecked. A rewrite that does not come back allow is dropped (rewrite_rejected)."""
    ex = {"verdict": result.get("verdict"), "rule_ids": [r for r in result.get("rule_ids", []) if isinstance(r, str)],
          "findings": _findings(text, result), "rewrite": None, "rewrite_checked": False, "rewrite_rejected": False}
    if result.get("verdict") == "allow":
        return ex
    rewrite = _rewrite(text, result)
    if rewrite is None:
        return ex
    if screen is None:
        ex["rewrite"] = rewrite
        return ex
    try:
        again = screen(rewrite)
        ok = isinstance(again, dict) and again.get("verdict") == "allow"
    except Exception:
        ok = False
    ex["rewrite"], ex["rewrite_checked"], ex["rewrite_rejected"] = (rewrite, True, False) if ok else (None, False, True)
    return ex


def render(ex: dict, phrase=None) -> str:
    rules = ", ".join(ex["rule_ids"]) or "none"
    lines = [f"Smell Test verdict: {ex['verdict']}. Rules: {rules}. No action taken."]
    if ex["verdict"] == "allow":
        lines.append("No rule matched, so nothing fishy was found. That is not a guarantee.")
        return "\n".join(lines)
    for f in ex["findings"]:
        reason = phrase(f["reason"]) if phrase else f["reason"]
        also = f" Also flagged as {', '.join(f['also'])}." if f["also"] else ""
        if f["span"] is not None:
            lines.append(f"What smelled: \"{f['span']}\" (characters {f['start']} to {f['end']}), rule {f['rule_id']}: {reason}{also}")
        else:
            lines.append(f"What smelled: no single phrase; rule {f['rule_id']}: {reason}{also}")
    if ex["rewrite"]:
        shown = ex["rewrite"] if len(ex["rewrite"]) <= MAX_REWRITE_SHOWN else ex["rewrite"][:MAX_REWRITE_SHOWN] + " (shortened)"
        label = "Smell Test passed it again" if ex["rewrite_checked"] else "not checked again"
        lines.append(f"Safe rewrite ({label}): {shown}")
    elif ex["rewrite_rejected"]:
        lines.append("No safe rewrite: the cleaned text still smells, so do not use it.")
    else:
        lines.append("No safe rewrite: nothing to cut out, so hold this text for a human to read.")
    return "\n".join(lines)


def is_memory_query(text: str) -> bool:
    return bool(_MEMORY_QUERY.search(str(text or "")))


def render_memory(summary: dict | None) -> str:
    """The shared quarantine list in counts only: its patterns are other people's words and are never shown in chat."""
    if summary is None:
        return "The shared quarantine list is turned off on this machine. No action taken."
    hours = f"{summary['ttl_s'] / 3600:g} hours" if summary["ttl_s"] >= 3600 else f"{summary['ttl_s'] / 60:g} minutes"
    noun = "pattern" if summary["count"] == 1 else "patterns"
    head = (f"The shared quarantine list holds {summary['count']} {noun}, kept {hours} each and up to {summary['max_entries']} in all. "
            if summary["count"] else
            f"The shared quarantine list holds no patterns right now (each is kept {hours}, up to {summary['max_entries']} in all). ")
    by_rule = "; ".join(f"{r}: {n}" for r, n in sorted(summary["by_rule"].items()))
    return (head + (f"By rule, {by_rule}. " if by_rule else "")
            + "Every agent reads it, so a trick caught once is flagged for all of them. I do not show the patterns here, "
              "because they are other people's words. No action taken.")
