"""Central Computers (SF) category pages -> MIRROR cards for the Build Story parts (#342).

Central Computers is a real San Francisco store (837 Howard St) that never joined Tech Bazaar: its cards are shown for
comparison and are never orderable (data/mirror/not_partners.py, enforced on every money path). One crawl of a category page
lists every product on that page with its title, link, Model, Item (the store's sku), per-store stock and price, so a card is
the page's own figures and nothing else. Condition stays "unknown": the page does not state it.
"""
from __future__ import annotations

import re

from data.mirror.normalize import to_spec_card

STORE = "centralcomputers"
SELLER = "Central Computers"
SF_ADDRESS = "837 Howard St, San Francisco, CA 94103"
ENTRY = re.compile(r"(?m)^\s*\d+\.\s+\[!\[")
TITLE_URL = re.compile(r"\[!\[(?P<title>[^\]]*)\]\([^)]*\)\]\((?P<url>https://www\.centralcomputer\.com/[^)\s]+\.html)\)")
STORE_QTY = re.compile(r"\*\s+(?P<addr>\d[^\n]*?)\s{2,}\n\s*(?P<phone>[\d-]+)\s*\n\s*(?P<qty>\d+)\s*\n")
MONEY = re.compile(r"\$(?P<p>[\d,]+\.\d{2})\s*$", re.M)   # the last price on its line: a sale line reads "was $34.99 Special Price $19.99"


def entries(markdown: str) -> list[str]:
    starts = [m.start() for m in ENTRY.finditer(markdown or "")]
    return [markdown[a:b] for a, b in zip(starts, starts[1:] + [len(markdown or "")])]


def parse_entry(block: str) -> dict | None:
    """One product block -> {title, url, model, sku, price, store_inventory, sf_store_qty}, or None when it is not readable
    (no title, link or price). An unreadable block is dropped, never guessed."""
    t = TITLE_URL.search(block)
    prices = MONEY.findall(block)
    if not t or not prices or not t.group("title").strip():
        return None
    model = re.search(r"Model:\s*(.+?)\s*$", block, re.M)
    sku = re.search(r"Item:\s*(\S+)", block)
    inventory = [{"address": m.group("addr").strip(), "phone": m.group("phone"), "qty": int(m.group("qty"))} for m in STORE_QTY.finditer(block)]
    sf = next((s["qty"] for s in inventory if s["address"].startswith("837 Howard")), None)
    return {"title": t.group("title").strip(), "url": t.group("url"), "model": model.group(1).strip() if model else None,
            "sku": sku.group(1) if sku else None, "price": float(prices[-1].replace(",", "")), "store_inventory": inventory, "sf_store_qty": sf}


def availability(sf_qty, inventory) -> str:
    if sf_qty and sf_qty > 0:
        return "in_stock_sf_store"
    return "not_in_sf_store" if any(s["qty"] > 0 for s in inventory) else "special_order"


def cards(part: str, items: list, snapshot_id: str, snapshot_date: str, actor: str = "apify/website-content-crawler", run_id: str | None = None) -> list[dict]:
    out = []
    for it in (i for i in items if isinstance(i, dict)) if isinstance(items, list) else []:
        page = it.get("url")
        for block in entries(it.get("markdown") if isinstance(it.get("markdown"), str) else ""):
            p = parse_entry(block)
            if not p:
                continue
            card = to_spec_card(STORE, {"title": p["title"], "url": p["url"], "price": p["price"], "modelNumber": p["model"]},
                                snapshot_id, snapshot_date, part=part)
            card["listing"].update(
                availability=availability(p["sf_store_qty"], p["store_inventory"]), sku=p["sku"], seller=SELLER, seller_location=SF_ADDRESS,
                sf_store_qty=p["sf_store_qty"], store_inventory=p["store_inventory"], source_page=page, apify_actor=actor,
                stock=(f"{p['sf_store_qty']} in stock at SF store (837 Howard St)" if p["sf_store_qty"] else "not in stock at the SF store"))
            if run_id:
                card["listing"]["apify_run_id"] = run_id
            out.append(card)
    return out
