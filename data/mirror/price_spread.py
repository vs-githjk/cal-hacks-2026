"""First measured price numbers (MIRROR): store asks vs a dated eBay sold baseline.
python -m data.mirror.price_spread [--md]   reads data/mirror/snapshots/*.json"""
import json
import statistics
import sys
from pathlib import Path

SNAPS = Path(__file__).resolve().parent / "snapshots"
BASELINE_STORE = "ebay_sold"


def load():
    cards = {}
    for f in sorted(SNAPS.glob("*.json")):
        store = f.name.rsplit("-", 1)[0]
        cards.setdefault(store, []).extend(json.loads(f.read_text()))
    return cards


def _stats(prices):
    if not prices:
        return {"n": 0}
    return {"n": len(prices), "min": min(prices), "median": statistics.median(prices), "max": max(prices)}


def out_of_stock(card):
    stock = card.get("listing", {}).get("stock")
    return stock is False or (isinstance(stock, str) and ("out" in stock.lower() or "sold out" in stock.lower()))


def summarize(cards):
    """Asks exclude out-of-stock listings (not buyable at that price); they are counted, not ranged."""
    every = [c for s, cs in cards.items() if s != BASELINE_STORE for c in cs]
    asks = [c for c in every if not out_of_stock(c)]
    sold = [c for c in cards.get(BASELINE_STORE, []) if c.get("price")]
    priced = [c for c in asks if c.get("price")]
    base = _stats([c["price"] for c in sold])
    dates = sorted({c["listing"].get("sold_date") for c in sold if c["listing"].get("sold_date")})
    base["dates"] = (dates[0], dates[-1]) if dates else None
    base["conditions"] = sorted({c["condition"] for c in sold})
    out = {"asks": _stats([c["price"] for c in priced]), "baseline": base, "no_price": len(asks) - len(priced),
           "out_of_stock": len(every) - len(asks),
           "per_store": {s: _stats([c["price"] for c in cs if c.get("price") and not out_of_stock(c)])
                         for s, cs in cards.items() if s != BASELINE_STORE},
           "snapshot_dates": sorted({c["snapshot_date"][:16] for cs in cards.values() for c in cs})}
    if base["n"] and out["asks"]["n"]:
        pct = lambda a: round(100 * (a - base["median"]) / base["median"])
        out["ask_vs_baseline_pct"] = {k: pct(out["asks"][k]) for k in ("min", "median", "max")}
    return out


def markdown(s):
    a, b = s["asks"], s["baseline"]
    lines = [f"Snapshots (MIRROR): {', '.join(s['snapshot_dates'])} UTC. Query \"RTX 5070 Ti\", 3 to 5 items per store.", "",
             "| what | n | min | median | max |", "|---|---|---|---|---|",
             f"| store asks, in stock or stock unknown | {a['n']} | ${a['min']:,.2f} | ${a['median']:,.2f} | ${a['max']:,.2f} |",
             f"| eBay sold baseline, {b['dates'][0]} to {b['dates'][1]} | {b['n']} | ${b['min']:,.2f} | ${b['median']:,.2f} | ${b['max']:,.2f} |"]
    if "ask_vs_baseline_pct" in s:
        p = s["ask_vs_baseline_pct"]
        lines += ["", f"Asks vs the sold median: {p['min']:+d}% (lowest ask) to {p['max']:+d}% (highest), median {p['median']:+d}%."]
    lines += ["", "| store | n priced | min | median | max |", "|---|---|---|---|---|"]
    for st, x in sorted(s["per_store"].items()):
        lines.append(f"| {st} | {x['n']} | " + (" | ".join(f"${x[k]:,.2f}" for k in ("min", "median", "max")) if x["n"] else "- | - | -") + " |")
    lines.append(f"\nLeft out of the ask range: {s['out_of_stock']} out-of-stock listings. Listings with no price on the page: {s['no_price']}. "
                 f"Baseline conditions: {', '.join(b['conditions'])}.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(markdown(summarize(load())))
