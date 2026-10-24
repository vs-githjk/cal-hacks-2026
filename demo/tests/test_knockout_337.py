"""#337: sealed knockout stages on the demo's own round pipeline (the Python mirror of #336's close_stage)."""
import json
from datetime import datetime, timezone

import pytest

from demo import knockout as K
from demo.beats import owned_attrs
from demo.common import Narrator
from demo.goal import run_beat1
from demo.sellers import all_sellers

NOW = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def setup():
    b1 = run_beat1(NOW, Narrator(False))
    sellers, _ = all_sellers()
    return b1, {s.id: s for s in sellers}


def run(setup, ids, **kw):
    b1, by_id = setup
    return K.run_knockout(b1["need"], [by_id[i] for i in ids], owned_attrs(b1["owned_parts"]), b1["goal"]["cap"], NOW, **kw)


def statuses(stage):
    return {e["seller_id"]: e["status"] for e in stage["entries"]}


def test_the_roster_is_five_sellers_and_stage_1_knocks_out_three_for_real_reasons(setup):
    assert len(K.ROSTER) == 5
    out = run(setup, K.ROSTER)
    s1 = out["stages"][0]
    assert statuses(s1) == {"shady-sam": "knocked_out", "bargain-bin": "knocked_out", "ebay-235887": "knocked_out",
                            "best-buy": "advancing", "gadget-grove": "advancing"}
    why = {e["seller_id"]: e for e in s1["entries"]}
    assert why["shady-sam"]["rule_id"] == "advocate.condition" and why["shady-sam"]["source_url"].startswith("http")
    assert why["bargain-bin"]["rule_id"] == "fit.gpu_length"
    assert why["ebay-235887"]["rule_id"] == "knockout.last_place" and "fit not confirmed" in why["ebay-235887"]["reason"]


def test_survivors_improve_by_their_tactic_and_the_demo_winner_is_champion(setup):
    out = run(setup, K.ROSTER)
    assert [s["stage"] for s in out["stages"]] == [1, 2]
    s2 = {e["seller_id"]: e for e in out["stages"][1]["entries"]}
    assert s2["best-buy"]["offer"] == 1299.99                         # MIRROR holds: its price is the real listing's
    assert s2["gadget-grove"]["offer"] == round(1286.02 - 10.0, 2)    # steps down 10, inside its floor
    assert s2["gadget-grove"]["status"] == "knocked_out" and s2["gadget-grove"]["rule_id"] == "knockout.last_place"
    assert out["champion"]["seller_id"] == "best-buy" and out["champion"]["stage"] == 2 and out["champion"]["landed"] == 1299.99
    assert s2["best-buy"]["status"] == "champion"


def test_no_offer_is_under_its_floor_or_above_the_last_one(setup):
    _, by_id = setup
    out = run(setup, K.ROSTER)
    for o in out["offers"]:
        floors = {l.condition: l.floor for l in by_id[o["seller_id"]].lines}
        assert o["price"] >= floors[o["condition"]]
        assert o["previous"] is None or o["price"] <= o["previous"]


def test_loss_reports_name_the_stage_and_reason_and_never_a_price(setup):
    out = run(setup, K.ROSTER)
    reports = {r["seller_id"]: r for r in K.loss_reports(out, NOW)}
    assert set(reports) == {"shady-sam", "bargain-bin", "ebay-235887", "gadget-grove"}
    assert reports["gadget-grove"]["stage"] == 2 and reports["shady-sam"]["stage"] == 1
    assert {k: r["reason"] for k, r in reports.items()} == {"shady-sam": "condition", "bargain-bin": "fit",
                                                             "ebay-235887": "fit", "gadget-grove": "price"}
    assert reports["gadget-grove"]["id"] == "lr-round-1-s2-gadget-grove"
    for r in reports.values():
        text = json.dumps(r)
        assert "1,299.99" not in text and "1299.99" not in text and "1276.02" not in text   # no price, rival or own


def test_one_stage_round_picks_the_champion_at_the_final_stage(setup):
    out = run(setup, K.ROSTER, max_stages=1)
    assert len(out["stages"]) == 1 and out["champion"]["seller_id"] == "best-buy"
    assert statuses(out["stages"][0])["gadget-grove"] == "knocked_out"


def test_a_lone_survivor_is_champion_at_once(setup):
    out = run(setup, ["shady-sam", "bargain-bin", "best-buy"])
    assert len(out["stages"]) == 1 and out["champion"]["seller_id"] == "best-buy" and out["champion"]["stage"] == 1


def test_no_survivor_means_no_deal_and_nothing_paid(setup):
    out = run(setup, ["shady-sam", "bargain-bin"])
    assert out["champion"] is None and out["result"] == "no deal: every seller was knocked out, nothing is paid"


@pytest.mark.parametrize("bad", [0, 4, True, "3"])
def test_max_stages_is_one_to_three(setup, bad):
    with pytest.raises(ValueError):
        run(setup, K.ROSTER, max_stages=bad)
