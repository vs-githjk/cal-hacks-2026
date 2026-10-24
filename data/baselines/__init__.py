"""Dated price baselines (Lane C, c11; issue #47). MIRROR.

baseline(sku, at) -> {status: ok|one_source|stale|empty, median, n, providers, from, to, rows, sold, marketplace}
A baseline needs asks from at least 2 different providers (Apify, Bright Data) observed within 24 h before `at`.
Only retail asks that are in stock and new (or condition not stated by a first-party retailer) enter the median.
eBay sold rows are a separate, labelled series and never enter the median (they fooled a lowest-price reference:
$640 for a $1,250 card); eBay live asks are reported as marketplace, also outside the median.

    python3 -m data.baselines        # writes data/baselines/feed.json, the recorded price feed with its date range
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from data.mirror.price_spread import load, out_of_stock

HERE = Path(__file__).resolve().parent
RETAIL = {"bestbuy", "microcenter", "bh", "amazon", "newegg"}
MARKETPLACE = {"ebay_live"}
SOLD = {"ebay_sold"}
WINDOW = timedelta(hours=24)
MIN_PROVIDERS = 2


def _ts(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s if "+" in s[10:] else s + "+00:00")


def observations() -> list[dict]:
    """Every priced listing in the Apify snapshots as one dated observation."""
    rows = []
    for store, cards in load().items():
        for c in cards:
            if not c.get("price"):
                continue
            rows.append({"provider": "apify", "store": store, "sku": "rtx 5070 ti" if c["attrs"].get("chipset") == "RTX 5070 Ti" else c["name"],
                         "price": c["price"], "in_stock": not out_of_stock(c), "condition": c.get("condition", "unknown"),
                         "kind": "sold" if store in SOLD else "ask", "observed_at": c["snapshot_date"],
                         "url": c["listing"].get("url") or c.get("source"), "snapshot_id": c.get("snapshot_id"), "origin": "MIRROR"})
    return rows


def baseline(sku: str, at: str, rows: list[dict] | None = None) -> dict:
    rows = observations() if rows is None else rows
    t = _ts(at)
    fresh = [r for r in rows if r["sku"] == sku and t - WINDOW <= _ts(r["observed_at"]) <= t]
    asks = [r for r in fresh if r["kind"] == "ask" and r["store"] in RETAIL and r["in_stock"] and r["condition"] in ("new", "unknown")]
    sold = [r for r in fresh if r["kind"] == "sold"]
    market = [r for r in fresh if r["kind"] == "ask" and r["store"] in MARKETPLACE]
    providers = sorted({r["provider"] for r in asks})
    if not asks:
        stale = any(r["sku"] == sku for r in rows)
        return {"status": "stale" if stale else "empty", "median": None, "n": 0, "providers": [], "from": None, "to": None,
                "rows": [], "sold": {"n": len(sold)}, "marketplace": {"n": len(market)}, "origin": "MIRROR"}
    times = sorted(r["observed_at"] for r in asks)
    return {"status": "ok" if len(providers) >= MIN_PROVIDERS else "one_source",
            "median": round(statistics.median(r["price"] for r in asks), 2), "n": len(asks), "providers": providers,
            "from": times[0], "to": times[-1], "rows": asks,
            "sold": {"n": len(sold), "median": round(statistics.median(r["price"] for r in sold), 2) if sold else None,
                     "note": "eBay sold, mixed condition: never in the median"},
            "marketplace": {"n": len(market), "median": round(statistics.median(r["price"] for r in market), 2) if market else None},
            "origin": "MIRROR"}


def write_feed() -> dict:
    rows = sorted(observations(), key=lambda r: r["observed_at"])
    feed = {"origin": "MIRROR", "from": rows[0]["observed_at"] if rows else None, "to": rows[-1]["observed_at"] if rows else None,
            "providers": sorted({r["provider"] for r in rows}), "rows": rows}
    (HERE / "feed.json").write_text(json.dumps(feed, indent=1) + "\n")
    return feed


def main():
    f = write_feed()
    b = baseline("rtx 5070 ti", f["to"])
    print(f"feed: {len(f['rows'])} rows, {f['from']} to {f['to']}, providers {f['providers']}")
    print(f"baseline rtx 5070 ti at {f['to']}: {b['status']}, median {b['median']} from {b['n']} retail asks; "
          f"sold n={b['sold']['n']} (kept out); marketplace n={b['marketplace']['n']}")
