"""Central Computers (SF) as a MIRROR seller (issue #308, part of #283 T9).

Central Computers is a real San Francisco store (837 Howard St). Its 12 RTX 5070 Ti listings were captured with Apify
on Oct 24 2026 at 21:12 UTC (snapshot centralcomputers-20261024T2112Z). Central Computers is not a partner: it never
joined Tech Bazaar, and our agent bids from its public listings only.

Rules (tested in data/tests/test_central_computers.py):
- Only listings in stock at the SF store bid (listing.availability == "in_stock_sf_store"). Special-order rows and
  rows stocked only at other stores never bid. Stock is the store's own figure, and the store disclaims its accuracy.
- The bid is the listed price. The floor is FLOOR_OF_LIST of it (the same SIM assumption demo/sellers.py uses for
  MIRROR agents): the store set no floor, we did.
- Condition stays "unknown": the pages do not state it, so it is unverified, never "new".
- Length comes from the maker spec table (data/fit_checker/gpu_lengths.json), never a guess. A card whose length is
  unknown, or over the buyer's clearance when one is given, is never bid, so it cannot win a 305 mm round.
- Never orderable (#333): the store never agreed to sell here, so its bid is shown for comparison and can never win,
  be approved, get a mandate, be charged or be paid (data/mirror/not_partners.py, enforced on every money path).
- Never more units than the SF store's own stock figure.
"""
from __future__ import annotations

import json
from pathlib import Path

from data.fit_checker.gpu_lengths import fits, listing_length
from data.mirror import not_partners

SNAPSHOT_ID = "centralcomputers-20261024T2112Z"
SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / f"{SNAPSHOT_ID}.json"
STORE = "centralcomputers"   # snapshot file prefix (data.mirror.price_spread.load store key)
SELLER_ID = "central_computers_sf"
NAME = "Central Computers (SF)"
SKU = "rtx 5070 ti"
IN_STOCK_SF = "in_stock_sf_store"
FLOOR_OF_LIST = 0.93
CASE_CLEARANCE_MM = 305   # Vidyut's case in the demo
LABEL = not_partners.SELLERS[SELLER_ID]   # code-owned; the store never joined, so its bids are never orderable (#333)


def rows() -> list[dict]:
    """All 12 captured rows, as saved."""
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _offer(card: dict) -> dict:
    listing = card["listing"]
    length = listing_length(listing["url"], card["name"])
    price = float(card["price"])
    return {"id": card["id"], "model_number": card["model_number"], "title": card["name"], "price": price,
            "floor": round(price * FLOOR_OF_LIST, 2), "condition": card.get("condition") or "unknown",
            "listing_url": listing["url"], "sku": listing.get("sku"), "sf_store_qty": listing.get("sf_store_qty"),
            "stock": listing.get("stock"), "length_mm": length["length_mm"], "length_source": length.get("source"),
            "length_model": length.get("model"), "length_note": length.get("note"),
            "snapshot_id": card["snapshot_id"], "snapshot_date": card["snapshot_date"], "origin": "MIRROR"}


def in_stock_sf() -> list[dict]:
    """The listings in stock at the SF store, cheapest first."""
    return sorted((_offer(c) for c in rows() if (c.get("listing") or {}).get("availability") == IN_STOCK_SF
                   and c.get("price") and ((c["listing"].get("sf_store_qty") or 0) > 0)),
                  key=lambda o: (o["price"], o["model_number"]))


def _why_not(offer: dict, clearance_mm: int | None) -> str | None:
    if offer["length_mm"] is None:
        return "length unknown: model not identifiable from listing, so fit cannot be confirmed"
    if clearance_mm is not None and not fits(offer["length_mm"], clearance_mm):
        return f"maker length {offer['length_mm']} mm is over the {clearance_mm} mm clearance"
    return None


def choose(clearance_mm: int | None = None) -> tuple[dict | None, list[dict]]:
    """(the listing the agent bids, the in-stock listings it withholds with the reason).
    The bid is the cheapest in-stock SF card with a maker-confirmed length that fits `clearance_mm` (any confirmed
    length when the clearance is not shared). Unknown-length cards are always withheld."""
    pick, withheld = None, []
    for o in in_stock_sf():
        why = _why_not(o, clearance_mm)
        if why:
            withheld.append({**o, "reason": why})
        elif pick is None:
            pick = o
    return pick, withheld


def seller(clearance_mm: int | None = None) -> dict | None:
    """The seller dict agents/sellers/policy.make_bid reads, origin MIRROR. None when no card can be bid."""
    pick, withheld = choose(clearance_mm)
    if pick is None:
        return None
    qty = pick["sf_store_qty"]
    trace = (f"{LABEL} Bids {pick['model_number']} at its listed price ${pick['price']:,.2f}; floor "
             f"${pick['floor']:,.2f} is {FLOOR_OF_LIST:.0%} of list (SIM assumption, the store set none). "
             f"{qty} in stock at the SF store per the store's own figure, which it does not guarantee. "
             "Condition is not stated on the page, so it is unverified. "
             f"Maker length {pick['length_mm']} mm.")
    return {"id": SELLER_ID, "name": NAME, "owner": None,
            "archetype": "real San Francisco PC store, bid from its public listings (MIRROR, not a partner)",
            "origin": "MIRROR", "orderable": False, "seller_of_record": "Central Computers",
            "mirror_snapshot_date": pick["snapshot_date"], "discount": 0.0, "margin_pct": None, "shipping": 0.0,
            "perks": [f"{qty} in stock at the SF store, 837 Howard St (store's own figure)"], "claims": [],
            "mirror_snapshot_id": SNAPSHOT_ID, "mirror_label": LABEL, "trace_prefix": trace,
            "withheld": [{k: w[k] for k in ("model_number", "price", "length_mm", "reason", "listing_url")} for w in withheld],
            "listings": {SKU: {
                "price": pick["price"], "floor": pick["floor"], "condition": "unknown", "page_condition": "unknown",
                "variant": "retail", "listing_url": pick["listing_url"], "qty_available": qty, "alt_lines": [],
                # the maker length only; its source URL stays in gpu_lengths.json (a mixed-case URL path in a bid
                # reads as an encoded blob to Shield's shield.encoded.payload rule)
                "attrs": {"category": "gpu", "chipset": "RTX 5070 Ti", "model_number": pick["model_number"],
                          "length_mm": pick["length_mm"]}}}}


def stage_offers() -> list[dict]:
    """For Lane D's stage round (demo/sellers.py load_offers shape: {prefix, card, listing}), SF in-stock rows only.
    Offered, not wired: demo/sellers.py skips this store until Lane D adds it to SELLER_OF_RECORD."""
    keep = {o["id"] for o in in_stock_sf()}
    return [{"prefix": STORE, "card": c, "listing": c["listing"]} for c in rows() if c["id"] in keep]
