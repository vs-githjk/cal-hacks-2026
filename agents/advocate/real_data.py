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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, for data.* (no uagents needed, so it tests anywhere)
from data import baselines as price_baselines
from data import recalls as cpsc


REPO = "https://github.com/vs-githjk/cal-hacks-2026/blob/main"
NOTE_SOURCE = f"{REPO}/agents/advocate/real_data.py"
BRANDS = ("msi", "asus", "gigabyte", "pny", "zotac", "sapphire", "powercolor", "xfx", "evga", "nvidia", "amd", "palit", "inno3d")


def _norm(s) -> str:
    return " ".join(str(s or "").lower().replace("-", " ").replace("_", " ").split())


def _as_of(as_of=None) -> datetime:
    """The clock the baseline is read at. BASELINE_AS_OF pins it for a recorded demo (an ISO time), otherwise now."""
    raw = as_of or os.environ.get("BASELINE_AS_OF")
    if raw:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


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
                        "owners": b["owners"], "label": f"MIRROR dated {b['from'][:10]} to {b['to'][:10]}, {b['n']} retail asks"}
        else:  # never a silent sample price: no real baseline means no price comparison, and the card says so
            why = {"stale": "the newest retail prices are more than 24 h old", "empty": "we hold no price data for it",
                   "one_source": "only one data owner has priced it"}.get(b.get("status"), "the price lookup failed")
            notes.append(_note("advocate.baseline_unverified",
                               f"Price baseline unavailable for {sku} (unverified): {why}. No price comparison was made, and no sample price was used."))
    return out, notes


def brand_of(line: dict) -> str | None:
    """The brand a bid line names (attrs.brand or vendor, or a known maker word in its offered spec); None when it names none."""
    attrs = line.get("attrs") or {}
    for key in ("brand", "vendor"):
        if isinstance(attrs.get(key), str) and attrs[key].strip():
            return attrs[key].strip()
    text = _norm(f"{line.get('offered_spec') or ''} {attrs.get('name') or ''}")
    return next((b for b in BRANDS if f" {b} " in f" {text} "), None)


def recalls_for_bids(bids, fetch=None, now=None, cache_dir=None) -> tuple[list[dict], list[dict]]:
    """CPSC entries for the brands and models the bids name, as {"match": sku, "source_url"}. No brand or a failed lookup is unverified."""
    found, notes, seen = [], [], set()
    for bid in bids:
        for line in bid.get("lines", []):
            sku, brand = _norm(line.get("sku_spec")), brand_of(line)
            if (sku, brand) in seen:
                continue
            seen.add((sku, brand))
            r = cpsc.recalls_for(f"{brand or ''} {sku}".strip(), brand or "", fetch=fetch, now=now, cache_dir=cache_dir)
            if r["status"] == "found":
                found.append({"match": sku, "source_url": r["recalls"][0].get("url") or r.get("source_url") or "https://www.cpsc.gov/Recalls"})
            elif r["status"] == "unverified":
                why = r.get("reason") or "the CPSC lookup failed"
                notes.append(_note("advocate.recall_unverified", f"Recall check unavailable for {sku} (unverified): {why}.",
                                   r.get("source_url") or "https://www.cpsc.gov/Recalls"))
    return found, notes


def with_notes(cards: list[dict], notes: list[dict]) -> list[dict]:
    """One labelled note per unverified lookup on every card (an INFO warning: it never changes the recommendation)."""
    seen, unique = set(), []
    for n in notes:
        if n["text"] not in seen:
            seen.add(n["text"])
            unique.append(n)
    for c in cards:
        c["warnings"] = list(c.get("warnings", [])) + [dict(n) for n in unique]
    return cards


def advice_inputs(need: dict, bids: list[dict], fetch=None, now=None, as_of=None, rows=None, cache_dir=None):
    """Everything advocate_agent passes to checks.advise: baseline, records, recalls, notes. We hold no real seller records yet,
    so records is empty (no record warning) rather than the SIM table."""
    skus = [i["sku_spec"] for i in need.get("items", [])] + [l["sku_spec"] for b in bids for l in b.get("lines", [])]
    baseline, notes = baseline_for(skus, as_of=as_of, rows=rows)
    recalls, recall_notes = recalls_for_bids(bids, fetch=fetch, now=now, cache_dir=cache_dir)
    return baseline, {}, recalls, notes + recall_notes


def shield_baseline(as_of=None, rows=None) -> dict:
    """The buyer's trusted price references: only real, dated baselines (no sample prices). A SKU without one gets no price
    reference, which screen_bid and hunt.public_hint already handle."""
    real, _ = baseline_for(["rtx 5070 ti"], as_of=as_of, rows=rows)
    return real
