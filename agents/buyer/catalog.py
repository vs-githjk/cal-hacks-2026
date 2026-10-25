"""The parts the Buyer can name in a goal, read from our own catalog files; nothing here is guessed or invented.

Two tiers, both from the repo:
  * on the floor: SKUs the sealed-round sellers list today (agents/sellers/sellers.json). These can win a round.
  * known: the maker-spec parts the fit checker holds (data/fit_checker/part_specs.json). The Buyer understands them,
    but no seller on the floor lists them yet, and it says so.

Pure functions, no I/O after the first read. A SKU that is not in these two tiers does not exist for the Buyer.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_AGENTS = Path(__file__).resolve().parent.parent
SELLERS = _AGENTS / "sellers" / "sellers.json"
PART_SPECS = _AGENTS.parent / "data" / "fit_checker" / "part_specs.json"

CATEGORIES = ("gpu", "cpu", "motherboard", "memory", "storage", "cooler", "psu", "case")
NAMES = {"gpu": "graphics card", "cpu": "CPU", "motherboard": "motherboard", "memory": "RAM", "storage": "SSD",
         "cooler": "cooler", "psu": "power supply", "case": "case"}
# the words a person uses for each category (matched as whole words, case-insensitive)
WORDS = {
    "gpu": r"gpu|graphics card|video card|graphics",
    "cpu": r"cpu|processor",
    "motherboard": r"motherboard|mobo",
    "memory": r"ram|memory",
    "storage": r"ssd|nvme|storage|hard drive",
    "cooler": r"cooler|cpu cooler|heatsink",
    "psu": r"psu|power supply",
    "case": r"case|mid-tower|full-tower|mini-tower|tower",
}
# a whole PC: the parts a seller on the floor can fill today, in the order they are bought
BUILD_PARTS = ("gpu", "psu", "case")


@lru_cache(maxsize=1)
def _sellers() -> dict:
    return json.loads(SELLERS.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _specs() -> dict:
    try:
        return json.loads(PART_SPECS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _category_of_listing(sku: str, listing: dict) -> str:
    cat = (listing.get("attrs") or {}).get("category")
    if cat in CATEGORIES:
        return cat
    return sku.split()[0] if sku.split()[0] in CATEGORIES else "gpu" if re.match(r"(rtx|rx|gtx)\b", sku) else "case"


def _offers(listing: dict) -> list[tuple[str, float]]:
    """(condition, public price) for a listing's main line and its alternative lines. Never a seller's private floor when
    the listing has a price; a seller that prices from cost shows its per-condition floor as its only number."""
    main = listing.get("condition") or "new"
    floors = listing.get("floor_by_condition") or {}
    out = [(main, float(listing.get("price") or floors.get(main) or listing.get("cost") or 0))]
    out += [(a["condition"], float(a["price"])) for a in listing.get("alt_lines") or [] if a.get("condition") and a.get("price")]
    return [(c, p) for c, p in out if p > 0]


@lru_cache(maxsize=1)
def floor() -> dict:
    """sku_spec -> {"category", "attrs", "by_condition": {condition: lowest price}, "sellers": n} for every SKU a seller
    on the floor lists."""
    out: dict[str, dict] = {}
    for seller in _sellers().get("sellers", {}).values():
        for sku, listing in (seller.get("listings") or {}).items():
            row = out.setdefault(sku, {"category": _category_of_listing(sku, listing), "by_condition": {}, "sellers": 0,
                                       "attrs": {k: v for k, v in (listing.get("attrs") or {}).items() if k != "category"}})
            row["sellers"] += 1
            for cond, price in _offers(listing):
                row["by_condition"][cond] = min(price, row["by_condition"].get(cond, price))
    return out


def price(sku: str, conditions=None) -> float | None:
    """The lowest listed price of this SKU in one of the wanted conditions (any condition when None), else None."""
    by = floor().get(sku, {}).get("by_condition", {})
    prices = [p for c, p in by.items() if conditions is None or c in conditions]
    return min(prices) if prices else None


def is_listed(sku: str) -> bool:
    return sku in floor()


def category_of(sku: str) -> str | None:
    if sku in floor():
        return floor()[sku]["category"]
    for cat, rows in _specs().items():
        if cat in CATEGORIES and any(isinstance(r, dict) and r.get("name", "").lower() == sku for r in rows):
            return cat
    return None


def known_skus(category: str) -> list[str]:
    """Every SKU the Buyer may put in a goal for this category: floor SKUs first, then maker-spec parts."""
    skus = [s for s, r in floor().items() if r["category"] == category]
    skus += [r["name"].lower() for r in (_specs().get(category) or []) if isinstance(r, dict) and r.get("name")
             and r["name"].lower() not in skus]
    return skus


def label(sku: str) -> str:
    """A plain-words name for a SKU ('RTX 4070 Super 12GB', '750W power supply', 'case')."""
    if m := re.fullmatch(r"psu (\d+)w", sku):
        return f"{m.group(1)}W power supply"
    if sku == "case":
        return "case"
    words = []
    for w in sku.split():
        words.append(w.upper() if re.fullmatch(r"(rtx|rx|gtx|xt|xtx|gre|amd|cpu|ssd|\d+gb)", w) else w.capitalize() if w.isalpha() else w.upper())
    return " ".join(words).replace("Gb", "GB")


def _gpu_pattern(sku: str) -> str:
    """'rtx 4070 super 12gb' -> a regex that also takes '4070 super', 'RTX4070 SUPER' and the full name."""
    core = re.sub(r"\s*\d+gb$", "", sku)
    brand, _, rest = core.partition(" ")
    tokens = [re.escape(t) for t in rest.split()]
    return rf"\b(?:{re.escape(brand)}\s*)?{r'[\s-]*'.join(tokens)}\b(?:\s*\d+\s*gb)?"


def find_models(text: str, category: str) -> list[str]:
    """Catalog SKUs of this category that the text names (floor GPUs by alias, maker-spec parts by their strict rule)."""
    found = []
    if category == "gpu":
        for sku in known_skus("gpu"):
            if sku in floor() and re.search(_gpu_pattern(sku), text, re.I):
                found.append(sku)
        return found
    if category == "psu":
        m = re.findall(r"(\d{3,4})\s*-?\s*w(?:att)?s?\b", text, re.I)
        return [f"psu {w}w" for w in dict.fromkeys(m) if f"psu {w}w" in floor()]
    for r in _specs().get(category) or []:
        pat = r.get("match") if isinstance(r, dict) else None
        if pat and re.search(pat, text, re.I):
            found.append(r["name"].lower())
    return found


def unknown_models(text: str, category: str) -> list[str]:
    """Model names the text mentions that the catalog does not hold (never turned into a SKU)."""
    if category == "gpu":
        named = re.findall(r"\b(?:RTX|RX|GTX)\s*\d{3,4}(?:\s*(?:Ti|SUPER|XTX|XT|GRE))?\b", text, re.I)
        have = find_models(text, "gpu")
        misses = []
        for n in named:
            if not any(re.search(_gpu_pattern(s), n, re.I) for s in have):
                misses.append(" ".join(n.split()))
        return misses
    if category == "psu":
        ws = re.findall(r"(\d{3,4})\s*-?\s*w(?:att)?s?\b[^.;,]*?\b(?:psu|power supply)|\b(?:psu|power supply)[^.;,]*?(\d{3,4})\s*-?\s*w(?:att)?s?\b", text, re.I)
        return [f"{a or b}W power supply" for a, b in ws if f"psu {a or b}w" not in floor()]
    return []


def options(category: str, limit: int = 3, max_price: float | None = None, conditions=None) -> list[str]:
    """Up to `limit` concrete SKUs to offer: floor SKUs with a listing in a wanted condition, by price (high to low, so
    the best card fitting the budget leads), then maker-spec parts. `max_price` keeps only floor SKUs whose lowest
    wanted-condition listing fits."""
    have = [s for s in known_skus(category) if s in floor() and price(s, conditions) is not None]
    listed = sorted((s for s in have if max_price is None or price(s, conditions) <= max_price), key=lambda s: -price(s, conditions))
    rest = [s for s in known_skus(category) if s not in floor()] if max_price is None else []
    return (listed + rest)[:limit]


def attrs_of(sku: str) -> dict:
    """Spec attrs we hold for an owned or wanted SKU (for later fit checks); empty when the catalog has none."""
    return dict(floor().get(sku, {}).get("attrs") or {})


def cheapest(category: str, conditions=None) -> float | None:
    prices = [p for sku in known_skus(category) if sku in floor() and (p := price(sku, conditions)) is not None]
    return min(prices) if prices else None
