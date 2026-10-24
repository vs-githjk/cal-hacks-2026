"""Double-entry general ledger with a vendor subledger and period close.

Entries are immutable. A mistake is fixed by a reversing entry, never an edit. Every entry carries a reason and
source refs (po:..., invoice:..., decision:...), must balance to the cent, and cannot be posted into a closed period.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

ASSET, LIABILITY, EQUITY, EXPENSE = "asset", "liability", "equity", "expense"

CHART = {
    "1000": ("Cash", ASSET),
    "1200": ("Prepaid vendor deposits", ASSET),
    "1300": ("Vendor credits receivable", ASSET),
    "1500": ("IT equipment", ASSET),
    "2000": ("Accounts payable", LIABILITY),
    "2100": ("Accrued liabilities (received, not billed)", LIABILITY),
    "3000": ("Owner equity", EQUITY),
    "5900": ("Purchase price variance", EXPENSE),
    "6100": ("Bank and processing fees", EXPENSE),
}
SUBLEDGER_ACCOUNTS = ("1200", "1300", "2000", "2100")  # lines on these carry a party (vendor id)


class LedgerError(Exception):
    code = "ledger_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Unbalanced(LedgerError):
    code = "unbalanced"


class UnknownAccount(LedgerError):
    code = "unknown_account"


class PeriodLocked(LedgerError):
    code = "period_locked"


class BadEntry(LedgerError):
    code = "bad_entry"


@dataclass(frozen=True)
class Line:
    account: str
    debit: int = 0
    credit: int = 0
    party: Optional[str] = None


@dataclass(frozen=True)
class Entry:
    id: str
    date: str  # YYYY-MM-DD, the accounting date
    period: str  # YYYY-MM
    lines: tuple
    reason: str
    refs: tuple
    posted_at: str
    posted_by: str
    reverses: Optional[str] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "date": self.date, "period": self.period, "reason": self.reason, "refs": list(self.refs),
                "posted_at": self.posted_at, "posted_by": self.posted_by, "reverses": self.reverses,
                "lines": [{"account": l.account, "debit": l.debit, "credit": l.credit, "party": l.party} for l in self.lines]}


def period_of(date: str) -> str:
    if not isinstance(date, str) or len(date) < 7 or date[4] != "-":
        raise BadEntry(f"date must start YYYY-MM: {date!r}")
    return date[:7]


class Ledger:
    def __init__(self) -> None:
        self.entries: list[Entry] = []
        self.locked: dict[str, dict] = {}  # period -> {"by", "at"}
        self._by_id: dict[str, Entry] = {}
        self._reversed: dict[str, str] = {}

    # ----- posting -----
    def post(self, *, date: str, lines: Iterable, reason: str, refs: Iterable[str], by: str, at: str,
             reverses: Optional[str] = None) -> Entry:
        refs = tuple(r for r in refs if isinstance(r, str) and r.strip())
        if not isinstance(reason, str) or not reason.strip():
            raise BadEntry("an entry needs a reason")
        if not refs:
            raise BadEntry("an entry needs at least one source ref")
        norm = []
        for l in lines:
            l = l if isinstance(l, Line) else Line(**l)
            if l.account not in CHART:
                raise UnknownAccount(f"unknown account {l.account}")
            for v in (l.debit, l.credit):
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    raise BadEntry("debit and credit must be whole cents, not negative")
            if (l.debit > 0) == (l.credit > 0):
                raise BadEntry("a line is a debit or a credit, not both and not neither")
            if l.account in SUBLEDGER_ACCOUNTS and not l.party:
                raise BadEntry(f"account {l.account} needs a party (vendor id)")
            norm.append(l)
        if len(norm) < 2:
            raise BadEntry("an entry needs at least two lines")
        debit, credit = sum(l.debit for l in norm), sum(l.credit for l in norm)
        if debit != credit:
            raise Unbalanced(f"debits {debit} do not equal credits {credit}")
        period = period_of(date)
        if period in self.locked:
            raise PeriodLocked(f"period {period} is closed")
        e = Entry(f"je_{len(self.entries) + 1:04d}", date, period, tuple(norm), reason.strip(), refs, at, by, reverses)
        self.entries.append(e)
        self._by_id[e.id] = e
        if reverses:
            self._reversed[reverses] = e.id
        return e

    def reverse(self, entry_id: str, *, date: str, reason: str, refs: Iterable[str], by: str, at: str) -> Entry:
        orig = self._by_id.get(entry_id)
        if orig is None:
            raise BadEntry(f"no entry {entry_id}")
        if entry_id in self._reversed:
            raise BadEntry(f"{entry_id} was already reversed by {self._reversed[entry_id]}")
        lines = [Line(l.account, l.credit, l.debit, l.party) for l in orig.lines]
        return self.post(date=date, lines=lines, reason=reason, refs=[*refs, f"entry:{entry_id}"], by=by, at=at, reverses=entry_id)

    # ----- periods -----
    def is_locked(self, period: str) -> bool:
        return period in self.locked

    def next_open_period(self, period: str) -> str:
        y, m = int(period[:4]), int(period[5:7])
        while True:
            p = f"{y:04d}-{m:02d}"
            if p not in self.locked:
                return p
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    def close_period(self, period: str, *, by: str, at: str) -> dict:
        if period in self.locked:
            raise PeriodLocked(f"period {period} is already closed")
        earlier_open = sorted({e.period for e in self.entries if e.period < period and e.period not in self.locked})
        if earlier_open:
            raise PeriodLocked(f"close {earlier_open[0]} first: periods close in order")
        tb = self.trial_balance()
        if tb["debit"] != tb["credit"]:
            raise Unbalanced("trial balance does not balance; cannot close")
        self.locked[period] = {"by": by, "at": at}
        return {"period": period, "closed_by": by, "closed_at": at, "trial_balance": tb}

    # ----- reports -----
    def balance(self, account: str, *, party: Optional[str] = None, through: Optional[str] = None) -> int:
        """Signed in the account's normal direction (assets and expenses: debit minus credit; the rest: credit minus debit)."""
        kind = CHART[account][1]
        total = 0
        for e in self.entries:
            if through and e.period > through:
                continue
            for l in e.lines:
                if l.account == account and (party is None or l.party == party):
                    total += l.debit - l.credit
        return total if kind in (ASSET, EXPENSE) else -total

    def trial_balance(self, through: Optional[str] = None) -> dict:
        rows, td, tc = [], 0, 0
        for acct, (name, kind) in sorted(CHART.items()):
            d = sum(l.debit for e in self.entries if not (through and e.period > through) for l in e.lines if l.account == acct)
            c = sum(l.credit for e in self.entries if not (through and e.period > through) for l in e.lines if l.account == acct)
            if d or c:
                rows.append({"account": acct, "name": name, "type": kind, "debit": d, "credit": c, "balance": self.balance(acct, through=through)})
            td, tc = td + d, tc + c
        return {"rows": rows, "debit": td, "credit": tc, "balanced": td == tc}

    def party_balances(self, account: str) -> dict:
        out: dict[str, int] = {}
        for e in self.entries:
            for l in e.lines:
                if l.account == account:
                    out[l.party] = out.get(l.party, 0) + l.debit - l.credit
        sign = 1 if CHART[account][1] == ASSET else -1
        return {p: sign * v for p, v in out.items() if v}

    def subledger_ties(self) -> list[str]:
        """Problems where a vendor subledger does not add up to its general-ledger account (empty list is good)."""
        bad = []
        for acct in SUBLEDGER_ACCOUNTS:
            if sum(self.party_balances(acct).values()) != self.balance(acct):
                bad.append(acct)
        return bad

    def entries_for_ref(self, ref: str) -> list[Entry]:
        return [e for e in self.entries if ref in e.refs]

    def get(self, entry_id: str) -> Optional[Entry]:
        return self._by_id.get(entry_id)
