"""How much do loss reports leak, and can sellers collude on them? (issue #142). SIM, first run is BLIND.

    python3 -m sim.leak --seeds 3        # prints the table, writes sim/RESULTS_leak.md

A standalone model, not the full market: fixed control sellers at prices around the real band, the clearing price is the lowest
bid, and a loss report gives the gap band of (my_bid - clearing) / clearing. The band names and steps are demo.learning's
(imported, not edited). Mitigations are parameters that live here only: a coarser band set, and a report only every 3rd round.
Do not tune a mitigation and re-quote it as blind: any later run goes in a separate "not blind" section.
"""
from __future__ import annotations

import argparse
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from demo.learning import STEP_BY_BAND, gap_band

CONTROLS = {"Bargain Bin": 1199.0, "Median Market": 1248.50, "Fair Price": 1289.0}
PROBE_START = 1349.0
LEARNER_STARTS = (1349.0, 1339.0)
TOL = 0.02
CAP = 40
ROUNDS = 20
# band sets: (name, bottom %, top %) ; the default is demo.learning.gap_band's
DEFAULT_BANDS = (("within5", 0.0, 5.0), ("within10", 5.0, 10.0), ("within20", 10.0, 20.0), ("over20", 20.0, float("inf")))
COARSE_BANDS = (("within10", 0.0, 10.0), ("over10", 10.0, float("inf")))
COARSE_STEP = {"within10": STEP_BY_BAND["within10"], "over10": STEP_BY_BAND["over20"]}
CONFIGS = {  # name -> (bands, report_every)
    "default (4 bands, every round)": (DEFAULT_BANDS, 1),
    "coarse (2 bands, every round)": (COARSE_BANDS, 1),
    "default bands, report every 3rd round": (DEFAULT_BANDS, 3),
    "coarse bands and every 3rd round": (COARSE_BANDS, 3),
}


def market(seed: int) -> dict[str, float]:
    rng = random.Random(seed)
    return {k: round(v * (1 + rng.uniform(-0.01, 0.01)), 2) for k, v in CONTROLS.items()}


def band_of(bid: float, clearing: float, bands) -> tuple[str, float, float]:
    pct = (bid - clearing) / clearing * 100
    if bands is DEFAULT_BANDS:
        name = gap_band(pct)  # the demo's own function for the default set
        return next(b for b in bands if b[0] == name)
    return next(b for b in bands if pct <= b[2])


def probe(seed: int, bands, every: int) -> dict:
    """A seller that binary-searches the price to beat from its own reports. Rounds until its bid is within 2 percent."""
    rival = min(market(seed).values())
    lo, hi, bid = 0.0, float("inf"), PROBE_START
    for rnd in range(1, CAP + 1):
        if abs(bid - rival) / rival <= TOL:
            return {"rounds": rnd, "bid": round(bid, 2), "rival": rival, "reached": True}
        if rnd % every == 0:  # a report arrives: a win, or the band of the loss
            if bid < rival:
                lo = max(lo, bid)
            else:
                _, bottom, top = band_of(bid, rival, bands)
                hi = min(hi, bid / (1 + bottom / 100))
                lo = max(lo, bid / (1 + top / 100) if top != float("inf") else 0.0)
            bid = (lo + hi) / 2 if hi != float("inf") else bid * 0.9
    return {"rounds": None, "bid": round(bid, 2), "rival": rival, "reached": False}


def collude(seed: int, bands, every: int, with_controls: bool) -> dict:
    """Two learners with the same rule: a loss sets the price step from the band, a win raises the price 1 percent."""
    steps = STEP_BY_BAND if bands is DEFAULT_BANDS else COARSE_STEP
    ctrl = list(market(seed).values()) if with_controls else []
    price = list(LEARNER_STARTS)
    clearing_by_round = []
    for rnd in range(1, ROUNDS + 1):
        bids = price[:]
        clearing = min(bids + ctrl)
        clearing_by_round.append(clearing)
        winner = bids.index(min(bids)) if min(bids) < min(ctrl, default=float("inf")) else None
        if rnd % every:
            continue
        for i in range(2):
            if i == winner:
                price[i] = bids[i] * 1.01
            else:
                name = band_of(bids[i], clearing, bands)[0]
                price[i] = LEARNER_STARTS[i] * (1 - steps[name])
    at = lambda n: round(clearing_by_round[n - 1], 2)
    return {"r1": at(1), "r10": at(10), "r20": at(20), "rose": at(ROUNDS) > at(1) + 0.005,
            "cheapest_control": min(ctrl) if ctrl else None}


def run(seeds: int = 3) -> dict:
    out = {"probe": {}, "collusion": {}}
    for name, (bands, every) in CONFIGS.items():
        out["probe"][name] = [probe(s, bands, every) for s in range(seeds)]
        out["collusion"][name] = {mk: [collude(s, bands, every, mk == "with controls") for s in range(seeds)]
                                  for mk in ("with controls", "learners only")}
    return out


def markdown(res: dict, seeds: int, sha: str, when: str) -> str:
    lines = [f"# Loss-report leak (SIM), BLIND first run", "",
             f"Run {when} at git {sha}: `python3 -m sim.leak --seeds {seeds}`. Standalone model, not the full market: controls at "
             f"{', '.join(f'{k} ${v:,.2f}' for k, v in CONTROLS.items())} with a seeded +-1% jitter; clearing price is the lowest bid; "
             "a loss report gives the gap band. Band names and steps are demo.learning's; mitigations are parameters in sim only. "
             "Nothing was tuned after seeing these numbers; any rerun goes in a separate not-blind section below.", "",
             "## Probe: rounds for a seller varying its bid to land within 2 percent of the price to beat",
             f"Start ${PROBE_START:,.0f}, cap {CAP} rounds ('not reached' if capped).", "",
             "| reports | " + " | ".join(f"seed {s}" for s in range(seeds)) + " |", "|---|" + "---|" * seeds]
    for name, rs in res["probe"].items():
        lines.append(f"| {name} | " + " | ".join(str(r["rounds"]) if r["reached"] else "not reached" for r in rs) + " |")
    lines += ["", "## Collusion: two learners with the same rule, 20 rounds",
              f"Starts ${LEARNER_STARTS[0]:,.0f} and ${LEARNER_STARTS[1]:,.0f}. A loss sets the price to start x (1 - step for its band); a win raises 1% next round. "
              "Clearing price at rounds 1, 10, 20 per seed; 'rose' = round 20 above round 1.", "",
              "| reports | market | " + " | ".join(f"seed {s} (r1 / r10 / r20, rose)" for s in range(seeds)) + " |", "|---|---|" + "---|" * seeds]
    for name, per in res["collusion"].items():
        for mk, rs in per.items():
            lines.append(f"| {name} | {mk} | " + " | ".join(f"{r['r1']:,.2f} / {r['r10']:,.2f} / {r['r20']:,.2f}, {'yes' if r['rose'] else 'no'}" for r in rs) + " |")
    lines += ["", "With the controls present the clearing price can never exceed the cheapest control (the lowest bid sets it), so a rise there would need the controls to leave.",
              "", "Caveats: a model with fixed controls and one probe, 3 seeds; it says what the reports leak in this setup, not what a real market would do."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    n = ap.parse_args().seeds
    res = run(n)
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        sha = "unknown"
    text = markdown(res, n, sha, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    (Path(__file__).resolve().parent / "RESULTS_leak.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
