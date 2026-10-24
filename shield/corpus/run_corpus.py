"""Run the attack corpus through Shield. `python3 -m shield.corpus.run_corpus --write` rewrites RESULTS.md.

"Block rate" here means the share of attack cases that were stopped (verdict quarantine or block). The
classifier is always off: results are deterministic and need no network.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date

from shield.core import screen

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.join(HERE, "dev.jsonl")
PROBE = os.path.join(HERE, "evasion_probe.jsonl")
RESULTS = os.path.join(HERE, "RESULTS.md")


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run(path: str) -> dict:
    rows = load(path)
    lat, missed, wrong_rule, fp_ids, per_rule = [], [], [], [], {}
    blocked = quarantined = attacks = controls = 0
    for r in rows:
        out = screen(r["message"], r.get("context"), classifier=None)
        lat.append(out["latency_ms"])
        if r["label"] == "attack":
            attacks += 1
            if out["verdict"] == "allow":
                missed.append(r["id"])
                continue
            blocked += out["verdict"] == "block"
            quarantined += out["verdict"] == "quarantine"
            for rid in out["rule_ids"]:
                per_rule[rid] = per_rule.get(rid, 0) + 1
            if r.get("expect_rule") and r["expect_rule"] not in out["rule_ids"]:
                wrong_rule.append(r["id"])
        else:
            controls += 1
            if out["verdict"] != "allow":
                fp_ids.append(r["id"])
    lat.sort()
    p95 = lat[max(0, math.ceil(0.95 * len(lat)) - 1)] if lat else 0.0
    stopped = blocked + quarantined
    return {
        "attacks": attacks, "controls": controls, "blocked": blocked, "quarantined": quarantined,
        "stopped": stopped, "block_rate": stopped / attacks if attacks else 0.0,
        "false_positives": len(fp_ids), "false_positive_rate": len(fp_ids) / controls if controls else 0.0,
        "false_positive_ids": fp_ids, "missed": missed, "wrong_rule": wrong_rule,
        "p95_ms": round(p95, 2), "per_rule": dict(sorted(per_rule.items())),
    }


def render_results(dev: dict, probe: dict, today: str) -> str:
    rules = "\n".join(f"| `{k}` | {v} |" for k, v in dev["per_rule"].items())
    return f"""# Shield corpus results

Run date: {today}. Command: `python3 -m shield.corpus.run_corpus --write`. Classifier off, no network, rules only.

## Dev corpus (`dev.jsonl`: 30 attacks, 10 clean controls)

| Metric | Value |
|---|---|
| Attacks stopped (quarantine or block) | {dev["stopped"]} of {dev["attacks"]} ({dev["block_rate"]:.1%}) |
| of which block | {dev["blocked"]} |
| of which quarantine | {dev["quarantined"]} |
| Clean controls wrongly stopped | {dev["false_positives"]} of {dev["controls"]} ({dev["false_positive_rate"]:.1%}) |
| p95 latency per message | {dev["p95_ms"]} ms |

Read this honestly: the dev corpus was written by the same author as the rules, so it is in-sample.
100% here shows the rules do what they were written to do, not that Shield is secure. The held-out set (Anoop, c8) and the
adaptive set (Claude-generated after the rules freeze) are the numbers to quote to Armadin. Never say "secure".

Rule hits across the {dev["attacks"]} attacks (a case can fire several rules):

| Rule | Cases |
|---|---|
{rules}

Cases from outside our lane: a01 (injected listing page) and c09, c10 (honest pages) are Anoop's pages from
`data/liar_pages` (Lane C c4), copied unchanged into the corpus.

## Evasion probe (`evasion_probe.jsonl`, 10 paraphrases written after the rules, NOT tuned)

Stopped {probe["stopped"]} of {probe["attacks"]}. Missed: {", ".join(probe["missed"]) or "none"}.

These are the known gaps of a deterministic rule layer: paraphrase with no trigger words, other languages,
spaced or leetspeak letters, payees given as a bank account or a name, shortened links, and instructions split
across messages. They are what the optional Claude classifier (quarantine only) and the held-out and adaptive
sets are for. They are reported, not hidden, and not asserted by a test.
"""


def main(argv: list[str]) -> int:
    dev, probe = run(DEV), run(PROBE)
    print(f"dev: stopped {dev['stopped']}/{dev['attacks']} (block {dev['blocked']}, quarantine {dev['quarantined']}), "
          f"block rate {dev['block_rate']:.1%}, false positives {dev['false_positives']}/{dev['controls']}, "
          f"p95 {dev['p95_ms']} ms")
    print(f"evasion probe: stopped {probe['stopped']}/{probe['attacks']}")
    if "--write" in argv:
        with open(RESULTS, "w", encoding="utf-8") as f:
            f.write(render_results(dev, probe, date.today().isoformat()))
        print(f"wrote {RESULTS}")
    return 0 if not (dev["missed"] or dev["wrong_rule"] or dev["false_positive_ids"]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
