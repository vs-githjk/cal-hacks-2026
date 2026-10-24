"""Apify Actor entry: check each PC build and write one dataset row per rule (pass, fail or uncertain, with maker sources)."""
import asyncio

from apify import Actor

from src.data.fit_checker.build_check import check_build


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


async def main():
    async with Actor:
        builds = builds_from(await Actor.get_input())
        if not builds:
            await Actor.set_status_message("No build given: add your parts under Your build", is_terminal=True)
            return
        results = [check_one(b) for b in builds]
        for r in results:
            await Actor.push_data(rows_of(r))
        await Actor.set_value("OUTPUT", {"summary": summary(results), "builds": results})
        await Actor.set_status_message(summary(results), is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
