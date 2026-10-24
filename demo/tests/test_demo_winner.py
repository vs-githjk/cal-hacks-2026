"""T1: the demo winner fits Vidyut's case. The ASUS Prime RTX 5070 Ti (304 mm, maker spec) at Best Buy, $1,299.99
before sales tax, beats cheaper cards that are too long (maker-spec length, cited) or whose length is unknown.

Run from the repo root: python3 -m pytest demo/tests/test_demo_winner.py
"""
import io
from datetime import datetime, timezone

import pytest

from demo import run_demo
from demo.common import Narrator
from demo.goal import build_goal, need_from_goal, vidyut_owned_parts
from demo.beats import owned_attrs
from demo.round import run_round
from demo.sellers import all_sellers, mirror_sellers
from demo.standins import market

NOW = datetime(2026, 10, 24, 5, 40, 0, tzinfo=timezone.utc)
MSI_TRIO_SPEC = "https://www.msi.com/Graphics-Card/GeForce-RTX-5070-Ti-16G-GAMING-TRIO-OC/Specification"
GIGABYTE_SPEC = "https://www.gigabyte.com/Graphics-Card/GV-N507TGAMING-OC-16GD/sp"
ASUS_PRIME_SPEC = "https://www.asus.com/motherboards-components/graphics-cards/prime/prime-rtx5070ti-o16g/techspec/"


def full_run():
    buf = io.StringIO()
    run = run_demo.run_all(now=NOW, say=Narrator(True, buf))
    return run, buf.getvalue()


@pytest.fixture(scope="module")
def result():
    return full_run()


@pytest.fixture(scope="module")
def b2(result):
    return result[0]["beats"]["2"]


def bid_of(b2, seller_id):
    return next(b for b in b2["bids"] if b["seller_id"] == seller_id)


def card_of(b2, seller_id):
    bid = bid_of(b2, seller_id)
    return next(c for c in b2["cards"] if c["bid_id"] == bid["id"])


# (a) the ASUS Prime line is awarded, with the fit stated in numbers

def test_a_best_buy_asus_prime_wins_at_1299_99_with_a_fit_pass(result, b2):
    run, text = result
    win = b2["winner"]
    assert win["seller_id"] == "best-buy" and win["landed"] == 1299.99
    line = bid_of(b2, "best-buy")["lines"][win["line"]]
    assert "asus-prime-nvidia-geforce-rtx-5070-ti" in line["listing_url"] and line["unit_price"] == 1299.99
    assert line["origin"] == "MIRROR" and line["attrs"]["length_mm"] == 304
    card = card_of(b2, "best-buy")
    assert card["recommendation"] == "buy" and card["fit"]["verdict"] == "pass"
    assert any("304 mm within case clearance 305 mm" in c["reason"] for c in card["fit"]["checks"])
    assert "304 mm within case clearance 305 mm" in text


def test_a_three_of_three_runs_award_the_asus_line():
    for _ in range(3):
        run, _ = full_run()
        win = run["beats"]["2"]["winner_bid"]
        assert win["seller_id"] == "best-buy" and win["lines"][run["beats"]["2"]["winner"]["line"]]["unit_price"] == 1299.99


# (b) cards that are too long are out, with the maker's spec page as the source

def test_b_msi_gaming_trio_is_withheld_with_the_fit_rule_and_the_maker_spec_url(result, b2):
    held = {w["model"]: w for w in bid_of(b2, "best-buy")["withheld_lines"]}
    trio = next(w for m, w in held.items() if "GAMING TRIO" in m)
    assert trio["rule_id"] == "fit.gpu_length" and trio["reason"] == "GPU length 338 mm exceeds case clearance 305 mm"
    assert trio["source_url"] == MSI_TRIO_SPEC and trio["unit_price"] == 1249.99
    assert any("GAMING OC" in m for m in held)                          # the 342 mm Gigabyte at the same store
    _, text = result
    assert "withheld MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC at 1,249.99" in text and MSI_TRIO_SPEC in text


def test_b_a_too_long_listing_that_does_bid_is_vetoed_citing_the_maker_spec(b2):
    card = card_of(b2, "ebay-824742")      # the eBay open-box Gigabyte Gaming OC, 342 mm
    assert card["recommendation"] == "veto"
    warn = next(w for w in card["warnings"] if w["rule_id"] == "fit.gpu_length")
    # main #121 closed the advocate warning text (a rule template, no numbers); the 342/305 numbers reach the veto
    # through the card's own fit checks, which carry the fit checker's reason.
    assert warn["text"].startswith("Does not fit") and warn["source_url"] == GIGABYTE_SPEC
    length = next(c for c in card["fit"]["checks"] if c["rule_id"] == "fit.gpu_length")
    assert length["verdict"] == "fail" and "342 mm exceeds case clearance 305 mm" in length["reason"]
    assert b2["winner"]["seller_id"] != "ebay-824742"


def test_b_sim_seller_too_long_card_is_still_vetoed(b2):
    card = card_of(b2, "bargain-bin")
    assert card["recommendation"] == "veto" and card["warnings"][0]["rule_id"] == "fit.gpu_length"


# (c) fit unknown cannot beat a confirmed fit inside the cap

def unknown_length_seller(price=1239.99):
    offer = {"prefix": "bh", "listing": {"stock": True},
             "card": {"id": "bh:synthetic", "name": "Acme RTX 5070 Ti Mystery Edition 16GB", "price": price, "condition": "open-box",
                      "source": "https://example.com/acme-mystery-5070-ti", "snapshot_id": "synthetic-test", "snapshot_date": "2026-10-24T05:00:00Z"}}
    (seller,) = mirror_sellers([offer])
    return seller


def test_c_unknown_length_is_flagged_not_guessed():
    seller = unknown_length_seller()
    assert "length_mm" not in seller.lines[0].attrs


def test_c_cheaper_fit_unknown_bid_ranks_above_but_cannot_win_while_a_fit_pass_is_inside_the_cap():
    goal = build_goal("RTX 5070 Ti that fits my case, under $1,300, by Friday, new or open-box", vidyut_owned_parts(NOW), NOW)
    need = need_from_goal(goal)
    sellers, _ = all_sellers()
    sellers = [s for s in sellers if s.id in ("best-buy", "shady-sam")] + [unknown_length_seller()]
    res = run_round(need, sellers, owned_attrs(vidyut_owned_parts(NOW)), 1300.0, NOW)
    by_seller = {r["seller_id"]: (r, c) for r, c in zip(res["ranking"]["ranked"], res["cards"])}
    unk_rank, unk_card = by_seller["b-h-photo"]
    best_rank, _ = by_seller["best-buy"]
    assert unk_rank["landed"] < best_rank["landed"] and unk_rank["rank"] < best_rank["rank"]    # cheaper, ranked first
    warn = next(w for w in unk_card["warnings"] if w["rule_id"] == "advocate.fit_unknown")
    assert "Fit not confirmed" in warn["text"] and warn["source_url"] == "https://example.com/acme-mystery-5070-ti"
    assert res["winner"]["seller_id"] == "best-buy"


def test_c_a_fit_unknown_bid_may_still_win_when_no_fit_pass_is_inside_the_cap():
    goal = build_goal("RTX 5070 Ti that fits my case, under $1,300, by Friday, new or open-box", vidyut_owned_parts(NOW), NOW)
    res = run_round(need_from_goal(goal), [unknown_length_seller()], owned_attrs(vidyut_owned_parts(NOW)), 1300.0, NOW)
    assert res["winner"]["seller_id"] == "b-h-photo"


# (d) the winner line is honest about tax and shipping

def test_d_the_winner_line_says_before_sales_tax_and_shipping_not_captured(result):
    _, text = result
    line = next(l for l in text.splitlines() if "winner:" in l and "Best Buy" in l)
    assert "$1,299.99" in line and "before sales tax" in line and "shipping: not captured" in line


def test_d_every_winner_line_in_the_run_says_before_sales_tax(result):
    _, text = result
    deal = next(l for l in text.splitlines() if "winning deal:" in l)
    assert "Best Buy at $1,299.99 before sales tax, shipping: not captured" in deal
    r2 = next(l for l in text.splitlines() if "round-2 winner:" in l)
    assert "before sales tax" in r2 and "shipping:" in r2
    for l in text.splitlines():
        if "winner:" in l or "winning deal:" in l:
            assert "before sales tax" in l, l


# (e) cap edge: exactly the cap is inside, one cent over is out

def test_e_landed_exactly_at_the_cap_is_inside_and_one_cent_over_is_out():
    item = {"sku_spec": "rtx 5070 ti", "allowed_conditions": ["new"], "condition": "new"}
    line = {"sku_spec": "rtx 5070 ti", "offered_condition": "new"}
    assert market.line_problems(line, 1300.00, item, 1300.0) == []
    assert market.line_problems(line, 1300.01, item, 1300.0) == ["price: landed $1,300.01 is over the goal cap"]


# the screen bridge replays the same winner (read only: bridge.plan builds the reducer calls, nothing is sent)

def test_bridge_plan_places_the_asus_prime_bid_for_best_buy(result):
    from demo import bridge
    run, _ = result
    steps = bridge.plan(run, delay=0, rounds=1)
    bid = next(s.args for s in steps if s.reducer == "place_bid" and s.args["id"].endswith("-best-buy"))
    assert "asus-prime-nvidia-geforce-rtx-5070-ti" in bid["source"] and bid["lines"][0]["unit_price"] == 1299.99
    mandate = next(s.args for s in steps if s.reducer == "create_mandate")
    assert mandate["amount"] == 1299.99
