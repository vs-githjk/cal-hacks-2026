"""Is this product recalled? A recall check for any consumer electronics product (Lane C, issue #271; the recall Actor).

check_product(product, brand, upc=None, fetch=None, now=None, cache_dir=None) ->
    {"status": "recalled"|"possible"|"none"|"unverified", "summary", "product", "brand", "upc",
     "matches": [recall], "possible": [recall], "checked_at", "source_url", "searched", "origin"}
    recall = {"title", "date", "url", "products", "hazard", "remedy", "units", "match_on"}

Data: the U.S. Consumer Product Safety Commission's public recall API (saferproducts.gov), searched by brand and cached
per brand for 24 hours (data.recalls.brand_items). How a recall is matched, strictest first:
  recalled  the brand (as a whole word) AND either the UPC, or a model token from the product name (letters and digits,
            such as A1263, Note7 or B650E-F), appears in the recall's title, product names, models or description;
  possible  the brand AND a product-line number (digits only, such as 10000 or 5070) or a distinctive product word (such
            as Soundcore or iPhone, never a generic word like "power bank"): a lead to check, never called a match;
  none      the API answered and nothing of that brand matched;
  unverified no brand given, or the lookup failed. Never "none" on a failure.
"none" covers U.S. CPSC recalls only; it does not mean the product was never recalled anywhere.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from data.recalls import API, brand_in, brand_items

GENERIC = {"power", "bank", "banks", "pro", "max", "plus", "mini", "ultra", "wireless", "portable", "charger", "charging", "smart",
           "phone", "black", "white", "edition", "series", "model", "with", "and", "for", "the", "new", "case", "cable", "battery",
           "speaker", "headphones", "laptop", "tablet", "watch", "camera", "monitor", "keyboard", "mouse", "gaming", "graphics", "card"}
UNIT = re.compile(r"^(\d+)(gb|tb|mb|mah|wh|w|v|hz|mm|cm|in|inch|k|p|ft|m)$")  # 16GB, 10000mAh, 65W: a size, not a model


def _names(product: str, brand: str) -> set[str]:
    """Distinctive product words (Soundcore, iPhone, PowerCore): letters only, 4+ long, not the brand, not a generic word."""
    skip = set(brand.lower().split()) | GENERIC
    return {t for t in re.findall(r"[a-z]+", product.lower()) if len(t) >= 4 and t not in skip}


def _tokens(product: str, brand: str) -> tuple[set[str], set[str]]:
    """(model tokens, product-line numbers) from the product name. Brand words never count."""
    skip = set(brand.lower().split())
    model, line = set(), set()
    for t in re.findall(r"[a-z0-9][a-z0-9\-]*[a-z0-9]|[a-z0-9]", product.lower()):
        if t in skip or not re.search(r"\d", t):
            continue
        unit = UNIT.match(t)
        if unit:
            if len(unit.group(1)) >= 3:
                line.add(unit.group(1))
        elif re.search(r"[a-z]", t) and len(t) >= 3:
            model.add(t)
        elif t.isdigit() and len(t) >= 3:
            line.add(t)
    return model, line


def _word(token: str, text: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text))


def _text(item: dict) -> str:
    prods = item.get("Products") or []
    parts = [item.get("Title"), item.get("Description")] + [p.get("Name") for p in prods] + [p.get("Model") for p in prods]
    return " ".join(str(p) for p in parts if p).lower()


def _upcs(item: dict) -> set[str]:
    out = set()
    for u in item.get("ProductUPCs") or []:
        v = u.get("UPC") if isinstance(u, dict) else u
        if v:
            out.add(re.sub(r"\D", "", str(v)))
    return out


def _first(item: dict, key: str) -> str:
    rows = item.get(key) or []
    return str((rows[0] or {}).get("Name") or "").strip() if rows and isinstance(rows[0], dict) else ""


def _recall(item: dict, match_on: str) -> dict:
    prods = item.get("Products") or []
    return {"title": item.get("Title"), "date": str(item.get("RecallDate") or "")[:10], "url": item.get("URL"),
            "products": [p.get("Name") for p in prods if p.get("Name")], "hazard": _first(item, "Hazards"),
            "remedy": _first(item, "Remedies"), "units": next((p.get("NumberOfUnits") for p in prods if p.get("NumberOfUnits")), None),
            "match_on": match_on}


def _brand_of(item: dict, brand: str) -> bool:
    makers = [m.get("Name") for m in item.get("Manufacturers") or [] if isinstance(m, dict)]
    return brand_in(brand, _text(item) + " " + " ".join(str(m) for m in makers if m))


def check_product(product: str, brand: str, upc: str | None = None, fetch=None, now=None, cache_dir=None) -> dict:
    now = now or datetime.now(timezone.utc)
    product, brand = str(product or "").strip(), str(brand or "").strip()
    upc_digits = re.sub(r"\D", "", str(upc or ""))
    out = {"product": product, "brand": brand, "upc": upc_digits or None, "status": "unverified", "matches": [], "possible": [],
           "checked_at": now.isoformat(timespec="seconds"), "source_url": None, "searched": None, "origin": "MIRROR"}
    if not brand:
        return {**out, "summary": "UNVERIFIED: no brand given, so no recall lookup was made (add the brand and run again)"}
    out["source_url"] = API + brand
    try:
        out["checked_at"], items, out["source_url"] = brand_items(brand, fetch=fetch, now=now, cache_dir=cache_dir)
        if not isinstance(items, list):
            raise ValueError("unexpected answer")
    except Exception as e:  # any failure: we do not know, so never "none"
        return {**out, "error": type(e).__name__, "summary": f"UNVERIFIED: the CPSC recall lookup for {brand} failed ({type(e).__name__}); nothing is known"}
    out["searched"] = f"CPSC recalls for brand {brand}, read {out['checked_at'][:10]}"
    model, line = _tokens(product, brand)
    names = _names(product, brand)
    for item in items:
        if not isinstance(item, dict) or not _brand_of(item, brand):
            continue
        text = _text(item)
        hit_upc = upc_digits and upc_digits in _upcs(item)
        hit_model = sorted(t for t in model if _word(t, text))
        hit_line = sorted(t for t in line if _word(t, text))
        hit_name = sorted(t for t in names if _word(t, text))
        if hit_upc or hit_model:
            out["matches"].append(_recall(item, f"UPC {upc_digits}" if hit_upc else f"model {hit_model[0].upper()}"))
        elif hit_line or hit_name:
            out["possible"].append(_recall(item, f"product line {hit_line[0]}" if hit_line else f"product name {hit_name[0]}"))
    for key in ("matches", "possible"):
        out[key].sort(key=lambda r: r["date"], reverse=True)
    if out["matches"]:
        r = out["matches"][0]
        out["status"] = "recalled"
        out["summary"] = f"RECALLED: {brand} {product} matches {len(out['matches'])} CPSC recall(s) on {r['match_on']}; latest {r['date']}: {r['title']}"
    elif out["possible"]:
        out["status"] = "possible"
        out["summary"] = (f"POSSIBLE: {len(out['possible'])} CPSC recall(s) of {brand} on the same product line or product name, but none names "
                          f"this model; check the recall page and your model number")
    else:
        out["status"] = "none"
        out["summary"] = f"NONE: no CPSC recall of {brand} matches {product or 'this product'} ({out['searched']}); U.S. CPSC recalls only"
    return out
