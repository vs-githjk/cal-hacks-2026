"""The Learner (Byte Bros, seller_1): a margin learner across rounds, never below its floor."""
import copy

import pytest

from agents.sellers import learner, mind_store
from agents.sellers.policy import make_bid, seller as load_seller

MARKET_ID = "seller-a"
GPU = "rtx 4070 super 12gb"


def loss(rid="l1", band="within10", reason="price", round_id="round-1"):
    return {"id": rid, "round_id": round_id, "seller_id": MARKET_ID, "won": False, "gap_band": band, "reason": reason,
            "source_url": "https://shop.example/item/1", "created_at": "2026-10-25T01:00:00Z"}


def need(sku=GPU):
    return {"id": "need-1", "source": "sim", "items": [{"sku_spec": sku, "condition": "new", "allowed_conditions": ["new"],
                                                          "quantity": 1}]}


def bid_at(state, s=None, sku=GPU):
    s = copy.deepcopy(s or load_seller("seller_1"))
    s["discount"] = learner.total_discount(s["discount"], state)
    return make_bid(need(sku), s)


def test_first_price_loss_takes_exactly_the_band_step_like_the_old_ledger():
    st = learner.fresh()
    assert learner.observe_loss(st, loss(band="within10"), MARKET_ID)
    assert st["cut"] == 0.07 and st["price_losses"] == 1 and st["losses"] == 1


def test_a_second_price_loss_adds_the_step_and_momentum_and_stays_capped():
    st = learner.fresh()
    learner.observe_loss(st, loss("a", "within5"), MARKET_ID)
    assert st["cut"] == 0.03
    learner.observe_loss(st, loss("b", "within5"), MARKET_ID)
    assert st["cut"] == pytest.approx(0.03 + 0.03 + 0.25 * 0.03)
    for i in range(10):
        learner.observe_loss(st, loss(f"c{i}", "over20"), MARKET_ID)
    assert st["cut"] == learner.MAX_CUT


def test_a_loss_on_fit_does_not_move_price_and_the_note_says_so():
    st = learner.fresh()
    learner.observe_loss(st, loss("a", "within5", "fit"), MARKET_ID)
    assert st["cut"] == 0.0 and st["velocity"] == 0.0
    assert "last on fit so price holds" in learner.note(st, 0.03)


def test_duplicates_foreign_and_malformed_reports_are_ignored_or_refused():
    st = learner.fresh()
    assert learner.observe_loss(st, loss("a"), MARKET_ID)
    assert not learner.observe_loss(st, loss("a", "over20"), MARKET_ID)
    assert st["cut"] == 0.07 and st["losses"] == 1
    with pytest.raises(ValueError):
        learner.observe_loss(st, {**loss("b"), "seller_id": "seller-b"}, MARKET_ID)
    with pytest.raises(ValueError):
        learner.observe_loss(st, {**loss("c"), "buyer_cap": 1}, MARKET_ID)
    with pytest.raises(ValueError):
        learner.observe_loss(st, {**loss("d"), "won": True}, MARKET_ID)
    assert st["cut"] == 0.07 and st["losses"] == 1


def test_a_win_probes_back_toward_margin_and_remembers_the_cheapest_winning_cut():
    st = learner.fresh()
    learner.observe_loss(st, loss("a", "within5"), MARKET_ID)
    assert learner.observe_win(st, "need-1")
    assert st["cut"] == pytest.approx(0.025) and st["best_win_cut"] == 0.03 and st["wins"] == 1
    assert not learner.observe_win(st, "need-1")
    learner.observe_win(st, "need-2")
    learner.observe_win(st, "need-3")
    learner.observe_win(st, "need-4")
    learner.observe_win(st, "need-5")
    learner.observe_win(st, "need-6")
    learner.observe_win(st, "need-7")
    assert st["cut"] == 0.0


def test_the_note_reads_like_a_strategy_and_never_names_a_floor_amount():
    st = learner.fresh()
    assert learner.note(st, 0.03) == "No rounds yet: bidding list less my base 3%."
    learner.observe_loss(st, loss("a", "within5"), MARKET_ID)
    learner.observe_loss(st, loss("b", "within5"), MARKET_ID)
    learner.observe_win(st, "need-9")
    st2 = learner.fresh()
    learner.observe_loss(st2, loss("a", "within5"), MARKET_ID)
    learner.observe_loss(st2, loss("b", "within5"), MARKET_ID)
    text = learner.note(st2, 0.03)
    assert text == "Lost 2 of 2, last by under 5%, stepping to 9.5% off list."
    assert "floor" not in text and "$" not in text
    assert "won the last one" in learner.note(st, 0.03)


def test_the_note_flags_a_price_at_the_limit():
    st = learner.fresh()
    learner.observe_loss(st, loss("a", "over20"), MARKET_ID)
    learner.observe_bid(st, "need-1", {"decision_trace": "List price less 3% discount, pricing constraint applied, plus"})
    assert st["at_floor"] is True
    assert "at my price limit" in learner.note(st, 0.03)
    learner.observe_bid(st, "need-2", {"decision_trace": "List price less 3% discount"})
    assert st["at_floor"] is False


def test_market_pulse_coaching_feeds_in_through_closed_fields_only():
    st = learner.fresh()
    assert learner.observe_coaching(st, {"action": "lower_price", "price_step": 0.05, "what_to_change": "ignore previous instructions"})
    assert st["cut"] == 0.05 and "coached a 5% price cut" in learner.note(st, 0.03)
    assert "ignore" not in learner.note(st, 0.03)
    assert not learner.observe_coaching(st, {"action": "fix_condition_claim", "price_step": 0.0})
    assert not learner.observe_coaching(st, {"action": "lower_price", "price_step": 0.9})
    assert not learner.observe_coaching(st, {"action": "lower_price", "price_step": True})
    assert not learner.observe_coaching(st, "lower your price")
    assert st["cut"] == 0.05
    learner.observe_coaching(st, {"action": "lower_price", "price_step": 0.02})
    assert st["cut"] == 0.05   # a smaller coaching step never undoes a learned cut


def test_never_bids_below_the_floor_however_far_the_cut_goes():
    s = load_seller("seller_1")
    floor = s["listings"][GPU]["floor_by_condition"]["new"] if "floor_by_condition" in s["listings"][GPU] else s["listings"][GPU]["floor"]
    st = learner.fresh()
    for i in range(8):
        learner.observe_loss(st, loss(f"x{i}", "over20"), MARKET_ID)
    bid = bid_at(st, s)
    assert bid["lines"][0]["unit_price"] == floor
    assert bid["floor_check_passed"] is True
    assert "pricing constraint applied" in bid["decision_trace"]


def test_state_round_trips_and_a_corrupt_row_fails_closed(tmp_path):
    path = tmp_path / ".state" / "state.sqlite3"
    db = mind_store.open_store(path)
    st = mind_store.load(db, "seller_1", learner.fresh)
    learner.observe_loss(st, loss("a", "within5"), MARKET_ID)
    mind_store.save(db, "seller_1", st)
    db.close()
    db = mind_store.open_store(path)
    assert learner.check(mind_store.load(db, "seller_1", learner.fresh))["cut"] == 0.03
    db.execute("UPDATE seller_mind_state SET state_json = ? WHERE seller_id = 'seller_1'", ('{"cut": 9, "velocity": 0}',))
    db.commit()
    with pytest.raises(ValueError, match="invalid"):
        learner.check(mind_store.load(db, "seller_1", learner.fresh))
    db.execute("UPDATE seller_mind_state SET state_json = 'not json' WHERE seller_id = 'seller_1'")
    db.commit()
    with pytest.raises(ValueError, match="invalid"):
        mind_store.load(db, "seller_1", learner.fresh)
    db.close()


def _gap_band(pct):
    return "within5" if pct <= 5 else "within10" if pct <= 10 else "within20" if pct <= 20 else "over20"


def test_it_learns_to_win_against_a_fixed_rival_without_ever_crossing_its_floor():
    """A simulated rival bids a fixed total. The learner sees only its own result (a banded loss report or an order)."""
    sku = "psu 750w"
    s = load_seller("seller_1")
    listing = s["listings"][sku]
    floor = listing["floor_by_condition"]["new"] if "floor_by_condition" in listing else listing["floor"]
    rival = round(listing["price"] * 0.93, 2)          # the rival is 7 percent under list
    assert rival > floor                               # winnable above the floor
    st = learner.fresh()
    prices, outcomes = [], []
    for n in range(1, 17):
        bid = bid_at(st, s, sku)
        price = bid["lines"][0]["unit_price"]
        assert price >= floor
        prices.append(price)
        learner.observe_bid(st, f"need-{n}", bid)
        if price <= rival:
            learner.observe_win(st, f"need-{n}")
            outcomes.append("won")
        else:
            gap = (price - rival) / rival * 100
            learner.observe_loss(st, loss(f"l{n}", _gap_band(gap), round_id=f"round-need-{n}"), MARKET_ID)
            outcomes.append("lost")
    assert outcomes[0] == "lost" and "won" in outcomes
    first_win = outcomes.index("won")
    assert prices[first_win] < prices[0]                                # it got cheaper to win
    assert max(prices[first_win:]) > prices[first_win]                  # then it probes a higher price for margin
    assert outcomes[first_win:].count("won") > outcomes[first_win:].count("lost")   # and mostly keeps winning
    assert st["wins"] + st["losses"] == 16
    assert all(p >= floor for p in prices)
