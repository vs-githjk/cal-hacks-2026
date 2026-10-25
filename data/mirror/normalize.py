"""Store listing (any actor's item) -> SpecCard with attrs and a listing block. Field names differ per actor,
so each SpecCard field tries a list of candidate paths; a field no path finds stays absent (unknown)."""
import hashlib
import re

FIELDS = {
    "shipping_type": ["shippingType"],
    "title": ["title", "name", "productTitle", "productName", "product.title"],
    "url": ["url", "productUrl", "link", "itemUrl", "product.url"],
    "price": ["price.value", "price.current", "currentPrice", "salePrice", "price", "soldPrice", "priceValue", "offerPrice"],
    "was_price": ["originalPrice", "listPrice", "wasPrice", "regularPrice", "price.was", "strikethroughPrice"],
    "shipping": ["shipping", "shippingPrice", "shippingCost", "delivery", "shippingInfo"],
    "condition": ["condition", "itemCondition", "conditionName"],
    "seller": ["seller.name", "seller", "sellerName", "sellerUsername", "soldBy", "seller.username", "store"],
    "return_policy": ["returnPolicy", "returns", "returnsAccepted"],
    "stock": ["stock", "availability", "stock_availability", "inStock", "in_stock", "stockStatus", "isAvailable", "available"],
    "model_number": ["modelNumber", "mpn", "model", "sku", "itemNumber"],
    "date": ["soldDate", "endedAt", "dateSold"],
}
# Marketplaces where sellers are often private people: never keep their handles.
PRIVATE_SELLER_STORES = {"ebay_sold", "ebay_live"}
CONDITIONS = [("open box", "open-box"), ("open-box", "open-box"), ("refurb", "refurbished"),
              ("pre-owned", "used"), ("used", "used"), ("new", "new")]


def pick(item, path):
    cur = item
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def first(item, paths):
    for p in paths:
        v = pick(item, p)
        if v not in (None, "", [], {}):
            return v
    return None


def money(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return money(first(v, ["value", "amount", "current", "price"]))
    m = re.search(r"\d[\d,]*\.?\d*", str(v or ""))
    return float(m.group(0).replace(",", "")) if m else None


def condition(v, title=""):
    text = f"{v or ''} {title}".lower() if v else ""
    return next((c for k, c in CONDITIONS if k in text), "unknown")


def attrs_from_title(title):
    t = re.sub(r"[\u2122\u00ae]", "", title or "")
    m = re.search(r"\b(RTX|RX|GTX)\s?(\d{4})\s?(Ti SUPER|Ti|SUPER|XTX|XT|GRE)?\b", t, re.I)
    if m:
        chip = f"{m.group(1).upper()} {m.group(2)}" + (f" {m.group(3).replace('ti', 'Ti').replace('super', 'SUPER')}" if m.group(3) else "")
        return "gpu", {"chipset": chip.replace(" TI", " Ti")}
    m = re.search(r"\b(\d{3,4})\s?W\b", t)
    if m and re.search(r"power supply|PSU|80\+|80 PLUS", t, re.I):
        return "psu", {"wattage": int(m.group(1)), "form_factor": "SFX" if re.search(r"\bSFX", t) else "ATX"}
    if re.search(r"\b(mid|full|mini)[- ]tower|\bcase\b", t, re.I):
        return "case", {}
    return "unknown", {}


def store_condition(store, item):
    """A condition the store's own listing data states as flags, or None. B&H marks every listing with is_used and
    condition_flags.isRefurbished / isOpenBox; all three present and false is B&H saying the item is new (#397 A3)."""
    if store == "bh" and isinstance(item, dict) and isinstance(item.get("condition_flags"), dict):
        flags = item["condition_flags"]
        marks = (item.get("is_used"), flags.get("isUsed"), flags.get("isRefurbished"), flags.get("isOpenBox"))
        if any(m is True for m in marks):
            return "used" if item.get("is_used") is True or flags.get("isUsed") is True else \
                   "refurbished" if flags.get("isRefurbished") is True else "open-box"
        if all(m is False for m in marks):
            return "new"
    return None


def strip_private(store, item):
    if store not in PRIVATE_SELLER_STORES:
        return item
    return {k: v for k, v in item.items() if not k.lower().startswith("seller")}


def landed(listing, price):
    """Shipping, landed price and availability as text. Unknown shipping is None, never 0; a free-shipping condition is not free."""
    ship = listing.get("shipping")
    cost = None
    if isinstance(ship, (int, float)) and not isinstance(ship, bool):
        cost = float(ship)
    elif isinstance(ship, str):
        t = ship.strip()
        if re.fullmatch(r"\$?\s*\d[\d,]*(\.\d+)?", t):
            cost = float(t.replace("$", "").replace(",", ""))
        elif re.fullmatch(r"\s*free(\s+(standard\s+)?(shipping|delivery))?\s*\.?\s*", t, re.I):  # only the bare phrase; anything conditional stays unknown
            cost = 0.0
        elif m := re.fullmatch(r"\+\s*\$\s*(\d[\d,]*(?:\.\d+)?)\s+(?:shipping|delivery)\s*\.?", t, re.I):  # eBay "+$12.99 delivery"; "+C $N" is not USD and stays unknown
            cost = float(m.group(1).replace(",", ""))
    if cost is None and str(listing.get("shipping_type") or "").lower() == "free":
        cost = 0.0
    stock = listing.get("stock")
    if isinstance(stock, bool):
        avail = "in stock" if stock else "out of stock"
    elif stock in (0, "0"):
        avail = "out of stock"
    else:
        avail = str(stock) if stock not in (None, "") else None
    ok = cost is not None and price is not None
    return {"shipping_cost": cost, "shipping_captured": cost is not None,
            "landed_price": round(price + cost, 2) if ok else None, "availability": avail}


def part_attrs(part, title, model_number):
    """(category, attrs, maker model) for a CPU, board, memory, storage or cooler listing (#342). The category is the search's,
    the attrs come only from the maker row for this EXACT model (model number first, then a strict title rule), never from
    the listing text; a model with no maker row has no attrs and no maker model, so it can never bid."""
    from data.fit_checker import part_specs   # local: the GPU path and the Actors that bundle this file never need it
    row = part_specs.find(part, model_number, title)
    return part, {a: v for a, (v, _) in part_specs.specs(part, row).items()}, (row or {}).get("model_number")


def to_spec_card(store, item, snapshot_id, snapshot_date, part=None):
    """`part` (cpu, motherboard, memory, storage, cooler) makes the card category-aware; without it the GPU rules apply as before."""
    item = strip_private(store, item)
    f = {k: first(item, paths) for k, paths in FIELDS.items()}
    title = str(f["title"] or "")
    maker_model = None
    if part:
        cat, attrs, maker_model = part_attrs(part, title, f["model_number"])
    else:
        cat, attrs = attrs_from_title(title)
    seller = f["seller"]
    listing = {
        "url": f["url"], "price": money(f["price"]), "was_price": money(f["was_price"]),
        "shipping_type": f["shipping_type"],
        "shipping": f["shipping"] if isinstance(f["shipping"], (str, int, float, bool)) else money(f["shipping"]),
        "seller": seller if isinstance(seller, str) else (seller or {}).get("name") if isinstance(seller, dict) else None,
        "return_policy": f["return_policy"], "stock": f["stock"], "sold_date": f["date"],
    }
    key = f"{store}:{f['url'] or title}"
    card = {
        "id": f"{store}:{hashlib.sha1(key.encode()).hexdigest()[:12]}", "category": cat, "name": title,
        "model_number": str(f["model_number"]) if f["model_number"] else None,
        "condition": condition(f["condition"], title) if f["condition"] else (store_condition(store, item) or "unknown"),
        "attrs": attrs, "price": listing["price"], "currency": "USD", "origin": "MIRROR",
        "source": f["url"] or store, "snapshot_id": snapshot_id, "snapshot_date": snapshot_date,
        "listing": {**{k: v for k, v in listing.items() if v is not None}, **landed(listing, listing["price"])},
    }
    if part:
        card["maker_model"] = maker_model
    return card
