"""Scoreboard numbers feed (Lane C, c12; issue #31). python3 -m data.scoreboard  -> data/scoreboard.json

Tiles (contracts/Scoreboard.schema.json), each recomputed from its source run when this module runs.
A tile with no trustworthy number has value null, status none_yet or not_quotable, and a note saying why.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from data.fit_checker import eval_builds

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "scoreboard.json"


def _tile(**kw) -> dict:
    return {"detail": {}, **kw}


def savings_tile() -> dict:
    from data.baselines import baseline, observations
    rows = observations()
    at = max((r["observed_at"] for r in rows), default=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    b = baseline("rtx 5070 ti", at, rows=rows)
    ok = b["status"] == "ok"
    why = "no verified purchase recorded yet" if ok else "no purchase has a confirmed dated baseline to compare against"
    ref = b["median"] if ok else b.get("reference_unconfirmed")
    ref_txt = (f"{'Baseline' if ok else 'Unconfirmed reference (not a baseline)'}: median ${ref:,.2f} of {b['n']} in-stock retail asks "
               f"({b['status']}, providers {', '.join(b['providers'])}; a baseline needs two distinct data owners). "
               if ref is not None else f"No reference ({b['status']}). ")
    sd = b["sold"]
    sold_txt = (f"eBay sold median ${sd['median']:,.2f} of {sd['n']} (last 30 days, mixed condition), shown beside the ask median, never blended. "
                if sd.get("median") is not None else "")
    owners_txt = f"Data owners: {' and '.join(b['owners'])}. " if b.get("owners") else ""
    return _tile(id="verified_savings", title="Dated verified savings", status="none_yet", value=None, unit="USD",
                 display=(f"No verified savings yet: {why} (reference {b['status']}, "
                          f"{b['n']} retail asks from {len(b['providers'])} provider{'s' if len(b['providers']) != 1 else ''})"),
                 count=b["n"], date_range={"from": b["from"] or at, "to": b["to"] or at}, origin="MIRROR",
                 source_run="python3 -m data.baselines",
                 detail={"reference": {"status": b["status"], "median": b["median"], "reference_unconfirmed": b.get("reference_unconfirmed"), "n": b["n"], "providers": b["providers"], "owners": b.get("owners", []), "ask_median": b.get("ask_median")},
                         "sold_kept_out": b["sold"], "sold": b["sold"], "marketplace": b["marketplace"]},
                 note=ref_txt + owners_txt + sold_txt + "apify-b re-checked Best Buy only (3 listings) and is the same data owner as apify. "
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
                         f"{full['correct']} of {full['decided']} on all; {len(full['false_ok'])} false OK (tuned set, not held out)",
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
    rows = "; ".join(f"{a}: learner {v['learner']:.2f}, untrained {v['untrained']:.2f}, median control {v['control_median']:.2f}, "
                     f"lift vs median control {v['learner'] - v['control_median']:+.2f}" for a, v in arch.items())
    return _tile(id="learning_lift", title="Seller learning lift", status="measured" if L["quotable"] else "not_quotable",
                 value=None, unit="points",
                 display=(f"No lift to quote ({len(L['winning_archetypes'])} of {len(arch)} archetypes, not quotable): the learner "
                          "beats the fair control on too few held-out buyer types") if not L["quotable"] else rows,
                 count=sum(v["n"] for v in arch.values()), date_range={"from": w["run_at"], "to": w["run_at"]}, origin="SIM",
                 source_run=f"python3 -m sim.wind_tunnel --builders {w['builders']} --seeds {len(w['seeds'])}",
                 detail={"per_archetype": arch, "winning_archetypes": L["winning_archetypes"], "run_file": pick.name},
                 note=f"{rows}. A simulator we built, not the market. Negative or zero lift is shown, never hidden.")


def _grab(rx: str, text: str) -> tuple[int, ...]:
    m = re.search(rx, text, re.S)
    if not m:
        raise ValueError(f"results file no longer states: {rx}")
    return tuple(int(g) for g in m.groups())


def voice_tile() -> dict:
    """Headline = the first run in pay/VOICE_ATTACKS.md (Lane D, d9); the after-fix run goes in detail only."""
    text = (ROOT / "pay" / "VOICE_ATTACKS.md").read_text()
    denied, n = _grab(r"First run, before any fix \(headline\): (\d+) of (\d+) denied", text)
    fixed, fixed_n = _grab(r"After the fix: (\d+) of (\d+) denied", text)
    when = "2026-10-24T08:22:00+00:00"  # "Sat Oct 24 01:22 PDT" in VOICE_ATTACKS.md
    return _tile(id="voice_attacks", title="Voice attacks (held-out)", status="measured", value=round(denied / n, 4), unit="ratio",
                 display=f"{denied} of {n} held-out voice attacks denied on the first run (after the fix: {fixed} of {fixed_n}; "
                         "v04 is no longer blind)",
                 count=n, date_range={"from": when, "to": when}, origin="SIM",
                 source_run="python3 -m pytest pay/tests/test_voice_attacks.py -q",
                 detail={"first_run": {"denied": denied, "n": n, "missed": ["v04"]}, "after_fix": {"denied": fixed, "n": fixed_n},
                         "results_file": "pay/VOICE_ATTACKS.md"},
                 note="Cases written by Lane C before the rules froze (sim/attacks/voice.jsonl). Headline is the first run; "
                      "the fix was made after reading it, so the 10 of 10 is not blind.")


def hyphenate_tile() -> dict:
    """Headline = the first blind run in hyphenate/RESULTS-blind.md; the after-fixes rerun goes in detail only."""
    text = (ROOT / "hyphenate" / "RESULTS-blind.md").read_text()
    caught, planted = _grab(r"FIRST BLIND RUN.*?Planted: (\d+) of (\d+) caught", text)
    passed, clean, flags = _grab(r"FIRST BLIND RUN.*?Clean: (\d+) of (\d+) passed, (\d+) false flags", text)
    after_caught, after_planted, after_clean, after_clean_n = _grab(
        r"After fixes.*?\*\*(\d+)/(\d+) planted caught, (\d+)/(\d+) clean passed", text)
    (when,) = re.search(r"Run (\S+) UTC", text).groups()
    return _tile(id="hyphenate_blind", title="Hyphenate blind planted errors", status="measured",
                 value=round(caught / planted, 4), unit="ratio",
                 display=f"{caught} of {planted} planted errors caught on the first blind run; {flags} of {clean} clean cases "
                         "falsely flagged",
                 count=planted + clean, date_range={"from": when, "to": when}, origin="SIM",
                 source_run="python3 -m hyphenate.scenarios.blind_run --write",
                 detail={"first_run": {"planted_caught": caught, "planted": planted, "clean_passed": passed, "clean": clean,
                                       "clean_false_flags": flags},
                         "after_fixes": {"planted_caught": after_caught, "planted": after_planted,
                                         "clean_passed": after_clean, "clean": after_clean_n, "not_blind": ["b24", "k02", "k03"]},
                         "results_file": "hyphenate/RESULTS-blind.md"},
                 note="Cases frozen and hashed before any run, written without reading the engine. Headline is the first run; "
                      "b24, k02 and k03 were fixed after it, so the rerun is not blind.")


DEMO_WINNER = {"sku": "rtx 5070 ti", "price": 1299.99, "condition": "new"}  # ASUS Prime at Best Buy


def position_block() -> dict:
    """Where the demo winner's price sits among the dated listings we hold (data.baselines.position)."""
    from data.baselines import observations
    from data.baselines.position import price_position
    rows = observations()
    as_of = max((r["observed_at"] for r in rows), default=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return price_position(DEMO_WINNER["sku"], DEMO_WINNER["price"], DEMO_WINNER["condition"], as_of, rows=rows)


def build() -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"generated_at": now, "tiles": [savings_tile(), attacks_tile(now), fit_tile(now), learning_tile(),
                                                voice_tile(), hyphenate_tile()], "price_position": position_block()}


if __name__ == "__main__":
    sb = build()
    OUT.write_text(json.dumps(sb, indent=1) + "\n")
    for t in sb["tiles"]:
        print(f"[{t['origin']}] {t['title']}: {t['display']}  ({t['status']}, n={t['count']}, {t['source_run']})")
