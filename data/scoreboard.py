"""Scoreboard numbers feed (Lane C, c12; issue #31). python3 -m data.scoreboard  -> data/scoreboard.json

Four tiles (contracts/Scoreboard.schema.json), each recomputed from its source run when this module runs.
A tile with no trustworthy number has value null, status none_yet or not_quotable, and a note saying why.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from data.fit_checker import eval_builds
from data.mirror import price_spread

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "scoreboard.json"


def _tile(**kw) -> dict:
    return {"detail": {}, **kw}


def savings_tile() -> dict:
    s = price_spread.summarize(price_spread.load())
    dates = s["snapshot_dates"]
    return _tile(id="verified_savings", title="Dated verified savings", status="none_yet", value=None, unit="USD",
                 display="No verified savings yet: the only was prices captured (Best Buy) equal the price",
                 count=s["asks"]["n"], date_range={"from": dates[0], "to": dates[-1]}, origin="MIRROR",
                 source_run="python3 -m data.mirror.price_spread",
                 detail={"asks": s["asks"], "baseline": {k: v for k, v in s["baseline"].items() if k != "dates"},
                         "out_of_stock_left_out": s["out_of_stock"]},
                 note="Store asks vs 5 eBay sales from one day, mixed condition: the gap is not a markup and not a saving. "
                      "SIM savings, when they exist, go in a separate column and are never added to real ones.")


def attacks_tile(now: str) -> dict:
    from shield.bench import SETS, bench
    b = bench(SETS)
    h, d = b["held_out"], b["dev"]
    return _tile(id="attacks_blocked", title="Attacks blocked (held-out)", status="measured", value=h["block_rate"], unit="ratio",
                 display=f"{h['attacks'] - len(h['missed'])} of {h['attacks']} held-out attacks stopped; "
                         f"{len(h['false_blocks'])} of {h['clean']} honest listings wrongly blocked",
                 count=h["attacks"], date_range={"from": now, "to": now}, origin="SIM", source_run="python3 -m shield.bench",
                 detail={"held_out": {"attacks": h["attacks"], "block_rate": h["block_rate"], "false_block_rate": h["false_block_rate"],
                                      "missed": h["missed"], "false_blocks": h["false_blocks"]},
                         "dev": {"attacks": d["attacks"], "block_rate": d["block_rate"], "false_block_rate": d["false_block_rate"]},
                         "adaptive": b["adaptive"], "judge_attempts": {"count": 0, "status": "console not built yet"},
                         "voice": {"status": "voice set written (sim/attacks/voice.jsonl), not yet run"}},
                 note=f"Run at {now} (the bench reruns when the feed is built). Rules only, no classifier. Held-out was written before the rules froze and is never tuned on. "
                      "Dev (what the rules were written against) is shown separately, never pooled. Never say secure.")


def fit_tile(now: str) -> dict:
    data = json.loads(eval_builds.BUILDS.read_text())
    full, checked = eval_builds.score(), eval_builds.score(only_checked=True)
    when = data.get("frozen", "")[:10]
    return _tile(id="fit_accuracy", title="Fit accuracy", status="measured",
                 value=round(checked["correct"] / checked["decided"], 4) if checked["decided"] else None, unit="ratio",
                 display=f"{checked['correct']} of {checked['decided']} right on maker-checked builds; "
                         f"{full['correct']} of {full['decided']} on all; {len(full['false_ok'])} false OK",
                 count=checked["n"], date_range={"from": when, "to": now[:10]}, origin="SIM",
                 source_run="python3 -m data.fit_checker.eval_builds",
                 detail={"checked": {"n": checked["n"], "correct": checked["correct"], "decided": checked["decided"]},
                         "all": {"n": full["n"], "correct": full["correct"], "decided": full["decided"], "uncertain": full["uncertain"]},
                         "false_ok": len(full["false_ok"]), "false_fail": len(full["false_fail"])},
                 note="Specs checked on maker pages by an agent, not a person. The set was tuned on once, so this is not held out.")


def learning_tile() -> dict:
    runs = sorted((ROOT / "sim" / "out").glob("wind_tunnel-*.json"))
    pick = max(runs, key=lambda p: json.loads(p.read_text())["builders"] * len(json.loads(p.read_text())["seeds"]))
    w = json.loads(pick.read_text())
    L = w["learning"]
    arch = L["per_archetype"]
    rows = "; ".join(f"{a}: learner {v['learner']:.2f}, untrained {v['untrained']:.2f}, median control {v['control_median']:.2f}"
                     for a, v in arch.items())
    return _tile(id="learning_lift", title="Seller learning lift", status="measured" if L["quotable"] else "not_quotable",
                 value=None, unit="points",
                 display=("No lift to quote: the learner beats the fair control on "
                          f"{len(L['winning_archetypes'])} of {len(arch)} held-out buyer types") if not L["quotable"] else rows,
                 count=sum(v["n"] for v in arch.values()), date_range={"from": w["run_at"], "to": w["run_at"]}, origin="SIM",
                 source_run=f"python3 -m sim.wind_tunnel --builders {w['builders']} --seeds {len(w['seeds'])}",
                 detail={"per_archetype": arch, "winning_archetypes": L["winning_archetypes"], "run_file": pick.name},
                 note=f"{rows}. A simulator we built, not the market. Negative or zero lift is shown, never hidden.")


def build() -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"generated_at": now, "tiles": [savings_tile(), attacks_tile(now), fit_tile(now), learning_tile()]}


if __name__ == "__main__":
    sb = build()
    OUT.write_text(json.dumps(sb, indent=1) + "\n")
    for t in sb["tiles"]:
        print(f"[{t['origin']}] {t['title']}: {t['display']}  ({t['status']}, n={t['count']}, {t['source_run']})")
