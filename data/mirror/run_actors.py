"""Run each c1 actor once with a small input; save raw items, SpecCards and cost per run.
python -m data.mirror.run_actors [store ...]
python -m data.mirror.run_actors --second [store ...]   (second-source Actor family, #47: snapshots_b/, provider apify-b)
python -m data.mirror.run_actors --parts [part ...] [--cap USD] [--items N] [--dry-run] [--approved-by TEXT]
    real listings for the Build Story parts (cpu, motherboard, memory, storage, cooler; #342), saved to parts_snapshots/.
    --dry-run prints the plan and the estimate and spends nothing. A real run needs the human to type SPEND (no flag skips it);
    --cap is in dollars (default 5, at most 10) and a run is not started if its worst case would pass it.
python -m data.mirror.run_actors --renormalize   (rebuild snapshots from the logged runs; no new runs, no cost)   (reads APIFY_TOKEN from env or .env; never prints it)"""
import argparse
import json
import os
import re
import threading
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

from .actors import ACTORS, SECOND_SOURCE
from .normalize import FIELDS, first, strip_private, to_spec_card

HERE = Path(__file__).resolve().parent
API = "https://api.apify.com/v2"


def token():
    if os.environ.get("APIFY_TOKEN"):
        return os.environ["APIFY_TOKEN"]
    for line in (HERE.parents[1] / ".env").read_text().splitlines():
        if line.startswith("APIFY_TOKEN="):
            return line.split("=", 1)[1].strip()
    sys.exit("APIFY_TOKEN missing")


def call(method, path, body=None, timeout=330):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read())


def run(store, second=False, max_items=10, max_usd=None):
    """Never raises: every outcome, including a paid run that broke later, comes back as a log record.
    max_items caps the items Apify may return and the items we read; max_usd (if given) is sent as Apify's maxTotalChargeUsd,
    which binds pay-per-event Actors (others are bounded by max_items and the 420 s abort)."""
    if store not in (SECOND_SOURCE if second else ACTORS):
        return {"store": store, "status": "SKIPPED", "error": f"no {'second-family ' if second else ''}actor for {store}"}
    actor, inp = (SECOND_SOURCE if second else ACTORS)[store]
    snaps, raw = ("snapshots_b", f"{store}-b") if second else ("snapshots", store)
    started = time.time()
    rec = {"store": store, "actor": actor, "input": inp, **({"family": "b"} if second else {})}
    try:
        r = call("POST", f"/acts/{actor.replace('/', '~')}/runs?waitForFinish=300&maxItems={int(max_items)}"
                 + (f"&maxTotalChargeUsd={max_usd:.2f}" if max_usd else ""), inp)["data"]
        rec.update(run_id=r["id"], status=r["status"], cost_usd=r.get("usageTotalUsd"))
        while r["status"] in ("READY", "RUNNING") and time.time() - started < 420:
            time.sleep(10)
            r = call("GET", f"/actor-runs/{r['id']}")["data"]
        if r["status"] in ("READY", "RUNNING"):
            call("POST", f"/actor-runs/{r['id']}/abort")
        rec.update(status=r["status"], cost_usd=r.get("usageTotalUsd"))
        items = call("GET", f"/datasets/{r['defaultDatasetId']}/items?clean=1&limit={int(max_items)}")
        now = datetime.now(timezone.utc)
        snap = f"{store}-{now:%Y%m%dT%H%MZ}"
        (HERE / "raw" / f"{raw}.json").write_text(json.dumps([strip_private(store, it) for it in items[:3]], indent=1))
        cards = [to_spec_card(store, it, snap, now.isoformat(timespec="seconds")) for it in items]
        (HERE / snaps / f"{snap}.json").write_text(json.dumps(cards, indent=1))
        rec.update(items=len(items), snapshot_id=snap,
                   fields=sorted(k for k in FIELDS if any(first(it, FIELDS[k]) not in (None, "") for it in items)))
    except Exception as e:  # a broken low-user actor is skipped, not retried; its cost stays in the log
        rec["status"] = f"ERROR {type(e).__name__}: {str(e)[:120]}"
    rec["secs"] = round(time.time() - started)
    return rec


def renormalize():
    """Re-read each store's latest real run (one with a run_id). A SKIPPED or ERROR record never replaces a real run,
    and every record stays in the log."""
    log = HERE / "runs.json"
    records = json.loads(log.read_text())
    latest = {r["store"]: r for r in records if not r.get("family") and r.get("run_id")}
    for r in latest.values():
        run = call("GET", f"/actor-runs/{r['run_id']}")["data"]
        items = call("GET", f"/datasets/{run['defaultDatasetId']}/items?clean=1&limit=10")
        cards = [to_spec_card(r["store"], it, r["snapshot_id"], run["finishedAt"]) for it in items]
        if cards:
            (HERE / "snapshots" / f"{r['snapshot_id']}.json").write_text(json.dumps(cards, indent=1))
        r.update(cost_usd=round(run.get("usageTotalUsd") or 0, 5), items=len(items), finished_at=run["finishedAt"],
                 fields=sorted(k for k in FIELDS if any(first(it, FIELDS[k]) not in (None, "") for it in items)))
    log.write_text(json.dumps(records, indent=1))
    return list(latest.values())


# ---- Build Story parts (#342) -------------------------------------------------------------------------------------------
DEFAULT_CAP, MAX_CAP = 5.0, 10.0
FLOOR_USD = 0.01      # a logged cost below this (repeat runs log near $0) is estimated at this
UNLOGGED_USD = 0.10   # an Actor with no logged run is estimated at this
CENTRAL_PAGE_USD = 0.20   # Central Computers crawl per category page: no past cost on record, so the high end of $0.25 to $1.00 over 5 pages


def worst_cost(actor, log):
    """The highest logged cost of this Actor, at least FLOOR_USD; UNLOGGED_USD when it has no logged run."""
    costs = [r["cost_usd"] for r in log if r.get("actor") == actor and isinstance(r.get("cost_usd"), (int, float))]
    return max(max(costs), FLOOR_USD) if costs else UNLOGGED_USD


def parts_plan(items=5, parts=None, log=None, stores=None):
    """[{..planned run.., worst_usd}]: every run a parts capture would make, with its worst-case cost."""
    from . import parts as P
    log = log if log is not None else (json.loads((HERE / "runs.json").read_text()) if (HERE / "runs.json").exists() else [])
    plan = [{**r, "worst_usd": round(worst_cost(r["actor"], log), 5)} for r in P.planned_runs(items, parts) if not stores or r["store"] in stores]
    for part, url in P.CENTRAL_PAGES.items():
        if (not parts or part in parts) and (not stores or P.CENTRAL in stores):
            plan.append({"part": part, "query": url, "slug": "category-page", "store": P.CENTRAL, "second": False,
                         "actor": P.CENTRAL_ACTOR, "worst_usd": CENTRAL_PAGE_USD,
                         "input": {"startUrls": [{"url": url}], "maxCrawlDepth": 0, "maxCrawlPages": 1, "crawlerType": "cheerio",
                                   "saveMarkdown": True}})
    return plan


def run_one_part(r, api=None, items=5, now=None):
    """One planned run -> a log record. Never raises. Writes parts_snapshots/<key>-<stamp>.json (cards) and raw/ (items)."""
    from . import parts as P
    api = api or call
    started = time.time()
    rec = {k: r[k] for k in ("part", "query", "store", "actor", "input")} | ({"family": "b"} if r["second"] else {})
    try:
        d = api("POST", f"/acts/{r['actor'].replace('/', '~')}/runs?waitForFinish=300&maxItems={items}", r["input"])["data"]
        rec.update(run_id=d["id"], status=d["status"], cost_usd=d.get("usageTotalUsd"))
        while d["status"] in ("READY", "RUNNING") and time.time() - started < 420:
            time.sleep(10)
            d = api("GET", f"/actor-runs/{d['id']}")["data"]
        if d["status"] in ("READY", "RUNNING"):
            api("POST", f"/actor-runs/{d['id']}/abort")
        rec.update(status=d["status"], cost_usd=d.get("usageTotalUsd"))
        got = api("GET", f"/datasets/{d['defaultDatasetId']}/items?clean=1&limit={items if r['store'] != P.CENTRAL else 40}")
        now = now or datetime.now(timezone.utc)
        key = P.snapshot_key(r["store"], r["second"], r["part"], r["slug"])
        snap, stamp = f"{key}-{now:%Y%m%dT%H%MZ}", now.isoformat(timespec="seconds")
        P.SNAPSHOTS.mkdir(exist_ok=True)
        P.RAW.mkdir(exist_ok=True)
        (P.RAW / f"{snap}.json").write_text(json.dumps([P.raw_item(strip_private(r["store"], it)) for it in got], indent=1))
        if r["store"] == P.CENTRAL:
            cards = P.central_cards(r["part"], got, snap, stamp)
        else:
            cards = [to_spec_card(r["store"], it, snap, stamp, part=r["part"]) for it in got]
        (P.SNAPSHOTS / f"{snap}.json").write_text(json.dumps(cards, indent=1))
        rec.update(items=len(got), snapshot_id=snap, cards=len(cards), maker_models=sum(1 for c in cards if c.get("maker_model")))
    except Exception as e:  # a broken Actor is logged with its cost, not retried
        rec["status"] = f"ERROR {type(e).__name__}: {str(e)[:120]}"
    rec["secs"] = round(time.time() - started)
    return rec


def run_parts(plan, cap, api=None, items=5, workers=4):
    """Run the plan under the dollar cap. Before each run its worst case is reserved; a run that would pass the cap is
    skipped (never started). Returns the log records, in plan order, skipped ones included."""
    lock, state = threading.Lock(), {"spent": 0.0, "reserved": 0.0}
    cap = min(float(cap), MAX_CAP)

    def one(r):
        with lock:
            if state["spent"] + state["reserved"] + r["worst_usd"] > cap + 1e-9:
                return {"part": r["part"], "query": r["query"], "store": r["store"], "actor": r["actor"], "status": "SKIPPED",
                        "error": f"cap ${cap:.2f} would be passed (spent ${state['spent']:.4f}, in flight ${state['reserved']:.4f}, "
                                 f"worst case ${r['worst_usd']:.4f})"}
            state["reserved"] += r["worst_usd"]
        rec = run_one_part(r, api, items)
        with lock:
            state["reserved"] -= r["worst_usd"]
            state["spent"] += rec["cost_usd"] if isinstance(rec.get("cost_usd"), (int, float)) else r["worst_usd"]  # unknown cost: assume the worst
        return rec

    with ThreadPoolExecutor(workers) as pool:
        out = list(pool.map(one, plan))
    return out


def parts_main(argv, api=None, ask=input, out=print, log_path=None, workers=None):
    ap = argparse.ArgumentParser(prog="python -m data.mirror.run_actors --parts", add_help=True)
    ap.add_argument("--parts", nargs="*", default=[], choices=["cpu", "motherboard", "memory", "storage", "cooler"])
    ap.add_argument("--cap", type=float, default=DEFAULT_CAP, help="dollars, default 5, at most 10")
    ap.add_argument("--stores", nargs="*", default=[], help="only these stores, e.g. centralcomputers (default: all)")
    ap.add_argument("--workers", type=int, default=4, help="runs at once (default 4; Central Computers needs 1 on the free plan)")
    ap.add_argument("--items", type=int, default=5, help="items per search (default 5)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the estimate; spend nothing")
    ap.add_argument("--approved-by", default="", help="who approved the spend, written into every log record")
    a = ap.parse_args(argv)
    if not 0 < a.cap <= MAX_CAP:
        out(f"refused: --cap must be above 0 and at most ${MAX_CAP:.0f}")
        return 2
    if not 1 <= a.items <= 10:
        out("refused: --items must be 1 to 10")
        return 2
    plan = parts_plan(a.items, a.parts or None, stores=a.stores or None)
    total = sum(r["worst_usd"] for r in plan)
    out(f"parts capture (MIRROR): {len(plan)} runs, {a.items} items each, {len({(r['part'], r['query']) for r in plan})} searches")
    for r in plan:
        out(f"  {r['part']:<11} {r['store']:<16}{'(b) ' if r['second'] else '    '}{r['query'][:48]:<50} worst ${r['worst_usd']:.4f}")
    out(f"estimated Apify cost: ${total:.2f} worst case for {len(plan)} runs (highest logged cost per Actor), cap ${a.cap:.2f}")
    if a.dry_run:
        out("dry run: nothing was run and nothing was spent")
        return 0
    if total > a.cap:
        out(f"refused: the estimate ${total:.2f} is over the cap ${a.cap:.2f}; lower --items or the parts, or raise --cap")
        return 2
    if ask(f"This spends real money, up to ${a.cap:.2f}, from the Apify account behind APIFY_TOKEN. Type SPEND to go on: ").strip() != "SPEND":
        out("not confirmed: nothing was run and nothing was spent")
        return 2
    records = run_parts(plan, a.cap, api, a.items, workers or a.workers)
    approval = a.approved_by or "typed SPEND at the prompt"
    for rec in records:
        rec["approval"] = f"{approval}; cap ${a.cap:.2f}"
    log = Path(log_path) if log_path else HERE / "runs.json"
    old = json.loads(log.read_text()) if log.exists() else []
    log.write_text(json.dumps(old + records, indent=1))
    spent = sum(r["cost_usd"] for r in records if isinstance(r.get("cost_usd"), (int, float)))
    for rec in records:
        out(f"{rec['part']} {rec['store']} {rec.get('error') or rec['status']} items={rec.get('items')} cost={rec.get('cost_usd')}")
    out(f"spent ${spent:.4f} of the ${a.cap:.2f} cap; {sum(1 for r in records if r['status'] == 'SKIPPED')} run(s) skipped by the cap")
    return 0


def describe(r):
    """One CLI line per record: the skip or error reason when there is one, else the status."""
    return f"{r['store']} {r.get('error') or r['status']} {r.get('items')} {r.get('cost_usd')} {r.get('fields')}"


if __name__ == "__main__":
    if "--parts" in sys.argv:
        sys.exit(parts_main([a for a in sys.argv[1:]]))
    if sys.argv[1:] == ["--renormalize"]:
        for r in renormalize():
            print(r["store"], r.get("items"), r.get("cost_usd"), r.get("fields"))
        sys.exit()
    second = "--second" in sys.argv
    stores = [a for a in sys.argv[1:] if a != "--second"] or list(SECOND_SOURCE if second else ACTORS)
    for d in ("raw", "snapshots", "snapshots_b"):
        (HERE / d).mkdir(exist_ok=True)
    with ThreadPoolExecutor(4) as pool:  # free plan: max 5 concurrent runs
        results = list(pool.map(lambda s: run(s, second), stores))
    log = HERE / "runs.json"
    old = json.loads(log.read_text()) if log.exists() else []
    log.write_text(json.dumps(old + results, indent=1))
    for r in results:
        print(describe(r))
