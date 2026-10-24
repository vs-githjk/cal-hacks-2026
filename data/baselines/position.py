"""Where a price sits among the dated listings we hold (Lane C, issue #141). MIRROR.

    price_position(sku, price, condition, as_of, max_gpu_length_mm=305, rows=None) -> dict

The honest claim behind "proves the price": rank among in-stock retail asks of the same condition (a first-party retailer's unstated condition counts as new, as in baseline()) that physically fit,
observed within 24 h before `as_of`, one row per listing URL. 305 mm is the demo case's GPU clearance today; the demo may
change it. A listing whose model we cannot name from its title is not counted as fitting (it is counted in `unknown_fit`).
The sentence never says "savings"; the sold-median clause appears only when the baseline status is "ok".
"""
from __future__ import annotations

from datetime import datetime

from data.baselines import RETAIL, WINDOW, _ts, baseline, observations
from data.fit_checker.gpu_lengths import listing_length


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _day(ts: str) -> str:
    d = _ts(ts)
    return f"{d:%b} {d.day}"


def price_position(sku: str, price: float, condition: str, as_of: str, max_gpu_length_mm: int = 305, rows: list[dict] | None = None) -> dict:
    rows = observations() if rows is None else rows
    t = _ts(as_of)
    live = [r for r in rows if r["sku"] == sku and r["kind"] == "ask" and r["store"] in RETAIL and r["in_stock"]
            and (r["condition"] == condition or (condition == "new" and r["condition"] == "unknown")) and t - WINDOW <= _ts(r["observed_at"]) <= t]
    latest = {}
    for r in sorted(live, key=lambda r: r["observed_at"]):  # one row per listing URL, the latest capture
        latest[r.get("url") or (r["store"], r["price"])] = r
    fitting, unknown_fit, too_long = [], 0, 0
    for r in latest.values():
        length = listing_length("", r.get("title") or "")["length_mm"]
        if length is None:
            unknown_fit += 1
        elif length <= max_gpu_length_mm:
            fitting.append(r)
        else:
            too_long += 1
    of_n = len(fitting)
    rank = 1 + sum(1 for r in fitting if r["price"] < price)
    stores = sorted({r["store"] for r in fitting})
    cheapest = min(fitting, key=lambda r: r["price"], default=None)
    b = baseline(sku, as_of, rows=rows)
    sold_median, sold_n = b["sold"].get("median"), b["sold"].get("n")
    status = b["status"] if b["status"] in ("ok", "one_source") else "one_source"
    where = "Cheapest" if rank == 1 else f"{_ordinal(rank)} cheapest"
    sentence = f"{where} fitting {condition} card of {of_n} listing{'s' * (of_n != 1)} at {len(stores)} store{'s' * (len(stores) != 1)}, {_day(as_of)}" if of_n else \
        f"No fitting {condition} listings held, {_day(as_of)}"
    if of_n and status == "ok" and sold_median is not None:
        if price < sold_median:
            sentence += f" and ${sold_median - price:,.2f} under the 30-day eBay sold median (mixed condition, n = {sold_n})"
        else:
            sentence += f" (30-day eBay sold median, mixed condition: ${sold_median:,.2f}, n = {sold_n})"
    return {"sku": sku, "price": price, "condition": condition, "as_of": as_of, "rank": rank if of_n else None, "of_n": of_n,
            "stores": stores, "cheapest_fitting": {"price": cheapest["price"], "store": cheapest["store"], "url": cheapest.get("url")} if cheapest else None,
            "snapshot_dates": sorted({r["observed_at"][:10] for r in fitting}), "sold_median": sold_median, "sold_n": sold_n,
            "unknown_fit": unknown_fit, "too_long": too_long, "max_gpu_length_mm": max_gpu_length_mm,
            "status": status, "sentence": sentence, "origin": "MIRROR"}
