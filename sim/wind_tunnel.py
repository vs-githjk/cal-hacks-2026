"""Wind tunnel (Lane C, c7; issues #30 and #34). SIM: a simulator we built, not the market.

    python3 -m sim.wind_tunnel --builders 10 --seeds 3      # writes sim/RESULTS.md and sim/out/wind_tunnel-<date>.json

Learning arm (benign builders only): parametric buyers from real part data (maker-checked PSUs and cases in
data/fit_builds.json) run sealed rounds through demo.round.run_round (real Shield, claim check, fit checker and
advocate) against every demo seller plus a second, field-median control. The learner (Gadget Grove (Vedant), a SIM seller) updates its price
step with demo.learning.update_strategy (a Lane D SIM stand-in, price step only; not Abhinav's a7 strategy) from its own
loss reports on TRAINING builders only, then is frozen and meets the frozen controls (sim/CONTROL.md) on builders from
HELD-OUT archetypes. A headline lift is printed only when the learner beats the field-median control on at least
MIN_WINNING_ARCHETYPES distinct held-out archetypes; otherwise only the per-archetype table is shown.
Attack arm (no learning measured): sim/attacks/held_out.jsonl and shield/corpus/dev.jsonl through shield.core.screen,
separate columns. Shield is never tuned on held_out.jsonl.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from demo.common import validate
from demo.learning import loss_reports, update_strategy
from demo.round import run_round
from demo.sellers import _sim_line, _sim_seller, all_sellers
from shield.core import screen

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
LEARNER, CONTROL, CONTROL_MEDIAN = "gadget-grove", "fair-price-pc", "median-market-pc"
LEARNER_RULE = "demo.learning.update_strategy (Lane D SIM stand-in, price step only; not Abhinav's a7 strategy)"
MIN_WINNING_ARCHETYPES = 2  # distinct held-out archetypes where learner > field-median control, before any headline

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


def median_control():
    """Second control, frozen in sim/CONTROL.md: static, honest, priced at the field median ($1,248.50)."""
    line = _sim_line(CONTROL_MEDIAN, "new", 1248.50, 1200.0, "SIM field-median control, honest card and 303 mm")
    return _sim_seller(CONTROL_MEDIAN, "Median Market PC (SIM)", [line], control=True)


def make_builders(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    names = list(ARCHETYPES)
    out = []
    for i in range(n):
        arch = names[i % len(names)]
        (lo, hi), conds, cases = ARCHETYPES[arch]
        case = rng.choice(cases)
        psu = rng.choice(list(PSUS))
        out.append({"id": f"b{seed}-{i:02d}", "archetype": arch, "cap": float(rng.randrange(lo, hi + 1, 5)),
                    "conditions": conds, "case_name": case, "case": CASES[case], "psu_name": psu, "psu": PSUS[psu]})
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
    sellers = all_sellers()[0] + [median_control()]
    by_id = {s.id: s for s in sellers}
    builders = make_builders(n_builders, seed)
    train = [b for b in builders if b["archetype"] not in HELD_OUT]
    held = [b for b in builders if b["archetype"] in HELD_OUT]
    strategy, diffs = {"price_step": 0.0}, []
    for r, b in enumerate(train, 1):  # learning: only from the learner's own loss reports
        res = _round(b, sellers, now, r, strategy)
        if _winner(res) != LEARNER and res["winner"]:
            mine = next((x for x in loss_reports(res, by_id, now)[0] if x["seller_id"] == LEARNER), None)
            if mine:
                strategy, diff = update_strategy(strategy, mine)
                if diff:
                    diffs.append({"builder": b["id"], "band": mine["gap_band"], "reason": mine["reason"], **diff})
    frozen = dict(strategy)
    rows = []
    for i, b in enumerate(held):
        rows.append({"builder": b["id"], "archetype": b["archetype"],
                     "winner_trained": _winner(_round(b, sellers, now, 100 + i, frozen)),
                     "winner_untrained": _winner(_round(b, sellers, now, 200 + i, {"price_step": 0.0}))})
    return {"seed": seed, "train_builders": len(train), "held_out_builders": len(held), "frozen_strategy": frozen,
            "strategy_diffs": diffs, "held_out": rows}


def per_archetype(seeds: list[dict]) -> dict:
    """Win rates pooled across seeds, one row per held-out archetype (the independent unit, not the round)."""
    out = {}
    for a in HELD_OUT:
        rows = [r for s in seeds for r in s["held_out"] if r["archetype"] == a]
        n = len(rows) or 1
        rate = lambda who, col="winner_trained": sum(r[col] == who for r in rows) / n
        out[a] = {"n": len(rows), "learner": rate(LEARNER), "untrained": rate(LEARNER, "winner_untrained"),
                  "control": rate(CONTROL), "control_median": rate(CONTROL_MEDIAN),
                  "winners": sorted({r["winner_trained"] or "none" for r in rows}),
                  "identical_across_seeds": len({tuple((r["winner_trained"], r["winner_untrained"]) for r in s["held_out"]
                                                       if r["archetype"] == a) for s in seeds}) <= 1}
    return out


def quote_gate(per_arch: dict, control_key: str = "control_median") -> tuple[bool, list]:
    winning = sorted(a for a, v in per_arch.items() if v["n"] and v["learner"] > v[control_key])
    return len(winning) >= MIN_WINNING_ARCHETYPES, winning


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
    arch = per_archetype(per)
    ok, winning = quote_gate(arch)
    return {"origin": "SIM", "run_at": now.isoformat(timespec="seconds"), "builders": builders, "seeds": list(range(seeds)),
            "learning": {"learner": LEARNER, "learner_rule": LEARNER_RULE, "controls": [CONTROL, CONTROL_MEDIAN],
                         "held_out_archetypes": list(HELD_OUT), "per_archetype": arch, "quotable": ok,
                         "winning_archetypes": winning, "seeds": per},
            "attack": attack_arm()}


def markdown(out: dict) -> str:
    L, A = out["learning"], out["attack"]
    arch = L["per_archetype"]
    n_held = sum(v["n"] for v in arch.values())
    pts = lambda x: f"{x * 100:+.0f} pts"
    if L["quotable"]:
        lift = sum(arch[a]["learner"] - arch[a]["control_median"] for a in arch) / len(arch)
        unt = sum(arch[a]["untrained"] - arch[a]["control_median"] for a in arch) / len(arch)
        verdict = (f"Learning sellers beat a fair static seller (field-median control) by {pts(lift)} on held-out simulated "
                   f"builders across {len(arch)} archetypes (n = {n_held} rounds, {len(out['seeds'])} seeds); the same seller "
                   f"without learning scored {pts(unt)}. This is a simulator we built, not the market.")
    else:
        verdict = (f"**No headline lift.** The learner beats the field-median control on {len(L['winning_archetypes'])} of "
                   f"{len(arch)} held-out archetypes ({', '.join(L['winning_archetypes']) or 'none'}); the gate needs "
                   f"{MIN_WINNING_ARCHETYPES}. Per-archetype results below; do not quote a single number.")
    lines = ["# Wind tunnel results (SIM)", "",
             f"Run {out['run_at']} UTC: `python3 -m sim.wind_tunnel --builders {out['builders']} --seeds {len(out['seeds'])}`. "
             "Everything here is SIM. Controls and learner are defined in sim/CONTROL.md.",
             f"Learner: {L['learner']}, updated by {L['learner_rule']}.", "",
             "## Learning arm (benign builders only)", verdict, "",
             "| held-out archetype | rounds (all seeds) | learner (trained) | learner (untrained) | control fair-price-pc ($1,289) | "
             "control median-market-pc ($1,248.50) | winners seen | identical across seeds |",
             "|---|---|---|---|---|---|---|---|"]
    for a, v in arch.items():
        lines.append(f"| {a} | {v['n']} | {v['learner']:.2f} | {v['untrained']:.2f} | {v['control']:.2f} | {v['control_median']:.2f} | "
                     f"{', '.join(v['winners'])} | {'yes' if v['identical_across_seeds'] else 'no'} |")
    lines += ["", "Frozen price step by seed: " + ", ".join(f"seed {s['seed']} {s['frozen_strategy']['price_step']:.2f}" for s in L["seeds"]),
              "", "## Attack arm (Shield, rules only, no classifier; no learning measured)",
              "| set | attacks | stopped | block rate | clean | false blocks |", "|---|---|---|---|---|---|"]
    for name in ("dev", "held_out"):
        x = A[name]
        lines.append(f"| {name} | {x['attacks']} | {x['stopped']} | {x['block_rate']:.0%} | {x['controls']} | {x['false_blocks']} |")
    lines += ["", f"Held-out misses: {', '.join(A['held_out']['missed']) or 'none'}. Held-out false blocks: "
              f"{', '.join(A['held_out']['false_block_ids']) or 'none'}.",
              "The dev column is what the rules were written against; quote held-out, never a pooled number, and never \"secure\".",
              "", "## Caveats",
              f"- The independent unit is the held-out archetype ({len(arch)} of them), not the round ({n_held} rounds).",
              "- Seeds vary builders (cap, case, PSU); sellers are deterministic."]
    if all(v["identical_across_seeds"] for v in arch.values()):
        lines.append("- **Per-archetype results are identical across seeds**: the seeds add no independent evidence.")
    if all(v["control"] == 0 for v in arch.values()):
        lines.append("- **The control at $1,289 never wins, by construction** (cheaper eligible sellers always exist), so lift "
                     "against it is just the learner's win rate. Use the field-median control column.")
    lines += ["- The learner also carries an open-box line the controls lack (sim/CONTROL.md); compare with the untrained column.",
              "- Rounds reuse demo/round.py on SIM and MIRROR sellers from one dated snapshot (Oct 24 UTC)."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builders", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    out = run(a.builders, a.seeds)
    (HERE / "out").mkdir(exist_ok=True)
    tag = f"{out['run_at'][:10]}-b{a.builders}x{a.seeds}"
    (HERE / "out" / f"wind_tunnel-{tag}.json").write_text(json.dumps(out, indent=1, default=list))
    (HERE / "RESULTS.md").write_text(markdown(out))
    print(markdown(out))


if __name__ == "__main__":
    main()
