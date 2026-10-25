"""The CPSC public recall API: fetch and cache (Lane C, issues #127, #271).

    brand_items(brand, fetch=None, now=None, cache_dir=None) -> (checked_at, items, url)
    brand_in(brand, text) -> bool

Answers are cached per brand for 24 hours. Matching a product against those recalls lives in ONE place,
data.recall_checker.check_product, which the Recall Checker Actor and the advocate both call (#412).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

CACHE = Path(__file__).resolve().parent / "recalls_cache"
API = "https://www.saferproducts.gov/RestWebServices/Recall?format=json&ProductName="


def _parse_time(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
    if fetch is None:  # only then: an Actor bundle passes its own fetch and does not ship data.claim_check
        from data.claim_check.fetch import guarded_get as fetch
    body = fetch(url)
    items = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
    checked_at = now.isoformat(timespec="seconds")
    if isinstance(items, list):
        cache_dir.mkdir(exist_ok=True)
        (cache_dir / f"{re.sub(r'[^a-z0-9]+', '-', brand.lower())}-{now:%Y%m%d}.json").write_text(json.dumps(
            {"origin": "MIRROR", "brand": brand, "checked_at": checked_at, "source_url": url, "items": items}, indent=1) + "\n")
    return checked_at, items, url


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
