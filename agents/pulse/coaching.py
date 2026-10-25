"""Coaching numbers for a losing seller: how far it lost, and what the market says the part costs.

    "You lost by 3.1%. The 7-day median for RTX 5070 TI is $1,279.00 (typical range $1,250.00 to $1,300.00, 12 prices).
     [Tiger Data price_obs, last 7 days; MIRROR]"

The gap is the percent the seller's own adjusted total was above the round's winner (round_result is public once a round
closes), only for a seller that was priced out, never for one that was disqualified. The market figures are fair_band's:
public, sourced, labelled. Nothing here names a rival, the winner's price or the buyer's cap.
"""
from __future__ import annotations

from typing import Any, Optional


def exact_gaps(rows: list[dict]) -> dict[str, float]:
    """{seller_id: percent above the winner's adjusted total, one decimal} for every row priced out of the round: ranked 2 and
    up, or disqualified on price (rule id "price: ..." in its reasons, for example over the goal cap). A row disqualified for
    anything else (fit, condition, the referee) has no price gap to report. {} unless the round has exactly one rank 1 row
    with a price above zero."""
    winners = [r for r in rows if r.get("rank") == 1]
    if len(winners) != 1 or not winners[0].get("adjusted") or winners[0]["adjusted"] <= 0:
        return {}
    win = winners[0]["adjusted"]
    out = {}
    for r in rows:
        rank, reasons = r.get("rank"), r.get("reasons") or []
        priced_out = isinstance(rank, int) and not isinstance(rank, bool) and (
            rank >= 2 or (rank == 0 and bool(reasons) and str(reasons[0]).split(":", 1)[0].strip().lower() == "price"))
        if priced_out and isinstance(r.get("adjusted"), (int, float)):
            gap = (r["adjusted"] - win) / win * 100
            if gap >= 0:
                out[r["seller_id"]] = round(gap, 1)
    return out


def _usd(v: float) -> str:
    return f"${v:,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def coaching_line(gap_pct: float, band: Optional[dict[str, Any]]) -> str:
    """One sentence pair: the gap, then the market's median and range with its source and label. A part with no price says so."""
    head = "You lost by less than 0.1%." if gap_pct < 0.05 else f"You lost by {gap_pct:.1f}%."
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
