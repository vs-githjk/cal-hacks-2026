"""Apify Actor entry: one dataset row per claim (the claim plus its check result)."""
import asyncio

from apify import Actor

from src.data.claim_check import check_claim


async def main():
    async with Actor:
        claims = (await Actor.get_input() or {}).get("claims") or []
        for claim in claims:
            try:
                result = await asyncio.to_thread(check_claim, claim)
            except Exception as e:  # one bad claim never stops the batch
                result = {"result": "unverified", "method": f"could not verify: {type(e).__name__}", "reason": "could not verify"}
            row = claim if isinstance(claim, dict) else {"claim": claim}
            await Actor.push_data({**row, **result})


if __name__ == "__main__":
    asyncio.run(main())
