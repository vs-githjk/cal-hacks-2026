"""Pins the two payment guards in hyphenate/payables.py `_pay_gate` that the 17:00 audit could delete with a green suite:
the payer must be independent of the requester and approvers (sod.payer_independent), and a payment may not
take a PO above the approved ceiling (approval.bind)."""
import pytest

from hyphenate.engine import seed_company
from hyphenate.org import Person
from hyphenate.tests.helpers import T, approved_po, codes, gpu, received

LINES = [{"sku": "RTX-5070-TI", "qty": 2, "price": 1249.99}]


def _matched(eng, pid, number="G1"):
    received(eng, pid)
    out = eng.invoice(po_id=pid, number=number, date="2026-10-09", at=T("10-09"), lines=LINES)
    assert out.ok and out.status == "matched", out.to_dict()
    return out.data["invoice"]["id"]


def _controller_requested_po():
    """Tony (a second controller, so he holds release_payment) asks; Pepper approves; Rhea is an unrelated controller."""
    eng = seed_company(mirror={})
    for pid_, name in (("tony", "Tony Stark"), ("rhea", "Rhea Ross")):
        eng.people[pid_] = Person(pid_, name, "controller", "engineering")
    po = eng.request(requester="tony", vendor_id="bestbuy", lines=[gpu()], at=T("10-05")).data["po"]["id"]
    assert eng.approve(po, by="pepper", at=T("10-05", 10)).ok
    return eng, po, _matched(eng, po)


# ----- requester and approver separation on payment (payables.py:226) -----

def test_the_requester_cannot_release_the_payment_for_their_own_order():
    eng, po, iid = _controller_requested_po()
    out = eng.pay(iid, at=T("10-10"), by="tony")
    assert not out.ok and out.data["code"] == "payer_not_independent"
    assert eng.ledger.balance("1000") == 0 and eng.invoices[iid]["status"] == "matched"
    assert any(d.rule["id"] == "sod.payer_independent" and d.outcome == "denied" for d in out.decisions)


def test_the_approver_cannot_release_the_payment_either():
    eng, po, iid = _controller_requested_po()
    out = eng.pay(iid, at=T("10-10"), by="pepper")
    assert not out.ok and out.data["code"] == "payer_not_independent" and eng.ledger.balance("1000") == 0


def test_an_independent_controller_can_release_it():
    eng, po, iid = _controller_requested_po()
    out = eng.pay(iid, at=T("10-10"), by="rhea")
    assert out.ok and eng.ledger.balance("1000") == -249998


# ----- the approved ceiling (payables.py:236) -----

def test_a_payment_above_the_approved_ceiling_is_denied_and_moves_no_money():
    eng, pid = approved_po()
    iid = _matched(eng, pid)
    ceiling = eng.pos[pid]["bound"]["ceiling"]
    eng.invoices[iid]["payable"] = ceiling + 1  # a record edited after matching; the gate must still hold the line
    out = eng.pay(iid, at=T("10-10"))
    assert not out.ok and out.data["code"] == "over_ceiling"
    assert eng.ledger.balance("1000") == 0 and eng.pos[pid]["paid"] == 0
    assert any(d.rule["id"] == "approval.bind" and d.outcome == "denied" for d in out.decisions)


def test_a_payment_exactly_at_the_ceiling_is_allowed():
    eng, pid = approved_po()
    iid = _matched(eng, pid)
    eng.invoices[iid]["payable"] = eng.pos[pid]["bound"]["ceiling"]
    out = eng.pay(iid, at=T("10-10"))
    assert out.ok and eng.pos[pid]["paid"] == eng.pos[pid]["bound"]["ceiling"]


def test_prepaid_money_counts_toward_the_ceiling():
    eng, pid = approved_po()
    iid = _matched(eng, pid)
    payable = eng.invoices[iid]["payable"]
    eng.pos[pid]["bound"]["ceiling"] = payable + 99
    eng.pos[pid]["prepaid"] = 100  # already out the door, so paying the bill takes the PO one cent over
    out = eng.pay(iid, at=T("10-10"))
    assert not out.ok and out.data["code"] == "over_ceiling"
