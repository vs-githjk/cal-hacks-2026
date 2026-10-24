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


def judged(result: dict) -> bool:
    """Billable: the page was fetched and gave a verdict (verified or false). Unverified is always free."""
    return bool(result.get("evidence_hash")) and result.get("result") in ("verified", "false")


async def run_claims(claims, check, push, charge, log=print, get_state=None, set_state=None) -> int:
    """Check each claim, push its row, charge one event per billable claim. Returns the number of events charged.

    The next index is saved after a row is pushed and before it is charged, so a restart resumes after it: a crash can at
    worst leave one claim uncharged, never charge it twice. apify 2.7.3's Actor.charge(event_name, count) has no
    idempotency key, so the saved index is the only guard. The loop stops when the user's charge limit is reached."""
    start = int((await get_state()) or 0) if get_state else 0
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
        claims = (await Actor.get_input() or {}).get("claims") or []
        await run_claims(claims, check_claim, Actor.push_data, Actor.charge, log=Actor.log.warning,
                         get_state=lambda: Actor.get_value(STATE_KEY), set_state=lambda v: Actor.set_value(STATE_KEY, v))


if __name__ == "__main__":
    asyncio.run(main())
