"""Apify Actor entry: what does a shopping agent see on each of your listings? One dataset row per listing URL.

Pricing (pay-per-event): one "listing-reported" event per listing whose page was fetched and read (blocks, warns or ready),
charged before its row is delivered. "unreadable" (the page could not be fetched) is free. A spent limit or a failed charge
stops the run and the summary says how many listings were not checked. The state marks a listing paid before delivery,
so a restarted run never charges a listing twice, and it keeps running status counts, so a restarted run's summary still
counts the listings checked before the restart.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the bundled src/data/ imports as data.*

from apify import Actor  # noqa: E402

from data.readiness import check_listing  # noqa: E402

EVENT = "listing-reported"
STATE_KEY = "STATE_next_listing"
MAX_LISTINGS = 200
STATUSES = ("blocks", "warns", "ready", "unreadable")


def urls_from(inp: dict) -> list[str]:
    """The listing URLs, one per line or list item, de-duplicated in order (at most MAX_LISTINGS)."""
    raw = (inp or {}).get("listingUrls") or []
    raw = raw.splitlines() if isinstance(raw, str) else raw
    out = []
    for item in raw:
        url = item.get("url") if isinstance(item, dict) else item  # the requestListSources editor gives {"url": ...}
        url = str(url or "").strip()
        if url and url not in out:
            out.append(url)
    return out[:MAX_LISTINGS]


def row_of(i: int, r: dict) -> dict:
    blocks = [f for f in r["findings"] if f["severity"] == "blocks"]
    first = (blocks or r["findings"] or [{}])[0]
    return {"id": f"l{i}", "url": r["url"], "status": r["status"], "summary": r["summary"],
            "blocks": len(blocks), "warns": len(r["findings"]) - len(blocks),
            "first_rule": first.get("rule_id"), "first_fix": first.get("fix"),
            "findings": r["findings"], "facts_read": r["facts_read"], "read_from": r.get("read_from"),
            "checked_at": r["checked_at"], "origin": r["origin"]}


def count(rows: list) -> dict:
    return {s: sum(1 for r in rows if r.get("status") == s) for s in STATUSES}


def _state(v) -> tuple[int, bool, dict | None]:
    """(next index, whether that listing is already paid, the status counts so far or None when the state has none)."""
    counts = None
    if isinstance(v, dict):
        c = v.get("counts")
        if isinstance(c, dict):
            try:
                counts = {s: max(0, int(c.get(s) or 0)) for s in STATUSES}
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
    checked = sum(n.values())
    if checked == 1 and total == 1 and len(rows) == 1:
        return rows[0]["summary"]
    out = f"{checked} listing(s): {n['blocks']} blocks, {n['warns']} warns, {n['ready']} ready, {n['unreadable']} unreadable"
    if checked < total:
        out += f"; {total - checked} not checked: {stopped or 'stopped early'}"
    return out


async def run_listings(urls, check, push, charge, log=print, get_state=None, set_state=None, prior=None):
    """Check each listing, charge it (only when its page was read), then deliver its row. Returns (rows, stopped, counts):
    counts covers every listing delivered, also those delivered before a restart (kept in the state, not in OUTPUT)."""
    index, paid, counts = _state(await get_state()) if get_state else (0, False, None)
    rows, stopped = list(prior or [])[:index], None
    counts = counts if counts is not None else count(rows)
    for i in range(index, len(urls)):
        try:
            r = check(urls[i])
        except Exception as e:  # one bad listing never stops the batch, and never reads as "ready"
            r = {"url": urls[i], "status": "unreadable", "summary": f"UNREADABLE: could not check ({type(e).__name__})",
                 "findings": [], "facts_read": {}, "read_from": None, "checked_at": None, "origin": "LIVE"}
        res = None
        if r["status"] != "unreadable" and not (paid and i == index):
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
        row = row_of(i + 1, r)
        await push(row)
        rows.append(row)
        counts = {**counts, row["status"]: counts[row["status"]] + 1}
        if set_state:
            await set_state({"index": i + 1, "paid": False, "counts": counts})
        if getattr(res, "event_charge_limit_reached", False):
            stopped = "your charge limit was reached"
            break
    return rows, stopped, counts


async def main():
    async with Actor:
        urls = urls_from(await Actor.get_input())
        if not urls:
            await Actor.set_status_message("No listing URL given: add one or more product page URLs", is_terminal=True)
            return
        prior = ((await Actor.get_value("OUTPUT")) or {}).get("results") or []
        rows, stopped, counts = await run_listings(urls, check_listing, Actor.push_data, Actor.charge, log=Actor.log.warning, prior=prior,
                                           get_state=lambda: Actor.get_value(STATE_KEY), set_state=lambda v: Actor.set_value(STATE_KEY, v))
        line = summary(rows, len(urls), stopped, counts)
        await Actor.set_value("OUTPUT", {"summary": line, "checked": sum(counts.values()), "total": len(urls), "results": rows})
        await Actor.set_status_message(line, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
