"""Apify Actor entry: one dataset row per claim (the claim plus its check result).

Pricing (pay-per-event): one "claim-checked" event per claim judged verified or false on a fetched page. Unverified is free,
including when the page cannot be fetched. A failed charge (or a run without pay-per-event pricing) is logged and never
fails the run.
"""
import asyncio

from apify import Actor

from src.data.claim_check import check_claim

EVENT = "claim-checked"
STATE_KEY = "STATE_next_claim"  # key-value store: index of the next claim, so a restarted run never charges a claim twice


def claims_from(inp: dict) -> list:
    """The simple form (one page, claims as plain lines) plus any batch claims (each with its own page)."""
    inp = inp or {}
    url = str(inp.get("listingUrl") or "").strip()
    raw = inp.get("claimTexts") or []
    raw = raw.splitlines() if isinstance(raw, str) else raw  # a plain string is one claim per line, never one per character
    texts = [t.strip() for t in raw if isinstance(t, str) and t.strip()]
    simple = [{"id": f"c{i}", "text": t, "evidence_url": url} for i, t in enumerate(texts, 1)] if url else []
    return simple + [c for c in inp.get("claims") or [] if c]


def summary(rows: list, total: int | None = None) -> str:
    """Counts over every row of the run (earlier rows included on a resume), and says plainly when claims were not checked."""
    counts = {k: sum(1 for r in rows if r.get("result") == k) for k in ("verified", "false", "unverified")}
    out = f"{len(rows)} claim(s): {counts['verified']} verified, {counts['false']} false, {counts['unverified']} unverified"
    if total is not None and len(rows) < total:
        out += f"; checked {len(rows)} of {total}, stopped at your charge limit ({total - len(rows)} not checked)"
    return out


def input_warning(inp: dict) -> str | None:
    inp = inp or {}
    if inp.get("claimTexts") and not str(inp.get("listingUrl") or "").strip():
        return "Claims to check were given without a product page URL, so they were skipped"
    return None


def _index(v) -> int:
    """A saved position, or 0 when it is missing or not a whole number."""
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def judged(result: dict) -> bool:
    """Billable: the page was fetched and gave a verdict (verified or false). Unverified is always free."""
    return bool(result.get("evidence_hash")) and result.get("result") in ("verified", "false")


async def run_claims(claims, check, push, charge, log=print, get_state=None, set_state=None) -> int:
    """Check each claim, push its row, charge one event per billable claim. Returns the number of events charged.

    The next index is saved after a row is pushed and before it is charged, so a restart resumes after it: a crash can at
    worst leave one claim uncharged, never charge it twice. apify 2.7.3's Actor.charge(event_name, count) has no
    idempotency key, so the saved index is the only guard. The loop stops when the user's charge limit is reached."""
    start = _index(await get_state()) if get_state else 0
    charged = 0
    for index in range(start, len(claims)):
        claim = claims[index]
        try:
            result = await asyncio.to_thread(check, claim)
        except Exception as e:  # one bad claim never stops the batch
            result = {"result": "unverified", "method": f"could not verify: {type(e).__name__}", "reason": "could not verify"}
        row = claim if isinstance(claim, dict) else {"claim": claim}
        await push({**row, **result})
        if set_state:
            await set_state(index + 1)
        if not judged(result):
            continue
        try:
            res = await charge(event_name=EVENT, count=1)
        except Exception as e:  # not on pay-per-event pricing, or the charge failed: log it and go on
            log(f"charge skipped ({type(e).__name__}): {e}")
            continue
        charged += int(getattr(res, "charged_count", 1) or 0)
        if getattr(res, "event_charge_limit_reached", False):
            log("the user's charge limit for claim-checked was reached; stopping")
            break
    return charged


async def main():
    async with Actor:
        inp = await Actor.get_input()
        claims, warning = claims_from(inp), input_warning(inp)
        if warning:
            Actor.log.warning(warning)
        if not claims:
            await Actor.set_status_message(warning or "No claims given: add a product page URL and one claim per line", is_terminal=True)
            return
        start = _index(await Actor.get_value(STATE_KEY))
        rows = (await (await Actor.open_dataset()).get_data(limit=start)).items[:start] if start else []  # a resume keeps earlier rows

        async def push(row):
            rows.append(row)
            await Actor.push_data(row)
        await run_claims(claims, check_claim, push, Actor.charge, log=Actor.log.warning,
                         get_state=lambda: Actor.get_value(STATE_KEY), set_state=lambda v: Actor.set_value(STATE_KEY, v))
        line = summary(rows, len(claims)) + (f". {warning}" if warning else "")
        await Actor.set_value("OUTPUT", {"summary": line, "checked": len(rows), "total": len(claims), "results": rows})
        await Actor.set_status_message(line, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
