"""Apify Actor entry: check each PC build and write one dataset row per rule (pass, fail or uncertain, with maker sources).

Pricing (pay-per-event): one "build-checked" event per build that ran at least one rule. A build with no pair of parts to
compare, or one we could not read, is free. A failed charge (or a run without pay-per-event pricing) is logged and never
fails the run. The next build index is saved before the charge, so a restarted run never charges a build twice.
"""
import asyncio

from apify import Actor

from src.data.fit_checker.build_check import check_build

EVENT = "build-checked"
STATE_KEY = "STATE_next_build"


def builds_from(inp: dict) -> list:
    """The single build form plus any batch builds, each as {id, parts}."""
    inp = inp or {}
    out = [{"id": "build-1", "parts": inp["parts"]}] if isinstance(inp.get("parts"), dict) and inp["parts"] else []
    for i, b in enumerate(inp.get("builds") or [], 1):
        if isinstance(b, dict) and isinstance(b.get("parts"), dict):
            out.append({"id": str(b.get("id") or f"batch-{i}"), "parts": b["parts"]})
    return out


def check_one(build: dict) -> dict:
    try:
        return {"build_id": build["id"], **check_build(build["parts"])}
    except Exception as e:  # one unreadable build never stops the batch, and never passes
        return {"build_id": build["id"], "verdict": "uncertain", "summary": f"UNCERTAIN: could not read this build ({type(e).__name__})",
                "checks": [], "notes": [], "parts": {}}


def rows_of(result: dict) -> list:
    checks = result["checks"] or [{"rule_id": "fit.no_checks", "verdict": "uncertain", "reason": result["summary"], "parts": [], "sources": []}]
    return [{"build_id": result["build_id"], "build_verdict": result["verdict"], **c} for c in checks]


def summary(results: list) -> str:
    if len(results) == 1:
        return results[0]["summary"]
    n = {v: sum(1 for r in results if r["verdict"] == v) for v in ("pass", "fail", "uncertain")}
    return f"{len(results)} builds: {n['pass']} pass, {n['fail']} fail, {n['uncertain']} uncertain"


async def run_builds(builds, push, charge, log=print, get_state=None, set_state=None) -> list:
    """Check each build, push its rows, charge one event per build that ran a rule. Stops at the user's charge limit."""
    start = int((await get_state()) or 0) if get_state else 0
    results = []
    for index in range(start, len(builds)):
        r = check_one(builds[index])
        results.append(r)
        await push(rows_of(r))
        if set_state:
            await set_state(index + 1)
        if not r["checks"]:
            continue
        try:
            res = await charge(event_name=EVENT, count=1)
        except Exception as e:  # not on pay-per-event pricing, or the charge failed: log it and go on
            log(f"charge skipped ({type(e).__name__}): {e}")
            continue
        if getattr(res, "event_charge_limit_reached", False):
            log("the user's charge limit for build-checked was reached; stopping")
            break
    return results


async def main():
    async with Actor:
        builds = builds_from(await Actor.get_input())
        if not builds:
            await Actor.set_status_message("No build given: add your parts under Your build", is_terminal=True)
            return
        results = await run_builds(builds, Actor.push_data, Actor.charge, log=Actor.log.warning,
                                   get_state=lambda: Actor.get_value(STATE_KEY), set_state=lambda v: Actor.set_value(STATE_KEY, v))
        await Actor.set_value("OUTPUT", {"summary": summary(results), "builds": results})
        await Actor.set_status_message(summary(results), is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
