"""Is this product recalled? A recall check for any consumer electronics product (Lane C, issue #271; the recall Actor).

check_product(product, brand, upc=None, fetch=None, now=None, cache_dir=None) ->
    {"status": "recalled"|"possible"|"none"|"unverified", "summary", "product", "brand", "upc",
     "matches": [recall], "possible": [recall], "checked_at", "source_url", "searched", "origin"}
    recall = {"title", "date", "url", "products", "hazard", "remedy", "units", "match_on"}

Data: the U.S. Consumer Product Safety Commission's public recall API (saferproducts.gov), searched by brand and cached
per brand for 24 hours (data.recalls.brand_items). How a recall is matched, strictest first:
  recalled  the UPC is listed on the recall (compared without leading zeros, so UPC-A and EAN-13 agree; no brand text
            needed), OR the brand (as a whole word) AND a model token from the product name (letters and digits, such as
            A1263, Note7 or B650E-F) appears in the recall's title, product names or models;
  possible  the brand AND a product-line number (digits only, such as 10000 or 5070), a distinctive product word (such as
            Soundcore or iPhone), a model token found only in the recall's description (which may say "NOT affected"), or,
            for a name of generic words only ("Power Bank"), every one of those words in the recall: a lead, never a match;
  none      the API answered and nothing of that brand matched a model, line or product word we were given;
  unverified no brand given, no product to match (no model, no product line of 4+ digits, no product word, and no category
            hit; a UPC that is not listed rules out nothing, since recalls rarely list one), or the lookup failed. Never "none"
            on a failure or on a brand alone.
"none" covers U.S. CPSC recalls only; it does not mean the product was never recalled anywhere.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from data.recalls import API, brand_in, brand_items

GENERIC = {"power", "bank", "banks", "pro", "max", "plus", "mini", "ultra", "wireless", "portable", "charger", "charging", "smart",
           "phone", "black", "white", "edition", "series", "model", "with", "and", "for", "the", "new", "case", "cable", "battery",
           "speaker", "headphones", "laptop", "tablet", "watch", "camera", "monitor", "keyboard", "mouse", "gaming", "graphics", "card"}
UNIT = re.compile(r"^(\d+)(gb|tb|mb|g|mah|wh|w|v|hz|ghz|mhz|mm|cm|in|inch|k|p|ft|m)$")  # 16GB, 10000mAh, 65W: a size, not a model


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


STOP = {"with", "and", "for", "the", "new"}


def _prods(item: dict) -> list[dict]:
    return [p for p in item.get("Products") or [] if isinstance(p, dict)]


def _names_text(item: dict) -> str:
    """Title, product names and models: the only places a model hit counts as recalled (#302)."""
    prods = _prods(item)
    parts = [item.get("Title")] + [p.get("Name") for p in prods] + [p.get("Model") for p in prods]
    return " ".join(str(p) for p in parts if p).lower()


def _text(item: dict) -> str:
    return (_names_text(item) + " " + str(item.get("Description") or "")).lower()


def _generic_hit(product: str, brand: str, text: str) -> bool:
    """Every generic word of a generic-only name ("Power Bank") is in the recall, singular or plural."""
    words = [w for w in re.findall(r"[a-z]+", product.lower()) if w in GENERIC and w not in STOP and w not in brand.lower().split()]
    return bool(words) and all(_word(w, text) or _word(w + "s", text) or (w.endswith("s") and _word(w[:-1], text)) for w in words)


GTIN_MAX = 14  # the longest barcode number (GTIN-14); more digits than this is several codes


def _upc_codes(v) -> set[str]:
    """Each code in one UPC value, without leading zeros. Commas, slashes, semicolons or words separate codes; hyphens and
    spaces inside one code ("8-41234-56789-0") are kept together unless the digits run past GTIN_MAX, then they split too."""
    out = set()
    for chunk in re.split(r"[^\d\s-]+", str(v or "")):
        pieces = [chunk]
        if len(re.sub(r"\D", "", chunk)) > GTIN_MAX:
            pieces = chunk.split()
            if any(len(re.sub(r"\D", "", p)) > GTIN_MAX for p in pieces):
                pieces = re.split(r"\D+", chunk)
        out |= {re.sub(r"\D", "", p).lstrip("0") for p in pieces}
    return out - {""}


def _upcs(item: dict) -> set[str]:
    out = set()
    for u in item.get("ProductUPCs") or []:
        out |= _upc_codes(u.get("UPC") if isinstance(u, dict) else u)
    return out


def _first(item: dict, key: str) -> str:
    rows = item.get(key) or []
    return str((rows[0] or {}).get("Name") or "").strip() if rows and isinstance(rows[0], dict) else ""


def _recall(item: dict, match_on: str) -> dict:
    prods = _prods(item)
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
    upc_key = upc_digits.lstrip("0")
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
    generic_only = not (model or any(len(t) >= 4 for t in line) or names)  # "128g" alone is a size, not a product signal (#314)
    for item in items:
        if not isinstance(item, dict):
            continue
        if upc_key and upc_key in _upcs(item):  # a listed UPC is this product, whatever the recall's text says about brands
            out["matches"].append(_recall(item, f"UPC {upc_digits}"))
            continue
        if not _brand_of(item, brand):
            continue
        named, text = _names_text(item), _text(item)
        hit_model = sorted(t for t in model if _word(t, named))
        desc_model = sorted(t for t in model if _word(t, text))  # a description hit may be "Model A1229 is NOT affected"
        hit_line = sorted(t for t in line if _word(t, text))
        hit_name = sorted(t for t in names if _word(t, text))
        if hit_model:
            out["matches"].append(_recall(item, f"model {hit_model[0].upper()}"))
        elif desc_model:
            out["possible"].append(_recall(item, f"model {desc_model[0].upper()} in the recall description only"))
        elif hit_line or hit_name:
            out["possible"].append(_recall(item, f"product line {hit_line[0]}" if hit_line else f"product name {hit_name[0]}"))
        elif generic_only and _generic_hit(product, brand, text):
            out["possible"].append(_recall(item, f"product category {' '.join(w for w in product.lower().split() if w in GENERIC)}"))
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
    elif generic_only:  # a brand alone (or only generic words or a size) never earns "none", even with a UPC: no real recall lists one
        out["status"] = "unverified"
        out["summary"] = (f"UNVERIFIED: no model, product line or product name given for {brand}, so no recall could be ruled out "
                          + (f"(UPC {upc_digits} is not listed on any {brand} recall, but most recalls list no UPC; add the model number "
                             "and run again)" if upc_key else "(add the model number or UPC and run again)"))
    else:
        out["status"] = "none"
        out["summary"] = f"NONE: no CPSC recall of {brand} matches {product or 'this product'} ({out['searched']}); U.S. CPSC recalls only"
    return out
