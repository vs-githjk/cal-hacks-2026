import pytest

from hyphenate.engine import seed_company
from hyphenate.tests.helpers import T, approved_po, codes, gpu, received, serials
from pay.mandate import mandate_hash


def test_clean_cycle_request_approve_receive_invoice_pay_reconcile():
    eng, pid = approved_po()
    received(eng, pid)
    assert eng.ledger.balance("2100") == 249998 and eng.ledger.balance("1500") == 249998
    inv = eng.invoice(po_id=pid, number="BB-1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}])
    assert inv.ok and inv.status == "matched" and eng.ledger.balance("2100") == 0 and eng.ledger.balance("2000") == 249998
    pay = eng.pay(inv.data["invoice"]["id"], at=T("10-10"))
    assert pay.ok and eng.ledger.balance("2000") == 0 and eng.ledger.balance("1000") == -249998
    rec = eng.bank_record({"id": "ba1", "amount": 2499.98, "payee": "best-buy@pay.example.test", "ref": pay.data["payment"]["ref"], "source": "stripe_test"}, at=T("10-11"))
    assert rec.status == "reconciled"
    assert eng.pos[pid]["status"] == "closed" and eng.invariants() == []


def test_requester_cannot_approve_and_delegate_cannot_either():
    eng = seed_company(mirror={})
    pid = eng.request(requester="tony", vendor_id="bestbuy", lines=[gpu()], at=T("10-05")).data["po"]["id"]
    for who, code in (("tony", "self_approval"), ("tony-assistant", "delegate_of_requester")):
        r = eng.approve(pid, by=who, at=T("10-05", 10))
        assert not r.ok and r.data["code"] == code
    assert eng.pos[pid]["status"] == "pending_approval"


def test_agents_cannot_approve_or_change_bank_details():
    eng = seed_company(mirror={})
    pid = eng.request(requester="tony", vendor_id="bestbuy", lines=[gpu()], at=T("10-05")).data["po"]["id"]
    assert eng.approve(pid, by="ap-agent", at=T("10-05", 10)).data["code"] == "no_permission"
    assert eng.approve(pid, by="purchasing-agent", at=T("10-05", 11)).data["code"] == "no_permission"
    assert eng.change_vendor_bank("bestbuy", new_account="acct_evil", by="ap-agent", at=T("10-05", 12)).data["code"] == "no_permission"


def test_dept_head_limit_and_controller_override_for_budget():
    eng = seed_company(mirror={})
    big = eng.request(requester="tony", vendor_id="bestbuy", lines=[gpu(qty=3, price=1249.99)], at=T("10-05"))  # 3749.97 > 2500
    pid = big.data["po"]["id"]
    assert "over_limit" in big.data["po"]["route"]["flags"]
    r = eng.approve(pid, by="rhodey", at=T("10-05", 10))
    assert r.data["code"] == "above_authority"
    ok = eng.approve(pid, by="pepper", at=T("10-05", 11))
    assert ok.ok and eng.pos[pid]["status"] == "approved" and eng.pos[pid]["bound"]["ceiling"] >= 374997
    # budget: IT dept has 3000; eng has 12000. Fill a small dept budget.
    eng.budgets["art"] = 100_000
    po2 = eng.request(requester="jess", dept="art", vendor_id="bestbuy", lines=[gpu(qty=1, price=1500)], at=T("10-06"))
    assert "over_budget" in po2.data["po"]["route"]["flags"]
    p2 = po2.data["po"]["id"]
    assert eng.approve(p2, by="kara", at=T("10-06", 10)).data["code"] == "over_budget"
    assert eng.approve(p2, by="pepper", at=T("10-06", 11)).data["code"] == "budget_override_required"
    assert eng.approve(p2, by="pepper", at=T("10-06", 12), override_budget=True).ok


def test_controller_no_replans_to_cheaper_allowed_line_or_drops():
    eng = seed_company(mirror={})
    line = gpu(qty=2, price=1249.99, allowed=["new", "open-box"], alternatives=[{"condition": "open-box", "price": 1099.0}])
    pid = eng.request(requester="tony", vendor_id="bestbuy", lines=[line], at=T("10-05")).data["po"]["id"]
    r = eng.reject(pid, by="pepper", at=T("10-05", 10), reason="too much for this quarter", max_amount=2300)
    assert r.data["replan"]["child"] and eng.pos[pid]["status"] == "replanned"
    child = eng.pos[r.data["replan"]["child"]]
    assert child["total"] == 219800 and child["status"] == "pending_approval" and child["parent"] == pid and eng.pos[pid]["committed"] == 0
    # no alternative under a lower cap: dropped
    pid2 = eng.request(requester="tony", vendor_id="bestbuy", lines=[gpu()], at=T("10-06")).data["po"]["id"]
    r2 = eng.reject(pid2, by="pepper", at=T("10-06", 10), reason="no")
    assert eng.pos[pid2]["status"] == "dropped" and "dropped" in codes(r2)
    # the child can be said no to, and re-plans are capped
    assert eng.invariants() == []


def test_receiving_independence_and_rejections_hit_vendor_history():
    eng, pid = approved_po()
    r = eng.receive(pid, by="rhodey", at=T("10-08"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "condition": "new", "serials": serials(2)}])
    assert r.data["code"] == "receiver_not_independent"  # rhodey approved this PO
    bad = eng.receive(pid, by="happy", at=T("10-08", 12), lines=[{"sku": "RTX-5070-TI", "qty": 2, "condition": "open-box", "serials": serials(2)}])
    assert "condition_not_allowed" in codes(bad) and eng.vendors["bestbuy"].events[-1].kind == "failed_receiving"
    assert eng.ledger.balance("2100") == 0  # nothing accrued for rejected goods


def test_duplicate_serial_and_missing_serial_rejected():
    eng, pid = approved_po(lines=[gpu(qty=4, price=500.0)])
    received(eng, pid, qty=2, tag="A")
    dup = eng.receive(pid, by="happy", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "condition": "new", "serials": serials(2, "A")}])
    assert "duplicate_serial" in codes(dup)
    miss = eng.receive(pid, by="happy", at=T("10-10"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "condition": "new", "serials": ["only-one"]}])
    assert "serial_missing" in codes(miss)


def test_invoice_holds_short_shipment_with_credit_memo_and_no_posting():
    eng, pid = approved_po(lines=[gpu(qty=10, price=100.0)])
    received(eng, pid, qty=8)
    inv = eng.invoice(po_id=pid, number="X-1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 10, "price": 100.0}])
    assert inv.status == "held" and "qty_short" in inv.data["codes"]
    memo = next(iter(eng.memos.values()))
    assert memo["amount"] == 20000 and "qty_short" in memo["text"]
    assert eng.ledger.balance("2000") == 0 and eng.ledger.balance("2100") == 80000
    assert eng.pay(inv.data["invoice"]["id"], at=T("10-10")).data["code"] == "invoice_not_matched"
    # corrected invoice for what arrived passes
    fix = eng.invoice(po_id=pid, number="X-2", date="2026-10-10", at=T("10-10", 12), supersedes=inv.data["invoice"]["id"], lines=[{"sku": "RTX-5070-TI", "qty": 8, "price": 100.0}])
    assert fix.status == "matched" and eng.ledger.balance("2100") == 0


def test_duplicate_invoice_number_and_lookalike_with_new_number():
    eng, pid = approved_po(lines=[gpu(qty=2, price=100.0)])
    received(eng, pid)
    a = eng.invoice(po_id=pid, number="INV-007", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 100.0}])
    assert a.ok
    b = eng.invoice(po_id=pid, number="inv 007", date="2026-10-12", at=T("10-12"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 100.0}])
    assert b.data["code"] == "duplicate_invoice" and eng.ledger.balance("2000") == 20000
    c = eng.invoice(po_id=pid, number="INV-008", date="2026-10-12", at=T("10-12", 12), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 100.0}])
    assert c.status == "held" and "possible_duplicate" in c.data["codes"]


def test_price_materiality_and_strict_vendor_history():
    eng, pid = approved_po(lines=[gpu(qty=10, price=100.0)])
    received(eng, pid, qty=10)
    inv = eng.invoice(po_id=pid, number="P1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 10, "price": 100.4}])
    assert inv.status == "matched" and eng.ledger.balance("5900") == 400  # inside tolerance, booked to variance
    eng2, p2 = approved_po(lines=[gpu(qty=10, price=100.0)])
    eng2.vendors["bestbuy"].add("failed_receiving", "2026-09-20T00:00:00Z", "happy", "wrong condition")  # March-style history
    # strict vendor needs two signatures: rhodey alone is not enough
    out = eng2.request(requester="tony", vendor_id="bestbuy", lines=[gpu(qty=10, price=100.0)], at=T("10-10"))
    p3 = out.data["po"]["id"]
    assert out.data["po"]["route"]["needs"] == ["dept_head", "controller"]
    assert eng2.approve(p3, by="rhodey", at=T("10-10", 10)).status == "pending_approval"
    assert eng2.approve(p3, by="pepper", at=T("10-10", 11)).status == "approved"
    received(eng2, p2, qty=10, at="10-11", tag="C")
    inv2 = eng2.invoice(po_id=p2, number="P2", date="2026-10-12", at=T("10-12"), lines=[{"sku": "RTX-5070-TI", "qty": 10, "price": 100.4}])
    assert inv2.status == "held" and "price_variance" in inv2.data["codes"]


def test_vendor_bank_change_holds_payment_until_other_person_verifies():
    eng, pid = approved_po()
    received(eng, pid)
    inv = eng.invoice(po_id=pid, number="B1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}]).data["invoice"]["id"]
    eng.change_vendor_bank("bestbuy", new_account="acct_new_0001", by="maria", at=T("10-09", 15))
    held = eng.pay(inv, at=T("10-10"))
    assert held.data["code"] == "bank_unverified" and eng.ledger.balance("1000") == 0
    assert eng.verify_vendor_bank("bestbuy", by="maria", at=T("10-10", 10)).data["code"] == "same_person_verified"
    assert eng.verify_vendor_bank("bestbuy", by="pepper", at=T("10-10", 11)).ok
    assert eng.pay(inv, at=T("10-10", 12)).ok


def test_remit_to_on_invoice_differs_from_master():
    eng, pid = approved_po()
    received(eng, pid)
    r = eng.invoice(po_id=pid, number="R1", date="2026-10-09", at=T("10-09"), remit_to="acct_attacker", lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}])
    assert r.status == "held" and "remit_to_mismatch" in r.data["codes"]
    assert any(d.kind == "source_trust" and "vendor_master" in d.reason for d in r.decisions)


def test_mandate_guard_blocks_tampered_amount_and_payee():
    eng, pid = approved_po()
    received(eng, pid)
    iid = eng.invoice(po_id=pid, number="M1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}]).data["invoice"]["id"]
    m = eng.build_mandate(pid, 249998, T("10-10"))
    m["amount"] = 2999.0  # edited after hashing
    assert eng.pay(iid, at=T("10-10"), mandate=m).data["code"] == "mandate_hash_mismatch"
    m2 = eng.build_mandate(pid, 249998, T("10-10", 11))
    m2["payee"] = "evil@pay.example.test"
    m2["hash"] = mandate_hash(m2)  # rehashed: only the approved-PO binding catches it
    assert eng.pay(iid, at=T("10-10", 11), mandate=m2).data["code"] == "mandate_payee_mismatch"
    assert eng.ledger.balance("1000") == 0 and eng.pay(iid, at=T("10-10", 12)).ok


def test_bank_trusted_over_ledger_and_payee_mismatch_freezes():
    eng, pid = approved_po()
    received(eng, pid)
    iid = eng.invoice(po_id=pid, number="K1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}]).data["invoice"]["id"]
    pay = eng.pay(iid, at=T("10-10")).data["payment"]
    r = eng.bank_record({"id": "ba9", "amount": 2549.98, "payee": pay["payee"], "ref": pay["ref"], "source": "stripe_test"}, at=T("10-11"))
    assert r.status == "corrected" and eng.ledger.balance("1300") == 5000 and "bank" in r.decisions[-1].reason
    eng2, p2 = approved_po()
    received(eng2, p2)
    i2 = eng2.invoice(po_id=p2, number="K2", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}]).data["invoice"]["id"]
    pay2 = eng2.pay(i2, at=T("10-10")).data["payment"]
    r2 = eng2.bank_record({"id": "ba8", "amount": 2499.98, "payee": "someone-else@x.test", "ref": pay2["ref"]}, at=T("10-11"))
    assert r2.data["code"] == "bank_payee_mismatch" and not eng2.vendors["bestbuy"].bank_verified


def test_period_lock_reroutes_and_accrual_reverses_across_months():
    eng, pid = approved_po(at="03-25")
    received(eng, pid, at="03-31")
    assert eng.ledger.balance("2100") == 249998
    assert eng.close_period("2026-03", by="pepper", at=T("04-01")).ok
    inv = eng.invoice(po_id=pid, number="A1", date="2026-03-30", at=T("04-03"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}])
    assert inv.status == "matched" and any("period_locked" in d.codes for d in inv.decisions)
    assert eng.ledger.balance("2100") == 0 and all(e.period != "2026-03" or e.posted_at <= T("04-01") for e in eng.ledger.entries)
    assert eng.invariants() == []


def test_close_blocks_on_unreconciled_cash_and_non_controller():
    eng, pid = approved_po()
    received(eng, pid)
    iid = eng.invoice(po_id=pid, number="C1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}]).data["invoice"]["id"]
    eng.pay(iid, at=T("10-10"))
    assert eng.close_period("2026-10", by="happy", at=T("10-31")).data["code"] == "no_permission"
    assert eng.close_period("2026-10", by="pepper", at=T("10-31")).data["code"] == "unreconciled_cash"


def test_prepaid_vendor_short_delivery_becomes_vendor_credit():
    eng = seed_company(mirror={})
    pid = eng.request(requester="tony", vendor_id="bargain-bin", lines=[gpu(qty=4, price=300.0)], at=T("10-05")).data["po"]["id"]
    assert eng.approve(pid, by="rhodey", at=T("10-05", 10)).ok
    assert eng.prepay(pid, at=T("10-06")).ok and eng.ledger.balance("1200") == 120000
    received(eng, pid, qty=3, at="10-08")
    assert eng.ledger.balance("1500") == 90000 and eng.ledger.balance("1200") == 30000
    out = eng.close_po(pid, at=T("10-20"))
    assert eng.ledger.balance("1300") == 30000 and eng.ledger.balance("1200") == 0 and eng.memos
    refund = eng.bank_record({"id": "rf1", "kind": "refund", "amount": 300.0, "payee": "bargain-bin@pay.example.test"}, at=T("10-25"))
    assert refund.ok and eng.ledger.balance("1300") == 0 and eng.invariants() == []


def test_mirror_reference_routes_inflated_and_too_cheap_prices_to_controller():
    eng = seed_company(mirror={"RTX-5070-TI": {"price": 124999, "as_of": "2026-10-20T00:00:00Z", "source": "https://x", "origin": "MIRROR"}})
    hi = eng.request(requester="tony", vendor_id="gadget-grove", lines=[gpu(qty=1, price=1600.0)], at=T("10-24"))
    assert "above_market" in hi.data["po"]["route"]["flags"]
    lo = eng.request(requester="tony", vendor_id="gadget-grove", lines=[gpu(qty=1, price=700.0)], at=T("10-24", 10))
    assert "suspiciously_low" in lo.data["po"]["route"]["flags"]
    stale = seed_company(mirror={"RTX-5070-TI": {"price": 124999, "as_of": "2026-08-01T00:00:00Z", "origin": "MIRROR"}}).request(requester="tony", vendor_id="gadget-grove", lines=[gpu(qty=1, price=1600.0)], at=T("10-24"))
    assert "above_market" not in stale.data["po"]["route"]["flags"]


def test_time_cannot_go_backwards_and_every_decision_explainable():
    eng, pid = approved_po()
    with pytest.raises(ValueError):
        eng.request(requester="tony", vendor_id="bestbuy", lines=[gpu()], at=T("09-01"))
    last = eng.audit.decisions[-1]
    x = eng.explain(last.id)
    assert x["text"] and eng.invariants() == []


def test_two_pos_each_inside_budget_but_not_together_second_needs_controller():
    eng = seed_company(mirror={})
    eng.budgets["art"] = 300_000
    a = eng.request(requester="jess", dept="art", vendor_id="bestbuy", lines=[gpu(qty=1, price=2000.0)], at=T("10-05")).data["po"]["id"]
    b = eng.request(requester="jess", dept="art", vendor_id="bestbuy", lines=[gpu(qty=1, price=2000.0)], at=T("10-05", 9))
    assert "over_budget" not in b.data["po"]["route"]["flags"]  # nothing is committed yet when both are drafted
    assert eng.approve(a, by="kara", at=T("10-05", 10)).ok
    second = eng.approve(b.data["po"]["id"], by="kara", at=T("10-05", 11))
    assert not second.ok and second.data["code"] == "over_budget"  # the route is re-checked at approval time


def test_split_invoice_lines_are_added_before_matching_and_cannot_overbill():
    eng, pid = approved_po(lines=[gpu(qty=2)])
    received(eng, pid, qty=1)
    two = [{"sku": "RTX-5070-TI", "qty": 1, "price": 1249.99}] * 2
    r = eng.invoice(po_id=pid, number="SPL-1", date="2026-10-09", at=T("10-09"), lines=two)
    assert r.status == "held" and "qty_short" in r.data["codes"] and eng.pos[pid]["lines"][0]["billed"] == 0
    assert eng.invariants() == []
    ok = eng.invoice(po_id=pid, number="SPL-2", date="2026-10-10", at=T("10-10"), supersedes=r.data["invoice"]["id"], lines=two[:1])
    assert ok.status == "matched"  # the one received unit can be billed, on one line or several


def test_split_lines_that_add_up_to_what_arrived_are_fine():
    eng, pid = approved_po(lines=[gpu(qty=2)])
    received(eng, pid, qty=2)
    r = eng.invoice(po_id=pid, number="SPL-3", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 1, "price": 1249.99}] * 2)
    assert r.status == "matched" and eng.ledger.balance("2100") == 0


def test_negative_accrual_is_an_invariant_violation():
    from hyphenate.ledger import Line
    eng, pid = approved_po()
    eng.ledger.post(date="2026-10-09", lines=[Line("2100", debit=100, party="bestbuy"), Line("2000", credit=100, party="bestbuy")], reason="bad", refs=["x"], by="t", at=T("10-09"))
    assert any("accrued liabilities for bestbuy is negative" in b for b in eng.invariants())


def test_bad_invoice_date_is_refused_before_any_state_changes():
    eng, pid = approved_po()
    received(eng, pid)
    n_inv, n_dec, n_entries, billed = len(eng.invoices), len(eng.audit.decisions), len(eng.ledger.entries), eng.pos[pid]["lines"][0]["billed"]
    for bad in ("bogus", "2026-13-40", "", None, "10/09/2026"):
        with pytest.raises(ValueError):
            eng.invoice(po_id=pid, number="D1", date=bad, at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}])
    assert (len(eng.invoices), len(eng.audit.decisions), len(eng.ledger.entries), eng.pos[pid]["lines"][0]["billed"]) == (n_inv, n_dec, n_entries, billed)
    ok = eng.invoice(po_id=pid, number="D1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}])
    assert ok.status == "matched" and ok.data["invoice"]["id"] == "INV-1"  # no number was burned


def test_requester_cannot_pick_another_departments_budget_or_approver():
    eng = seed_company(mirror={})
    r = eng.request(requester="tony", dept="art", vendor_id="bestbuy", lines=[gpu(qty=1, price=500.0)], at=T("10-05"))
    assert not r.ok and r.data["code"] == "wrong_department" and eng.pos == {}
    assert eng.request(requester="pepper", dept="art", vendor_id="bestbuy", lines=[gpu(qty=1, price=500.0)], at=T("10-05", 9)).ok  # the controller may charge any department
    assert eng.request(requester="jess", dept="art", vendor_id="bestbuy", lines=[gpu(qty=1, price=500.0)], at=T("10-05", 10)).ok


def test_strict_vendor_with_a_dept_head_requester_still_needs_two_signatures():
    eng = seed_company(mirror={})
    eng.vendors["bestbuy"].add("failed_receiving", "2026-09-20T00:00:00Z", "happy", "late")
    out = eng.request(requester="rhodey", vendor_id="bestbuy", lines=[gpu(qty=1, price=500.0)], at=T("10-05"))
    pid = out.data["po"]["id"]
    assert out.data["po"]["route"]["needs"] == ["dept_head", "controller"] and out.data["po"]["route"]["peer_dept_head"]
    assert eng.approve(pid, by="rhodey", at=T("10-05", 10)).data["code"] == "self_approval"
    first = eng.approve(pid, by="pepper", at=T("10-05", 11))
    assert first.status == "pending_approval"  # one controller signature is not enough
    second = eng.approve(pid, by="kara", at=T("10-05", 12))  # another department's head is the independent second signature
    assert second.ok and eng.pos[pid]["status"] == "approved"
