"""Recall check against the CPSC public API (Lane C, issue #127).

    recalls_for(product_title, brand, fetch=None, now=None, cache_dir=None)
        -> {"status": "none"|"found"|"partial"|"unverified", "recalls": [{"title", "date", "url"}], "partial": [...],
            "checked_at", "source_url"}

"none" only when the API answered and nothing matched; any fetch or parse error is "unverified", never "none".
"found" (a full match, the only kind that may veto) needs the brand in the recall title, a product name or a manufacturer,
a graphics card word, and ONE recall product name that holds every model token of the product title (tokens with a digit,
such as 5070) with the same variant words (Ti, Super, XT, XTX, GRE). "partial" is brand plus a graphics card word plus
some model token, such as a 4070 Ti recall against a 4070 Super (#291): a caution with the recall link at most, never a veto.
Generic words alone never match. Answers are cached per brand for 24 hours.
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
VARIANTS = ("ti", "super", "xt", "xtx", "gre")  # a model is not the same model without the same variant words


def _parse_time(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _model_tokens(title, brand):
    """Tokens that name a model: they contain a digit (5070, gv-n507tgaming). Capacity and memory words do not count."""
    skip = re.compile(r"\d+gb|gddr\d+x?|\d+\.\d+|pcie.*")
    return {t for t in re.findall(r"[a-z0-9][a-z0-9\-]*", title.lower()) if re.search(r"\d", t) and len(t) >= 4 and not skip.fullmatch(t)} \
        - set(brand.lower().split())


def _words(text, terms):
    return {t for t in terms if re.search(rf"\b{re.escape(t)}\b", text)}


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


def _matches(item, brand, title):
    """-> "full", "partial" or None. Brand AND a graphics-card word, then: one recall product name with every model token and
    the same variant words as the product title is "full"; any model token alone is "partial". Generic words alone never match."""
    names = [str(item.get("Title") or "")] + [str(p.get("Name") or "") for p in item.get("Products") or []]
    makers = [str(m.get("Name") or "") for m in item.get("Manufacturers") or []]
    hay = " ".join(names + makers).lower()
    if not brand_in(brand, hay):
        return None
    product_text = " ".join(names).lower()
    if not _words(product_text, GPU_TERMS):
        return None
    tokens = _model_tokens(title, brand)
    if not tokens or not _words(product_text, tokens):
        return None
    variants = _words(title.lower(), VARIANTS)
    for name in (n.lower() for n in names):
        if _words(name, tokens) == tokens and _words(name, VARIANTS) == variants:
            return "full"
    return "partial"


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
        found, partial = [], []
        for i in items:
            kind = _matches(i, brand, product_title) if isinstance(i, dict) else None
            if kind:
                (found if kind == "full" else partial).append(
                    {"title": i.get("Title"), "date": str(i.get("RecallDate") or "")[:10], "url": i.get("URL")})
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as e:  # any failure: we do not know, so never "none"
        return {**out, "error": type(e).__name__}
    searched = f"searched ProductName={brand} on {out['checked_at'][:10]}"
    reason = (f"{len(found)} CPSC recall(s) matched brand {brand} and the full model ({searched})" if found else
              f"{len(partial)} CPSC recall(s) named brand {brand} and a similar model, not this exact model ({searched})" if partial else
              f"no CPSC recall matched brand {brand} and graphics card or model words ({searched}); this does not mean the product was never recalled anywhere")
    return {**out, "status": "found" if found else "partial" if partial else "none", "recalls": found, "partial": partial, "reason": reason}


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
