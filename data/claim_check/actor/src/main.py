"""Apify Actor entry: one dataset row per claim (the claim plus its check result).

Pricing (pay-per-event): one "claim-checked" event per claim whose page was fetched and judged. Nothing is charged when the page
cannot be fetched or the claim is not checked. A failed charge (or a run without pay-per-event pricing) is logged and never
fails the run.
"""
import asyncio

from apify import Actor

from src.data.claim_check import check_claim

EVENT = "claim-checked"


def judged(result: dict) -> bool:
    """True when the page was fetched and a verdict was reached on it (the check hashes every page it reads)."""
    return bool(result.get("evidence_hash")) and result.get("result") in ("verified", "false", "unverified")


async def run_claims(claims, check, push, charge, log=print) -> int:
    """Check each claim, push its row, charge one event per judged claim. Returns the number of events charged."""
    charged = 0
    for claim in claims:
        try:
            result = await asyncio.to_thread(check, claim)
        except Exception as e:  # one bad claim never stops the batch
            result = {"result": "unverified", "method": f"could not verify: {type(e).__name__}", "reason": "could not verify"}
        row = claim if isinstance(claim, dict) else {"claim": claim}
        await push({**row, **result})
        if judged(result):
            try:
                await charge(event_name=EVENT, count=1)
                charged += 1
            except Exception as e:  # not on pay-per-event pricing, or the charge failed: log it and go on
                log(f"charge skipped ({type(e).__name__}): {e}")
    return charged


async def main():
    async with Actor:
        claims = (await Actor.get_input() or {}).get("claims") or []
        await run_claims(claims, check_claim, Actor.push_data, Actor.charge, log=Actor.log.warning)


if __name__ == "__main__":
    asyncio.run(main())
