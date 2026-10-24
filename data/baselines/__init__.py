"""Dated price baselines (Lane C, c11; issue #47). MIRROR.

baseline(sku, at) -> {status: ok|one_source|stale|empty, median, ask_median, n, providers, owners, from, to, rows, sold, marketplace}
A baseline needs two distinct data owners: retail asks within 24 h before `at` (Apify families apify and apify-b are ONE owner) and eBay sold within 30 days.
Only retail asks that are in stock and new (or condition not stated by a first-party retailer) enter the median.
eBay sold rows are a separate, labelled series and never enter the median (they fooled a lowest-price reference:
$640 for a $1,250 card); eBay live asks are reported as marketplace, also outside the median.

    python3 -m data.baselines        # writes data/baselines/feed.json, the recorded price feed with its date range
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data.mirror.price_spread import load, out_of_stock

HERE = Path(__file__).resolve().parent
RETAIL = {"bestbuy", "microcenter", "bh", "newegg"}  # amazon is out until the seller of record is captured
MARKETPLACE = {"ebay_live"}
SOLD = {"ebay_sold"}
WINDOW = timedelta(hours=24)
SOLD_WINDOW = timedelta(days=30)
MIN_OWNERS = 2
RETAILER_OWNER = "retailer listings (Apify)"
OWNERS = {"apify": RETAILER_OWNER, "apify-b": RETAILER_OWNER, "ebay-sold": "eBay sold"}  # two Actor families are still one data owner


def _ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


SECOND = Path(__file__).resolve().parents[1] / "mirror" / "snapshots_b"  # #47: a second Actor family per store


def _load_second() -> dict:
    cards = {}
    for f in sorted(SECOND.glob("*.json")):
        cards.setdefault(f.name.rsplit("-", 1)[0], []).extend(json.loads(f.read_text()))
    return cards


def observations() -> list[dict]:
    """Every priced listing in the Apify snapshots as one dated observation. The first Actor set is provider "apify";
    the second Actor family (data/mirror/actors.py SECOND_SOURCE, run separately) is provider "apify-b"."""
    rows = []
    sources = [(store, cards, "apify") for store, cards in load().items()] + \
              [(store, [{**c, "provider": "apify-b"} for c in cards], "apify-b") for store, cards in _load_second().items()]
    for store, cards, _ in sources:
        for c in cards:
            if not c.get("price"):
                continue
            rows.append({"provider": "ebay-sold" if store in SOLD else c.get("provider", "apify"),  # a second Actor family sets its own label to count as a second source
                          "store": store, "sku": "rtx 5070 ti" if c["attrs"].get("chipset") == "RTX 5070 Ti" else c["name"],
                         "title": c.get("name"), "price": c["price"], "in_stock": not out_of_stock(c), "condition": c.get("condition", "unknown"),
                         "kind": "sold" if store in SOLD else "ask", "observed_at": c["snapshot_date"],
                         "sold_date": c["listing"].get("sold_date"),
                         "url": c["listing"].get("url") or c.get("source"), "snapshot_id": c.get("snapshot_id"), "origin": "MIRROR"})
    return rows


def _sold_in_window(rows, sku, t):
    """eBay sold rows from the last 30 days (by sold_date, else observed_at), one per listing URL."""
    out = {}
    for r in sorted((r for r in rows if r["sku"] == sku and r["kind"] == "sold"), key=lambda r: r["observed_at"]):
        when = _ts(r.get("sold_date") or r["observed_at"])
        if t - SOLD_WINDOW <= when <= t:
            out[r.get("url") or (r["store"], r["price"], r.get("sold_date"))] = r
    return list(out.values())


def baseline(sku: str, at: str, rows: list[dict] | None = None) -> dict:
    """status ok needs two distinct data owners: dated retail asks (24 h) and eBay sold (30 days). ask_median and sold are kept apart."""
    rows = observations() if rows is None else rows
    t = _ts(at)
    fresh = [r for r in rows if r["sku"] == sku and r["kind"] != "sold" and t - WINDOW <= _ts(r["observed_at"]) <= t]
    asks = [r for r in fresh if r["kind"] == "ask" and r["store"] in RETAIL and r["in_stock"] and r["condition"] in ("new", "unknown")]
    sold = _sold_in_window(rows, sku, t)
    sold_info = {"n": len(sold), "median": round(statistics.median(r["price"] for r in sold), 2) if sold else None,
                 "from": min((r.get("sold_date") or r["observed_at"] for r in sold), default=None),
                 "to": max((r.get("sold_date") or r["observed_at"] for r in sold), default=None),
                 "note": "eBay sold, mixed condition, 30-day window: never blended into the ask median"}
    market = [r for r in fresh if r["kind"] == "ask" and r["store"] in MARKETPLACE]
    providers = sorted({r["provider"] for r in asks})
    latest = {}
    for r in sorted(asks, key=lambda r: r["observed_at"]):  # one observation per listing URL: a re-check is not a new listing
        latest[r.get("url") or (r["store"], r["price"])] = r
    rechecked = len(asks) - len(latest)
    asks = list(latest.values())
    if not asks:
        stale = any(r["sku"] == sku for r in rows)
        return {"status": "stale" if stale else "empty", "median": None, "ask_median": None, "n": 0, "providers": [], "owners": [],
                "from": None, "to": None, "rows": [], "sold": sold_info, "marketplace": {"n": len(market)}, "origin": "MIRROR"}
    owners = sorted({OWNERS.get(r["provider"], r["provider"]) for r in asks} | ({OWNERS["ebay-sold"]} if sold else set()))
    times = sorted(r["observed_at"] for r in asks)
    ok = len(owners) >= MIN_OWNERS
    mid = round(statistics.median(r["price"] for r in asks), 2)
    return {"status": "ok" if ok else "one_source", "median": mid if ok else None, "ask_median": mid,
            "reference_unconfirmed": None if ok else mid, "n": len(asks), "providers": providers, "owners": owners,
            "note": f"{rechecked} re-check(s) of an already counted listing dropped" if rechecked else None,
            "from": times[0], "to": times[-1], "rows": asks, "sold": sold_info,
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
    print(f"baseline rtx 5070 ti at {f['to']}: {b['status']}, median {b['median'] or b.get('reference_unconfirmed')} from {b['n']} retail asks; "
          f"sold n={b['sold']['n']} (kept out); marketplace n={b['marketplace']['n']}")
