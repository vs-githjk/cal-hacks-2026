"""Audit trail: every decision is a record that traces to data, a rule or a person, with a timestamp.

Records are appended to a hash chain, so an edit or a deletion later shows up in `verify_chain`.
`explain(decision_id)` answers "why" from the record, its evidence and the decisions it rests on.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

ACTOR_KINDS = ("person", "rule", "data", "system")


class AuditError(Exception):
    pass


@dataclass(frozen=True)
class Decision:
    id: str
    at: str
    kind: str  # e.g. po_approval, invoice_match, payment_release
    subject: str  # po:PO-1, invoice:INV-1, vendor:v1
    outcome: str  # approved, denied, hold, matched, posted, blocked, ...
    codes: tuple  # machine reasons, e.g. ("qty_short",)
    reason: str  # one plain sentence, written when the call was made
    actor: dict  # {"kind": person|rule|data|system, "id": ...}
    rule: Optional[dict]  # {"id": ..., "text": ...}
    evidence: tuple  # ({"type", "id", "detail"}, ...)
    parents: tuple  # decision ids this call rests on
    prev_hash: str
    hash: str

    def to_dict(self) -> dict:
        return {"id": self.id, "at": self.at, "kind": self.kind, "subject": self.subject, "outcome": self.outcome,
                "codes": list(self.codes), "reason": self.reason, "actor": self.actor, "rule": self.rule,
                "evidence": [dict(e) for e in self.evidence], "parents": list(self.parents),
                "prev_hash": self.prev_hash, "hash": self.hash}


def _digest(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class AuditLog:
    def __init__(self) -> None:
        self.decisions: list[Decision] = []
        self._by_id: dict[str, Decision] = {}

    def record(self, *, at: str, kind: str, subject: str, outcome: str, reason: str, actor: dict,
               codes: Iterable[str] = (), rule: Optional[dict] = None, evidence: Iterable[dict] = (),
               parents: Iterable[str] = ()) -> Decision:
        if not isinstance(reason, str) or not reason.strip():
            raise AuditError("a decision needs a reason")
        if not isinstance(actor, dict) or actor.get("kind") not in ACTOR_KINDS or not actor.get("id"):
            raise AuditError("a decision needs an actor with kind person, rule, data or system and an id")
        evidence, parents = tuple(dict(e) for e in evidence), tuple(parents)
        if rule is None and not evidence and not parents and actor["kind"] != "person":
            raise AuditError("a decision must trace to a rule, data or a person")
        for p in parents:
            if p not in self._by_id:
                raise AuditError(f"unknown parent decision {p}")
        did = f"dec_{len(self.decisions) + 1:04d}"
        prev = self.decisions[-1].hash if self.decisions else "genesis"
        body = {"id": did, "at": at, "kind": kind, "subject": subject, "outcome": outcome, "codes": list(codes),
                "reason": reason.strip(), "actor": actor, "rule": rule, "evidence": list(evidence),
                "parents": list(parents), "prev_hash": prev}
        d = Decision(did, at, kind, subject, outcome, tuple(codes), reason.strip(), dict(actor), rule, evidence, parents, prev, _digest(body))
        self.decisions.append(d)
        self._by_id[did] = d
        return d

    def get(self, did: str) -> Optional[Decision]:
        return self._by_id.get(did)

    def for_subject(self, subject: str) -> list[Decision]:
        return [d for d in self.decisions if d.subject == subject]

    def verify_chain(self) -> list[str]:
        """Ids whose stored hash or link no longer matches (empty list means the trail is intact)."""
        bad, prev = [], "genesis"
        for d in self.decisions:
            body = {"id": d.id, "at": d.at, "kind": d.kind, "subject": d.subject, "outcome": d.outcome, "codes": list(d.codes),
                    "reason": d.reason, "actor": d.actor, "rule": d.rule, "evidence": [dict(e) for e in d.evidence],
                    "parents": list(d.parents), "prev_hash": d.prev_hash}
            if d.prev_hash != prev or _digest(body) != d.hash:
                bad.append(d.id)
            prev = d.hash
        return bad

    def explain(self, did: str, *, journal: Optional[Callable[[str], list]] = None) -> dict:
        """Why was this call made: the decision, who or what stood behind it, the evidence, the decisions it rests on
        (oldest first) and any journal entries that cite it. `journal(ref)` maps a ref to ledger entries."""
        d = self._by_id.get(did)
        if d is None:
            raise AuditError(f"no decision {did}")
        chain, seen = [], set()

        def walk(x: Decision):
            for p in x.parents:
                if p not in seen:
                    seen.add(p)
                    walk(self._by_id[p])
                    chain.append(self._by_id[p])

        walk(d)
        entries = [e.to_dict() for e in (journal(f"decision:{did}") if journal else [])]
        who = d.actor["id"] if d.actor["kind"] != "rule" else (d.rule or {}).get("id", d.actor["id"])
        text = f"{d.at}: {d.kind} on {d.subject} -> {d.outcome}. {d.reason} "
        if d.rule:
            text += f"Rule {d.rule['id']}: {d.rule['text']} "
        text += f"Decided by {d.actor['kind']} {who}. "
        if d.evidence:
            text += "Evidence: " + "; ".join(f"{e['type']} {e['id']}" + (f" ({e['detail']})" if e.get("detail") else "") for e in d.evidence) + ". "
        if chain:
            text += "Rests on " + ", ".join(f"{c.id} ({c.kind}: {c.outcome})" for c in chain) + ". "
        if entries:
            text += "Journal: " + ", ".join(e["id"] for e in entries) + "."
        return {"decision": d.to_dict(), "chain": [c.to_dict() for c in chain], "journal_entries": entries, "text": text.strip()}
