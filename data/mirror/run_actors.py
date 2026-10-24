"""Run each c1 actor once with a small input; save raw items, SpecCards and cost per run.
python -m data.mirror.run_actors [store ...]   (reads APIFY_TOKEN from env or .env; never prints it)"""
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .actors import ACTORS
from .normalize import FIELDS, first, to_spec_card

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
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run(store):
    actor, inp = ACTORS[store]
    started = time.time()
    try:
        r = call("POST", f"/acts/{actor.replace('/', '~')}/runs?waitForFinish=300&maxItems=10", inp)["data"]
        while r["status"] in ("READY", "RUNNING") and time.time() - started < 420:
            time.sleep(10)
            r = call("GET", f"/actor-runs/{r['id']}")["data"]
        items = call("GET", f"/datasets/{r['defaultDatasetId']}/items?clean=1&limit=10")
        if r["status"] in ("READY", "RUNNING"):
            call("POST", f"/actor-runs/{r['id']}/abort")
    except Exception as e:  # a broken low-user actor is skipped, not retried
        return {"store": store, "actor": actor, "status": f"ERROR {type(e).__name__}: {str(e)[:120]}"}
    now = datetime.now(timezone.utc)
    snap = f"{store}-{now:%Y%m%dT%H%MZ}"
    (HERE / "raw" / f"{store}.json").write_text(json.dumps(items[:3], indent=1))
    cards = [to_spec_card(store, it, snap, now.isoformat(timespec="seconds")) for it in items]
    (HERE / "snapshots" / f"{snap}.json").write_text(json.dumps(cards, indent=1))
    present = sorted(k for k in FIELDS if items and any(first(it, FIELDS[k]) not in (None, "") for it in items))
    return {"store": store, "actor": actor, "run_id": r["id"], "status": r["status"], "items": len(items),
            "cost_usd": r.get("usageTotalUsd"), "secs": round(time.time() - started), "fields": present,
            "snapshot_id": snap, "input": inp}


if __name__ == "__main__":
    stores = sys.argv[1:] or list(ACTORS)
    with ThreadPoolExecutor(4) as pool:  # free plan: max 5 concurrent runs
        results = list(pool.map(run, stores))
    log = HERE / "runs.json"
    old = json.loads(log.read_text()) if log.exists() else []
    log.write_text(json.dumps(old + results, indent=1))
    for r in results:
        print(r["store"], r["status"], r.get("items"), r.get("cost_usd"), r.get("fields"))
