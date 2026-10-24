#!/usr/bin/env python3
"""Tech Bazaar end-to-end demo runner: one command walks the five stage beats through the real code that exists,
with clearly labelled stand-ins where a lane is not merged yet. Offline by default.

    python3 demo/run_demo.py                 # all five beats, writes demo/out/run-<timestamp>.json
    python3 demo/run_demo.py --beat 3        # one beat (earlier beats it needs run silently)
    python3 demo/run_demo.py --json          # the JSON on stdout, the story on stderr
    python3 demo/run_demo.py --stripe        # Stripe TEST charge, only with STRIPE_SECRET_KEY=sk_test_...

Tags on every data line: LIVE (a real outside party right now), MIRROR (our agent on a real, dated listing),
SIM (anything we generated). See demo/README.md for what is real and what is a stand-in, per beat.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.adapters import claim_checker  # noqa: E402
from demo.approval_flow import run_beat4  # noqa: E402
from demo.beats import run_beat2, run_beat3  # noqa: E402
from demo.common import Narrator, utc_iso  # noqa: E402
from demo.goal import run_beat1  # noqa: E402
from demo.learning import run_beat5  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "out"
SCHEMA = "tech-bazaar-demo-run/1"
NEEDS = {1: set(), 2: {1}, 3: set(), 4: {1, 2}, 5: {1, 2}}


def provenance() -> dict:
    _, label, real = claim_checker()
    return {
        "real_code": ["data.fit_checker (Lane C)", "shield.screen (Lane D)", "pay.mandate", "pay.callscript", "pay.approval", "pay.tap", "pay.replay"],
        "claim_check": {"label": label, "real": real},
        "stand_ins": {
            "agents/buyer goal parsing and ownership memory (Lane A, origin/agents)": "demo/goal.py",
            "agents/sellers bid policy (Lane A, origin/agents)": "demo/sellers.py",
            "agents/advocate card (Lane A, origin/agents)": "demo/standins/advocate.py",
            "market rules: sealing, floor, scoring, loss reports (Lane B, origin/lane-b-market-floor)": "demo/standins/market.py, demo/learning.py",
            "merchant simulator (Lane C): verify_request is called directly": "demo/approval_flow.py",
            "call transport (Cartesia): transcripts typed by the runner": "demo/approval_flow.py",
        },
        "data": {"MIRROR": "data/mirror/snapshots (real, dated listings)", "SIM": "Joe, Hal, Sam, Bargain Bin, Gadget Grove, Lowball, derived lines",
                 "LIVE": "none offline; Stripe test API only with --stripe"},
    }


def checks_of(run: Mapping) -> dict:
    """The five expectations the demo exists to show. main() exits non-zero if any is false."""
    beats = run["beats"]
    out = {}
    if "2" in beats:
        b2 = beats["2"]
        top = b2["cards"][0] if b2["cards"] else None
        out["beat2_cheapest_eligible_vetoed_with_source"] = bool(
            top and top["recommendation"] == "veto" and all(w["source_url"] for w in top["warnings"]) and b2["winner"])
        out["beat1_psu_skipped"] = any(i.get("skipped_owned_part_id") for i in beats["1"]["goal"]["items"]) if "1" in beats else None
    if "3" in beats:
        out["beat3_injected_listing_blocked"] = beats["3"]["blocked"] and bool(beats["3"]["injected"]["evidence_spans"])
    if "4" in beats:
        b4 = beats["4"]
        results = [a["decision"]["approved"] for a in b4["attempts"]]
        out["beat4_approved_only_on_third_try"] = results == [False, False, True]
        out["beat4_can_charge_only_after_approval"] = (not b4["can_charge_before"]["ok"]) and b4["can_charge_after"]["ok"]
        out["beat4_signature_valid_and_replay_fails"] = b4["verify"]["first"]["ok"] and not b4["verify"]["replay"]["ok"]
    if "5" in beats:
        b5 = beats["5"]
        out["beat5_learner_closes_gap_above_floor"] = b5["gap_closed"] and b5["learner"]["above_floor"] and b5["control"]["unchanged"]
    return {k: v for k, v in out.items() if v is not None}


def run_all(beats: Optional[set] = None, now: Optional[datetime] = None, say: Optional[Narrator] = None, use_stripe: bool = False,
            env: Optional[Mapping[str, str]] = None) -> dict:
    """Run the requested beats (default all) and return the run dict. Prerequisite beats run silently."""
    beats = beats or {1, 2, 3, 4, 5}
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    say = say or Narrator()
    quiet = say.quiet()
    want = set(beats)
    for b in list(beats):
        want |= NEEDS[b]
    out: dict = {}
    show = lambda n: say if n in beats else quiet
    out[1] = run_beat1(now, show(1)) if 1 in want else None
    out[2] = run_beat2(out[1], now, show(2)) if 2 in want else None
    out[3] = run_beat3(show(3)) if 3 in want else None
    out[4] = run_beat4(out[1], out[2], now, show(4), use_stripe=use_stripe, env=env) if 4 in want else None
    out[5] = run_beat5(out[1], out[2], now, show(5)) if 5 in want else None
    done = {str(n): v for n, v in out.items() if v is not None}
    run = {"schema": SCHEMA, "run_id": "run-" + now.strftime("%Y%m%dT%H%M%SZ"), "generated_at": utc_iso(now),
           "beats_shown": sorted(beats), "beats_run": sorted(int(k) for k in done), "provenance": provenance(), "beats": done}
    run["artifacts"] = artifacts_of(done)
    run["checks"] = checks_of(run)
    return run


def artifacts_of(beats: Mapping) -> dict:
    """The flat index Lane B's screens replay from: goal, bids, verdicts, mandate, approval, signatures, loss reports."""
    a: dict = {}
    if "1" in beats:
        a.update(goal=beats["1"]["goal"], owned_parts=beats["1"]["owned_parts"], need=beats["1"]["need"], allowance=beats["1"]["allowance"])
    if "2" in beats:
        b2 = beats["2"]
        a.update(seller_agents=b2["sellers"], bids=b2["bids"], claims=[c for cs in b2["claims"].values() for c in cs],
                 verdicts={"referee": b2["referee"], "shield": b2["shield"], "ranking": b2["ranking"], "advocate_cards": b2["cards"],
                           "winner": b2["winner"]})
    if "3" in beats:
        a.setdefault("verdicts", {})["injected_listing"] = beats["3"]["injected"]
        a["verdicts"]["control_listing"] = beats["3"]["control"]
    if "4" in beats:
        b4 = beats["4"]
        a.update(mandate=b4["mandate"], mandate_at_approval=b4["mandate_at_approval"], approval_record=b4["approval_record"],
                 approval_attempts=b4["attempts"], signatures=b4["signature"], signature_checks=b4["verify"], charge=b4["charge"],
                 call_script=b4["call_script"])
    if "5" in beats:
        a.update(loss_reports=beats["5"]["round1_loss_reports"] + beats["5"]["round2"]["loss_reports"],
                 strategy_diff=beats["5"]["strategy"], what_to_change=beats["5"]["what_to_change"])
    return a


def write_run(run: Mapping, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run['run_id']}.json"
    path.write_text(json.dumps(run, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def summary(say: Narrator, run: Mapping, path: Optional[Path]) -> None:
    say.blank()
    say.note("=" * 78)
    say.note("RESULT")
    for k, v in run["checks"].items():
        say.note(f"  {'PASS' if v else 'FAIL'}  {k}")
    if path:
        say.note(f"  JSON for Lane B's screens: {path}")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Tech Bazaar end-to-end demo runner (offline by default)")
    ap.add_argument("--beat", type=int, choices=[1, 2, 3, 4, 5], help="run a single beat")
    ap.add_argument("--json", action="store_true", help="print the run JSON to stdout (the story goes to stderr)")
    ap.add_argument("--stripe", action="store_true", help="use the Stripe TEST API when STRIPE_SECRET_KEY is an sk_test_ key")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR, help="where run-<timestamp>.json is written")
    ap.add_argument("--no-write", action="store_true", help="do not write the JSON file")
    args = ap.parse_args(argv)
    say = Narrator(True, sys.stderr if args.json else sys.stdout)
    say.note("Tech Bazaar end-to-end demo runner  (offline: no network, no real keys printed)")
    say.note("Tags: [LIVE] real outside party now   [MIRROR] our agent on a real dated listing   [SIM] generated by us")
    say.note("Joe, the sellers named (SIM) and every derived line are simulated. Real code runs on them; the headers say which.")
    run = run_all({args.beat} if args.beat else None, say=say, use_stripe=args.stripe)
    path = None if args.no_write else write_run(run, args.out_dir)
    summary(say, run, path)
    if args.json:
        print(json.dumps(run, indent=2, sort_keys=True, default=str))
    return 0 if all(run["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
