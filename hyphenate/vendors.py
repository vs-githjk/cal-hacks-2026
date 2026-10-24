"""Vendor master and vendor history. What a vendor did in March changes what the system does in June."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pay.mandate import parse_ts

STRICT_WINDOW_DAYS = 120  # a failed receiving check this recent makes the vendor strict
WATCH_WINDOW_DAYS = 365  # older than strict but inside this: watch
STRICT_REPEAT = 2  # this many failures inside the watch window is also strict


@dataclass
class VendorEvent:
    kind: str  # failed_receiving | credit_memo | bank_change | bank_verified | completed_order | fraud_hold
    at: str
    by: str
    detail: str = ""


@dataclass
class Vendor:
    id: str
    name: str
    payee_id: str  # the payee string a mandate carries
    bank_account: str  # masked token, never a real number
    terms: str = "net30"  # net30 | prepay
    origin: str = "SIM"
    events: list = field(default_factory=list)
    bank_verified: bool = True  # False from a bank change until a different person verifies it

    def add(self, kind: str, at: str, by: str, detail: str = "") -> VendorEvent:
        e = VendorEvent(kind, at, by, detail)
        self.events.append(e)
        return e

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "payee_id": self.payee_id, "bank_account": self.bank_account,
                "terms": self.terms, "origin": self.origin, "bank_verified": self.bank_verified,
                "events": [e.__dict__ for e in self.events]}


@dataclass(frozen=True)
class Risk:
    level: str  # normal | watch | strict
    reasons: tuple
    price_tolerance_zero: bool  # strict vendors get no price or quantity leeway
    extra_approval: bool  # controller must co-approve every PO
    new_vendor: bool


def _days(now: str, then: str) -> int:
    return (parse_ts(now) - parse_ts(then)).days


def assess(v: Vendor, now: str) -> Risk:
    """Pure function of the vendor's dated history and `now`; replaying the same history gives the same answer."""
    fails = [e for e in v.events if e.kind == "failed_receiving" and 0 <= _days(now, e.at) <= WATCH_WINDOW_DAYS]
    recent = [e for e in fails if _days(now, e.at) <= STRICT_WINDOW_DAYS]
    completed = [e for e in v.events if e.kind == "completed_order"]
    reasons = []
    if recent:
        reasons.append(f"failed receiving check {_days(now, recent[-1].at)} days ago ({recent[-1].detail or 'no detail'})")
    if len(fails) >= STRICT_REPEAT:
        reasons.append(f"{len(fails)} failed receiving checks in the last {WATCH_WINDOW_DAYS} days")
    if recent or len(fails) >= STRICT_REPEAT:
        level = "strict"
    elif fails:
        level = "watch"
        reasons.append(f"one older failed receiving check ({_days(now, fails[-1].at)} days ago)")
    else:
        level = "normal"
    new = not completed and not fails
    return Risk(level, tuple(reasons), level == "strict", level == "strict", new)
