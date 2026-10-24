"""Wind tunnel (Lane C, c7; issue #30). SIM: a simulator we built, not the market.

    python3 -m sim.wind_tunnel --builders 10 --seeds 3      # writes sim/RESULTS.md and sim/out/wind_tunnel-<date>.json

Learning arm (benign builders only): parametric buyers from real part data (maker-checked PSUs and cases in
data/fit_builds.json) run sealed rounds through demo.round.run_round (real Shield, claim check, fit checker and
advocate) against every demo seller. The learner (Gadget Grove) updates its price step from its own loss reports on
the TRAINING builders only; then its strategy is frozen and it meets the frozen control (Fair Price PC, sim/CONTROL.md)
on builders from HELD-OUT archetypes. Lift = learner win rate minus control win rate on those builders. An untrained
learner column shows how much of any lift is learning rather than the learner's extra open-box line.
Attack arm (no learning measured): every row of sim/attacks/held_out.jsonl and shield/corpus/dev.jsonl through
shield.core.screen, reported in separate columns. Shield is never tuned on held_out.jsonl.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

from demo.common import validate
from demo.learning import loss_reports, update_strategy
from demo.round import run_round
from demo.sellers import all_sellers
from shield.core import screen

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
LEARNER, CONTROL = "gadget-grove", "fair-price-pc"

# Real parts, values confirmed on maker pages (data/fit_builds.json, hand_checked builds).
CASES = {"north": {"max_gpu_length_mm": 355, "max_cooler_height_mm": 145}, "lancool216": {"max_gpu_length_mm": 392},
         "q300l": {"max_gpu_length_mm": 360}, "nr200p": {"max_gpu_length_mm": 330}}
PSUS = {"rm850x": {"wattage": 850, "form_factor": "ATX", "pcie_16pin": 1, "pcie_8pin": 3},
        "rm1000x": {"wattage": 1000, "form_factor": "ATX", "pcie_16pin": 1, "pcie_8pin": 4},
        "rm750e": {"wattage": 750, "form_factor": "ATX", "pcie_16pin": 1}}
ARCHETYPES = {  # cap range (USD), allowed conditions, case pool. Caps sit around the real Oct 24 ask band.
    "tight_budget": ((1180, 1260), ["new", "open-box"], ["q300l", "north"]),
    "comfort": ((1280, 1380), ["new"], ["north", "lancool216"]),
    "premium": ((1400, 1550), ["new"], ["lancool216"]),
    "new_only_mid": ((1250, 1350), ["new"], ["north", "q300l"]),
    "open_box_ok": ((1200, 1320), ["new", "open-box"], ["north", "lancool216"]),
    "small_case": ((1250, 1400), ["new"], ["nr200p"]),
}
HELD_OUT = ("open_box_ok", "small_case")  # never seen in training
MIN_ROUNDS_TO_QUOTE = 20  # below this, the lift tile shows raw counts, not a number


def make_builders(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    names = list(ARCHETYPES)
    out = []
    for i in range(n):
        arch = names[i % len(names)]
        (lo, hi), conds, cases = ARCHETYPES[arch]
        case = rng.choice(cases)
        out.append({"id": f"b{seed}-{i:02d}", "archetype": arch, "cap": float(rng.randrange(lo, hi + 1, 5)),
                    "conditions": conds, "case_name": case, "case": CASES[case], "psu_name": (p := rng.choice(list(PSUS))),
                    "psu": PSUS[p]})
    return out


def _need(b: dict) -> dict:
    item = {"sku_spec": "rtx 5070 ti", "quantity": 1, "unit": "each", "condition": b["conditions"][0],
            "allowed_conditions": b["conditions"], "variant": "retail"}
    return validate("Need", {"id": f"need-{b['id']}", "buyer_id": b["id"], "items": [item], "delivery_window": "by Friday",
                             "spend_limit": b["cap"], "consent": True, "auction_window_s": 12, "source": "simulated"})


def _round(b: dict, sellers: list, now: datetime, round_no: int, strategy: dict) -> dict:
    owned = {"psu": b["psu"], "case": b["case"]}
    return run_round(_need(b), sellers, owned, b["cap"], now, round_no, strategies={LEARNER: strategy})


def _winner(res: dict):
    return res["winner"]["seller_id"] if res["winner"] else None


def run_seed(seed: int, n_builders: int, now: datetime) -> dict:
    sellers, _ = all_sellers()
    by_id = {s.id: s for s in sellers}
    builders = make_builders(n_builders, seed)
    train = [b for b in builders if b["archetype"] not in HELD_OUT]
    held = [b for b in builders if b["archetype"] in HELD_OUT]
    strategy, diffs = {"price_step": 0.0}, []
    for r, b in enumerate(train, 1):  # learning: only from the learner's own loss reports
        res = _round(b, sellers, now, r, strategy)
        if _winner(res) != LEARNER and res["winner"]:
            reports, _ = loss_reports(res, by_id, now)
            mine = next((x for x in reports if x["seller_id"] == LEARNER), None)
            if mine:
                strategy, diff = update_strategy(strategy, mine)
                if diff:
                    diffs.append({"builder": b["id"], "band": mine["gap_band"], "reason": mine["reason"], **diff})
    frozen = dict(strategy)

    def rates(strat):
        wins = [_winner(_round(b, sellers, now, 100 + i, strat)) for i, b in enumerate(held)]
        n = len(held) or 1
        return wins, {"learner": wins.count(LEARNER) / n, "control": wins.count(CONTROL) / n}

    wins, trained = rates(frozen)
    _, untrained = rates({"price_step": 0.0})
    per_arch = {}
    for a in HELD_OUT:
        idx = [i for i, b in enumerate(held) if b["archetype"] == a]
        n = len(idx) or 1
        per_arch[a] = {"n": len(idx), "learner": sum(wins[i] == LEARNER for i in idx) / n,
                       "control": sum(wins[i] == CONTROL for i in idx) / n}
    return {"seed": seed, "train_builders": len(train), "held_out_builders": len(held), "frozen_strategy": frozen,
            "strategy_diffs": diffs, "held_out_winners": wins, "learner": trained["learner"], "control": trained["control"],
            "untrained": untrained["learner"], "per_archetype": per_arch}


def summarize_lift(seeds: list[dict]) -> dict:
    lifts = [s["learner"] - s["control"] for s in seeds]
    untrained = [s["untrained"] - s["control"] for s in seeds]
    return {"lift_mean": round(statistics.mean(lifts), 4), "lift_range": (min(lifts), max(lifts)),
            "untrained_lift_mean": round(statistics.mean(untrained), 4), "per_seed": lifts}


def attack_arm() -> dict:
    def score(path: Path) -> dict:
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        atk = [r for r in rows if r["label"] == "attack"]
        ok = [r for r in rows if r["label"] == "clean"]
        stopped = [r["id"] for r in atk if screen(r["message"], r.get("context"), classifier=None)["verdict"] != "allow"]
        false_blocks = [r["id"] for r in ok if screen(r["message"], r.get("context"), classifier=None)["verdict"] != "allow"]
        return {"attacks": len(atk), "stopped": len(stopped), "block_rate": round(len(stopped) / len(atk), 4) if atk else None,
                "missed": sorted(set(r["id"] for r in atk) - set(stopped)), "controls": len(ok),
                "false_blocks": len(false_blocks), "false_block_ids": false_blocks}
    return {"dev": score(ROOT / "shield" / "corpus" / "dev.jsonl"), "held_out": score(HERE / "attacks" / "held_out.jsonl")}


def run(builders: int = 10, seeds: int = 3, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    per = [run_seed(s, builders, now) for s in range(seeds)]
    return {"origin": "SIM", "run_at": now.isoformat(timespec="seconds"), "builders": builders, "seeds": list(range(seeds)),
            "learning": {**summarize_lift(per), "held_out_archetypes": list(HELD_OUT), "learner": LEARNER, "control": CONTROL,
                         "seeds": per},
            "attack": attack_arm()}


def markdown(out: dict) -> str:
    L, A = out["learning"], out["attack"]
    n_held = sum(s["held_out_builders"] for s in L["seeds"])
    lo, hi = L["lift_range"]
    pct = lambda x: f"{x * 100:+.0f} pts"
    wins = sum(s["held_out_winners"].count(L["learner"]) for s in L["seeds"])
    cwins = sum(s["held_out_winners"].count(L["control"]) for s in L["seeds"])
    verdict = (f"**Too few held-out rounds to quote a lift (n = {n_held}, below {MIN_ROUNDS_TO_QUOTE}).** Raw counts: the learner won "
               f"{wins} of {n_held} held-out rounds, the control {cwins} of {n_held}. Run with more builders before using a number."
               if n_held < MIN_ROUNDS_TO_QUOTE else
               "**No positive lift: the learning seller did not beat the static control on held-out builders.**"
               if L["lift_mean"] <= 0 else
               f"Learning sellers beat a fair static seller by {pct(L['lift_mean'])} on held-out simulated builders "
               f"(n = {n_held} held-out rounds, {len(out['seeds'])} seeds, range {pct(lo)} to {pct(hi)}); "
               "this is a simulator we built, not the market.")
    lines = [f"# Wind tunnel results (SIM)", "",
             f"Run {out['run_at']} UTC: `python3 -m sim.wind_tunnel --builders {out['builders']} --seeds {len(out['seeds'])}`. "
             "Everything here is SIM. Control and learner are defined in sim/CONTROL.md.", "",
             "## Learning arm (benign builders only)", verdict, "",
             "| seed | train builders | held-out builders | learner win rate | control win rate | untrained learner | lift | frozen price step |",
             "|---|---|---|---|---|---|---|---|"]
    for s in L["seeds"]:
        lines.append(f"| {s['seed']} | {s['train_builders']} | {s['held_out_builders']} | {s['learner']:.2f} | {s['control']:.2f} | "
                     f"{s['untrained']:.2f} | {pct(s['learner'] - s['control'])} | {s['frozen_strategy']['price_step']:.2f} |")
    lines += ["", f"Mean lift {pct(L['lift_mean'])} (range {pct(lo)} to {pct(hi)}); untrained learner vs control {pct(L['untrained_lift_mean'])}. "
              f"Held-out archetypes: {', '.join(L['held_out_archetypes'])}.", "",
              "Per held-out archetype (learner / control win rate, by seed): " + "; ".join(
                  f"seed {s['seed']}: " + ", ".join(f"{a} {v['learner']:.2f}/{v['control']:.2f} (n={v['n']})" for a, v in s["per_archetype"].items())
                  for s in L["seeds"]),
              "", "## Attack arm (Shield, rules only, no classifier; no learning measured)",
              "| set | attacks | stopped | block rate | clean | false blocks |", "|---|---|---|---|---|---|"]
    for name in ("dev", "held_out"):
        x = A[name]
        lines.append(f"| {name} | {x['attacks']} | {x['stopped']} | {x['block_rate']:.0%} | {x['controls']} | {x['false_blocks']} |")
    lines += ["", f"Held-out misses: {', '.join(A['held_out']['missed']) or 'none'}. Held-out false blocks: {', '.join(A['held_out']['false_block_ids']) or 'none'}.",
              "The dev column is what the rules were written against; quote held-out, never a pooled number, and never \"secure\".",
              "", "## Caveats", f"- n is small: {n_held} held-out rounds in total. Seeds vary builders (cap, case, PSU); sellers are deterministic.",
              *(["- **Every seed gave the same lift.** Winners depend on the builder's archetype only, so the seeds add no "
                 "independent evidence and the range is not an interval. Seeds that vary sellers too are needed before quoting."]
                if lo == hi and len(L["seeds"]) > 1 else []),
              "- The learner has an open-box line the control lacks (sim/CONTROL.md); compare with the untrained column.",
              "- Rounds reuse demo/round.py on SIM and MIRROR sellers from one dated snapshot (Oct 24)."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builders", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    out = run(a.builders, a.seeds)
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out" / f"wind_tunnel-{out['run_at'][:10]}.json").write_text(json.dumps(out, indent=1, default=list))
    (HERE / "RESULTS.md").write_text(markdown(out))
    print(markdown(out))


if __name__ == "__main__":
    main()
