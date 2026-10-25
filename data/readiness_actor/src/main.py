"""Apify Actor entry: what does a shopping agent see on each of your listings? One dataset row per listing URL.

Pricing (pay-per-event): one "listing-reported" event per listing whose page was fetched and read (blocks, warns or ready),
charged before its row is delivered. "unreadable" (the page could not be fetched) is free. A spent limit or a failed charge
stops the run and the summary says how many listings were not checked. The state marks a listing paid before delivery,
so a restarted run never charges a listing twice, and it keeps running status counts, so a restarted run's summary still
counts the listings checked before the restart. The rows delivered before a restart are read back from the dataset, so
OUTPUT holds every row. A run stops checking OUTPUT_RESERVE_S before its run timeout (each page fetch is capped at 30 s,
so 200 slow pages could otherwise run for well over an hour, and the platform kills a run at its timeout before it can
write OUTPUT); the listings left are not checked and not charged. URLs past MAX_LISTINGS are counted in the summary.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the bundled src/data/ imports as data.*

from apify import Actor  # noqa: E402

from data.readiness import check_listing  # noqa: E402

EVENT = "listing-reported"
STATE_KEY = "STATE_next_listing"
MAX_LISTINGS = 200
STATUSES = ("blocks", "warns", "ready", "unreadable")
# #449 RT-29: the Actor's default run timeout is 300 s (set in the Apify Console, docs/ACTORS.md; actor.json has no
# defaultRunOptions), and the old 15 minute budget meant a big run was killed before it wrote OUTPUT. The budget keeps
# OUTPUT_RESERVE_S free at the end: one page still in flight (30 s cap) plus time to write OUTPUT and the status line.
DEFAULT_TIMEOUT_S = 300
OUTPUT_RESERVE_S = 60
RUN_BUDGET_S = DEFAULT_TIMEOUT_S - OUTPUT_RESERVE_S


def run_budget_s(environ=os.environ, now: datetime | None = None) -> float:
    """Seconds this run may spend checking pages. When the platform names the run's deadline (ACTOR_TIMEOUT_AT, or the
    older APIFY_TIMEOUT_AT, an ISO time with a zone) it is that deadline minus OUTPUT_RESERVE_S, so a run started with a
    longer or shorter timeout is still safe; with none, or an unreadable one, the default timeout's budget."""
    raw = str(environ.get("ACTOR_TIMEOUT_AT") or environ.get("APIFY_TIMEOUT_AT") or "").strip()
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return RUN_BUDGET_S
    if at.tzinfo is None:
        return RUN_BUDGET_S
    return max(0.0, (at - (now or datetime.now(timezone.utc))).total_seconds() - OUTPUT_RESERVE_S)


def urls_and_dropped(inp: dict) -> tuple[list[str], int]:
    """The listing URLs, one per line or list item, de-duplicated in order, at most MAX_LISTINGS; and how many distinct
    URLs came after the cap and were dropped (#449 RT-29: that used to be silent)."""
    raw = (inp if isinstance(inp, dict) else {}).get("listingUrls") or []
    raw = raw.splitlines() if isinstance(raw, str) else raw if isinstance(raw, (list, tuple)) else []  # 5, {..}: no URLs
    out, seen = [], set()
    for item in raw:
        url = item.get("url") if isinstance(item, dict) else item  # the requestListSources editor gives {"url": ...}
        url = str(url or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out[:MAX_LISTINGS], max(0, len(out) - MAX_LISTINGS)


def urls_from(inp: dict) -> list[str]:
    """The listing URLs checked (see urls_and_dropped)."""
    return urls_and_dropped(inp)[0]


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


def summary(rows: list, total: int, stopped: str | None = None, counts: dict | None = None, dropped: int = 0) -> str:
    n = counts or count(rows)
    checked = sum(n.values())
    if checked == 1 and total == 1 and len(rows) == 1 and not dropped:
        return rows[0]["summary"]
    out = f"{checked} listing(s): {n['blocks']} blocks, {n['warns']} warns, {n['ready']} ready, {n['unreadable']} unreadable"
    if checked < total:
        out += f"; {total - checked} not checked: {stopped or 'stopped early'}"
    if dropped:
        out += f"; {dropped} URL(s) over the {MAX_LISTINGS}-listing limit were not checked"
    return out


async def run_listings(urls, check, push, charge, log=print, get_state=None, set_state=None, prior=None,
                       budget_s=RUN_BUDGET_S, clock=time.monotonic):
    """Check each listing, charge it (only when its page was read), then deliver its row. Returns (rows, stopped, counts):
    counts covers every listing delivered, also those delivered before a restart (kept in the state). prior is the rows
    delivered before a restart (the dataset). The run stops once budget_s has passed; the listings left are not checked."""
    index, paid, counts = _state(await get_state()) if get_state else (0, False, None)
    rows, stopped = list(prior or [])[:index], None
    counts = counts if counts is not None else count(rows)
    end = clock() + budget_s
    for i in range(index, len(urls)):
        if clock() >= end:
            stopped = f"the run time limit of {budget_s / 60:g} minutes was reached"
            break
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
        urls, dropped = urls_and_dropped(await Actor.get_input())
        if not urls:
            await Actor.set_status_message("No listing URL given: add one or more product page URLs", is_terminal=True)
            return
        prior = [item async for item in (await Actor.open_dataset()).iterate_items()]  # rows delivered before a restart
        rows, stopped, counts = await run_listings(urls, check_listing, Actor.push_data, Actor.charge, log=Actor.log.warning, prior=prior,
                                           get_state=lambda: Actor.get_value(STATE_KEY), set_state=lambda v: Actor.set_value(STATE_KEY, v),
                                           budget_s=run_budget_s())
        line = summary(rows, len(urls), stopped, counts, dropped)
        await Actor.set_value("OUTPUT", {"summary": line, "checked": sum(counts.values()), "total": len(urls), "dropped": dropped,
                                         "results": rows})
        await Actor.set_status_message(line, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
