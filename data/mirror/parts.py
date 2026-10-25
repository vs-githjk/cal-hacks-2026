"""Real MIRROR listings for the Build Story parts: CPU, motherboard, memory, storage, cooler (Lane C, #342).

PART_SEARCHES            the 11 searches we capture (3 CPU, 2 board, 2 memory, 2 SSD, 2 cooler) (design: the planner's budgets on #344, one real trap per part)
search_input(store, q)   the Actor input for one store and one query
offers(part, owned=None, max_price_cents=None) -> [offer]   #344's offer shape, cheapest first
skipped(part) -> [{title, store, reason}]                   listings that cannot bid, and why

An offer is {seller, price_cents, spec, source} plus origin "MIRROR", snapshot_id, captured_at, orderable, condition.
Rules (tested in data/tests/test_part_listings.py):
- Only a listing whose EXACT model has a maker row (data/fit_checker/part_specs.json) ever bids. Its spec comes from that
  row, never from the seller's text. An unknown model is skipped with a reason, never guessed.
- Central Computers rows are `orderable: False`, always (data/mirror/not_partners.py): shown for comparison only.
- Condition stays "unknown" unless the page states it. Sold history (eBay sold) is a baseline source, never an offer.
- Only the newest snapshot of each store and search counts, so an old capture never prices a new round.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, quote_plus

from data.fit_checker import part_specs
from data.mirror import not_partners
from data.mirror.actors import ACTORS, SECOND_SOURCE

HERE = Path(__file__).resolve().parent
SNAPSHOTS = HERE / "parts_snapshots"
RAW = HERE / "raw"

PART_SEARCHES = [
    {"part": "cpu", "query": "Ryzen 7 9700X"},
    {"part": "cpu", "query": "Ryzen 7 7700X"},
    {"part": "cpu", "query": "Core i5-14600K"},
    {"part": "motherboard", "query": "B650 motherboard"},
    {"part": "motherboard", "query": "B760 motherboard DDR5"},
    {"part": "memory", "query": "DDR5 32GB 6000 CL30"},
    {"part": "memory", "query": "DDR4 32GB 3200"},
    {"part": "storage", "query": "1TB NVMe Gen4 SSD"},
    {"part": "storage", "query": "2TB NVMe Gen4 SSD"},
    {"part": "cooler", "query": "Thermalright Peerless Assassin 120 SE"},
    {"part": "cooler", "query": "DeepCool AK400"},
]
for _s in PART_SEARCHES:
    _s["slug"] = re.sub(r"[^a-z0-9]+", "-", _s["query"].lower()).strip("-")
PARTS = ("cpu", "motherboard", "memory", "storage", "cooler")

# stores we search, in the order we run them: (store key, family b?). eBay sold is the second data owner for the baseline.
STORES = [("bestbuy", False), ("microcenter", False), ("bh", False), ("amazon", False), ("ebay_sold", False),
          ("bestbuy", True), ("microcenter", True)]
SELLER_OF_RECORD = {"bestbuy": "Best Buy", "microcenter": "Micro Center", "bh": "B&H Photo", "amazon": "Amazon",
                    "centralcomputers": "Central Computers (SF)"}
NOT_OFFERS = {"ebay_sold", "ebay_live", "pcpartpicker", "newegg"}   # sold history and marketplaces with private sellers
CENTRAL = "centralcomputers"
CENTRAL_ACTOR = "apify/website-content-crawler"
CENTRAL_BASE = "https://www.centralcomputer.com/all-products/hardware/"
CENTRAL_PAGES = {   # part -> the store's own category page (all five return 200)
    "cpu": CENTRAL_BASE + "cpus.html", "motherboard": CENTRAL_BASE + "motherboards.html", "memory": CENTRAL_BASE + "memory.html",
    "storage": CENTRAL_BASE + "hard-drives-ssd/ssds.html", "cooler": CENTRAL_BASE + "fans-heatsinks/cpu-air-coolers.html"}


def central_cards(part: str, items: list, snapshot_id: str, snapshot_date: str) -> list[dict]:
    """Central Computers crawl items -> cards. Filled in once the crawl output is known (data/mirror/central_parts.py)."""
    from data.mirror.central_parts import cards
    return cards(part, items, snapshot_id, snapshot_date)


def raw_item(item):
    """The saved raw copy of a store item: only the fields the cards are built from (title, url, price, model, seller, stock,
    condition, shipping, returns), never the long description or feature text a store page carries."""
    if not isinstance(item, dict):
        return item
    if "markdown" in item:   # a Central Computers crawl page: the product list is what the cards are read from
        return {"url": item.get("url"), "markdown": item.get("markdown")}
    from data.mirror.normalize import FIELDS
    keep = {path.split(".")[0] for paths in FIELDS.values() for path in paths}
    return {k: v for k, v in item.items() if k in keep}


def search_input(store: str, query: str, second: bool = False, items: int = 5) -> dict:
    """The Actor input for one search. Same shapes as data/mirror/actors.py, with the query and item count swapped in."""
    q = query
    if second:
        if store == "bestbuy":
            return {"searchQuery": q, "maxResults": items, "fetchProductDetails": False}
        if store == "microcenter":
            return {"searchQuery": q, "maxProducts": items, "scrapeDetails": False}
    elif store == "bestbuy":
        return {"mode": "search", "searchQuery": q, "maxProducts": items}
    elif store == "microcenter":
        return {"keywords": [q], "scrapeMode": "overview", "maxResults": items}
    elif store == "bh":
        return {"startUrls": [{"url": "https://www.bhphotovideo.com/c/search?q=" + quote(q)}], "results_wanted": items, "max_pages": 1}
    elif store == "amazon":
        return {"categoryOrProductUrls": [{"url": "https://www.amazon.com/s?k=" + quote_plus(q)}],
                "maxItemsPerStartUrl": items, "maxSearchPagesPerStartUrl": 1}
    elif store == "ebay_sold":
        return {"keywords": [q.lower()], "count": items, "daysToScrape": 30, "ebaySite": "ebay.com"}
    raise KeyError(f"no part search input for {store}{' (second family)' if second else ''}")


def actor_for(store: str, second: bool = False) -> str:
    return (SECOND_SOURCE if second else ACTORS)[store][0]


def planned_runs(items: int = 5, parts=None) -> list[dict]:
    """Every Actor run a capture would make: {part, query, slug, store, second, actor, input}."""
    out = []
    for s in PART_SEARCHES:
        if parts and s["part"] not in parts:
            continue
        for store, second in STORES:
            out.append({**s, "store": store, "second": second, "actor": actor_for(store, second),
                        "input": search_input(store, s["query"], second, items)})
    return out


def snapshot_key(store: str, second: bool, part: str, slug: str) -> str:
    return f"{store}{'-b' if second else ''}-{part}-{slug}"


def _latest(root: Path) -> list[Path]:
    """The newest snapshot file of each store, part and search (names end in a UTC stamp)."""
    best: dict[str, Path] = {}
    for f in sorted(root.glob("*.json")):
        m = re.fullmatch(r"(.+)-(\d{8}T\d{4}Z)", f.stem)
        if m:
            best[m.group(1)] = f
    return list(best.values())


def _card_offer(card: dict) -> tuple[dict | None, str | None]:
    """(offer, None) or (None, why this listing cannot bid)."""
    listing = card.get("listing") or {}
    store = str(card.get("id", "")).split(":")[0]
    part = card.get("category")
    if store in NOT_OFFERS:
        return None, "sold history or a private marketplace seller, kept for the baseline only"
    price = card.get("price")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None, "no usable price"
    if str(listing.get("availability") or "").lower() in ("out of stock", "not_in_sf_store", "special_order"):
        return None, f"not in stock ({listing.get('availability')})"
    if store == "amazon" and str(listing.get("seller") or "") not in ("Amazon", "Amazon.com"):
        return None, "the Amazon seller is not Amazon itself (or not stated), and a third-party seller is its own seller of record"
    row = part_specs.find(part, card.get("model_number"), card.get("name"))
    if row is None:
        return None, "exact model has no maker spec row, so it cannot be fit-checked"
    attrs = {a: v for a, (v, _) in part_specs.specs(part, row).items()}
    seller = SELLER_OF_RECORD.get(store)
    if not seller:
        return None, f"no seller of record for {store}"
    return {
        "seller": seller, "price_cents": int(round(price * 100)),
        "spec": {"name": card.get("name"), "model_number": row.get("model_number"), "category": part, **attrs},
        "source": card.get("source") or listing.get("url"),
        "origin": "MIRROR", "snapshot_id": card.get("snapshot_id"), "captured_at": card.get("snapshot_date"),
        "orderable": store not in not_partners.STORES,   # Central Computers never joined: comparison only (#333)
        "condition": card.get("condition") or "unknown",
        "maker_source": row.get("source"), "maker_checked": row.get("checked"),
    }, None


def _cards(part: str, root: Path) -> list[dict]:
    out = []
    for f in _latest(root):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out += [c for c in data if isinstance(c, dict) and c.get("category") == part]
    return out


def offers(part: str, owned=None, max_price_cents: int | None = None, root: Path | None = None) -> list[dict]:
    """MIRROR offers for one part, cheapest first. An owned part gets no round, so no offers."""
    if part not in PARTS or (owned and part in owned):
        return []
    seen, out = set(), []
    for c in _cards(part, Path(root) if root else SNAPSHOTS):
        o, _ = _card_offer(c)
        if not o or (o["seller"], o["source"]) in seen:
            continue
        if max_price_cents is not None and o["price_cents"] > max_price_cents:
            continue
        seen.add((o["seller"], o["source"]))
        out.append(o)
    return sorted(out, key=lambda o: (o["price_cents"], o["seller"], str(o["source"])))


def skipped(part: str, root: Path | None = None) -> list[dict]:
    """The captured listings that cannot bid, with the reason (shown in the PR, never silently dropped)."""
    out = []
    for c in _cards(part, Path(root) if root else SNAPSHOTS):
        o, why = _card_offer(c)
        if not o:
            out.append({"title": c.get("name"), "store": str(c.get("id", "")).split(":")[0], "reason": why})
    return out


NAME = re.compile(r"(?P<store>[a-z_]+?)(?P<b>-b)?-(?P<part>cpu|motherboard|memory|storage|cooler)-.+-(?P<stamp>\d{8}T\d{4}Z)")


def renormalize(snapshots: Path | None = None, raw: Path | None = None) -> list[str]:
    """Rebuild every parts snapshot from its saved raw items (no network, no cost), so cards pick up the current maker rows.
    The capture time stays the original one. Returns the snapshot ids rebuilt."""
    from data.mirror.normalize import to_spec_card
    snapshots, raw = Path(snapshots or SNAPSHOTS), Path(raw or RAW)
    done = []
    for f in sorted(snapshots.glob("*.json")):
        m = NAME.fullmatch(f.stem)
        src = raw / f.name
        if not m or not src.exists():
            continue
        items = json.loads(src.read_text(encoding="utf-8"))
        old = json.loads(f.read_text(encoding="utf-8"))
        when = (old[0].get("snapshot_date") if old else None) or f"{m['stamp'][:4]}-{m['stamp'][4:6]}-{m['stamp'][6:8]}T{m['stamp'][9:11]}:{m['stamp'][11:13]}:00+00:00"
        if m["store"] == CENTRAL:
            cards = central_cards(m["part"], items, f.stem, when)
        else:
            cards = [to_spec_card(m["store"], it, f.stem, when, part=m["part"]) for it in items]
        f.write_text(json.dumps(cards, indent=1), encoding="utf-8")
        done.append(f.stem)
    return done


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--renormalize"]:
        for s in renormalize():
            print("rebuilt", s)
    else:
        sys.exit("usage: python -m data.mirror.parts --renormalize")
