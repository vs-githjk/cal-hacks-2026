"""#337: a seller still in after a knockout stage makes one improved sealed offer, never below its floor."""
import math

import pytest

from agents.sellers.tactics import STEP_USD, TACTICS, next_offer


def test_hold_keeps_the_old_offer():
    assert next_offer("hold", 1299.99, 1200.0) == (1299.99, "holds its offer")


def test_step_lowers_by_the_fixed_amount_and_stops_at_the_floor():
    assert next_offer("step", 1286.02, 1190.0)[0] == round(1286.02 - STEP_USD, 2)
    assert next_offer("step", 1195.0, 1190.0)[0] == 1190.0          # clamped at the floor, still strictly lower
    assert next_offer("step", 1190.0, 1190.0) == (1190.0, "at its floor, holds")


def test_best_now_goes_straight_to_the_floor():
    offer, why = next_offer("best_now", 1329.0, 1200.0)
    assert offer == 1200.0 and why == "best price now"
    assert next_offer("best_now", 1200.0, 1200.0)[0] == 1200.0


@pytest.mark.parametrize("tactic", TACTICS)
@pytest.mark.parametrize("last, floor", [(1300.0, 1200.0), (1200.01, 1200.0), (1200.0, 1200.0), (50.0, 49.99)])
def test_every_offer_is_at_or_above_the_floor_and_never_higher(tactic, last, floor):
    offer, _ = next_offer(tactic, last, floor)
    assert floor <= offer <= last


@pytest.mark.parametrize("tactic", ["", "raise", None, "STEP", "best now"])
def test_an_unknown_tactic_holds(tactic):
    assert next_offer(tactic, 1300.0, 1200.0)[0] == 1300.0


@pytest.mark.parametrize("last, floor", [(math.nan, 1.0), (1.0, math.nan), (math.inf, 1.0), (-5.0, -10.0), (0.0, 0.0),
                                         (True, 1.0), ("1300", 1200.0), (1100.0, 1200.0)])
def test_a_bad_or_under_floor_offer_is_refused(last, floor):
    with pytest.raises(ValueError):
        next_offer("step", last, floor)


@pytest.mark.parametrize("step", [0, -1, math.nan, math.inf, True])
def test_a_bad_step_is_refused(step):
    with pytest.raises(ValueError):
        next_offer("step", 1300.0, 1200.0, step=step)
