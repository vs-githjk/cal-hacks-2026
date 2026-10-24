from pathlib import Path

from data.claim_check import page_facts
from data.three_way import three_way_match

PO = {"sku_spec": "RTX 5070 Ti", "condition": "new", "price": 1299.99, "quantity": 2}
PAGE = {"price": 1299.99, "condition": "new"}
LISTING = {"url": "https://store.example/p", "page": PAGE, "claims": [{"result": "verified", "reason": "the page shows new"}]}
DELIVERY = {"condition": "new", "quantity": 2, "ok": True, "reasons": []}


def codes(out):
    return [m["code"] for m in out["mismatches"]]


def test_everything_agrees_is_a_match():
    out = three_way_match(PO, LISTING, DELIVERY, origin="SIM")
    assert out["result"] == "match" and out["mismatches"] == [] and out["missing"] == [] and out["origin"] == "SIM"


def test_price_differs():
    out = three_way_match(PO, {**LISTING, "page": {**PAGE, "price": 1249.99}}, DELIVERY)
    assert out["result"] == "mismatch" and codes(out) == ["price_differs"]
    assert out["mismatches"][0]["detail"] == "sources disagree: PO says $1,299.99, page says $1,249.99"


def test_condition_on_the_page():
    out = three_way_match(PO, {**LISTING, "page": {**PAGE, "condition": "open-box"}}, DELIVERY)
    assert codes(out) == ["condition_page"] and out["mismatches"][0]["detail"] == "sources disagree: page says open box"


def test_condition_delivered():
    out = three_way_match(PO, LISTING, {**DELIVERY, "condition": "open-box"})
    assert codes(out) == ["condition_delivered"] and out["mismatches"][0]["detail"] == "sources disagree: delivered open box, PO says new"


def test_a_false_claim():
    out = three_way_match(PO, {**LISTING, "claims": [{"result": "false", "reason": "claim says new; the page shows refurbished"}]}, DELIVERY)
    assert codes(out) == ["claim_false"] and "the page shows refurbished" in out["mismatches"][0]["detail"]


def test_short_delivery():
    out = three_way_match(PO, LISTING, {**DELIVERY, "quantity": 1})
    assert codes(out) == ["quantity_short"] and out["mismatches"][0]["detail"] == "delivered 1 of 2"


def test_failed_receiving_check():
    out = three_way_match(PO, LISTING, {**DELIVERY, "ok": False, "reasons": ["serial mismatch", "box opened"]})
    assert codes(out) == ["delivery_failed"] and "serial mismatch; box opened" in out["mismatches"][0]["detail"]


def test_two_mismatches_are_both_listed():
    out = three_way_match(PO, {**LISTING, "page": {**PAGE, "price": 1000.0}}, {**DELIVERY, "quantity": 1})
    assert out["result"] == "mismatch" and codes(out) == ["price_differs", "quantity_short"]


def test_unreadable_page_is_unverified_never_match():
    out = three_way_match(PO, {**LISTING, "page": None}, DELIVERY)
    assert out["result"] == "unverified" and "page" in out["missing"]
    assert three_way_match(PO, {**LISTING, "claims": [{"result": "unverified", "reason": "could not verify"}]}, DELIVERY)["result"] == "unverified"


def test_bad_delivery_quantity_is_missing():
    for bad in (True, -1, 1.5, "2", None):
        out = three_way_match(PO, LISTING, {**DELIVERY, "quantity": bad})
        assert out["result"] == "unverified" and "delivery quantity" in out["missing"], bad


def test_sim_liar_page_against_a_po_for_new():
    html = (Path(__file__).resolve().parents[1] / "liar_pages" / "site" / "renew-refurb-gpu-5070ti-lies.html").read_text()
    facts, _ = page_facts(html)
    out = three_way_match({**PO, "price": 719.0}, {"url": "https://liar.example/renew", "page": facts, "claims": []}, DELIVERY, origin="SIM")
    assert out["result"] == "mismatch" and "condition_page" in codes(out)
    assert "page says refurbished" in out["mismatches"][0]["detail"]


def test_over_delivery_is_a_named_mismatch_too():  # #155
    out = three_way_match(PO, LISTING, {**DELIVERY, "quantity": 3})
    assert out["result"] == "mismatch" and codes(out) == ["quantity_over"] and out["mismatches"][0]["detail"] == "delivered 3 of 2"
    assert codes(three_way_match(PO, LISTING, {**DELIVERY, "quantity": 1})) == ["quantity_short"]
    assert three_way_match(PO, LISTING, DELIVERY)["result"] == "match"
