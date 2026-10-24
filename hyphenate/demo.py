"""The moment, end to end, on the seeded studio. `python3 -m hyphenate.demo` narrates it; `--json` prints the structured run.

Everything is SIM (Pixel Forge Games, its people, vendors and bank records) except the MIRROR price reference read from
data/mirror/snapshots. No network, no keys, no model.
"""
from __future__ import annotations

import argparse
import json
import sys

from hyphenate.engine import Engine, seed_company

D = lambda s: f"2026-{s[:5]}T{s[6:8] if len(s) > 5 else '09'}:00:00Z"


def run_story(eng: Engine = None) -> dict:
    eng = eng or seed_company()
    log = []

    def step(label, out):
        log.append({"label": label, "ok": out.ok, "status": out.status, "decision_ids": [d.id for d in out.decisions]})
        return out

    gpu = {"sku": "RTX-5070-TI", "desc": "MSI GeForce RTX 5070 Ti 16GB (MIRROR-priced)", "qty": 3, "price": 1249.99, "condition": "new", "allowed": ["new"], "min_qty": 2}
    po = step("Tony requests 3 GPUs", eng.request(requester="tony", vendor_id="bestbuy", lines=[gpu], at=D("10-24 09"), justification="render farm, 3 nodes")).data["po"]["id"]
    step("Tony tries to approve his own PO", eng.approve(po, by="tony", at=D("10-24 10")))
    step("Rhodes (department head) tries; the PO is above his limit", eng.approve(po, by="rhodey", at=D("10-24 11")))
    rej = step("Pepper (controller) says no, ceiling $2,600", eng.reject(po, by="pepper", at=D("10-24 12"), reason="quarter budget, ceiling $2,600", max_amount=2600))
    po2 = rej.data["replan"]["child"]
    step("Rhodes approves the re-planned PO (2 units, inside his limit)", eng.approve(po2, by="rhodey", at=D("10-24 13")))
    rcv = step("Happy receives: one of two units is open-box", eng.receive(po2, by="happy", at=D("10-25 09"), lines=[
        {"sku": "RTX-5070-TI", "qty": 1, "condition": "new", "serials": ["MSI5070-A001"]}, {"sku": "RTX-5070-TI", "qty": 1, "condition": "open-box", "serials": ["MSI5070-A002"]}]))
    inv = step("Invoice for 2 new units arrives, remit-to account changed", eng.invoice(po_id=po2, number="BB-88213", date="2026-10-25", at=D("10-25 14"),
                                                                                       lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99, "condition": "new"}], remit_to="acct_bb_0099"))
    held_id = inv.data["invoice"]["id"]
    moment = next(d for d in inv.decisions if d.kind == "invoice_match")
    fix = step("Corrected invoice for the 1 accepted unit", eng.invoice(po_id=po2, number="BB-88214", date="2026-10-26", at=D("10-26 09"), supersedes=held_id,
                                                                         lines=[{"sku": "RTX-5070-TI", "qty": 1, "price": 1249.99, "condition": "new"}]))
    fid = fix.data["invoice"]["id"]
    step("Vendor admin changes the bank account the day before payment", eng.change_vendor_bank("bestbuy", new_account="acct_bb_5555", by="maria", at=D("10-26 15"), via="email"))
    step("Payment attempt the next morning", eng.pay(fid, at=D("10-27 09")))
    step("Pepper verifies the bank change by call-back", eng.verify_vendor_bank("bestbuy", by="pepper", at=D("10-27 10")))
    pay = step("Payment released under the mandate", eng.pay(fid, at=D("10-27 11")))
    p = pay.data["payment"]
    step("Stripe test record shows $5 more than the ledger", eng.bank_record({"id": "ba_test_1", "kind": "charge", "amount": 1254.99, "payee": p["payee"], "ref": p["ref"], "source": "stripe_test"}, at=D("10-27 12")))
    step("Pepper closes October", eng.close_period("2026-10", by="pepper", at=D("10-31 17")))
    x = eng.explain(moment.id)
    return {"po": po, "replanned_po": po2, "held_invoice": held_id, "paid_invoice": fid, "moment_decision": moment.id, "explain": x,
            "steps": log, "trial_balance": eng.ledger.trial_balance(), "invariants": eng.invariants(), "engine": eng}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = run_story()
    eng = r.pop("engine")
    if a.json:
        print(json.dumps(r, indent=1, default=str))
        return 0
    print("Pixel Forge Games (SIM). MIRROR price reference from data/mirror/snapshots. No model makes any control decision.\n")
    for s in r["steps"]:
        print(f"[{'ok ' if s['ok'] else 'NO '}] {s['label']:<72} -> {s['status']}")
    print("\nTHE MOMENT: invoice match on the order Tony's controller re-planned")
    print(r["explain"]["text"])
    print(f"\nTrial balance balanced: {r['trial_balance']['balanced']}; invariant problems: {r['invariants'] or 'none'}")
    return 0 if not r["invariants"] else 1


if __name__ == "__main__":
    sys.exit(main())
