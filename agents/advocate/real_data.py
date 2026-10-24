"""Real reference data for the advocate (Lane C, issue #283 T3). The agents no longer read mock_data.

baseline_for(skus, as_of=None)  -> (baseline, notes)   price baselines in the shape checks.advise reads
recalls_for_bids(bids, ...)     -> (recalls, notes)    CPSC recall entries in the shape checks.advise reads
with_notes(cards, notes)        -> cards               adds one labelled "note" warning per unverified lookup

Real means: price from data.baselines.baseline (dated retail asks from two data owners), recalls from data.recalls
(the CPSC public API), and a source_url that is a real page. A lookup that fails, is stale or has no data is "unverified":
there is no price or recall check for that SKU, and every card says so in a note, never a silent pass. The notes are
INFO warnings, so they never change a recommendation. Nothing falls back to mock_data: a SKU with no real data has no price
check and a "price baseline unavailable" note. Tests use fakes only; nothing here calls the network unless a fetch is passed or CPSC is reached.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, for data.* (no uagents needed, so it tests anywhere)
from data import baselines as price_baselines
from data import recalls as cpsc
from advocate import checks  # CALL_SUMMARIES, the closed set of spoken reasons


REPO = "https://github.com/vs-githjk/cal-hacks-2026/blob/main"
NOTE_SOURCE = f"{REPO}/agents/advocate/real_data.py"
BRANDS = ("msi", "asus", "gigabyte", "pny", "zotac", "sapphire", "powercolor", "xfx", "evga", "nvidia", "amd", "palit", "inno3d")
RECALL_BUDGET_S = 10.0  # all CPSC lookups together, inside the buyer's 15 s ADVICE_TIMEOUT_S


def _norm(s) -> str:
    return " ".join(str(s or "").lower().replace("-", " ").replace("_", " ").split())


def _as_of(as_of=None) -> datetime:
    """The clock the baseline is read at. BASELINE_AS_OF pins it for a recorded demo (an ISO time), otherwise now."""
    raw = as_of or os.environ.get("BASELINE_AS_OF")
    if raw:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _pinned(as_of=None) -> str:
    """A label suffix when the clock is pinned by BASELINE_AS_OF, so a recorded demo never passes for a live read (#291)."""
    return "" if as_of or not os.environ.get("BASELINE_AS_OF") else f", clock pinned to {_as_of().isoformat(timespec='minutes')} by BASELINE_AS_OF"


def _note(rule_id: str, text: str, url: str = NOTE_SOURCE) -> dict:
    return {"kind": "note", "rule_id": rule_id, "text": text, "source_url": url, "dollar_impact": 0.0}


def baseline_for(skus, as_of=None, rows=None) -> tuple[dict, list[dict]]:
    """A dated baseline per SKU we hold real data for. status ok only (two data owners); anything else is unverified."""
    at, out, notes = _as_of(as_of), {}, []
    for sku in dict.fromkeys(_norm(s) for s in skus):
        try:
            b = price_baselines.baseline(sku, at.isoformat(), rows=rows)
        except Exception as e:  # a lookup that fails is unverified, never a silent pass
            b = {"status": "error", "error": type(e).__name__, "rows": []}
        if b.get("status") == "ok" and b.get("median") and b.get("rows"):
            near = min(b["rows"], key=lambda r: abs(r["price"] - b["median"]))  # a real listing page near the median
            out[sku] = {"unit_price": b["median"], "source_url": near["url"], "source": "MIRROR", "as_of": b["to"], "n": b["n"],
                        "owners": b["owners"],
                        "label": f"MIRROR baseline as of {b['to'][:10]}, {b['n']} retail asks, {len(b['owners'])} sources{_pinned(as_of)}"}
        else:  # never a silent sample price: no real baseline means no price comparison, and the card says so
            why = {"stale": "the newest retail prices are more than 24 h old", "empty": "we hold no price data for it",
                   "one_source": "only one data owner has priced it",
                   "thin": "thin baseline, fewer than 2 prices from " + " and ".join(b.get("thin_owners") or ["a data owner"])
                   }.get(b.get("status"), "the price lookup failed")
            notes.append(_note("advocate.baseline_unverified",
                               f"Price baseline unavailable for {sku} (unverified): {why}. No price comparison was made, and no sample price was used."))
    return out, notes


def _brands_in(text) -> set[str]:
    t = f" {_norm(text)} "
    return {b for b in BRANDS if f" {b} " in t}


def _listing_titles(rows) -> dict:
    """Our own dated listing rows (data.baselines), as {listing url: title}. A failure means no titles, never an error."""
    try:
        rows = price_baselines.observations() if rows is None else rows
    except Exception:
        return {}
    return {r["url"]: r.get("title") or "" for r in rows if isinstance(r, dict) and r.get("url")}


def our_brands(line: dict, titles: dict | None = None) -> set[str]:
    """The brands OUR data names for a line: the SKU spec and our own listing row for its URL. Never seller fields."""
    return _brands_in(line.get("sku_spec")) | _brands_in((titles or {}).get(line.get("listing_url") or "", ""))


def brands_of(line: dict, titles: dict | None = None) -> tuple[set[str], str | None]:
    """-> (brands to look up, a note when the seller's brand disagrees). Our brand comes from the SKU spec and from our own
    listing row for the bid's listing URL; the seller's words (attrs.brand or vendor, offered spec, name, URL) can only ADD a
    lookup, never replace ours, so a seller-set brand is never a way past the recall check (#291)."""
    attrs = line.get("attrs") or {}
    ours = our_brands(line, titles)
    seller_set = {_norm(attrs[k]) for k in ("brand", "vendor") if isinstance(attrs.get(k), str) and attrs[k].strip()}
    theirs = _brands_in(f"{line.get('offered_spec') or ''} {attrs.get('name') or ''} {(line.get('listing_url') or '').replace('/', ' ')}")
    note = None
    if ours and seller_set and not seller_set & ours:
        note = (f"The seller's brand field does not match our listing data ({', '.join(sorted(ours))}); "  # #89: seller text never reaches a card
                f"the recall check used {', '.join(sorted(ours))}.")
    return ours | theirs | seller_set, note


def brand_of(line: dict) -> str | None:
    """One brand for the line (ours first), or None when nothing names one."""
    brands, _ = brands_of(line)
    return sorted(brands)[0] if brands else None


def _lookup_brand(brand, skus, fetch, now, cache_dir) -> dict:
    """All recall answers for one brand, in one thread (the first call fills the per-brand cache for the rest)."""
    out = {}
    for sku in skus:
        try:
            out[sku] = cpsc.recalls_for(f"{brand} {sku}", brand, fetch=fetch, now=now, cache_dir=cache_dir)
        except Exception as e:  # anything escaping recalls_for is unverified, never a crash that drops every card
            out[sku] = {"status": "unverified", "reason": f"the CPSC lookup failed ({type(e).__name__})", "source_url": None}
    return out


def _recall_text(sku: str, r: dict) -> str:
    title = " ".join(str(r.get("title") or "a CPSC recall").split())[:120]
    return f"'{title}'" + (f", {r['date']}" if r.get("date") else "")


def recalls_for_bids(bids, fetch=None, now=None, cache_dir=None, rows=None, budget_s: float = RECALL_BUDGET_S) -> tuple[list[dict], list[dict]]:
    """CPSC entries per bid line, as {"match": sku, "bid_ids", "partial", "title", "date", "source_url"}. A full model match
    vetoes; a partial one (same brand, a similar model) is a caution. No brand, a failed lookup or no answer within budget_s
    (all lookups run in parallel, one thread per brand) is unverified."""
    titles = _listing_titles(rows)
    wanted, notes = {}, []  # (sku, brand) -> bid ids
    for bid in bids:
        for line in _lines(bid):
            if not isinstance(line, dict):  # #330: a line we cannot read is unverified, never a TypeError that drops every card
                notes.append(_note("advocate.recall_unverified", "Recall check unavailable for one bid line (unverified): "
                                   "the line could not be read, so no recall lookup was made.", "https://www.cpsc.gov/Recalls"))
                continue
            sku = _norm(line.get("sku_spec"))
            brands, note = brands_of(line, titles)
            if note:
                notes.append(_note("advocate.brand_mismatch", note))
            if not brands:
                notes.append(_note("advocate.recall_unverified",
                                   f"Recall check unavailable for {sku} (unverified): no brand given, so no recall lookup was made.",
                                   "https://www.cpsc.gov/Recalls"))
            elif not our_brands(line, titles) & set(BRANDS):  # #330: only the seller named a brand, so the lookup is theirs, not ours
                notes.append(_note("advocate.recall_unverified",
                                   f"Recall check for {sku} is unverified: brand not confirmed from our data, so the recall "
                                   "lookup used the seller's brand only.", "https://www.cpsc.gov/Recalls"))
            for brand in brands:
                wanted.setdefault((sku, brand), []).append(bid.get("id"))
    by_brand = {}
    for sku, brand in wanted:
        by_brand.setdefault(brand, []).append(sku)
    answers = {}
    if by_brand:
        pool = ThreadPoolExecutor(max_workers=min(8, len(by_brand)))
        futures = {pool.submit(_lookup_brand, b, skus, fetch, now, cache_dir): b for b, skus in by_brand.items()}
        done, _ = wait(futures, timeout=budget_s)
        pool.shutdown(wait=False, cancel_futures=True)  # a slow CPSC call never holds the advice past the budget
        for f, brand in futures.items():
            res = f.result() if f in done and not f.exception() else {}
            for sku in by_brand[brand]:
                answers[(sku, brand)] = res.get(sku) or {
                    "status": "unverified", "source_url": None,
                    "reason": f"no CPSC answer within {budget_s:g} s" if f not in done else "the CPSC lookup failed"}
    found = []
    for (sku, brand), bid_ids in wanted.items():
        r = answers[(sku, brand)]
        hits = r.get("recalls") if r["status"] == "found" else r.get("partial") if r["status"] == "partial" else None
        if hits:
            h = hits[0]
            found.append({"match": sku, "bid_ids": bid_ids, "brand": brand, "partial": r["status"] == "partial",
                          "title": h.get("title"), "date": h.get("date"), "text": _recall_text(sku, h),
                          "source_url": h.get("url") or r.get("source_url") or "https://www.cpsc.gov/Recalls"})
        elif r["status"] == "unverified":
            why = r.get("reason") or "the CPSC lookup failed"
            notes.append(_note("advocate.recall_unverified", f"Recall check unavailable for {sku} (unverified): {why}.",
                               r.get("source_url") or "https://www.cpsc.gov/Recalls"))
    return found, notes


def _lines(bid) -> list:
    """A bid's lines as a list (anything else is no lines); each line is checked for shape by the caller."""
    lines = bid.get("lines") if isinstance(bid, dict) else None
    return lines if isinstance(lines, list) else []


def with_notes(cards: list[dict], notes: list[dict]) -> list[dict]:
    """One labelled note per unverified lookup on every card (an INFO warning: it never changes the recommendation).
    A card whose reason is "No problems found" while a check could not run says "Some checks could not run" instead (#291),
    because that reason is spoken on the call."""
    seen, unique = set(), []
    for n in notes:
        if n["text"] not in seen:
            seen.add(n["text"])
            unique.append(n)
    unverified = any(n["rule_id"].endswith("_unverified") for n in unique)
    for c in cards:
        c["warnings"] = list(c.get("warnings", [])) + [dict(n) for n in unique]
        if unverified and c.get("rule_id") == "advocate.ok":
            summary = checks.CALL_SUMMARIES["advocate.unverified"]
            c["rule_id"], c["reason"] = "advocate.unverified", summary
            c["call_reason"] = {**c.get("call_reason", {}), "rule_id": "advocate.unverified", "summary": summary}
    return cards


def advice_inputs(need: dict, bids: list[dict], fetch=None, now=None, as_of=None, rows=None, cache_dir=None):
    """Everything advocate_agent passes to checks.advise: baseline, records, recalls, notes. We hold no real seller records yet,
    so records is empty (no record warning) rather than the SIM table."""
    skus = [i.get("sku_spec") for i in need.get("items", []) if isinstance(i, dict)] + \
           [l.get("sku_spec") for b in bids for l in _lines(b) if isinstance(l, dict)]
    baseline, notes = baseline_for(skus, as_of=as_of, rows=rows)
    recalls, recall_notes = recalls_for_bids(bids, fetch=fetch, now=now, cache_dir=cache_dir, rows=rows)
    return baseline, {}, recalls, notes + recall_notes


def shield_baseline(skus, as_of=None, rows=None) -> dict:
    """The buyer's trusted price references for these SKUs: only real, dated baselines (no sample prices). A SKU without one
    gets no price reference, which screen_bid and hunt.public_hint already handle."""
    real, _ = baseline_for([s for s in skus if s], as_of=as_of, rows=rows)
    return real


SHIELD_TTL_S = 300.0  # the buyer re-reads its references this often, so a long-running agent never keeps a >24 h old price
_SHIELD_CACHE: dict = {}
_SHIELD_LOCK = threading.Lock()


def cached_shield_baseline(skus, ttl_s: float = SHIELD_TTL_S, clock=time.monotonic, **kw) -> dict:
    """shield_baseline for the round's own SKUs, cached for ttl_s (#330: not read once at import, not hard-coded to one SKU).
    A failing read gives no reference for those SKUs (no price check), never a stale or sample price."""
    key = tuple(sorted({_norm(s) for s in skus if s}))
    if not key:
        return {}
    now = clock()
    with _SHIELD_LOCK:
        hit = _SHIELD_CACHE.get(key)
        if hit and now - hit[0] < ttl_s:
            return hit[1]
    try:
        value = shield_baseline(key, **kw)
    except Exception:
        value = {}
    with _SHIELD_LOCK:
        _SHIELD_CACHE[key] = (now, value)
    return value
