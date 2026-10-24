import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
from policy import make_bid, seller

GPU, PSU, CASE = "rtx 4070 super 12gb", "psu 850w", "case"


def need(*skus):
    return {"id": "need-1", "buyer_id": "b1", "consent": True, "auction_window_s": 60, "source": "simulated",
            "items": [{"sku_spec": s, "condition": "new", "variant": "retail", "quantity": 1,
                       "grade": "new", "pack_size": "1"} for s in skus]}


def test_sellers_match_common():
    assert all(seller(n)["listings"] for n in common.SELLERS)


def test_every_bid_validates_and_respects_floor():
    for n in common.SELLERS:
        s = seller(n)
        bid = make_bid(need(GPU, PSU, CASE, "psu 750w", "rx 7800 xt 16gb"), s)
        common.validate("Bid", bid)
        assert bid["origin"] == "SIM" and bid["source"] == "simulated"
        assert bid["floor_check_passed"]
        for line in bid["lines"]:
            assert line["unit_price"] >= s["listings"][line["sku_spec"]]["floor"]


def test_below_floor_price_is_raised_to_floor():
    s = seller("seller_1")
    s = dict(s, discount=0.9)
    bid = make_bid(need(GPU), s)
    assert bid["lines"][0]["unit_price"] == s["listings"][GPU]["floor"]
    assert bid["floor_check_passed"] and "floor" in bid["decision_trace"]


def test_partial_bid_and_none():
    bid = make_bid(need(GPU, CASE), seller("seller_3"))  # seller_3 has no case
    assert [l["sku_spec"] for l in bid["lines"]] == [GPU]
    assert "case" in bid["decision_trace"]
    assert make_bid(need(CASE), seller("seller_3")) is None


def test_trap_listing_claims_new_but_page_says_open_box():
    line = make_bid(need(GPU), seller("seller_3"))["lines"][0]
    assert line["offered_condition"] == "new" and line["page_condition"] == "open-box"
    assert line["listing_url"].startswith("https://example.com/")
    assert line["attrs"]["length_mm"] > 0
    cheapest = min((make_bid(need(GPU), seller(n))["lines"][0]["unit_price"], n) for n in common.SELLERS)
    assert cheapest[1] == "seller_3"


def test_total_includes_shipping():
    s = seller("seller_2")
    bid = make_bid(need(PSU), s)
    assert bid["total_landed_price"] == round(bid["lines"][0]["unit_price"] + s["shipping"], 2)
