"""Run Lane C's blind Hyphenate cases (issue #45) through the public API only. SIM.

    python3 -m hyphenate.scenarios.blind_run            # prints per-case results
    python3 -m hyphenate.scenarios.blind_run --write    # also writes hyphenate/RESULTS-blind.md

The cases (blind_cases.json) were frozen and committed before this runner existed or anything ran. They follow the
README ("money is integer cents everywhere"); the API reads line prices and journal amounts as dollars, so this runner
divides case money by 100 on the way in (reported as a README/API mismatch). Roles map to the blank studio's people.
Scoring is the rule frozen in the case file. HTTP errors are runner errors, never caught or missed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from hyphenate.api import app

HERE = Path(__file__).resolve().parent
CASES = HERE / "blind_cases.json"
OUT = HERE.parent / "RESULTS-blind.md"
H = "/v1/hyphenate"
ROLES = {"$requester": "tony", "$dept_head": "rhodey", "$controller": "pepper", "$receiver": "happy",
         "$ap_clerk": "maria", "$vendor_contact": "maria", "$vendor": "gadget-grove", "$vendor2": "bargain-bin"}
NEED_TO_PERSON = {"dept_head": "rhodey", "controller": "pepper"}
GOOD_INVOICE = ("matched", "matched_prepaid", "paid")
OBSERVATIONS = {
    "b24": "missed. The $1,600.00 PO routed to the department head only: route flags and evidence were empty, so no MIRROR "
           "reference was consulted for 'rtx 5070 ti' in the blank studio (the README says a PO over 15 percent above a fresh "
           "MIRROR reference routes to the controller). Worth checking the SKU-to-reference lookup and freshness in the empty story.",
    "k02": "false flag by the frozen rule only: the invoice was matched and paid; the finding was the informational "
           "price_variance_immaterial. Lane D may treat this as correct behavior; it is reported, not re-scored.",
    "k03": "real false flag: after two partial deliveries, the second correct invoice (same lines and total as the first) was "
           "held as possible_duplicate and payment was refused. The duplicate rule (same vendor, PO, lines, total within 60 days) "
           "does not account for cumulative partial receipts.",
}


def _dollars(cents):
    return round(cents / 100, 2)


def _line(l):
    out = {"sku": l["sku"], "qty": l["qty"], "price": _dollars(l["price"]), "condition": l.get("condition", "new")}
    if "allowed" in l:
        out["allowed"] = l["allowed"]
    return out


class Run:
    def __init__(self, client):
        self.c, self.po, self.vendor, self.invoice, self.serial = client, None, None, None, 0
        self.period = None

    def _role(self, v):
        return ROLES.get(v, v)

    def step(self, s):
        """-> (flagged: bool, error: str|None, codes: list[str], note: str)"""
        op = s["op"]
        if op == "requisition":
            self.vendor = self._role(s["vendor"])
            r = self.c.post(H + "/requisitions", json={"requester": self._role(s["requester"]), "vendor_id": self.vendor,
                                                       "lines": [_line(l) for l in s["lines"]]})
            return self._outcome(r, lambda j: setattr(self, "po", j["po"]["id"]) if j.get("po") else None)
        if op == "approve_all":
            for _ in range(4):
                po = self.c.get(f"{H}/pos/{self.po}").json()
                if po["status"] != "pending_approval":
                    return (po["status"] not in ("approved",), None, [], f"PO {po['status']}")
                need = next((n for n in po["route"]["needs"] if n in NEED_TO_PERSON), None)
                if need is None:
                    return (True, None, [], f"no approver for needs {po['route']['needs']}")
                r = self.c.post(f"{H}/pos/{self.po}/approve", json={"by": NEED_TO_PERSON[need]})
                if r.status_code != 200 or not r.json()["ok"]:
                    return self._outcome(r)
            return (True, None, [], "approval did not finish")
        if op == "approve":
            return self._outcome(self.c.post(f"{H}/pos/{self.po}/approve", json={"by": self._role(s["by"])}))
        if op == "receive":
            lines = []
            for l in s["lines"]:
                serials = [f"SN-{self.serial + i}" for i in range(l["qty"])]
                self.serial += l["qty"]
                lines.append({"sku": l["sku"], "qty": l["qty"], "condition": l["condition"], "serials": serials, "ok": l.get("ok", True),
                              **({"reasons": l["reasons"]} if l.get("reasons") else {})})
            return self._outcome(self.c.post(f"{H}/pos/{self.po}/receive", json={"by": self._role(s["by"]), "lines": lines}))
        if op == "invoice":
            body = {"po_id": self.po, "number": s["number"], "date": "2026-10-24", "lines": [_line(l) for l in s["lines"]]}
            if "remit_to" in s:
                body["remit_to"] = s["remit_to"]
            if "total" in s:
                body["total"] = _dollars(s["total"])
            if s.get("supersedes") == "$prev_invoice":
                body["supersedes"] = self.invoice
            r = self.c.post(H + "/invoices", json=body)
            if r.status_code != 200:
                return (False, f"HTTP {r.status_code}: {r.text[:120]}", [], "")
            j = r.json()
            inv = j.get("invoice") or {}
            self.invoice = inv.get("id", self.invoice)
            codes = [f["code"] for f in inv.get("findings", [])]
            held = inv.get("status") not in GOOD_INVOICE or bool(inv.get("findings"))
            return (held or not j["ok"], None, codes or ([j["code"]] if j.get("code") else []), f"invoice {inv.get('status')}")
        if op == "pay":
            return self._outcome(self.c.post(f"{H}/invoices/{self.invoice}/pay", json={}))
        if op == "bank_change":
            return self._outcome(self.c.post(f"{H}/vendors/{self.vendor or ROLES['$vendor']}/bank-change",
                                             json={"new_account": s["new_account"], "by": self._role(s["by"])}))
        if op == "bank_verify":
            return self._outcome(self.c.post(f"{H}/vendors/{self.vendor or ROLES['$vendor']}/bank-verify", json={"by": self._role(s["by"])}))
        if op == "close_period":
            p = {"$last_period": "2026-09", "$current_period": "2026-10"}[s["period"]]
            return self._outcome(self.c.post(f"{H}/periods/{p}/close", json={"by": self._role(s["by"])}))
        if op == "journal":
            p = {"$last_period": "2026-09", "$current_period": "2026-10"}[s["period"]]
            date = {"2026-09": "2026-09-30", "2026-10": "2026-10-24"}[p]
            lines = [{"account": l["account"], "debit": _dollars(l["debit"]), "credit": _dollars(l["credit"])} for l in s["lines"]]
            return self._outcome(self.c.post(H + "/journal", json={"date": date, "period": p, "lines": lines, "reason": s["reason"],
                                                                   "by": "pepper"}))
        return (False, f"unknown op {op}", [], "")

    def _outcome(self, r, on_ok=None):
        if r.status_code != 200:
            return (False, f"HTTP {r.status_code}: {r.text[:120]}", [], "")
        j = r.json()
        if on_ok:
            on_ok(j)
        return (not j.get("ok", False), None, [j["code"]] if j.get("code") else [], j.get("status", ""))


def run_case(case) -> dict:
    c = TestClient(app)
    c.post(H + "/demo/reset?story=empty")
    run = Run(c)
    trace = []
    for i, s in enumerate(case["steps"]):
        flagged, err, codes, note = run.step(s)
        trace.append({"step": i, "op": s["op"], "flagged": flagged, "error": err, "codes": codes, "note": note})
    errors = [t for t in trace if t["error"]]
    if case["planted"]:
        at = case["expect"]["caught_at_or_after_step"]
        hit = next((t for t in trace if t["step"] >= at and t["flagged"]), None)
        early = next((t for t in trace if t["step"] < at and t["flagged"]), None)
        verdict = "caught" if hit else ("runner_error" if errors else "missed")
        if not hit and early:
            verdict = "flagged_early"  # stopped before the planted step, so the planted error was never tested
        return {"id": case["id"], "title": case["title"], "planted": True, "verdict": verdict, "where": hit or early, "trace": trace}
    flags = [t for t in trace if t["flagged"]]
    verdict = "runner_error" if errors else ("false_flag" if flags else "clean_pass")
    return {"id": case["id"], "title": case["title"], "planted": False, "verdict": verdict, "where": flags[0] if flags else None, "trace": trace}


def markdown(results, frozen, sha) -> str:
    P = [r for r in results if r["planted"]]
    C = [r for r in results if not r["planted"]]
    n = lambda rs, v: sum(r["verdict"] == v for r in rs)
    lines = ["# Hyphenate blind planted-error results (SIM)", "",
             f"Run {datetime.now(timezone.utc).isoformat(timespec='seconds')} UTC with `python3 -m hyphenate.scenarios.blind_run --write`, "
             "public API only, blank studio per case.",
             f"Cases: `hyphenate/scenarios/blind_cases.json`, frozen {frozen} and committed before any run (sha256 `{sha}`). Written by "
             "Lane C without reading hyphenate/*.py or the existing case files. No engine code was changed.", "",
             f"**Planted: {n(P, 'caught')} of {len(P)} caught, {n(P, 'missed')} missed, {n(P, 'flagged_early')} stopped before the planted step, "
             f"{n(P, 'runner_error')} runner errors. Clean: {n(C, 'clean_pass')} of {len(C)} passed, {n(C, 'false_flag')} false flags, "
             f"{n(C, 'runner_error')} runner errors.**", "",
             "| case | planted | result | where | codes |", "|---|---|---|---|---|"]
    for r in results:
        w = r["where"]
        where = f"step {w['step']} ({w['op']}): {w['note'] or w['error'] or ''}" if w else "-"
        err = next((t["error"] for t in r["trace"] if t["error"]), "")
        lines.append(f"| {r['id']} {r['title']} | {'yes' if r['planted'] else 'clean'} | {r['verdict']} | {where}{' ERR ' + err if err and r['verdict'] == 'runner_error' else ''} | "
                     f"{', '.join(w['codes']) if w else ''} |")
    misses = [r for r in results if r["verdict"] in ("missed", "false_flag", "flagged_early", "runner_error")]
    lines += ["", "## For Lane D (misses, false flags and anything that needs a look)"]
    lines += [f"- {r['id']} {r['title']}: {r['verdict']}" for r in misses] or ["- none"]
    lines += ["", "## Notes", "- README says money is integer cents everywhere, but the API reads line prices and journal amounts as dollars "
              "(124999 became $124,999.00). The cases follow the README; the runner divides by 100 on the way in.",
              "- There is no human AP clerk in the studio; bank changes in the cases use Maria Hill (vendor admin).",
              "- Planted cases count as caught only at or after the planted step; a refusal earlier means the planted error was never reached.",
              "", "## Observations (written after the run, from the API responses; the verdicts above use the frozen rule unchanged)"]
    lines += [f"- {cid}: {text}" for cid, text in OBSERVATIONS.items() if any(r["id"] == cid for r in results)]
    return "\n".join(lines) + "\n"


def main():
    import hashlib
    data = json.loads(CASES.read_text())
    sha = hashlib.sha256(CASES.read_bytes()).hexdigest()
    results = [run_case(c) for c in data["cases"]]
    for r in results:
        w = r["where"]
        print(f"{r['id']:<4} {r['verdict']:<14} {r['title'][:52]:<52} {('step ' + str(w['step']) + ' ' + w['op'] + ' ' + ','.join(w['codes'])) if w else ''}")
    if "--write" in sys.argv:
        if OUT.exists() and "AFTER-FIXES" in OUT.read_text() and "--force" not in sys.argv:
            sys.exit("RESULTS-blind.md has an AFTER-FIXES section that keeps the original first-run headline; refusing to overwrite it (use --force)")
        OUT.write_text(markdown(results, data["frozen"], sha))


if __name__ == "__main__":
    main()
