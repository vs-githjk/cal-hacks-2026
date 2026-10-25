"""Total cost of ownership: advisory, deterministic, and never a change to the referee's ranking or a veto."""
import json

import pytest

from advocate import checks, mock_data, tco

from advocate.test_checks import ATTRS, NEED, bid


def line_terms(b, **terms):
    b["lines"][0].update(terms)
    return b


def cards_for(bids, track=None):
    return checks.advise(NEED, bids, mock_data.BASELINE, {}, [], None, track=track)


def test_a_dearer_bid_with_a_long_warranty_and_returns_can_win_on_total_cost():
    cheap = line_terms(bid("b1", "seller_1", 590), warranty_months=0, return_window_days=0)
    solid = line_terms(bid("b2", "seller_2", 600), warranty_months=36, return_window_days=30)
    ranking = tco.rank(NEED, [cheap, solid], cards_for([cheap, solid]), {})
    assert [r["bid_id"] for r in ranking["ranking"]] == ["b2", "b1"]
    top = ranking["ranking"][0]
    assert top["landed"] == 600.0 and top["tco"] == 569.4 and ranking["ranking"][1]["tco"] == 590.0
    assert "$10.00 more" in ranking["note"] and "cheaper in effective cost" in ranking["note"] and "36 month warranty" in ranking["note"] and "30 day returns" in ranking["note"]
    assert ranking["advisory"] is True and "referee" in ranking["note"]


def test_all_in_is_never_below_landed_and_the_lower_figure_is_labelled_effective():
    import itertools
    import re
    terms = [(None, None), (0, 0), (36, 30), (120, 90)]
    conds = [("new", "new"), ("open-box", "open-box"), ("refurbished", "refurbished"), ("used", "used")]
    tracks = [{}, {"seller_1": {"deliveries": 40, "rejects": 10, "on_time_rate": 0.7}}]
    for (w, r), (offered, page), track in itertools.product(terms, conds, tracks):
        b = bid("b1", "seller_1", 600, offered=offered, page=page)
        if w is not None:
            line_terms(b, warranty_months=w, return_window_days=r)
        ranking = tco.rank(NEED, [b], cards_for([b]), track)
        row = ranking["ranking"][0]
        assert row["all_in"] >= row["landed"], row  # price plus risk costs can only add
        assert row["tco"] == round(row["all_in"] - row["credit"], 2)
        note = ranking["note"]
        assert float(re.search(r"\$([\d.]+) all in", note).group(1)) >= row["landed"]
        if row["tco"] < row["landed"]:  # a figure under the price is only ever shown as effective cost after warranty value
            assert f"effective cost ${row['tco']:.2f} after ${row['credit']:.2f} of warranty and returns value" in note
            assert f"${row['tco']:.2f} all in" not in note


def test_condition_costs_money_open_box_loses_to_the_same_price_new():
    new = bid("b1", "seller_1", 600)
    openbox = bid("b2", "seller_2", 600, offered="open-box", page="open-box")
    ranking = tco.rank(NEED, [openbox, new], cards_for([openbox, new]), {})["ranking"]
    assert [r["bid_id"] for r in ranking] == ["b1", "b2"] and ranking[1]["tco"] > ranking[0]["tco"]


def test_receiving_rejects_and_late_deliveries_raise_the_cost():
    a, b = bid("b1", "seller_1", 600), bid("b2", "seller_2", 600)
    track = {"seller_1": {"deliveries": 40, "rejects": 10, "on_time_rate": 0.7},
             "seller_2": {"deliveries": 40, "rejects": 0, "on_time_rate": 1.0}}
    ranking = tco.rank(NEED, [a, b], cards_for([a, b]), track)["ranking"]
    assert [r["bid_id"] for r in ranking] == ["b2", "b1"]
    assert ranking[1]["components"]["reject_risk"] > 0 and ranking[1]["components"]["late_risk"] > 0
    assert ranking[0]["components"]["reject_risk"] == 0


def test_a_thin_or_missing_record_is_said_not_assumed():
    a = bid("b1", "seller_1", 600)
    row = tco.rank(NEED, [a], cards_for([a]), {"seller_1": {"deliveries": 2, "rejects": 2, "on_time_rate": 0.0}})["ranking"][0]
    assert row["thin_record"] is True and row["components"]["reject_risk"] == 0  # 2 deliveries prove nothing
    none = tco.rank(NEED, [a], cards_for([a]), {})["ranking"][0]
    assert none["thin_record"] is True and "No track record on file" in tco.rank(NEED, [a], cards_for([a]), {})["note"]


def test_a_missing_warranty_or_return_window_gets_no_credit_and_is_listed():
    a = bid("b1", "seller_1", 600)
    row = tco.rank(NEED, [a], cards_for([a]), {})["ranking"][0]
    assert set(row["missing"]) == {"warranty", "return window"} and row["components"]["warranty_credit"] == 0
    assert "warranty not stated" in tco.rank(NEED, [a], cards_for([a]), {})["note"]


def test_a_vetoed_bid_is_never_ranked_even_when_it_is_cheapest():
    bad = line_terms(bid("b1", "seller_1", 400, offered="new", page="open-box"), warranty_months=36, return_window_days=30)
    ok = bid("b2", "seller_2", 600)
    ranking = tco.rank(NEED, [bad, ok], cards_for([bad, ok]), {})
    assert [r["bid_id"] for r in ranking["ranking"]] == ["b2"] and ranking["excluded"] == ["b1"]


def test_all_vetoed_gives_no_ranking_and_says_so():
    bad = bid("b1", "seller_1", 400, offered="new", page="open-box")
    r = tco.rank(NEED, [bad], cards_for([bad]), {})
    assert r["ranking"] == [] and "No bid is left" in r["note"]


def test_cards_carry_the_ranking_and_the_referee_choice_is_untouched():
    cheap = bid("b1", "seller_1", 590)
    solid = line_terms(bid("b2", "seller_2", 600), warranty_months=36, return_window_days=30)
    cards = cards_for([cheap, solid])
    assert [c["tco"]["rank"] for c in cards] == [2, 1]
    assert all(c["worth_it_note"] == cards[0]["worth_it_note"] for c in cards)
    assert checks.best_bid([cheap, solid], cards)["id"] == "b1"  # advisory only: the lowest landed price still ranks first
    assert "tco" not in json.dumps(cards[0]["call_reason"])


@pytest.mark.parametrize("weird", [None, "x", float("nan"), -5, True])
def test_unreadable_terms_count_as_missing_not_a_crash(weird):
    a = line_terms(bid("b1", "seller_1", 600), warranty_months=weird, return_window_days=weird)
    row = tco.rank(NEED, [a], cards_for([a]), {})["ranking"][0]
    assert set(row["missing"]) == {"warranty", "return window"}


def test_load_track_reads_a_closed_file_and_ignores_junk(tmp_path):
    f = tmp_path / "track.json"
    f.write_text(json.dumps({"seller_1": {"deliveries": 10, "rejects": 1, "on_time_rate": 0.9, "evil": "x"},
                             "seller_2": {"deliveries": "many"}, "../x": {"deliveries": 1}}))
    out = tco.load_track(str(f))
    assert out == {"seller_1": {"deliveries": 10, "rejects": 1, "on_time_rate": 0.9}}
    assert tco.load_track(str(tmp_path / "missing.json")) == {} and tco.load_track(None) == {}
