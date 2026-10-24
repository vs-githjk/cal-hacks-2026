import sys
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import policy
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


def test_quote_survives_review_and_call_window_for_shared_600_seconds():
    now = datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)
    bid = make_bid(need(GPU), seller("seller_1"), now=now)
    assert datetime.fromisoformat(bid["expires_at"]) == now.replace(minute=10)


def test_below_floor_price_is_raised_to_floor():
    s = seller("seller_1")
    s = dict(s, discount=0.9)
    bid = make_bid(need(GPU), s)
    assert bid["lines"][0]["unit_price"] == s["listings"][GPU]["floor"]
    assert bid["floor_check_passed"]
    assert "pricing constraint applied" in bid["decision_trace"]
    assert "floor" not in bid["decision_trace"].lower()


def test_sim_offer_refuses_nonfinite_price_or_nonpositive_quantity():
    s = copy.deepcopy(seller("seller_1"))
    s["listings"][GPU]["price"] = float("nan")
    assert make_bid(need(GPU), s) is None
    n = need(GPU)
    n["items"][0]["quantity"] = 0
    assert make_bid(n, seller("seller_1")) is None


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
    cheapest = min((make_bid(need(GPU), seller(n))["lines"][0]["unit_price"], n)
                   for n in ("seller_1", "seller_3"))
    assert cheapest[1] == "seller_3"


def test_total_includes_shipping():
    s = seller("seller_2")
    bid = make_bid(need(PSU), s)
    assert bid["total_landed_price"] == round(bid["lines"][0]["unit_price"] + s["shipping"], 2)
    assert sum(line["unit_price"] * line["quantity"] + line["shipping"] for line in bid["lines"]) == bid["total_landed_price"]


def test_mirror_snapshot_offer_refuses_when_shipping_or_floor_is_unknown():
    n = need("rtx 5070 ti")
    n["source"] = "live"
    assert make_bid(n, seller("seller_1")) is None


def _mirror_bid_with_shipping(shipping):
    s = seller("seller_1")
    card = next(c for c in s["mirror_listings"] if c["id"] == "bestbuy:9a072ed6c281")
    card["listing"]["stock"] = True
    s["mirror_inputs"] = {card["id"]: {
        "floor": {"value": 1200.0, "source": "https://seller.example/floor",
                  "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
        "shipping": shipping,
    }}
    n = need("rtx 5070 ti")
    n["source"] = "live"
    return make_bid(n, s)


def test_mirror_bid_keeps_listing_provenance_and_uses_only_supplied_terms():
    shipping = {"value": 0.0, "source": "https://www.bestbuy.com/shipping",
                "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"}
    bid = _mirror_bid_with_shipping(shipping)
    assert bid["origin"] == "MIRROR" and bid["seller_id"] == "seller_1"
    common.validate("Bid", bid)
    line = bid["lines"][0]
    assert line["unit_price"] == 1249.99
    assert line["listing_url"].startswith("https://www.bestbuy.com/")
    assert (line["snapshot_id"], line["snapshot_date"], line["seller_of_record"]) == (
        "bestbuy-20261024T0508Z", "2026-10-24T05:08:39.627Z", "Best Buy")
    assert line["model_number"] == "G507T-16GTC"
    assert line["floor_evidence"]["source"] == "https://seller.example/floor"
    assert "1200.0" not in json.dumps(bid)  # private floor input is never serialized
    assert line["shipping"] == 0.0
    assert line["shipping_evidence"] == {
        "origin": "MIRROR", "source": "https://www.bestbuy.com/shipping",
        "observed_at": "2026-10-24T05:00:00Z"}
    assert line["listing_id"] == "bestbuy:9a072ed6c281"
    assert bid["total_landed_price"] == 1249.99


@pytest.mark.parametrize("shipping", [
    {"value": 0.0, "source": "javascript:alert(1)", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    {"value": 0.0, "source": "https://user:pass@www.bestbuy.com/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    {"value": 0.0, "source": "https://bad host/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    {"value": 0.0, "source": "https://www.bestbuy.com/shipping\n.evil", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    {"value": 0.0, "source": "https://www.bestbuy.com:70000/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    {"value": 0.0, "source": "https://www.bestbuy.com:0/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    {"value": 0.0, "source": "https://www.bestbuy.com/shipping", "observed_at": "2026-10-24T05:00:00", "origin": "MIRROR"},
    {"value": float("inf"), "source": "https://www.bestbuy.com/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    {"value": -0.01, "source": "https://www.bestbuy.com/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    {"value": True, "source": "https://www.bestbuy.com/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
])
def test_mirror_offer_rejects_invalid_observed_shipping_evidence(shipping):
    assert _mirror_bid_with_shipping(shipping) is None


def test_mirror_listings_excludes_sold_history_filename(tmp_path, monkeypatch):
    card = {"id": "fixture", "origin": "MIRROR", "category": "gpu", "price": 1.0,
            "condition": "new", "source": "https://shop.example/item", "listing": {"stock": True}}
    (tmp_path / "ebay_sold-20261024T0000Z.json").write_text(json.dumps([card]), encoding="utf-8")
    (tmp_path / "ebay_live-20261024T0000Z.json").write_text(
        json.dumps([{**card, "id": "live-fixture"}]), encoding="utf-8")
    monkeypatch.setattr(policy, "SNAPSHOTS", tmp_path)
    monkeypatch.setitem(policy.CATALOG, "mirror_assignments", {
        "seller_1": {"ebay_sold": "Shop", "ebay_live": "Shop"}})

    rows = policy._mirror_listings("seller_1")

    assert [row["id"] for row in rows] == ["live-fixture"]


def test_bid_schema_keeps_the_closed_sim_unobserved_zero_shipping_variant():
    bid = make_bid(need(GPU), seller("seller_1"))
    bid["lines"][0]["shipping_evidence"] = {
        "origin": "SIM",
        "source": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/demo/sellers.py",
        "policy": "Shipping amount unobserved; zero is the existing SIM policy."}

    common.validate("Bid", bid)


def test_mirror_alternatives_must_share_seller_of_record_and_snapshot():
    s = seller("seller_1")
    card = next(c for c in s["mirror_listings"] if c["id"] == "bestbuy:9a072ed6c281")
    card["listing"]["stock"] = True
    second = dict(card, id="bestbuy:other", seller_of_record="Other Seller")
    s["mirror_listings"] = [card, second]
    term = {"value": 0.0, "source": "https://www.bestbuy.com/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"}
    floor = {**term, "value": 1200.0, "source": "https://seller.example/floor"}
    s["mirror_inputs"] = {row["id"]: {"floor": floor, "shipping": term} for row in (card, second)}
    n = need("rtx 5070 ti")
    n["source"] = "live"
    assert make_bid(n, s) is None


def test_mirror_offer_does_not_ignore_allowed_conditions():
    s = seller("seller_1")
    card = next(c for c in s["mirror_listings"] if c["id"] == "bestbuy:9a072ed6c281")
    card["listing"]["stock"] = True
    s["mirror_inputs"] = {card["id"]: {
        "floor": {"value": 1200.0, "source": "https://seller.example/floor", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
        "shipping": {"value": 0.0, "source": "https://www.bestbuy.com/shipping", "observed_at": "2026-10-24T05:00:00Z", "origin": "MIRROR"},
    }}
    n = need("rtx 5070 ti")
    n["items"][0]["allowed_conditions"] = ["open-box"]
    assert make_bid(n, s) is None


def test_unknown_condition_snapshot_rows_are_not_seller_offers():
    assert all(c["condition"] != "unknown" for c in seller("seller_1")["mirror_listings"])


def test_sim_refurbished_offer_requires_an_allowed_condition():
    n = need(GPU)
    n["items"][0]["allowed_conditions"] = ["new", "refurbished"]
    bid = make_bid(n, seller("seller_2"))
    assert bid["lines"][0]["offered_condition"] == "refurbished"
