"""The assembled company: purchasing seat + AP seat + ledger + audit trail, plus the seeded demo studio."""
from __future__ import annotations

import json
import os
from typing import Optional

from hyphenate.company import Company, Outcome
from hyphenate.money import cents
from hyphenate.payables import PayablesMixin
from hyphenate.procurement import ProcurementMixin
from hyphenate.vendors import Vendor

__all__ = ["Engine", "Outcome", "seed_company", "mirror_refs"]


class Engine(ProcurementMixin, PayablesMixin, Company):
    """Pixel Forge Games (SIM). Every method takes an explicit `at` timestamp so runs are reproducible."""


SNAP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mirror", "snapshots")


def mirror_refs(snap_dir: str = SNAP_DIR, min_listings: int = 3) -> dict:
    """Real MIRROR price references by SKU label, read from dated snapshots in data/mirror (offline). The reference is the MEDIAN
    asking price of current retail listings for the chipset (new, open-box or condition not stated). Sold-listing snapshots
    (ebay_sold) are history, not asking prices, and a lowest-price rule was fooled by them ($640 for a $1,250 card), so they are
    excluded. Fewer than `min_listings` listings -> no reference (the PO check then says so)."""
    prices: dict = {}
    latest: dict = {}
    if not os.path.isdir(snap_dir):
        return {}
    for fn in sorted(os.listdir(snap_dir)):
        if not fn.endswith(".json") or "sold" in fn:
            continue
        try:
            rows = json.load(open(os.path.join(snap_dir, fn), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            chip = (r.get("attrs") or {}).get("chipset")
            price = r.get("price")
            if not chip or isinstance(price, bool) or not isinstance(price, (int, float)) or r.get("condition") not in ("new", "open-box", "unknown"):
                continue
            sku = chip.upper().replace(" ", "-")
            prices.setdefault(sku, []).append(cents(price))
            at = (r.get("snapshot_date") or "")[:19] + "Z"
            latest[sku] = max(latest.get(sku, ""), at)
    refs = {}
    for sku, ps in prices.items():
        if len(ps) >= min_listings:
            ps.sort()
            mid = (ps[(len(ps) - 1) // 2] + ps[len(ps) // 2]) // 2
            refs[sku] = {"price": mid, "as_of": latest[sku], "source": f"median of {len(ps)} retail listings in data/mirror/snapshots", "origin": "MIRROR"}
    return refs


def seed_company(*, with_mirror: bool = True, mirror: Optional[dict] = None) -> Engine:
    """The demo studio: a 40-person game studio buying gear. Vendors are SIM except where a MIRROR reference prices a SKU."""
    eng = Engine(mirror=mirror if mirror is not None else (mirror_refs() if with_mirror else {}))
    for v in (
        Vendor("bestbuy", "Best Buy (MIRROR listing, SIM payee)", "best-buy@pay.example.test", "acct_bb_4412"),
        Vendor("gadget-grove", "Gadget Grove (SIM)", "gadget-grove@pay.example.test", "acct_gg_9087"),
        Vendor("bargain-bin", "Bargain Bin Marketplace (SIM)", "bargain-bin@pay.example.test", "acct_bin_2210", terms="prepay"),
        Vendor("newco", "NewCo Computers (SIM, no history)", "newco@pay.example.test", "acct_nc_7731"),
    ):
        eng.add_vendor(v)
    for vid in ("bestbuy", "gadget-grove", "bargain-bin"):
        eng.vendors[vid].add("completed_order", "2026-06-12T17:00:00Z", "ap-agent", "seed order")
    return eng
