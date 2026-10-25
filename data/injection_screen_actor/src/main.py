"""Apify Actor entry: screen listing text (title, description, seller notes) for prompt injection, approval skips,
payee swaps and secret asks before an AI shopping agent reads it. One dataset row per listing.

The screen is Bazaar Shield's deterministic rules, unchanged (src/screen.py wraps shield.core.screen; bundle.sh copies
shield/ in). The Shield classifier stays off: no LLM is called and no API key is read.

Pricing (pay-per-event): one "listing-screened" event per listing Shield read (block, flag or pass), charged before its
row is delivered. A listing with no text, a field that is not text, or text Shield did not read (over 20,000
characters, or an internal error) is free. A spent limit or a failed charge stops the run and the summary says how
many listings were not screened. The state marks a listing paid before delivery, so a restarted run never charges a
listing twice, and it keeps running verdict counts, so a restarted run's summary still counts the listings screened
before the restart. The rows delivered before a restart are read back from the dataset, so OUTPUT holds every row.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the bundled src/shield/ and src/screen.py import

from apify import Actor  # noqa: E402

from screen import screen_text  # noqa: E402

EVENT = "listing-screened"
STATE_KEY = "STATE_next_listing"
MAX_LISTINGS = 1000
VERDICTS = ("block", "flag", "pass", "skipped")
FIELDS = (("title", ("title",)), ("description", ("description",)), ("seller_notes", ("sellerNotes", "seller_notes")))
ORIGINS = ("LIVE", "MIRROR", "SIM")
SEP = "\n\n"


def listings_from(inp) -> list:
    """The listings: objects from `listings` (title, description, sellerNotes, optional id, url, origin), then one
    listing per item of `texts`. At most MAX_LISTINGS. Items of the wrong shape are kept, so they show as skipped."""
    inp = inp if isinstance(inp, dict) else {}
    out = []
    raw = inp.get("listings")
    for item in (raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []):
        out.append({"description": item} if isinstance(item, str) else item)
    texts = inp.get("texts")
    for t in (texts if isinstance(texts, list) else [texts] if isinstance(texts, str) else []):
        out.append({"description": t})
    return out[:MAX_LISTINGS]


def join_fields(listing) -> tuple:
    """(text, parts) where parts are (field, start, end) offsets in text; or (None, why) when nothing can be screened."""
    if not isinstance(listing, dict):
        return None, "the listing is not an object with title, description or sellerNotes"
    pieces = []
    for field, keys in FIELDS:
        value = next((listing[k] for k in keys if listing.get(k) is not None), None)
        if value is None:
            continue
        if not isinstance(value, str):
            return None, f"{field} is not text"
        if value.strip():
            pieces.append((field, value))
    if not pieces:
        return None, "no text to screen"
    text, parts = "", []
    for field, value in pieces:
        text += SEP if text else ""
        parts.append((field, len(text), len(text) + len(value)))
        text += value
    return text, parts


def _field_of(parts, start: int, end: int) -> dict:
    for field, s, e in parts:
        if s <= start < e or (start == e == s):
            return {"field": field, "start": start - s, "end": min(end, e) - s}
    return {"field": None, "start": start, "end": end}  # a span on a separator: offsets in the joined text


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _origin(listing) -> str:
    o = str(listing.get("origin") or "").strip().upper() if isinstance(listing, dict) else ""
    return o if o in ORIGINS else "LIVE"


def _summary(verdict: str, rule_ids: list, screened: bool, why: str | None = None) -> str:
    if verdict == "skipped":
        return f"SKIPPED: {why}; not screened, not charged"
    if verdict == "pass":
        return "PASS: no Shield rule fired (rules only; a pass is not proof the text is harmless)"
    head = f"{verdict.upper()}: {len(rule_ids)} rule(s) fired; first: {rule_ids[0]}" if rule_ids else verdict.upper()
    return head + ("" if screened else "; not screened, not charged")


def screen_listing(i: int, listing, screen=screen_text) -> dict:
    """One dataset row for one listing."""
    lid = listing.get("id") if isinstance(listing, dict) else None
    url = listing.get("url") if isinstance(listing, dict) else None
    row = {"id": f"l{i}", "listing_id": str(lid) if lid is not None else f"l{i}",
           "url": url if isinstance(url, str) and url.strip() else None,
           "checked_at": _now(), "origin": _origin(listing)}
    text, parts = join_fields(listing)
    if text is None:
        return {**row, "verdict": "skipped", "summary": _summary("skipped", [], False, parts), "rule_ids": [],
                "first_rule": None, "first_reason": None, "findings": [], "fields_screened": [], "screened": False,
                "shield_verdict": None, "severity": None, "screener": None}
    try:
        r = screen(text)
    except Exception as e:  # Shield fails closed itself; this is a second guard so nothing ever reads as pass
        r = {"verdict": "block", "shield_verdict": None, "severity": "critical", "rule_ids": ["shield.error"], "spans": [],
             "reasons": {"shield.error": f"the screen raised {type(e).__name__}; failed closed"}, "screened": False,
             "screener": None}
    findings = []
    for rule_id in r["rule_ids"]:
        matches = [{**_field_of(parts, s["start"], s["end"]), "excerpt": s["excerpt"]}
                   for s in r["spans"] if s["rule_id"] == rule_id]
        findings.append({"rule_id": rule_id, "reason": r["reasons"].get(rule_id, rule_id), "matches": matches})
    return {**row, "verdict": r["verdict"], "summary": _summary(r["verdict"], r["rule_ids"], r["screened"]),
            "rule_ids": r["rule_ids"], "first_rule": r["rule_ids"][0] if r["rule_ids"] else None,
            "first_reason": findings[0]["reason"] if findings else None, "findings": findings,
            "fields_screened": [p[0] for p in parts], "screened": r["screened"], "shield_verdict": r["shield_verdict"],
            "severity": r["severity"], "screener": r["screener"]}


def count(rows: list) -> dict:
    return {v: sum(1 for r in rows if r.get("verdict") == v) for v in VERDICTS}


def _state(v) -> tuple[int, bool, dict | None]:
    """(next index, whether that listing is already paid, the verdict counts so far or None when the state has none)."""
    counts = None
    if isinstance(v, dict):
        c = v.get("counts")
        if isinstance(c, dict):
            try:
                counts = {s: max(0, int(c.get(s) or 0)) for s in VERDICTS}
            except (TypeError, ValueError):
                counts = None
        v, paid = v.get("index"), bool(v.get("paid"))
    else:
        paid = False
    try:
        return max(0, int(v or 0)), paid, counts
    except (TypeError, ValueError):
        return 0, False, None


def summary(rows: list, total: int, stopped: str | None = None, counts: dict | None = None) -> str:
    n = counts or count(rows)
    done = sum(n.values())
    if done == 1 and total == 1 and len(rows) == 1:
        return rows[0]["summary"]
    out = f"{done} listing(s): {n['block']} block, {n['flag']} flag, {n['pass']} pass, {n['skipped']} skipped"
    if done < total:
        out += f"; {total - done} not screened: {stopped or 'stopped early'}"
    return out


async def run_listings(listings, screen_one, push, charge, log=print, get_state=None, set_state=None, prior=None):
    """Screen each listing, charge it (only when Shield read it), then deliver its row. Returns (rows, stopped, counts):
    counts covers every listing delivered, also those delivered before a restart (kept in the state). prior is the rows
    delivered before a restart (the dataset)."""
    index, paid, counts = _state(await get_state()) if get_state else (0, False, None)
    rows, stopped = list(prior or [])[:index], None
    counts = counts if counts is not None else count(rows)
    for i in range(index, len(listings)):
        row = screen_one(i + 1, listings[i])
        res = None
        if row["screened"] and not (paid and i == index):
            try:
                res = await charge(event_name=EVENT, count=1)
            except Exception as e:
                log(f"charge failed ({type(e).__name__}); stopping so no result is delivered unpaid")
                stopped = "the charge failed"
                break
            if getattr(res, "event_charge_limit_reached", False) and not getattr(res, "charged_count", 1):
                stopped = "your charge limit was reached"
                break
            if set_state:
                await set_state({"index": i, "paid": True, "counts": counts})
        await push(row)
        rows.append(row)
        counts = {**counts, row["verdict"]: counts[row["verdict"]] + 1}
        if set_state:
            await set_state({"index": i + 1, "paid": False, "counts": counts})
        if getattr(res, "event_charge_limit_reached", False):
            stopped = "your charge limit was reached"
            break
    return rows, stopped, counts


async def main():
    async with Actor:
        listings = listings_from(await Actor.get_input())
        if not listings:
            await Actor.set_status_message("No listing given: add a title, description or seller notes", is_terminal=True)
            return
        prior = [item async for item in (await Actor.open_dataset()).iterate_items()]  # rows delivered before a restart
        rows, stopped, counts = await run_listings(listings, screen_listing, Actor.push_data, Actor.charge, log=Actor.log.warning,
                                                   prior=prior, get_state=lambda: Actor.get_value(STATE_KEY),
                                                   set_state=lambda v: Actor.set_value(STATE_KEY, v))
        line = summary(rows, len(listings), stopped, counts)
        await Actor.set_value("OUTPUT", {"summary": line, "done": sum(counts.values()), "total": len(listings),
                                         "results": rows})
        await Actor.set_status_message(line, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
