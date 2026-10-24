"""Maker spec lengths for the demo's RTX 5070 Ti cards (issue #96). MIRROR, sources in gpu_lengths.json.

    python3 -m data.fit_checker.gpu_lengths      # which demo listings fit a 305 mm and a 340 mm GPU clearance

A listing whose model we cannot name from its title gets no length (unknown), never a guess.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TABLE = Path(__file__).resolve().parent / "gpu_lengths.json"
CLEARANCES = (305, 340)
NOT_IDENTIFIABLE = "model not identifiable from listing"


def _rows() -> list[dict]:
    return json.loads(TABLE.read_text())["models"]


def maker_length(title: str) -> dict | None:
    return next((r for r in _rows() if re.search(r["match"], title, re.I)), None)


def listing_length(url: str, title: str) -> dict:
    """Maker length for a store listing, from its title and URL; never a guess."""
    m = maker_length(title)  # the title only: a brand in a URL slug is a guess
    if not m:
        return {"length_mm": None, "note": NOT_IDENTIFIABLE}
    return {"length_mm": m["length_mm"], "model": m["model"], "source": m["source"], "confidence": m["confidence"]}


def fits(length_mm, clearance_mm) -> bool | None:
    return None if length_mm is None else length_mm <= clearance_mm


def _raw_listings() -> list[dict]:
    """5070 Ti listings that only exist in the raw Actor output (not in a normalized snapshot). eBay sold prices are not listings."""
    out = []
    for f in sorted((TABLE.parents[1] / "mirror" / "raw").glob("*.json")):
        if f.stem.startswith("ebay_sold"):
            continue
        for it in json.loads(f.read_text()):
            title = it.get("title") or it.get("name") or it.get("productTitle") or ""
            m = re.search(r"[\d,]+(?:\.\d+)?", str(it.get("priceValue") or it.get("price") or "").replace(",", ""))
            if re.search(r"5070\s*Ti", title, re.I) and it.get("url"):
                out.append({"seller": f.stem, "title": title, "origin": "MIRROR", "price": float(m.group()) if m else None,
                            "url": it["url"], "listed_length_mm": None})
    return out


def demo_listings() -> list[dict]:
    """Every 5070 Ti in the demo: MIRROR store listings (Apify snapshots) and the SIM sellers' stated lengths."""
    from data.mirror.price_spread import latest_by_url, load
    from demo.sellers import sim_sellers
    out = []
    for store, cards in load().items():
        for c in latest_by_url(cards):  # one row per listing URL, latest snapshot wins
            if c["attrs"].get("chipset") == "RTX 5070 Ti":
                out.append({"seller": store, "title": c["name"], "origin": "MIRROR", "price": c.get("price"),
                            "url": (c.get("listing") or {}).get("url") or c.get("source") or "",
                            "listed_length_mm": c["attrs"].get("length_mm")})
    seen = {o["url"] for o in out if o["url"]}
    for o in _raw_listings():
        if o["url"] not in seen:
            out.append(o)
            seen.add(o["url"])
    for s in sim_sellers():
        for l in s.lines:
            if l.attrs.get("chipset") and "5070" in str(l.attrs.get("chipset")):
                out.append({"seller": s.id, "title": l.basis, "origin": "SIM", "price": l.list_price,
                            "listed_length_mm": l.attrs.get("length_mm")})
    return out


def report() -> list[dict]:
    rows = []
    for d in demo_listings():
        m = maker_length(d["title"]) if d["origin"] == "MIRROR" else None
        length = m["length_mm"] if m else d["listed_length_mm"] if d["origin"] == "SIM" else None
        rows.append({**d, "model": m["model"] if m else None, "maker_length_mm": m["length_mm"] if m else None,
                     "length_used_mm": length, "source": m["source"] if m else ("SIM seller's stated length" if length else None),
                     "confidence": m["confidence"] if m else ("SIM seller's stated length" if length else None),
                     **{f"fits_{c}": fits(length, c) for c in CLEARANCES},
                     **({"note": NOT_IDENTIFIABLE} if d["origin"] == "MIRROR" and not m else {})})
    return rows


def main():
    rows = report()
    (TABLE.parent / "gpu_fit_report.json").write_text(json.dumps({"origin": "MIRROR and SIM", "clearances_mm": CLEARANCES,
                                                                  "rows": rows}, indent=1) + "\n")
    word = {True: "fits", False: "too long", None: "unknown"}
    for r in rows:
        print(f"[{r['origin']}] {r['seller']:<13} {str(r['length_used_mm'] or '?'):>4} mm  305: {word[r['fits_305']]:<8} "
              f"340: {word[r['fits_340']]:<8} {r['title'][:70]}")


if __name__ == "__main__":
    main()
