"""Recall check against the CPSC public API (Lane C, issue #127).

    recalls_for(product_title, brand, fetch=None, now=None, cache_dir=None)
        -> {"status": "none"|"found"|"unverified", "recalls": [{"title", "date", "url"}], "checked_at", "source_url"}

"none" only when the API answered and nothing matched; any fetch or parse error is "unverified", never "none".
Matching is conservative: the brand must be in the recall title, a product name or a manufacturer, AND the recall must
name a graphics card word AND a model token from the product title (it has a digit, such as 5070). Generic words alone never match. Answers are cached per brand for 24 hours.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

CACHE = Path(__file__).resolve().parent / "recalls_cache"
API = "https://www.saferproducts.gov/RestWebServices/Recall?format=json&ProductName="
GPU_TERMS = ("graphics card", "video card", "gpu", "geforce", "rtx")


def _parse_time(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _model_tokens(title, brand):
    """Tokens that name a model: they contain a digit (5070, gv-n507tgaming). Capacity and memory words do not count."""
    skip = re.compile(r"\d+gb|gddr\d+x?|\d+\.\d+|pcie.*")
    return {t for t in re.findall(r"[a-z0-9][a-z0-9\-]*", title.lower()) if re.search(r"\d", t) and len(t) >= 4 and not skip.fullmatch(t)} \
        - set(brand.lower().split())


def brand_in(brand: str, text: str) -> bool:
    """The brand as a whole word: "Anker" is not inside "Trankerloop"."""
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(brand.strip().lower())}(?![a-z0-9])", text.lower()))


def brand_items(brand: str, fetch=None, now=None, cache_dir=None):
    """-> (checked_at, items, url): the CPSC answer for ProductName=<brand>, cached per brand for 24 hours.
    Raises on a fetch or parse failure; items may be a non-list when the API answers oddly (the caller decides)."""
    now = now or datetime.now(timezone.utc)
    cache_dir = Path(cache_dir) if cache_dir else CACHE
    url = API + quote(brand)
    cached = _cached(brand, now, cache_dir)
    if cached:
        return cached[0], cached[1], url
    from data.claim_check.fetch import guarded_get
    body = (fetch or guarded_get)(url)
    items = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
    checked_at = now.isoformat(timespec="seconds")
    if isinstance(items, list):
        cache_dir.mkdir(exist_ok=True)
        (cache_dir / f"{re.sub(r'[^a-z0-9]+', '-', brand.lower())}-{now:%Y%m%d}.json").write_text(json.dumps(
            {"origin": "MIRROR", "brand": brand, "checked_at": checked_at, "source_url": url, "items": items}, indent=1) + "\n")
    return checked_at, items, url


def _matches(item, brand, title):
    """Brand AND a graphics-card word AND a model token from the product title, all in the recall. Generic words alone never match."""
    names = [str(item.get("Title") or "")] + [str(p.get("Name") or "") for p in item.get("Products") or []]
    makers = [str(m.get("Name") or "") for m in item.get("Manufacturers") or []]
    hay = " ".join(names + makers).lower()
    if not brand_in(brand, hay):
        return False
    product_text = " ".join(names).lower()
    if not any(re.search(rf"\b{re.escape(t)}\b", product_text) for t in GPU_TERMS):
        return False
    return any(re.search(rf"\b{re.escape(t)}\b", product_text) for t in _model_tokens(title, brand))


def recalls_for(product_title: str, brand: str, fetch=None, now=None, cache_dir=None) -> dict:
    now = now or datetime.now(timezone.utc)
    if not isinstance(brand, str) or not brand.strip():  # nothing to search for: no API call, we do not know
        return {"status": "unverified", "recalls": [], "checked_at": now.isoformat(timespec="seconds"), "source_url": None,
                "reason": "no brand given, so no recall lookup was made"}
    brand = brand.strip()
    out = {"status": "unverified", "recalls": [], "checked_at": now.isoformat(timespec="seconds"), "source_url": API + quote(brand)}
    try:
        out["checked_at"], items, _ = brand_items(brand, fetch=fetch, now=now, cache_dir=cache_dir)
        if not isinstance(items, list):
            return out
        found = [{"title": i.get("Title"), "date": str(i.get("RecallDate") or "")[:10], "url": i.get("URL")}
                 for i in items if isinstance(i, dict) and _matches(i, brand, product_title)]
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as e:  # any failure: we do not know, so never "none"
        return {**out, "error": type(e).__name__}
    searched = f"searched ProductName={brand} on {out['checked_at'][:10]}"
    reason = (f"{len(found)} CPSC recall(s) matched brand {brand} and graphics card or model words ({searched})" if found else
              f"no CPSC recall matched brand {brand} and graphics card or model words ({searched}); this does not mean the product was never recalled anywhere")
    return {**out, "status": "found" if found else "none", "recalls": found, "reason": reason}


def _cached(brand, now, cache_dir):
    """-> (checked_at, items) from a cache file younger than 24 h, else None."""
    slug = re.sub(r"[^a-z0-9]+", "-", brand.lower())
    for f in sorted(cache_dir.glob(f"{slug}-*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            if now - _parse_time(data["checked_at"]) < timedelta(hours=24) and data.get("brand") == brand:
                return data["checked_at"], data["items"]
        except (OSError, ValueError, KeyError):
            continue
    return None
