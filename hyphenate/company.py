"""The simulated company and its shared plumbing: people, vendors, budgets, the ledger and the audit trail.

`Company` is assembled from two mixins: procurement (request, approve, reject, replan, receive) and payables
(invoice, pay, bank, vendor bank changes, period close). Every public action returns an `Outcome` and writes at
least one decision to the audit trail. Nothing here calls a model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from hyphenate.audit import AuditLog, Decision
from hyphenate.ledger import Ledger, Line, PeriodLocked
from hyphenate.money import cents, usd
from hyphenate.org import STANDARD_BUDGETS, Person, Policy, standard_people
from hyphenate.vendors import Vendor
from pay.mandate import format_ts, parse_ts
from pay.replay import NonceStore

RULES = {
    "sod.requester_cannot_approve": "Whoever requests a purchase can never approve it, directly or through a delegate.",
    "sod.receiver_independent": "Whoever receives the goods cannot be the requester or an approver of the same PO.",
    "sod.payer_independent": "A person who releases a payment cannot be the requester or an approver of that PO.",
    "sod.bank_change_verified_by_other": "A vendor bank change must be verified by a different person than the one who made it.",
    "perm.role": "An action needs a role that holds that permission; the Hyphenate agents hold none that approve.",
    "approval.authority": "A department head approves only their department and only up to the policy limit; above it the controller approves.",
    "approval.budget": "A purchase that exceeds its department's budget needs the controller to approve with an explicit override.",
    "approval.route": "Route by amount, vendor history, budget and price reference; escalations are written down with their reason.",
    "approval.bind": "An approval binds the payee, deal and amount ceiling; a charge can only match the approved PO.",
    "price.reference": "A PO price is checked against a fresh MIRROR market reference; far above or far below goes to the controller.",
    "replan.after_no": "When a controller says no, re-plan inside what they allowed (cheaper allowed condition or fewer units), else drop and release the budget.",
    "receive.check": "Receiving counts units, checks condition against what the PO allows, and requires one unique serial per serialized unit.",
    "receive.accrue": "Accepted goods are a liability before the bill arrives: accrue them at the PO price (or draw down the prepaid deposit).",
    "match.three_way": "Bill only what the PO allows, what arrived accepted and what the contract priced; anything else is held with a credit memo request.",
    "match.duplicate": "The same vendor invoice number, or the same vendor, PO, lines and total inside the window, is never booked twice.",
    "match.remit_to": "Bank details on an invoice never override the verified vendor master.",
    "match.arithmetic": "An invoice total must equal the sum of its lines.",
    "match.claim": "A seller claim that an independent page check finds false cannot support a payment.",
    "post.bill": "A matched bill reverses its accrual and books the payable; price variance inside tolerance goes to variance expense.",
    "post.period_lock": "Nothing posts into a closed period; it posts to the next open period and says why.",
    "pay.gate": "A payment needs a matched bill, an approved PO, a verified bank account, an amount under the approved ceiling and a valid mandate.",
    "pay.mandate": "The charge goes through the pay/ mandate guard: same deal, same amount, same payee, one use.",
    "recon.trust": "When bank, ledger and seller disagree on cash, the bank record wins and the difference is booked and flagged.",
    "close.period": "Only the controller closes a period; the trial balance must balance and every payment must be reconciled to a bank record.",
    "vendor.history": "A vendor's dated history sets its risk level: strict means zero price tolerance and a second signature.",
}


@dataclass
class Outcome:
    ok: bool
    status: str
    decisions: list
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "status": self.status, "decision_ids": [d.id for d in self.decisions],
                "decisions": [d.to_dict() for d in self.decisions], **self.data}


class Company:
    APPROVED_STATES = ("approved", "partially_received", "received", "closed")

    def __init__(self, name: str = "Pixel Forge Games (SIM)", *, policy: Optional[Policy] = None, people=None,
                 vendors=None, budgets=None, mirror=None, nonce_store: Optional[NonceStore] = None):
        self.name = name
        self.id = "pixel-forge"
        self.policy = policy or Policy()
        self.people = {p.id: p for p in (people if people is not None else standard_people())}
        self.vendors: dict[str, Vendor] = {v.id: v for v in (vendors or [])}
        self.budgets: dict[str, int] = dict(STANDARD_BUDGETS if budgets is None else budgets)
        self.mirror: dict[str, dict] = dict(mirror or {})  # sku -> {"price": cents, "as_of": ts, "source": url, "origin": MIRROR|SIM}
        self.ledger = Ledger()
        self.audit = AuditLog()
        self.store = nonce_store or NonceStore()
        self.pos: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.receipts: dict[str, dict] = {}
        self.memos: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.bank: dict[str, dict] = {}
        self.serials: dict[str, str] = {}
        self._n = {"po": 1000, "rcv": 0, "cm": 0, "pay": 0, "inv": 0}
        self.clock = "1970-01-01T00:00:00Z"

    # ----- small helpers -----
    def _next(self, key: str, prefix: str) -> str:
        self._n[key] += 1
        return f"{prefix}-{self._n[key]}"

    def _now(self, at: Optional[str]) -> str:
        """Every action carries its own timestamp; time moves forward only (a past `at` is refused)."""
        if at is None:
            raise ValueError("at is required")
        parse_ts(at)
        if at < self.clock:
            raise ValueError(f"time cannot go backwards: {at} is before {self.clock}")
        self.clock = at
        return at

    def add_vendor(self, v: Vendor) -> Vendor:
        self.vendors[v.id] = v
        return v

    def person(self, pid: str) -> Optional[Person]:
        return self.people.get(pid)

    def _d(self, at: str, kind: str, subject: str, outcome: str, reason: str, *, rule: Optional[str] = None,
           actor: Optional[dict] = None, codes=(), evidence=(), parents=()) -> Decision:
        r = {"id": rule, "text": RULES[rule]} if rule else None
        if actor is None:
            actor = {"kind": "rule", "id": rule} if rule else {"kind": "system", "id": "hyphenate"}
        return self.audit.record(at=at, kind=kind, subject=subject, outcome=outcome, reason=reason, actor=actor,
                                 codes=tuple(codes), rule=r, evidence=evidence, parents=parents)

    def _deny(self, at, kind, subject, who, code, reason, rule, *, evidence=(), parents=()) -> Outcome:
        ev = [{"type": "person", "id": who or "unknown", "detail": "attempted by"}, *evidence]
        d = self._d(at, kind, subject, "denied", reason, rule=rule, codes=(code,), evidence=ev, parents=parents)
        return Outcome(False, "denied", [d], {"code": code})

    def _need(self, who: str, perm: str, at: str, kind: str, subject: str) -> Optional[Outcome]:
        p = self.people.get(who)
        if p is None or not p.can(perm):
            return self._deny(at, kind, subject, who, "no_permission",
                              f"{who} has no '{perm}' permission" + (f" (role {p.role})" if p else " (unknown person)"), "perm.role")
        return None

    def _post(self, *, at: str, date: str, lines: list, reason: str, refs: list, subject: str, kind: str, rule: str,
              parents=(), evidence=(), outcome="posted", codes=()) -> tuple:
        """Post one journal entry and record the decision that caused it (the entry cites the decision, the decision
        cites the entry). A closed period reroutes to the next open one with its own decision."""
        moved = None
        period = date[:7]
        if self.ledger.is_locked(period):
            nxt = self.ledger.next_open_period(period)
            moved_date = f"{nxt}-01"
            moved = self._d(at, "posting_period", subject, "rerouted",
                            f"{period} is closed, so the entry dated {date} posts on {moved_date} in {nxt}",
                            rule="post.period_lock", codes=("period_locked",),
                            evidence=[{"type": "period", "id": period, "detail": f"closed by {self.ledger.locked[period]['by']}"}], parents=parents)
            date, reason, parents = moved_date, f"{reason} (dated into closed period {period}, posted in {nxt})", (*parents, moved.id)
        did = f"dec_{len(self.audit.decisions) + 1:04d}"
        entry = self.ledger.post(date=date, lines=lines, reason=reason, refs=[*refs, f"decision:{did}"], by="ap-agent", at=at)
        d = self._d(at, kind, subject, outcome, reason, rule=rule, codes=codes, parents=parents,
                    evidence=[*evidence, {"type": "journal_entry", "id": entry.id, "detail": f"{entry.period}"}])
        assert d.id == did
        return entry, d, moved

    # ----- reads -----
    def explain(self, decision_id: str) -> dict:
        return self.audit.explain(decision_id, journal=self.ledger.entries_for_ref)

    def budget_used(self, dept: str, exclude: Optional[str] = None) -> int:
        return sum(p["committed"] for p in self.pos.values() if p["dept"] == dept and p["id"] != exclude)

    def facts(self) -> set:
        f = {f"po_status:{p['id']}:{p['status']}" for p in self.pos.values()}
        f |= {f"invoice_status:{i['id']}:{i['status']}" for i in self.invoices.values()}
        f |= {f"paid:{p['invoice_id']}" for p in self.payments.values() if p["kind"] == "payment"}
        f |= {f"prepaid:{p['po_id']}" for p in self.payments.values() if p["kind"] == "prepayment"}
        f |= {f"memo_requested:{m['invoice_id'] or m['po_id']}" for m in self.memos.values()}
        f |= {f"period_closed:{p}" for p in self.ledger.locked}
        f |= {f"vendor_bank_verified:{v.id}:{str(v.bank_verified).lower()}" for v in self.vendors.values()}
        for v, bal in self.ledger.party_balances("2100").items():
            f.add(f"accrual_open:{v}:{bal}")
        for v, bal in self.ledger.party_balances("1300").items():
            f.add(f"vendor_credit:{v}:{bal}")
        f |= {f"payment_corrected:{p['id']}" for p in self.payments.values() if p.get("bank_corrected")}
        f |= {f"po_approved_by:{p['id']}:{a['by']}" for p in self.pos.values() for a in p["approvals"]}
        return f

    def invariants(self) -> list:
        """Everything that must hold after any sequence of actions. Empty list means the books and trail are sound."""
        bad = []
        tb = self.ledger.trial_balance()
        if not tb["balanced"]:
            bad.append("trial balance does not balance")
        for a in self.ledger.subledger_ties():
            bad.append(f"vendor subledger for {a} does not tie to the general ledger")
        for acct, what in (("2100", "accrued liabilities"), ("1200", "prepaid deposits"), ("1300", "vendor credits receivable")):
            for party, bal in self.ledger.party_balances(acct).items():
                if bal < 0:
                    bad.append(f"{what} for {party} is negative ({bal} cents): more was billed or credited than was received or paid")
        for e in self.ledger.entries:
            if e.period in self.ledger.locked and e.posted_at > self.ledger.locked[e.period]["at"]:
                bad.append(f"{e.id} posted into closed period {e.period} after the close")
            if not e.reason or not e.refs:
                bad.append(f"{e.id} lacks reason or refs")
        bad += [f"audit chain broken at {d}" for d in self.audit.verify_chain()]
        for d in self.audit.decisions:
            try:
                self.explain(d.id)
            except Exception as ex:  # an unexplainable decision is itself a failure
                bad.append(f"{d.id} cannot be explained: {ex}")
        return bad
