"""Byte Bros Outlet (seller_1), the Learner: a margin learner that lives across rounds.

What it is: one number, `cut`, the extra price cut it takes off list on top of its base discount. It moves by a
clipped gradient step on its own results:
  - a price loss: the market's loss report gives a banded gap (within5, within10, within20, over20). The gap was
    measured at the price it bid, so the whole band step is added to `cut`, plus a quarter of the last step when the
    previous loss was also on price (momentum). The first loss of a streak takes exactly the band step, which is what
    the older price_step ledger (agents/sellers/learning.py) did, so the first move is unchanged.
  - a loss on anything else (fit, condition, delivery, record, advocate veto): price is not the problem, `cut` holds.
  - a win (a trusted order reached this agent): probe back toward margin by RECOVER, and remember the cheapest cut that
    ever won. If the probe loses, the next price loss steps it up again, so it searches for the highest winning price.
  - Market Pulse coaching (observe_coaching): a lower_price note raises `cut` to the note's step. Only the closed
    fields action and price_step are read; the note's free text never reaches this state. This is an input hook, tested
    but NOT wired: nothing in the repo delivers a Pulse note to this agent yet (Pulse sends round notes to the referee
    and answers a seller's record over chat only when asked), so today the learner learns from its own reports only.
It never bids below its floor: make_bid clamps every line at the floor, and observe_bid records when that happened so
the note says the price is at its limit. The note never names a floor amount.
Sellers never see rivals' bids or the buyer's cap: the only inputs are this seller's own loss reports, its own orders
and its own bids.
"""
from __future__ import annotations

import math

from agents.sellers import learning

SELLER_ID = "seller_1"
STEP_BY_BAND = learning.STEP_BY_BAND
BAND_UNDER = {"within5": "5%", "within10": "10%", "within20": "20%", "over20": "more than 20%"}
MAX_CUT = 0.25          # the same cap as the largest band step
RECOVER = 0.005         # margin probed back after a win
MOMENTUM = 0.25         # share of the last price step added again when the loss streak is on price
KEEP_IDS = 200
COACH_ACTIONS = {"lower_price"}


def fresh() -> dict:
    return {"v": 1, "cut": 0.0, "velocity": 0.0, "bids": [], "wins": 0, "losses": 0, "price_losses": 0,
            "seen": [], "last_band": None, "last_reason": None, "at_floor": False, "best_win_cut": None,
            "coach": None, "streak_price": False}


def check(state: dict) -> dict:
    """The state as saved, or ValueError when a number is out of range (a corrupt row must not steer prices)."""
    try:
        cut, velocity = state["cut"], state["velocity"]
        ok = (all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (cut, velocity))
              and 0.0 <= cut <= MAX_CUT and isinstance(state["bids"], list) and isinstance(state["seen"], list)
              and all(isinstance(state[k], int) and not isinstance(state[k], bool) and state[k] >= 0
                      for k in ("wins", "losses", "price_losses")))
    except (KeyError, TypeError):
        ok = False
    if not ok:
        raise ValueError("saved learner state is invalid")
    return state


def _remember(state: dict, key: str, value: str) -> bool:
    if value in state[key]:
        return False
    state[key] = [*state[key], value][-KEEP_IDS:]
    return True


def observe_loss(state: dict, report: dict, market_id: str) -> bool:
    """One loss report addressed to this seller's Market identity (for example seller-a). False when it was already
    counted; ValueError when it is not a valid loss report for that identity."""
    report = learning._validate_report(report, market_id)
    if not _remember(state, "seen", "loss:" + report["id"]):
        return False
    state["losses"] += 1
    state["last_band"], state["last_reason"] = report["gap_band"], report["reason"]
    if report["reason"] == "price":
        delta = STEP_BY_BAND[report["gap_band"]]
        if state["streak_price"]:
            delta += MOMENTUM * state["velocity"]
        state["cut"] = round(min(MAX_CUT, state["cut"] + delta), 4)
        state["velocity"] = delta
        state["streak_price"] = True
        state["price_losses"] += 1
    else:
        state["velocity"] = 0.0
        state["streak_price"] = False
    return True


def observe_win(state: dict, need_id: str) -> bool:
    """A trusted order for `need_id` reached this agent: it won. Probe back toward margin."""
    if not isinstance(need_id, str) or not need_id or not _remember(state, "seen", "win:" + need_id):
        return False
    state["wins"] += 1
    best = state["best_win_cut"]
    state["best_win_cut"] = state["cut"] if best is None else min(best, state["cut"])
    state["cut"] = round(max(0.0, state["cut"] - RECOVER), 4)
    state["velocity"] = 0.0
    state["streak_price"] = False
    state["last_reason"] = "won"
    return True


def observe_bid(state: dict, need_id: str, bid: dict) -> None:
    """Record the round it bid in and whether make_bid had to lift a line to its floor."""
    if isinstance(need_id, str) and need_id and need_id not in state["bids"]:
        state["bids"] = [*state["bids"], need_id][-KEEP_IDS:]
    state["at_floor"] = "pricing constraint applied" in str(bid.get("decision_trace", ""))


def observe_coaching(state: dict, note: dict) -> bool:
    """A Market Pulse note for this seller. Only a lower_price note with a step in (0, MAX_CUT] moves anything."""
    if not isinstance(note, dict):
        return False
    action, step = note.get("action"), note.get("price_step")
    if (action not in COACH_ACTIONS or isinstance(step, bool) or not isinstance(step, (int, float))
            or not math.isfinite(step) or not 0 < step <= MAX_CUT):
        return False
    state["coach"] = f"Market Pulse coached a {step:.0%} price cut"
    if step > state["cut"]:
        state["cut"] = round(float(step), 4)
    return True


def total_discount(base_discount: float, state: dict) -> float:
    """The discount off list the bid uses: its base discount, then the learned extra cut on what is left."""
    return 1 - (1 - base_discount) * (1 - state["cut"])


def _pct(x: float) -> str:
    return f"{x * 100:.1f}".rstrip("0").rstrip(".") + "%"


def note(state: dict, base_discount: float) -> str:
    """The visible strategy note, in the learner's own words, from its own record only."""
    total = _pct(total_discount(base_discount, state))
    decided = state["wins"] + state["losses"]
    coach = f" ({state['coach']})" if state["coach"] else ""
    if not decided and not state["bids"]:
        return f"No rounds yet: bidding list less my base {_pct(base_discount)}, now {total} off list{coach}." if coach \
            else f"No rounds yet: bidding list less my base {_pct(base_discount)}."
    if not decided:
        return f"Bid {len(state['bids'])} round(s), no result yet: holding {total} off list{coach}."
    head = f"Lost {state['losses']} of {decided}"
    if state["last_reason"] == "price" and state["last_band"]:
        under = BAND_UNDER[state["last_band"]]
        head += f", last by {under}" if under.startswith("more") else f", last by under {under}"
        tail = f", stepping to {total} off list"
    elif state["last_reason"] == "won":
        tail = f", won the last one and probing back to {total} off list for more margin"
    elif state["last_reason"]:
        tail = f", last on {state['last_reason'].replace('_', ' ')} so price holds at {total} off list"
    else:
        tail = f", holding {total} off list"
    if state["at_floor"]:
        tail = tail.replace("stepping to", "stepping toward") + "; at my price limit, I cannot go lower"
    return head + tail + coach + "."
