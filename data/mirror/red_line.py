"""Is the demo's red line real? (#342) Free, offline: reads the captured MIRROR offers and the planner's rule.

python -m data.mirror.red_line

The planner (#344) tries each part's offers cheapest first and, after every pick, splits what is left of the budget across the
parts still open. If the cheapest offer for a part clashes with a part already picked (the fit checker's own rules, maker rows
only), that is the red; the next offer that fits is the swap; the line goes green. This prints which clash the Build Story would
hit on the real prices, or says there is none, so the beat is only shown as real when it is.
"""
from __future__ import annotations

from data.fit_checker import build_check

ORDER = ("cpu", "motherboard", "memory", "storage", "cooler")
# the planner's budgets on #344 for the parts around the GPU (cents)
BUDGETS = {"cpu": 28400, "motherboard": 17200, "memory": 10126, "storage": 12151, "cooler": 5569}
CASE = "Fractal Design North"   # the demo case (maker row in depth_data.json): the cooler height rule reads it
SPEC_KEYS = ("name", "model_number", "category")


def _build(picks: dict, case: str | None) -> dict:
    build = {}
    for part, o in picks.items():
        attrs = {k: v for k, v in o["spec"].items() if k not in SPEC_KEYS}
        d = {"name": o["spec"].get("name", ""), **attrs}
        if part == "storage":
            build["storage"] = [d]
        else:
            build[part] = d
    if case:
        build["case"] = {"name": case}
    return build


def _fails(picks: dict, case: str | None) -> list[dict]:
    return [c for c in build_check.check_build(_build(picks, case))["checks"] if c["verdict"] == "fail"]


def find(offers: dict, budgets: dict | None = None, case: str | None = None) -> dict:
    """offers: {part: [offer]} in #344's shape. -> {verdict, clash, swap, picks, events, total_cents}."""
    budgets = dict(budgets or BUDGETS)
    picks, events, clash, swap = {}, [], None, None
    open_parts = [p for p in ORDER if offers.get(p)]
    pool = sum(budgets[p] for p in open_parts)
    for part in ORDER:
        if not offers.get(part):
            continue
        share = pool * budgets[part] / sum(budgets[p] for p in open_parts)
        # the planner moves budget between open parts: a pick may pass its own share if the parts still open can be covered
        rest = [p for p in open_parts if p != part]
        room = pool - sum(min(o["price_cents"] for o in offers[p]) for p in rest)
        chosen = None
        for o in sorted(offers[part], key=lambda o: (o["price_cents"], o["seller"], str(o["source"]))):
            if o["price_cents"] > max(share, room):
                events.append({"kind": "over_budget", "part": part, "title": o["spec"].get("name"), "price_cents": o["price_cents"],
                               "seller": o["seller"], "budget_cents": int(max(share, room))})
                continue
            bad = _fails({**picks, part: o}, case)
            if bad:
                ev = {"kind": "clash", "part": part, "title": o["spec"].get("name"), "price_cents": o["price_cents"], "seller": o["seller"],
                      "rule_id": bad[0]["rule_id"], "reason": bad[0]["reason"], "sources": bad[0].get("sources", [])}
                events.append(ev)
                clash = clash or ev
                continue
            chosen = o
            events.append({"kind": "pick", "part": part, "title": o["spec"].get("name"), "price_cents": o["price_cents"], "seller": o["seller"]})
            if clash and swap is None and part == clash["part"]:
                swap = events[-1]
            break
        open_parts.remove(part)
        if chosen is None:
            return {"verdict": "blocked", "blocked_part": part, "clash": clash, "swap": swap, "picks": picks, "events": events,
                    "total_cents": sum(o["price_cents"] for o in picks.values())}
        picks[part] = chosen
        pool -= chosen["price_cents"]
    return {"verdict": "red-swap-green" if clash and swap else "none", "clash": clash, "swap": swap, "picks": picks, "events": events,
            "total_cents": sum(o["price_cents"] for o in picks.values())}


def _usd(cents) -> str:
    return f"${cents / 100:,.2f}"


def report(res: dict) -> list[str]:
    lines = []
    for e in res["events"]:
        tag = {"pick": "GREEN", "clash": "RED", "over_budget": "over budget"}[e["kind"]]
        extra = f" ({e['rule_id']}: {e['reason']})" if e["kind"] == "clash" else (f" (budget {_usd(e['budget_cents'])})" if e["kind"] == "over_budget" else "")
        lines.append(f"{tag:<11} {e['part']:<11} {e['title']} from {e['seller']} {_usd(e['price_cents'])}{extra}")
    v = res["verdict"]
    if v == "red-swap-green":
        c, s = res["clash"], res["swap"]
        lines.append(f"REAL RED LINE: {c['rule_id']} on the {c['part']}: {c['title']} {_usd(c['price_cents'])} clashes; swapped to {s['title']} {_usd(s['price_cents'])}. "
                     "Maker pages cited, MIRROR prices.")
    elif v == "blocked":
        lines.append(f"BLOCKED at the {res['blocked_part']}: no captured offer fits and stays in budget. Nothing would be paid.")
    else:
        lines.append("NO REAL RED LINE on these prices: no captured offer clashes with an earlier pick. The beat stays on SIM parts, labelled SIM.")
    lines.append(f"Locked so far: {len(res['picks'])} parts, {_usd(res['total_cents'])}")
    return lines


def main(argv=None) -> int:
    """python -m data.mirror.red_line [--budget part=cents ...]: a budget override shows a what-if, never the planner's real budget."""
    import sys
    from data.mirror import parts
    budgets = dict(BUDGETS)
    for a in (argv if argv is not None else sys.argv[1:]):
        if a == "--budget":
            continue
        k, _, v = a.partition("=")
        if k in budgets and v.isdigit():
            budgets[k] = int(v)
            print(f"what-if: {k} budget {_usd(int(v))} instead of {_usd(BUDGETS[k])}")
    offers = {p: parts.offers(p) for p in ORDER}
    for p in ORDER:
        print(f"{p}: {len(offers[p])} offer(s) with a maker row, {len(parts.skipped(p))} captured listing(s) skipped")
    for line in report(find(offers, budgets, case=CASE)):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
