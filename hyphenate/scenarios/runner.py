"""Planted-errors runner. Each case is a short script of company events plus an answer key.

A planted case is CAUGHT only if every expected decision was written, every expected fact holds, no forbidden fact holds
(for example "paid"), the books and audit trail still pass `invariants()`, and nothing crashed. A clean control is OK
only if the system raised no flag at all (a flag on a clean case is a false positive). All of it is SIM.
"""
from __future__ import annotations

import hashlib
import importlib
import os
from dataclasses import dataclass, field

from hyphenate.engine import seed_company
from hyphenate.ledger import Line
from hyphenate.vendors import Vendor
from pay.mandate import mandate_hash

FLAG_OUTCOMES = {"denied", "hold", "blocked", "exception", "rejected", "dropped", "failed"}


def ts(s: str) -> str:
    """'10-05' -> 2026-10-05T09:00:00Z, '10-05 14' -> 14:00."""
    day, _, hour = s.partition(" ")
    return f"2026-{day}T{int(hour or 9):02d}:00:00Z"


class Run:
    def __init__(self, case: dict):
        setup = case.get("setup", {})
        self.eng = seed_company(mirror=setup.get("mirror", {}))
        for vid, cfg in setup.get("vendors", {}).items():
            if vid not in self.eng.vendors:
                self.eng.add_vendor(Vendor(vid, cfg.get("name", vid), f"{vid}@pay.example.test", f"acct_{vid}", terms=cfg.get("terms", "net30")))
            v = self.eng.vendors[vid]
            v.terms = cfg.get("terms", v.terms)
            for e in cfg.get("events", []):
                v.add(e["kind"], e["at"], e.get("by", "seed"), e.get("detail", ""))
        self.eng.budgets.update(setup.get("budgets", {}))
        self.alias: dict = {}
        self.step_n = 0
        self.errors: list = []

    def r(self, key):  # alias -> real id
        return self.alias.get(key, key)

    def sub(self, text: str) -> str:
        return text.format_map({**self.alias, **{k: v for k, v in self.alias.items()}})

    def step(self, s: dict) -> None:
        self.step_n += 1
        e, do, at = self.eng, s["do"], ts(s["at"])
        if do == "request":
            lines = [{**l, "alternatives": [{"condition": a["condition"], "price": a["price"]} for a in l.get("alt", [])]} for l in s["lines"]]
            out = e.request(requester=s["requester"], vendor_id=s["vendor"], lines=lines, at=at, dept=s.get("dept"), justification=s.get("why", ""))
            if s.get("as"):
                self.alias[s["as"]] = out.data["po"]["id"]
        elif do == "approve":
            e.approve(self.r(s["po"]), by=s["by"], at=at, override_budget=s.get("override", False))
        elif do == "reject":
            e.reject(self.r(s["po"]), by=s["by"], at=at, reason=s.get("reason", "no"), max_amount=s.get("max"))
        elif do == "receive":
            lines = []
            for l in s["lines"]:
                n = l.get("serials", l["qty"])
                tag = l.get("tag", f"S{self.step_n}")
                sers = list(n) if isinstance(n, list) else [f"{tag}-{l['sku']}-{i}" for i in range(n)]
                lines.append({"sku": l["sku"], "qty": l["qty"], "condition": l.get("condition", "new"), "serials": sers, "ok": l.get("ok", True), "reasons": l.get("reasons")})
            e.receive(self.r(s["po"]), by=s["by"], at=at, lines=lines)
        elif do == "invoice":
            out = e.invoice(po_id=self.r(s["po"]), number=s["number"], date="2026-" + s["date"], at=at, lines=s["lines"], remit_to=s.get("remit_to"), total=s.get("total"),
                            claim=s.get("claim"), supersedes=self.r(s["supersedes"]) if s.get("supersedes") else None)
            if s.get("as"):
                self.alias[s["as"]] = out.data["invoice"]["id"]
        elif do == "pay":
            iid = self.r(s["invoice"])
            mandate = None
            if s.get("tamper"):
                po = e.invoices[iid]["po_id"]
                mandate = e.build_mandate(po, e.invoices[iid]["payable"], at)
                mandate.update(s["tamper"].get("set", {}))
                if s["tamper"].get("rehash"):
                    mandate["hash"] = mandate_hash(mandate)
            out = e.pay(iid, at=at, by=s.get("by", "ap-agent"), mandate=mandate)
            if s.get("as") and out.ok:
                self.alias[s["as"]] = out.data["payment"]["id"]
        elif do == "prepay":
            e.prepay(self.r(s["po"]), at=at)
        elif do == "close_po":
            e.close_po(self.r(s["po"]), at=at)
        elif do == "bank":
            payee = e.vendors[s["vendor"]].payee_id if s.get("vendor") else s["payee"]
            ref = e.payments[self.r(s["pay"])]["ref"] if s.get("pay") else s.get("ref")
            e.bank_record({"id": s["id"], "kind": s.get("kind", "charge"), "amount": s["amount"], "payee": payee, "ref": ref, "source": s.get("source", "sim")}, at=at)
        elif do == "vendor_bank_change":
            e.change_vendor_bank(s["vendor"], new_account=s.get("account", "acct_new_0001"), by=s["by"], at=at)
        elif do == "vendor_bank_verify":
            e.verify_vendor_bank(s["vendor"], by=s["by"], at=at)
        elif do == "close_period":
            e.close_period(s["period"], by=s["by"], at=at)
        elif do == "journal":
            e.manual_journal(by=s["by"], at=at, date="2026-" + s["date"], reason=s.get("reason", "manual"), refs=s.get("refs", ["manual:1"]),
                             lines=[Line(l["account"], l.get("debit", 0), l.get("credit", 0), l.get("party")) for l in s["lines"]])
        elif do == "memo_issued":
            e.credit_memo_issued(s["memo"], at=at)
        else:
            raise ValueError(f"unknown step {do}")


def _matches(d, want: dict) -> bool:
    return (d.kind == want["kind"] and d.outcome == want["outcome"] and (want.get("code") is None or want["code"] in d.codes))


def run_case(case: dict) -> dict:
    run = Run(case)
    res = {"id": case["id"], "title": case["title"], "fault": case["fault"], "planted": case["planted"], "split": case.get("split", "dev")}
    try:
        for s in case["steps"]:
            run.step(s)
    except Exception as ex:  # a crash is a miss, never a pass
        res.update(verdict="error", error=f"{type(ex).__name__}: {ex}", missing=[], forbidden=[], invariants=[])
        return res
    eng, key = run.eng, case["key"]
    decisions = eng.audit.decisions
    facts = eng.facts()
    missing = [f"decision {w['kind']}/{w['outcome']}/{w.get('code')}" for w in key.get("expect", []) if not any(_matches(d, w) for d in decisions)]
    missing += [f"fact {run.sub(f)}" for f in key.get("expect_facts", []) if run.sub(f) not in facts]
    forbidden = [run.sub(f) for f in key.get("forbid_facts", []) if run.sub(f) in facts]
    inv = eng.invariants()
    flags = [d for d in decisions if d.outcome in FLAG_OUTCOMES]
    res.update(missing=missing, forbidden=forbidden, invariants=inv, decisions=len(decisions), explained=len(decisions) - sum(1 for d in decisions if not eng.explain(d.id)["text"]))
    if case["planted"]:
        res["verdict"] = "caught" if not (missing or forbidden or inv) else "missed"
    else:
        res["flags"] = [f"{d.kind}/{d.outcome}/{','.join(d.codes)}" for d in flags]
        res["verdict"] = "clean_ok" if not (missing or forbidden or inv or flags) else "false_positive"
    return res


def load(name: str) -> list:
    mod = importlib.import_module(f"hyphenate.scenarios.{name}")
    return mod.CASES


def file_sha256(name: str) -> str:
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run_set(name: str, split: str) -> list:
    return [run_case({**c, "split": split}) for c in load(name)]


def summarize(results: list) -> dict:
    planted = [r for r in results if r["planted"]]
    clean = [r for r in results if not r["planted"]]
    return {"planted": len(planted), "caught": sum(r["verdict"] == "caught" for r in planted), "missed": [r["id"] for r in planted if r["verdict"] != "caught"],
            "clean": len(clean), "false_positives": [r["id"] for r in clean if r["verdict"] != "clean_ok"],
            "decisions": sum(r.get("decisions", 0) for r in results), "explained": sum(r.get("explained", 0) for r in results)}
