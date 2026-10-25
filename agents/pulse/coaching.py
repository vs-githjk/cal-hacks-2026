"""Coaching numbers for a losing seller: how far it lost (as the loss report's BAND), and what the market says the part costs.

    "You lost by less than 5 percent. The 7-day median for RTX 5070 TI is $1,279.00 (typical range $1,250.00 to $1,300.00,
     12 prices). [Tiger Data price_obs, last 7 days; MIRROR]"

The gap is only ever the loss report's band (within5, within10, within20, over20), never an exact percent: an exact gap plus
the seller's own price would give away the winner's price. The only dollar figures are the market's public fair band
(25th, 50th and 75th percentile of dated asks), never a bid, a rival or the buyer's cap.
"""
from __future__ import annotations

from typing import Any, Optional

from agents.pulse.market_pulse import BAND_TEXT


def _usd(v: float) -> str:
    return f"${v:,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def coaching_line(gap_band: str, band: Optional[dict[str, Any]]) -> str:
    """One sentence pair: the banded gap, then the market's median and range with its source and label. A part with no price
    says so. ValueError for a band the market does not use."""
    if gap_band not in BAND_TEXT:
        raise ValueError("unknown gap band")
    head = f"You lost by {BAND_TEXT[gap_band]}."
    if not band:
        return head
    tag = f" [{band['source']}; {band['origin']}]"
    sku = band["sku"].upper()
    if not band["n"]:
        return f"{head} I have no price history for {sku} yet, so there is no market median to compare.{tag}"
    window = band.get("window_days")
    which = f"The {window}-day median" if window else "The simulated median"
    only = f", only {_plural(band['n'], 'price')}" if band.get("thin") else f", {_plural(band['n'], 'price')}"
    text = (f"{head} {which} for {sku} is {_usd(band['median'])} "
            f"(typical range {_usd(band['low'])} to {_usd(band['high'])}{only}).{tag}")
    if band["origin"] == "SIM":
        text += " This is a SIM figure, not a real market price."
    return text
