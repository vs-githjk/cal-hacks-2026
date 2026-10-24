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


def mirror_refs(snap_dir: str = SNAP_DIR) -> dict:
    """Real MIRROR price references by SKU label, read from dated snapshots in data/mirror (offline). The lowest in-stock
    price per chipset is used, with its snapshot date and source URL. Missing folder -> {} (then PO price checks say 'no reference')."""
    refs: dict = {}
    if not os.path.isdir(snap_dir):
        return refs
    for fn in sorted(os.listdir(snap_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            rows = json.load(open(os.path.join(snap_dir, fn), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            chip = (r.get("attrs") or {}).get("chipset")
            price = r.get("price")
            if not chip or not isinstance(price, (int, float)) or r.get("condition") not in ("new", "open-box"):
                continue
            sku = chip.upper().replace(" ", "-")
            at = (r.get("snapshot_date") or "")[:19] + "Z"
            c = cents(price)
            if sku not in refs or c < refs[sku]["price"]:
                refs[sku] = {"price": c, "as_of": at, "source": r.get("source", ""), "origin": "MIRROR"}
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
