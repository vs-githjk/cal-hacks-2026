"""The in-memory market ranks like the real one: by the quality-adjusted score (market/rules/scoring.ts), not by landed price.

#373 review, Low: demo/build_sim.py ranked by landed price while the market ranks by adjusted score, so the dry run's champion could
differ from the real result. The weights are read from market/config.ts here, so a change to them breaks this test, not the run."""
from __future__ import annotations

import re
from pathlib import Path

from demo.build_sim import QUALITY, SimMarket, make_clients

CONFIG = Path(__file__).resolve().parents[2] / "market" / "config.ts"


def _bid(bid_id, seller, price, condition="new", perks=("30-day returns",)):
    return {"id": bid_id, "round_id": "r1", "persona": seller, "stated_total": price, "perks": list(perks), "claims": [], "origin": "SIM",
            "source": "simulated", "lines": [{"sku_spec": "gpu", "offered_spec": "", "offered_condition": condition, "unit_price": price,
                                              "quantity": 1}]}


def _round(*bids, allowed=("new", "open-box", "refurbished")):
    m = SimMarket()
    c = make_clients(m)
    c["buyer"].call("post_need", id="n1", buyer_id="vidyut", goal_id="g1", delivery_window="", spend_limit=2000.0, consent=True,
                    auction_window_s=30, origin="SIM",
                    items=[{"sku_spec": "gpu", "condition": "new", "allowed_conditions": list(allowed), "variant": "retail", "quantity": 1,
                            "unit": "each"}])
    c["referee"].call("open_round", round_id="r1", need_id="n1", window_s=30)
    for b in bids:
        c[f"seller:{b['persona']}"].call("place_bid", **b)
    c["referee"].call("close_round", round_id="r1")
    return m


def _ranked(m):
    return [(r[4], r[5], r[11]) for r in sorted(m.rows, key=lambda r: r[5]) if r[5]]


def test_the_weights_are_the_markets_own():
    text = CONFIG.read_text(encoding="utf-8")
    block = re.search(r"condition_adj:\s*\{([^}]*)\}", text).group(1)
    cond = {(a or b): float(v) for a, b, v in re.findall(r'(?:"([\w-]+)"|(\w+)):\s*([\d.]+)', block)}
    assert QUALITY["condition_adj"] == cond
    assert QUALITY["no_returns_adj"] == float(re.search(r"no_returns_adj:\s*([\d.]+)", text).group(1))
    assert QUALITY["min_returns_days"] == int(re.search(r"min_returns_days:\s*(\d+)", text).group(1))


def test_a_cheaper_refurbished_bid_loses_to_a_new_one_the_market_scores_lower():
    # refurbished is +8%: 1000 scores 1080; new with returns at 1050 scores 1050 and wins although it landed higher
    m = _round(_bid("b-refurb", "cheap-refurb", 1000.0, "refurbished"), _bid("b-new", "pricier-new", 1050.0, "new"))
    ranked = _ranked(m)
    assert [p for p, _r, _s in ranked] == ["pricier-new", "cheap-refurb"]
    assert [s for _p, _r, s in ranked] == [1050.0, 1080.0]


def test_no_returns_perk_costs_two_percent_like_the_market():
    m = _round(_bid("b-a", "no-returns", 1000.0, "new", perks=("free shipping",)), _bid("b-b", "returns", 1010.0, "new"))
    assert [p for p, _r, _s in _ranked(m)] == ["returns", "no-returns"]   # 1020 for the first, 1010 for the second


def test_equal_scores_keep_the_order_the_bids_were_sealed_in():
    m = _round(_bid("b-1", "first", 500.0), _bid("b-2", "second", 500.0))
    assert [p for p, _r, _s in _ranked(m)] == ["first", "second"]
