"""A fair-price check on the winning bid: "fair", "high" or "suspiciously low", with its source.

ADVISORY ONLY. This produces one line of chat text. It never changes a ranking, a veto, an approval or a payment.

Where the band comes from, in order:
  1. Market Pulse, when it publishes one: `pulse.fair_band.fair_band(sku)` returning
     {"low", "high", "source", "as_of", "source_url"}. Market Pulse has no such function on main today, so this step is
     skipped until it lands; nothing here depends on it.
  2. Otherwise the dated price-history baseline the Advocate already trusts (agents/advocate/real_data.py): real retail
     asks, median per SKU. The band is the median plus or minus the Advocate's own PRICE_TOLERANCE (10 percent);
     more than 25 percent below the median is "suspiciously low".
No baseline for a SKU, or a part that is not new, gives no verdict (the history covers new retail asks only).
"""
from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

TOLERANCE = 0.10      # same as advocate.checks.PRICE_TOLERANCE (pinned by a test)
LOW_FLOOR = 0.75      # below this share of the median, a "good" price is a warning sign


def _pulse_band(sku: str) -> dict | None:
    try:
        from pulse import fair_band as pulse_fair_band  # not on main yet: ImportError is the normal case
        band = pulse_fair_band.fair_band(sku)
    except Exception:
        return None
    ok = isinstance(band, dict) and all(isinstance(band.get(k), (int, float)) and band[k] > 0 for k in ("low", "high"))
    return {**band, "who": "Market Pulse fair band"} if ok and band["low"] <= band["high"] else None


def _baseline_band(sku: str) -> dict | None:
    try:
        from advocate.real_data import cached_shield_baseline
        base = cached_shield_baseline([sku]).get(sku)
    except Exception:
        return None
    if not isinstance(base, dict) or not base.get("unit_price"):
        return None
    m = float(base["unit_price"])
    return {"low": m * (1 - TOLERANCE), "high": m * (1 + TOLERANCE), "median": m, "as_of": base.get("as_of"),
            "source_url": base.get("source_url"), "source": base.get("source"), "label": base.get("label"),
            "who": "dated price history"}


def band_for(sku: str) -> dict | None:
    return _pulse_band(sku) or _baseline_band(sku)


def verdict(price: float, band: dict) -> str:
    median = band.get("median") or (band["low"] + band["high"]) / 2
    if price > band["high"]:
        return "high"
    if price < median * LOW_FLOOR:
        return "suspiciously low"
    return "fair"  # at or under the top of the band and not below the low floor


def _host(url) -> str:
    try:
        return urlparse(str(url)).netloc.removeprefix("www.") or "source unavailable"
    except Exception:
        return "source unavailable"


def price_line(bid: dict, lookup: Callable[[str], dict | None] = band_for) -> str | None:
    """One advisory sentence per priced line of the winning bid, or None when there is no band to compare against.
    Never raises: an advisory line must not be able to disturb a round."""
    try:
        return _price_line(bid, lookup)
    except Exception:
        return None


def _price_line(bid: dict, lookup: Callable[[str], dict | None]) -> str | None:
    import catalog
    parts = []
    for line in bid.get("lines", []):
        sku, price = line.get("sku_spec"), line.get("unit_price")
        if not isinstance(sku, str) or isinstance(price, bool) or not isinstance(price, (int, float)):
            continue
        if line.get("condition", "new") != "new":
            continue  # the history covers new retail asks; an open-box price is not compared to it
        band = lookup(sku)
        if not band:
            continue
        v = verdict(float(price), band)
        src = f"{band['who']}, {band['as_of'][:10]}, {_host(band.get('source_url'))}" if band.get("as_of") else band["who"]
        note = {"fair": "looks fair", "high": "looks high", "suspiciously low": "looks suspiciously low, so be careful"}[v]
        parts.append(f"{catalog.label(sku)} at ${price:,.2f} {note} against ${band['low']:,.0f} to ${band['high']:,.0f} ({src})")
    if not parts:
        return None
    return "Price check (advice only, it never changes the ranking): " + "; ".join(parts) + "."
