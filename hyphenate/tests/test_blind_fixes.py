"""Fixes after the blind run (Lane C, issue #45): SKU spelling must not hide a MIRROR check, partial deliveries are not
duplicates, and an informational variance is not a finding that needs a person."""
from hyphenate.engine import seed_company
from hyphenate.tests.helpers import T, approved_po, gpu, received

MIRROR = {"RTX-5070-TI": {"price": 129999, "as_of": "2026-10-20T00:00:00Z", "source": "median of 14 retail listings", "origin": "MIRROR"}}


def test_mirror_reference_matches_any_spelling_of_the_sku_and_records_the_trust_reason():
    for spelling in ("rtx 5070 ti", "RTX-5070-TI", "Rtx_5070-Ti ", "RTX  5070   TI"):
        eng = seed_company(mirror=MIRROR)
        out = eng.request(requester="tony", vendor_id="gadget-grove", lines=[{"sku": spelling, "qty": 1, "price": 1600.0}], at=T("10-24"))
        route = out.data["po"]["route"]
        assert "above_market" in route["flags"] and route["needs"] == ["controller"], spelling
        assert any("believed mirror" in n and "dated listing" in n for n in route["notes"])
        d = next(d for d in out.decisions if d.kind == "approval_route")
        assert "above_market" in d.codes and "believed mirror" in d.reason
        assert eng.approve(out.data["po"]["id"], by="rhodey", at=T("10-24", 10)).data["code"] == "controller_required"


def test_price_at_the_threshold_is_not_flagged_and_just_over_is():
    eng = seed_company(mirror=MIRROR)
    at_limit = eng.request(requester="tony", vendor_id="gadget-grove", lines=[gpu(qty=1, price=1494.98)], at=T("10-24"))  # just inside +15 percent of 1299.99
    assert "above_market" not in at_limit.data["po"]["route"]["flags"]
    over = eng.request(requester="tony", vendor_id="gadget-grove", lines=[gpu(qty=1, price=1495.0)], at=T("10-24", 10))
    assert "above_market" in over.data["po"]["route"]["flags"]


def two_partials(eng, pid, second_receipt=True):
    eng.receive(pid, by="happy", at=T("10-08"), lines=[{"sku": "RTX-5070-TI", "qty": 1, "condition": "new", "serials": ["P1"]}])
    first = eng.invoice(po_id=pid, number="OK-3001", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 1, "price": 1249.99}])
    if second_receipt:
        eng.receive(pid, by="happy", at=T("10-10"), lines=[{"sku": "RTX-5070-TI", "qty": 1, "condition": "new", "serials": ["P2"]}])
    second = eng.invoice(po_id=pid, number="OK-3002", date="2026-10-11", at=T("10-11"), lines=[{"sku": "RTX-5070-TI", "qty": 1, "price": 1249.99}])
    return first, second


def test_second_identical_invoice_after_a_new_receipt_is_not_a_duplicate_and_is_paid():
    eng, pid = approved_po(lines=[gpu(qty=2)])
    first, second = two_partials(eng, pid)
    assert first.status == "matched" and second.status == "matched" and not second.data["invoice"]["findings"]
    assert eng.pay(first.data["invoice"]["id"], at=T("10-12")).ok and eng.pay(second.data["invoice"]["id"], at=T("10-12", 10)).ok
    assert eng.invariants() == []


def test_identical_invoice_with_no_new_receipt_is_still_held_as_a_possible_duplicate():
    eng, pid = approved_po(lines=[gpu(qty=2)])
    first, second = two_partials(eng, pid, second_receipt=False)
    assert second.status == "held" and "possible_duplicate" in second.data["codes"]
    # four units received at once, the same two-unit bill twice under new numbers: the goods would cover it, so the look-alike alone holds it
    eng2, p2 = approved_po(lines=[gpu(qty=4, price=500.0)])
    eng2.receive(p2, by="happy", at=T("10-08"), lines=[{"sku": "RTX-5070-TI", "qty": 4, "condition": "new", "serials": list("abcd")}])
    a = eng2.invoice(po_id=p2, number="LK-1", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 500.0}])
    b = eng2.invoice(po_id=p2, number="LK-2", date="2026-10-10", at=T("10-10"), lines=[{"sku": "RTX-5070-TI", "qty": 2, "price": 500.0}])
    assert a.status == "matched" and b.status == "held" and b.data["codes"] == ["possible_duplicate"]


def test_immaterial_variance_is_info_not_a_finding_and_is_still_booked_and_paid():
    eng, pid = approved_po(lines=[gpu(qty=1)])
    received(eng, pid, qty=1)
    r = eng.invoice(po_id=pid, number="OK-2001", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 1, "price": 1250.49}])
    inv = r.data["invoice"]
    assert r.status == "matched" and inv["findings"] == []
    assert [i["code"] for i in inv["info"]] == ["price_variance_immaterial"] and "50 cents" in inv["info"][0]["detail"]
    assert eng.ledger.balance("5900") == 50 and eng.pay(inv["id"], at=T("10-10")).ok


def test_a_held_invoice_keeps_its_holds_as_findings_and_its_notes_as_info():
    eng, pid = approved_po(lines=[gpu(qty=2)])
    received(eng, pid, qty=1)
    r = eng.invoice(po_id=pid, number="X", date="2026-10-09", at=T("10-09"), lines=[{"sku": "RTX-5070-TI", "qty": 1, "price": 1250.49}, {"sku": "RTX-5070-TI", "qty": 1, "price": 1250.49}])
    inv = r.data["invoice"]
    assert inv["status"] == "held" and all(f["hold"] for f in inv["findings"]) and {i["code"] for i in inv["info"]} >= {"price_variance_immaterial"}
