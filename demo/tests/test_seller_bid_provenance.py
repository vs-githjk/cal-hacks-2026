from copy import deepcopy
from datetime import datetime, timezone

from demo.common import MIRROR, schema_errors
from demo.sellers import all_sellers, line_price, load_offers, make_bid, mirror_sellers


POLICY_SOURCE = "https://github.com/vs-githjk/cal-hacks-2026/blob/main/demo/sellers.py"
NEED = {"id": "provenance-test", "items": [{"sku_spec": "rtx 5070 ti", "quantity": 1,
                                                  "condition": "new", "allowed_conditions": ["new"]}]}
NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def _known_mirror():
    sellers, _ = all_sellers()
    return next(seller for seller in sellers if seller.origin == MIRROR and seller.id == "best-buy")


def test_known_mirror_bid_maps_snapshot_facts_and_labels_sim_policies():
    seller = _known_mirror()
    source_line = seller.lines[0]
    bid = make_bid(seller, NEED, NOW)

    assert schema_errors("Bid", bid) == []
    line = bid["lines"][0]
    assert bid["seller_of_record"] == "Best Buy"
    assert line["listing_id"] == "bestbuy:9a072ed6c281"
    assert line["seller_of_record"] == "Best Buy"
    assert line["snapshot_id"] == source_line.snapshot_id
    assert line["snapshot_date"] == source_line.snapshot_date
    assert line["shipping"] == seller.shipping == 0.0
    assert "free shipping" not in bid["perks"]
    assert line["floor_evidence"] == {"origin": "SIM", "source": POLICY_SOURCE,
                                      "observed_at": source_line.snapshot_date}
    assert line["shipping_evidence"] == {
        "origin": "SIM", "source": POLICY_SOURCE,
        "policy": "Shipping amount unobserved; zero is the existing SIM policy.",
    }
    assert "floor" not in line
    assert "MIRROR asking price" in bid["decision_trace"]
    assert "SIM operator floor" in bid["decision_trace"]
    assert "SIM shipping policy" in bid["decision_trace"]


def test_unknown_marketplace_sellers_are_ineligible_and_report_the_source():
    offers, _ = load_offers()
    raw_sellers = mirror_sellers(offers)
    unknown = [seller for seller in raw_sellers if seller.seller_of_record is None]
    assert unknown
    assert all(make_bid(seller, NEED, NOW) is None for seller in unknown)

    eligible, skips = all_sellers()
    assert not {seller.id for seller in eligible} & {seller.id for seller in unknown}
    for seller in unknown:
        line = seller.lines[0]
        assert any("seller identity not captured" in skip and line.listing_url in skip
                   and line.snapshot_id in skip for skip in skips)


def test_bid_schema_rejects_unregistered_sim_source_and_numeric_floor_leaks():
    bid = make_bid(_known_mirror(), NEED, NOW)
    bad_source = deepcopy(bid)
    bad_source["lines"][0]["floor_evidence"]["source"] = "https://attacker.example/floor-policy"
    assert any("floor_evidence/source" in error for error in schema_errors("Bid", bad_source))

    leaked_line_floor = deepcopy(bid)
    leaked_line_floor["lines"][0]["floor"] = 1162.49
    assert any("floor" in error for error in schema_errors("Bid", leaked_line_floor))

    leaked_provenance_floor = deepcopy(bid)
    leaked_provenance_floor["lines"][0]["floor_evidence"]["floor"] = 1162.49
    assert any("floor_evidence" in error and "floor" in error
               for error in schema_errors("Bid", leaked_provenance_floor))


def test_floor_clamp_reason_does_not_repeat_its_numeric_value():
    seller = _known_mirror()
    line = seller.lines[0]
    line.discount = 0.20
    price, reason = line_price(line)

    assert price == line.floor
    assert reason == "held at the configured floor"
    bid = make_bid(seller, NEED, NOW)
    assert "held at the configured floor" in bid["decision_trace"]
    assert not any(f"held at floor {line.floor}" in note for note in [bid["decision_trace"]])
