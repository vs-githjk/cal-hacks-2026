import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
from policy import load, make_bid

CAT = load()
SUP = {s["name"]: s for s in CAT["suppliers"]}


def need(*items):
    return {"id": "need-1", "buyer_id": "r1", "delivery_window": "tomorrow 6-9am", "consent": True,
            "auction_window_s": 60, "source": "simulated",
            "items": [{"sku_spec": s, "grade": g, "pack_size": p, "quantity": q, "unit": "case"} for s, g, p, q in items]}


ONIONS = ("yellow onions", "US No. 1", "50 lb", 4)
FLOUR = ("all-purpose flour", "Enriched Bleached", "50 lb", 2)


def test_every_bid_validates_and_respects_floor():
    for s in CAT["suppliers"]:
        bid = make_bid(need(ONIONS), s, CAT)
        if bid is None:
            continue
        common.validate("Bid", bid)
        for line in bid["lines"]:
            assert line["unit_price"] >= s["items"][line["sku_spec"]]["floor"]
        assert bid["floor_check_passed"]


def test_floor_clamps_deep_discount():
    s = dict(SUP["Honest Hal"], discount=0.9)
    bid = make_bid(need(ONIONS), s, CAT)
    assert bid["lines"][0]["unit_price"] == s["items"]["yellow onions"]["floor"]
    assert "floor" in bid["decision_trace"]


def test_total_includes_delivery():
    s = SUP["Honest Hal"]
    bid = make_bid(need(ONIONS), s, CAT)
    assert bid["total_landed_price"] == round(bid["lines"][0]["unit_price"] * 4 + s["delivery_fee"], 2)


def test_spec_mismatch_skipped():
    assert make_bid(need(FLOUR), SUP["Golden Mill Supply"], CAT) is None  # 40 lb vs 50 lb
    assert make_bid(need(FLOUR), SUP["Valley Produce Co."], CAT) is None  # doesn't carry it


def test_spec_swapper_flagged_in_trace():
    bid = make_bid(need(ONIONS), SUP["Shady Sam"], CAT)
    assert bid is not None
    assert "SPEC SWAP" in bid["decision_trace"] and "US No. 2" in bid["decision_trace"]
    assert "ships today" in bid["claims"]
    common.validate("Bid", bid)
