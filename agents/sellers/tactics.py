"""Knockout stage tactics (#337): a seller still in after a stage answers with one improved sealed offer.

Three tactics, so Market Pulse can compare them later: "hold" keeps the offer, "step" lowers it by a fixed amount, and
"best_now" goes straight to the seller's floor. An offer is never below the floor and never above the last offer; an
unknown tactic holds. The market (#336) also refuses an offer that is not strictly lower, so "hold" just lets the old
offer stand. The reason text never names the floor.
"""
from __future__ import annotations

import math

TACTICS = ("hold", "step", "best_now")
STEP_USD = 10.0


def _money(x, name: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return float(x)


def next_offer(tactic, last, floor, step: float = STEP_USD) -> tuple[float, str]:
    """(offer, why) for the next stage. offer == last means the old offer stands."""
    last, floor, step = _money(last, "last offer"), _money(floor, "floor"), _money(step, "step")
    if last < floor:
        raise ValueError("the last offer is under the floor; the referee refuses it before any stage")
    if tactic == "step":
        offer = round(max(floor, last - step), 2)
        return (offer, f"steps down {step:,.2f}") if offer < last else (last, "at its floor, holds")
    if tactic == "best_now":
        return (floor, "best price now") if floor < last else (last, "best price now")
    return last, "holds its offer"
