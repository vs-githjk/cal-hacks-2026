"""Apify Actor entry: check each PC build and write one dataset row per rule (pass, fail or uncertain, with maker sources).

Pricing (pay-per-event): one "build-checked" event per build that ran at least one rule, charged before its rows are delivered.
A build with no pair of parts to compare is free. A spent limit or a failed charge stops the run and the summary says how many
builds were not run. The state marks a build paid before delivery, so a restarted run never charges a build twice.
"""
import asyncio

from apify import Actor

from src.data.fit_checker.build_check import check_build

EVENT = "build-checked"
STATE_KEY = "STATE_next_build"


FORM_SPECS = {"cpuSocket": ("cpu", "socket"), "cpuVendor": ("cpu", "vendor"), "cpuTdpW": ("cpu", "tdp_w"),
              "boardSocket": ("motherboard", "socket"), "boardFormFactor": ("motherboard", "form_factor"),
              "boardMemorySlots": ("motherboard", "memory_slots"), "memoryType": ("memory", "type"), "memoryForm": ("memory", "form"),
              "memoryModules": ("memory", "modules"), "gpuLengthMm": ("gpu", "length_mm"), "psuWattage": ("psu", "wattage"),
              "psuFormFactor": ("psu", "form_factor"), "psu16pin": ("psu", "pcie_16pin"), "psu8pin": ("psu", "pcie_8pin"),
              "caseMaxGpuLengthMm": ("case", "max_gpu_length_mm"), "caseMaxCoolerHeightMm": ("case", "max_cooler_height_mm"),
              "caseBoardSizes": ("case", "motherboard_form_factors"), "casePsuSizes": ("case", "psu_form_factors"),
              "coolerHeightMm": ("cooler", "height_mm")}
FORM_PARTS = ("cpu", "motherboard", "memory", "gpu", "psu", "case", "cooler")


def form_parts(inp: dict) -> dict:
    """The form's part names and specs as a parts object. A spec without its part's name still makes that part."""
    parts = {}
    for cat in FORM_PARTS:
        if isinstance(inp.get(cat), str) and inp[cat].strip():
            parts.setdefault(cat, {})["name"] = inp[cat].strip()
    for key, (cat, attr) in FORM_SPECS.items():
        v = inp.get(key)
        if v not in (None, "", []):
            parts.setdefault(cat, {}).setdefault("name", "")
            parts[cat][attr] = v
    return parts


def builds_from(inp: dict) -> list:
    """The form build (with the advanced JSON build merged over it, part by part) plus any batch builds, each as {id, parts}."""
    inp = inp or {}
    parts = form_parts(inp)
    if isinstance(inp.get("parts"), dict):
        for cat, given in inp["parts"].items():
            parts[cat] = {**parts.get(cat, {}), **given} if isinstance(given, dict) and isinstance(parts.get(cat), dict) else given
    out = [{"id": "build-1", "parts": parts}] if parts else []
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
    return [{"build_id": result["build_id"], "build_verdict": result["verdict"], "complete": result.get("complete", False),
             "missing_parts": result.get("missing_parts", []), **c} for c in checks]


def summary(results: list, total: int | None = None, stopped: str | None = None, earlier: int = 0) -> str:
    if len(results) == 1 and not stopped:
        out = results[0]["summary"]
    else:
        n = {v: sum(1 for r in results if r["verdict"] == v) for v in ("pass", "partial", "fail", "uncertain")}
        out = f"{len(results)} build(s): {n['pass']} pass, {n['partial']} partial, {n['fail']} fail, {n['uncertain']} uncertain"
    if earlier:
        out += f"; {earlier} earlier build(s) were checked before a restart (their rows are in the dataset)"
    if total is not None and len(results) + earlier < total:
        out += f"; {total - len(results) - earlier} build(s) not run: {stopped or 'stopped early'}"
    return out


def _index(v) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def _state(v) -> tuple[int, bool]:
    """(next build index, whether that build is already paid). A missing or corrupt state starts from the top."""
    if isinstance(v, dict):
        return _index(v.get("index")), bool(v.get("paid"))
    return _index(v), False


async def run_builds(builds, push, charge, log=print, get_state=None, set_state=None, prior=None, save=None):
    """Check each build, charge it, then deliver its rows. Returns (results, stopped).

    Charge first, so no build is delivered once the user's limit is spent. The state records a paid build before its rows
    are pushed, so a restart re-delivers it without charging again. A failed charge stops the run (nothing is delivered
    unpaid). A build that ran no rule is free and is always delivered."""
    index, paid = _state(await get_state()) if get_state else (0, False)
    results, stopped = list(prior or [])[:index], None
    unrecorded = index - len(results)  # checked before a restart, but the OUTPUT record that listed them was lost
    for i in range(index, len(builds)):
        r, res = check_one(builds[i]), None
        if r["checks"] and not (paid and i == index):
            try:
                res = await charge(event_name=EVENT, count=1)
            except Exception as e:
                log(f"charge failed ({type(e).__name__}); stopping so no build is delivered unpaid")
                stopped = "the charge failed"
                break
            if getattr(res, "event_charge_limit_reached", False) and not getattr(res, "charged_count", 1):
                stopped = "your charge limit was reached"
                break
            if set_state:
                await set_state({"index": i, "paid": True})
        await push(rows_of(r))
        results.append(r)
        if set_state:
            await set_state({"index": i + 1, "paid": False})
        if save:
            await save(results)
        if getattr(res, "event_charge_limit_reached", False):
            stopped = "your charge limit was reached"
            break
    return results, stopped, unrecorded


async def main():
    async with Actor:
        builds = builds_from(await Actor.get_input())
        if not builds:
            await Actor.set_status_message("No build given: add your parts under Your build", is_terminal=True)
            return
        prior = ((await Actor.get_value("OUTPUT")) or {}).get("builds") or []  # a resume keeps the builds already reported

        async def save(results):
            await Actor.set_value("OUTPUT", {"summary": summary(results, len(builds)), "builds": results})
        results, stopped, earlier = await run_builds(builds, Actor.push_data, Actor.charge, log=Actor.log.warning, prior=prior, save=save,
                                            get_state=lambda: Actor.get_value(STATE_KEY), set_state=lambda v: Actor.set_value(STATE_KEY, v))
        line = summary(results, len(builds), stopped, earlier)
        await Actor.set_value("OUTPUT", {"summary": line, "checked": len(results), "total": len(builds), "builds": results})
        await Actor.set_status_message(line, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
