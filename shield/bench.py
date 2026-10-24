"""shield-bench (Lane C, c9): block rate, false-block rate and p95 latency, one column per attack set, never pooled.

    python3 -m shield.bench                                   # local rules (shield.core.screen, no classifier)
    python3 -m shield.bench --url http://127.0.0.1:8788 --key sk_shield_...   # through the keyed API
    python3 -m shield.bench --extra path/to/their_attacks.jsonl              # credit a third party's attacks

Columns: dev (what the rules were written against), held_out (Lane C c8, written before the rules froze; never tune
on it), adaptive (Claude-generated after the freeze; "not run yet" until the file exists), plus any --extra file.
Rows use the corpus shape: {id, label: attack|clean, message, context}. An attack counts as stopped on any verdict
other than allow; a clean row counts as a false block on anything other than allow.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERROR = "error"
SETS = {"dev": ROOT / "shield" / "corpus" / "dev.jsonl", "held_out": ROOT / "sim" / "attacks" / "held_out.jsonl",
        "adaptive": ROOT / "sim" / "attacks" / "adaptive.jsonl"}


def _local(message, context):
    from shield.core import screen
    return screen(message, context, classifier=None)["verdict"]


def bench(sets: dict, screen_fn=_local) -> dict:
    out = {}
    for name, path in sets.items():
        path = Path(path)
        if not path.exists():
            out[name] = {"status": "not run yet"}
            continue
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        lat, missed, false_blocks, errors = [], [], [], []
        for r in rows:
            t = time.perf_counter()
            verdict = screen_fn(r["message"], r.get("context"))
            lat.append((time.perf_counter() - t) * 1000)
            if verdict == ERROR:  # 401, 429, timeout: not a Shield verdict, so it never counts as a block
                errors.append(r["id"])
                continue
            if r["label"] == "attack" and verdict == "allow":
                missed.append(r["id"])
            if r["label"] != "attack" and verdict != "allow":
                false_blocks.append(r["id"])
        scored = [r for r in rows if r["id"] not in errors]
        atk = sum(r["label"] == "attack" for r in scored)
        clean = len(scored) - atk
        lat.sort()
        out[name] = {"attacks": atk, "clean": clean, "block_rate": round((atk - len(missed)) / atk, 4) if atk else None,
                     "false_block_rate": round(len(false_blocks) / clean, 4) if clean else None,
                     "p95_ms": round(lat[max(0, math.ceil(0.95 * len(lat)) - 1)], 2) if lat else None,
                     "missed": missed, "false_blocks": false_blocks, "errors": errors}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--key")
    ap.add_argument("--extra", action="append", default=[])
    a = ap.parse_args()
    sets = dict(SETS, **{Path(p).stem: p for p in a.extra})
    fn = _local
    if a.url:
        from shield.client import ShieldClient
        client = ShieldClient(a.url, a.key)
        fn = lambda m, c: (lambda r: ERROR if "error" in r else r["verdict"])(client.screen(m, c))
    res = bench(sets, fn)
    print(f"{'set':<12}{'attacks':>8}{'block rate':>12}{'clean':>7}{'false blocks':>14}{'p95 ms':>9}{'errors':>8}")
    for name, r in res.items():
        if "status" in r:
            print(f"{name:<12}{r['status']:>8}")
            continue
        br = "-" if r["block_rate"] is None else f"{r['block_rate']:.0%}"
        fb = "-" if r["false_block_rate"] is None else f"{r['false_block_rate']:.0%}"
        print(f"{name:<12}{r['attacks']:>8}{br:>12}{r['clean']:>7}{fb:>14}{r['p95_ms']:>9}{len(r['errors']):>8}")
    print("Quote held_out and adaptive, never a pooled number, and never 'secure'. Mode:", "API " + a.url if a.url else "local rules")


if __name__ == "__main__":
    main()
