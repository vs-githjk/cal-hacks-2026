"""#308 (part of #283 T9): Central Computers (SF) bids in the agent path as a MIRROR seller from its real listings."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
from advocate import checks
from policy import make_bid, mirror_seller, seller
from shield.core import screen as shield_screen

SKU = "rtx 5070 ti"
LABEL = "MIRROR: real Central Computers listing captured Oct 24 21:12 UTC via Apify. Central Computers is not a partner."
CASE_305 = {"psu": {"wattage": 850, "pcie_16pin": 1}, "case": {"max_gpu_length_mm": 305}}


def need(condition="new"):
    return {"id": "need-308", "buyer_id": "b1", "consent": True, "auction_window_s": 60, "source": "live",
            "items": [{"sku_spec": SKU, "condition": condition, "variant": "retail", "quantity": 1}]}


def cc_bid(clearance_mm=None):
    return make_bid(need(), mirror_seller("central_computers_sf", clearance_mm))


def test_the_bid_is_mirror_at_the_listed_price_with_the_real_link_and_snapshot():
    bid = cc_bid()
    common.validate("Bid", bid)
    [line] = bid["lines"]
    assert bid["origin"] == "MIRROR" and bid["persona"] == "Central Computers (SF)"
    assert bid["source"] == line["listing_url"].strip() and line["listing_url"].startswith("https://www.centralcomputer.com/")
    assert "example.com" not in json.dumps(bid)
    assert bid["mirror_snapshot_id"] == "centralcomputers-20261024T2112Z"
    assert line["unit_price"] == 1249.99 == bid["total_landed_price"] and bid["floor_check_passed"]
    assert line["qty_available"] == 3 and line["attrs"]["length_mm"] == 303


def test_the_label_shows_wherever_the_bid_is_shown_and_never_implies_they_joined():
    bid = cc_bid()
    assert bid["mirror_label"] == LABEL and bid["decision_trace"].startswith(LABEL)
    text = json.dumps(bid, ensure_ascii=False)
    assert chr(0x2014) not in text and chr(0x2013) not in text  # no em or en dashes
    for word in ("joined", "our partner", "partner store", "official"):
        assert word not in text.lower()


def test_condition_stays_unknown_never_new():
    for condition in ("new", "open-box", None):
        [line] = make_bid(need(condition), mirror_seller("central_computers_sf"))["lines"]
        assert line["offered_condition"] == "unknown" == line["page_condition"]


def test_the_bid_never_drops_under_its_floor():
    s = mirror_seller("central_computers_sf")
    bid = make_bid(need(), dict(s, discount=0.5))
    assert bid["lines"][0]["unit_price"] == s["listings"][SKU]["floor"] == 1162.49 and bid["floor_check_passed"]


def test_shield_allows_the_bid_from_a_seller():
    out = shield_screen(json.dumps(cc_bid()), {"sender_role": "seller", "payee_of_record": None, "price_history": []},
                        classifier=None)
    assert out["verdict"] == "allow", out["rule_ids"]


def test_sim_sellers_are_unchanged():
    for n in common.SELLERS:
        bid = make_bid(need(), seller(n))
        if bid:
            assert bid["origin"] == "SIM" and bid["source"] == "simulated"
            assert bid["mirror_snapshot_id"] == "sim-pcparts-2026-10-23" and "mirror_label" not in bid


def test_one_305_mm_round_shows_the_mirror_bid_unverified_and_fitting():
    bids = [b for b in (make_bid(need(), seller(n)) for n in common.SELLERS) if b] + [cc_bid(305)]
    cards = {c["bid_id"]: c for c in checks.advise(dict(need(), owned=CASE_305), bids, {}, {}, [], CASE_305)}
    card = cards["bid-need-308-central_computers_sf"]
    assert card["recommendation"] == "caution"  # condition unverified; fit confirmed, so no veto
    kinds = [w["kind"] for w in card["warnings"]]
    assert "unverified" in kinds and "fit" not in kinds and "fit_unknown" not in kinds and "condition" not in kinds
    assert card["source_url"].startswith("https://www.centralcomputer.com/")
    text = json.dumps(card).lower()
    assert "is new" not in text and "listed as new" not in text


def _round_with_cc_line(attrs, in_cap=True):
    """A 305 mm round with one confirmed-fit SIM card and a Central Computers line of the given attrs."""
    s = mirror_seller("central_computers_sf")
    s = dict(s, listings={SKU: dict(s["listings"][SKU], attrs=attrs)})
    cc = make_bid(need(), s)
    sim = make_bid(need(), seller("seller_4"))  # SIM, 303 mm, fits 305
    n = dict(need(), owned=CASE_305, in_cap_bid_ids=[cc["id"], sim["id"]] if in_cap else None)
    cards = checks.advise(n, [cc, sim], {}, {}, [], CASE_305)
    return cc, sim, cards


def test_a_card_over_305_mm_cannot_win_a_305_mm_round():
    tuf = {"category": "gpu", "chipset": "RTX 5070 Ti", "length_mm": 329}
    cc, sim, cards = _round_with_cc_line(tuf)
    assert cards[0]["recommendation"] == "veto" and cards[0]["rule_id"] == "fit.gpu_length"
    assert checks.best_bid([cc, sim], cards)["id"] == sim["id"]


def test_a_card_of_unknown_length_cannot_win_a_305_mm_round():
    rog = {"category": "gpu", "chipset": "RTX 5070 Ti"}  # no maker length
    cc, sim, cards = _round_with_cc_line(rog)
    assert cards[0]["recommendation"] == "veto" and checks.best_bid([cc, sim], cards)["id"] == sim["id"]
    # and the seller agent itself never bids one: only maker-confirmed lengths reach a bid
    for clearance in (None, 305):
        assert mirror_seller("central_computers_sf", clearance)["listings"][SKU]["attrs"]["length_mm"] is not None
    assert mirror_seller("central_computers_sf", 305)["listings"][SKU]["attrs"]["length_mm"] <= 305
