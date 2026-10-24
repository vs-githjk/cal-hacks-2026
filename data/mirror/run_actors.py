"""Run each c1 actor once with a small input; save raw items, SpecCards and cost per run.
python -m data.mirror.run_actors [store ...]
python -m data.mirror.run_actors --second [store ...]   (second-source Actor family, #47: snapshots_b/, provider apify-b)
python -m data.mirror.run_actors --renormalize   (rebuild snapshots from the logged runs; no new runs, no cost)   (reads APIFY_TOKEN from env or .env; never prints it)"""
import json
import os
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


def describe(r):
    """One CLI line per record: the skip or error reason when there is one, else the status."""
    return f"{r['store']} {r.get('error') or r['status']} {r.get('items')} {r.get('cost_usd')} {r.get('fields')}"


if __name__ == "__main__":
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
