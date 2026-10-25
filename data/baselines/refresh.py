"""Dated baseline refresh (Lane C, issue #355). MIRROR. COSTS APIFY CREDITS when run without --dry-run.

The advocate's price baseline is valid only while a retail ask is under 24 h old (data.baselines.WINDOW). This re-runs the
existing Apify snapshot pipeline (data.mirror.run_actors.run, the same Actors in data/mirror/actors.py: no new Actors), which
writes new dated files to data/mirror/snapshots/ and snapshots_b/ and appends to data/mirror/runs.json; then it regenerates
data/baselines/feed.json and prints the new baseline and when it goes stale.

    python3 -m data.baselines.refresh --dry-run              # the plan and estimated cost; runs nothing, needs no token
    python3 -m data.baselines.refresh --yes-spend            # run it (or omit --yes-spend and type SPEND at the prompt)
    options: --max-items N (1 to 10, default 10)  --max-usd X (refuse if the estimate is over X, default 0.50)  --sku S

    python3 -m data.baselines.refresh --parts --dry-run      # #342: the Build Story parts (cpu, board, memory, SSD, cooler)
    python3 -m data.baselines.refresh --parts                # re-run run_actors --parts for Best Buy, Micro Center, B&H and eBay
                                                             # sold only; type SPEND; --cap dollars (default 2); --items N (default 5)

APIFY_TOKEN comes from the environment (or the gitignored .env, as run_actors reads it) and is never printed.
Exit codes: 0 baseline ok, 1 refreshed but the baseline is not ok, 2 refused (no token, not confirmed, over the cap).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import data.baselines as baselines
from data.mirror import run_actors
from data.mirror.actors import ACTORS, SECOND_SOURCE

DOTENV = Path(__file__).resolve().parents[2] / ".env"
# What the baseline needs (data.baselines): retail asks (bestbuy, microcenter, bh; newegg returned 0 items twice, so it is
# left out) and eBay sold (the second data owner). (store, second family?) pairs; the Best Buy second family adds a re-check.
DEFAULT_PLAN = [("bestbuy", False), ("microcenter", False), ("bh", False), ("ebay_sold", False), ("bestbuy", True)]
HARD_MAX_ITEMS = 10  # the most items any run may return or we read
FLOOR_USD = 0.01     # a logged cost below this (repeat runs log near $0) is estimated at this
UNLOGGED_USD = 0.10  # an Actor with no logged run is estimated at this
DEFAULT_MAX_USD = 0.50
SKU = "rtx 5070 ti"


def _actor(store: str, second: bool) -> str | None:
    table = SECOND_SOURCE if second else ACTORS
    return table[store][0] if store in table else None


def estimate(plan, log) -> list[dict]:
    """Per planned run: the highest cost logged for that Actor in runs.json, at least FLOOR_USD; UNLOGGED_USD if never logged."""
    out = []
    for store, second in plan:
        actor = _actor(store, second)
        logged = [r.get("cost_usd") for r in log if r.get("actor") == actor and isinstance(r.get("cost_usd"), (int, float))]
        est = max(max(logged), FLOOR_USD) if logged else UNLOGGED_USD
        out.append({"store": store, "second": second, "actor": actor, "est_usd": round(est, 5)})
    return out


def pacific(dt: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo
        local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
        return f"{local:%Y-%m-%d %H:%M} {local.tzname()}"
    except Exception:  # no tz database: say it in UTC minus 7 (PDT until Nov 1)
        return f"{dt.astimezone(timezone(timedelta(hours=-7))):%Y-%m-%d %H:%M} PDT"


def stale_at(sku: str, rows: list[dict], now: datetime) -> datetime | None:
    """When baseline(sku) stops being ok: the first moment after `now` a row leaves its window and the status changes.
    None when it is not ok now."""
    if baselines.baseline(sku, now.isoformat(), rows=rows)["status"] != "ok":
        return None
    edges = set()
    for r in rows:
        if r.get("sku") != sku:
            continue
        if r["kind"] == "sold":
            edges.add(baselines._ts(r.get("sold_date") or r["observed_at"]) + baselines.SOLD_WINDOW)
        else:
            edges.add(baselines._ts(r["observed_at"]) + baselines.WINDOW)
    for edge in sorted(e for e in edges if e >= now):
        if baselines.baseline(sku, (edge + timedelta(seconds=1)).isoformat(), rows=rows)["status"] != "ok":
            return edge
    return None


def _have_token(env) -> bool:
    if env.get("APIFY_TOKEN", "").strip():
        return True
    try:
        return any(l.startswith("APIFY_TOKEN=") and l.split("=", 1)[1].strip() for l in DOTENV.read_text().splitlines())
    except OSError:
        return False


def _print_baseline(sku, now, out) -> int:
    rows = baselines.observations()
    b = baselines.baseline(sku, now.isoformat(), rows=rows)
    median = b["median"] if b["median"] is not None else b.get("reference_unconfirmed")
    out(f"baseline {sku} at {now.isoformat(timespec='minutes')}: status {b['status']}, median "
        f"{'$' + format(median, '.2f') if median is not None else 'none'}{'' if b['status'] == 'ok' else ' (not usable)'}, "
        f"n={b['n']} retail asks, owners {', '.join(b['owners']) or 'none'}, from {b['from']} to {b['to']}; "
        f"eBay sold n={b['sold']['n']} (kept out of the median)")
    when = stale_at(sku, rows, now)
    if when:
        out(f"goes stale at {when.isoformat(timespec='minutes')} ({pacific(when)}); refresh before then")
    else:
        out("not ok now: the advocate's cards say 'Some checks could not run' for this SKU until a refresh gives two data owners")
    return 0 if b["status"] == "ok" else 1


PARTS_STORES = ("bestbuy", "microcenter", "bh", "ebay_sold")  # what a part baseline reads: retail asks and eBay sold (no
# second family, no Central Computers crawl and no Amazon: none of them enter the median)
PARTS_DEFAULT_CAP = 2.0


def parts_refresh_plan(items: int = 5, log=None) -> list[dict]:
    return [r for r in run_actors.parts_plan(items, log=log, stores=list(PARTS_STORES)) if not r["second"]]


def _part_why(b: dict) -> str:
    if b["status"] == "one_source":
        return f"only one data owner has priced it ({', '.join(b['owners']) or 'none'})"
    if b["status"] == "thin":
        return f"fewer than 2 prices from {' and '.join(b.get('thin_owners') or ['a data owner'])}"
    return {"stale": "no in-stock Best Buy, Micro Center or B&H ask in the last 24 h", "empty": "we hold no price data for it"}.get(b["status"], b["status"])


def _print_part_baselines(now: datetime, out) -> int:
    """One line per exact model we hold a maker row for: its baseline status now and when it goes stale."""
    from data.fit_checker import part_specs
    rows = baselines.part_observations()
    ok = 0
    for cat in part_specs.CATEGORIES:
        for r in part_specs.rows(cat):
            key = baselines.part_key(r["model_number"])
            b = baselines.baseline(key, now.isoformat(), rows=rows)
            when = stale_at(key, rows, now) if b["status"] == "ok" else None
            ok += b["status"] == "ok"
            out(f"  {cat} {r['model_number']}: status {b['status']}"
                + (f", median ${b['median']:.2f} from {b['n']} retail asks, eBay sold n={b['sold']['n']}, stale at {pacific(when)}" if when
                   else f" (no baseline: {_part_why(b)})" if b["status"] != "ok" else ""))
    out(f"part baselines ok now: {ok} model(s)")
    return 0


def parts_main(a, env, confirm, isatty, out, now) -> int:
    log_path = run_actors.HERE / "runs.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    plan = parts_refresh_plan(a.items, log)
    total = round(sum(r["worst_usd"] for r in plan), 4)
    out(f"parts refresh plan (MIRROR, {a.items} items per run): {len(plan)} runs, stores {', '.join(PARTS_STORES)}")
    for r in plan:
        out(f"  {r['part']} {r['store']}: {r['query']}  worst ${r['worst_usd']:.4f}")
    out(f"estimated Apify cost: ${total:.2f} worst case for {len(plan)} runs (highest logged cost per Actor), cap ${a.cap:.2f}")
    if a.dry_run:
        out("dry run: nothing was run and nothing was spent. Part baselines now:")
        return _print_part_baselines(now or datetime.now(timezone.utc), out)
    if total > a.cap or not 0 < a.cap <= run_actors.MAX_CAP:
        out(f"refused: the estimate ${total:.2f} is over the cap ${a.cap:.2f} (at most ${run_actors.MAX_CAP:.0f}); nothing was run")
        return 2
    if not _have_token(env):
        out("refused: APIFY_TOKEN is not set (export it or put it in the gitignored .env); nothing was run")
        return 2
    if not isatty() or confirm(f"This spends up to ${a.cap:.2f} of Apify credits. Type SPEND to run: ").strip() != "SPEND":
        out("refused: spend not confirmed; nothing was run")
        return 2
    records = run_actors.run_parts(plan, a.cap, None, a.items)
    old = json.loads(log_path.read_text()) if log_path.exists() else []
    log_path.write_text(json.dumps(old + records, indent=1))
    spent = sum(r["cost_usd"] for r in records if isinstance(r.get("cost_usd"), (int, float)))
    out(f"logged Apify cost this parts refresh: ${spent:.4f} of the ${a.cap:.2f} cap")
    return _print_part_baselines(now or datetime.now(timezone.utc), out)


def main(argv=None, env=None, runner=None, confirm=input, isatty=None, out=print, now=None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m data.baselines.refresh", description="Re-scrape the dated price baseline (costs Apify credits).")
    p.add_argument("--dry-run", action="store_true", help="show the plan and estimated cost; run nothing")
    p.add_argument("--yes-spend", action="store_true", help="confirm the Apify spend without the typed prompt")
    p.add_argument("--max-items", type=int, default=HARD_MAX_ITEMS, choices=range(1, HARD_MAX_ITEMS + 1), metavar=f"1..{HARD_MAX_ITEMS}")
    p.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="refuse if the estimated cost is over this")
    p.add_argument("--sku", default=SKU)
    p.add_argument("--parts", action="store_true", help="refresh the Build Story part baselines instead (#342)")
    p.add_argument("--cap", type=float, default=PARTS_DEFAULT_CAP, help="--parts only: dollars, default 2")
    p.add_argument("--items", type=int, default=5, choices=range(1, HARD_MAX_ITEMS + 1), metavar=f"1..{HARD_MAX_ITEMS}",
                   help="--parts only: items per search (default 5)")
    a = p.parse_args(argv)
    env = os.environ if env is None else env
    runner = runner or run_actors.run
    isatty = isatty or sys.stdin.isatty
    if a.parts:
        return parts_main(a, env, confirm, isatty, out, now)

    log_path = run_actors.HERE / "runs.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    plan = estimate(DEFAULT_PLAN, log)
    total = round(sum(x["est_usd"] for x in plan), 4)
    per_run_cap = round(a.max_usd / len(plan), 2)
    out(f"refresh plan (MIRROR, max {a.max_items} items per run, Apify maxTotalChargeUsd ${per_run_cap:.2f} per run):")
    for x in plan:
        out(f"  {x['store']}{' (second family, snapshots_b)' if x['second'] else ''}: {x['actor']}  est ${x['est_usd']:.3f}")
    out(f"estimated Apify cost: ${total:.2f} for {len(plan)} runs (highest logged cost per Actor, at least ${FLOOR_USD:.2f} each)")
    out(f"APIFY_TOKEN: {'set' if _have_token(env) else 'missing'}")
    if total > a.max_usd:
        out(f"refused: the estimate ${total:.2f} is over the --max-usd cap ${a.max_usd:.2f}")
        return 2
    if a.dry_run:
        out("dry run: nothing was run and nothing was spent. Current baseline:")
        _print_baseline(a.sku, now or datetime.now(timezone.utc), out)
        return 0
    if not _have_token(env):
        out("refused: APIFY_TOKEN is not set (export it or put it in the gitignored .env); nothing was run")
        return 2
    if not a.yes_spend:
        if not isatty():
            out("refused: this spends Apify credits; pass --yes-spend (or run in a terminal and type SPEND)")
            return 2
        if confirm(f"This spends about ${total:.2f} of Apify credits. Type SPEND to run: ").strip() != "SPEND":
            out("refused: spend not confirmed; nothing was run")
            return 2

    for d in ("raw", "snapshots", "snapshots_b"):  # output dirs before any paid call (AGENTS.md gotcha)
        (run_actors.HERE / d).mkdir(exist_ok=True)
    with ThreadPoolExecutor(4) as pool:  # free plan: max 5 concurrent runs
        results = list(pool.map(lambda x: runner(x["store"], x["second"], max_items=a.max_items, max_usd=per_run_cap), plan))
    old = json.loads(log_path.read_text()) if log_path.exists() else []
    log_path.write_text(json.dumps(old + results, indent=1))
    for r in results:
        out(f"  run: {run_actors.describe(r)} snapshot {r.get('snapshot_id')}")
    spent = sum(r.get("cost_usd") or 0 for r in results)
    out(f"logged Apify cost this refresh: ${spent:.2f}")
    feed = baselines.write_feed()
    out(f"feed.json regenerated: {len(feed['rows'])} rows, {feed['from']} to {feed['to']}")
    return _print_baseline(a.sku, now or datetime.now(timezone.utc), out)


if __name__ == "__main__":
    sys.exit(main())
