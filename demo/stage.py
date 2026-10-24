#!/usr/bin/env python3
"""Stage runner: one command to play the Tech Bazaar demo on the live screens for the video or a room.

    python3 demo/stage.py                  # check services, reset, then press Enter to play each beat
    python3 demo/stage.py --auto           # same, hands free: each beat starts after its reading delay
    python3 demo/stage.py --auto --live-call   # beat 4 places ONE real approval phone call

It reuses demo/bridge.py end to end (the beats, the reducer calls, the live approval gate) and adds only the show
around it: a service check (the launcher's own status), the reset, a one-line "say this" cue per beat and the pacing.
Nothing here charges anything. See demo/README.md ("Stage runner").
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo import bridge  # noqa: E402
from demo.bridge import Step  # noqa: E402
from demo.common import SIM, Narrator  # noqa: E402
from demo.run_demo import run_all  # noqa: E402

TITLES = {1: "Vidyut sets a goal", 2: "Sealed round", 3: "Shield blocks an injected listing",
          4: "Approval call and payment", 5: "Round two, the learner"}

# Seconds between a beat's cue and the beat starting in --auto mode (time to say the line). Override with --delays.
DEFAULT_DELAYS = {1: 7, 2: 8, 3: 6, 4: 9, 5: 8}

CUES = {
    1: "Vidyut tells the buyer agent what is needed: an RTX 5070 Ti that fits the case, under thirteen hundred dollars, "
       "new or open-box. Sellers never see the cap.",
    2: "Sellers bid in a sealed round. Every bid is tagged real listing or simulated, and the advocate vetoes the traps "
       "and shows its source.",
    3: "Bazaar Shield blocks the injected re-post of a listing and names the rules that fired.",
    4: "The winning bid becomes a signed mandate. The approval call is simulated here: wrong code, no 'approve', then "
       "right. The payment is a stub and no money moves.",
    5: "Every loser gets a reason. Gadget Grove (Vedant) uses its loss report to lower its open-box price for round two.",
}
LIVE_CUE_4 = ("The winning bid becomes a signed mandate and Vidyut's phone rings for real. Say the two-word code, then say "
              "approve. A wrong code or silence means nothing is paid.")


def cue_for(beat: int, live_call: bool = False) -> str:
    """The one line the narrator says at this beat. Beat 4 differs when the real call is on."""
    return LIVE_CUE_4 if beat == 4 and live_call else CUES[beat]


# ---------------------------------------------------------------- pure helpers

def assign_beats(steps: list[Step]) -> dict[int, list[Step]]:
    """Split the bridge's flat step list into the five stage beats, keeping order.
    1: goal and need. 2: the sealed round, open to close. 3: Shield blocks the injected listing (the step after round 1 closes).
    4: mandate, approval, payment. 5: round 2 (only when the plan has it)."""
    beats: dict[int, list[Step]] = {}
    beat, rounds_seen, round_one_closed = 1, 0, False
    for s in steps:
        if s.reducer == "open_round":
            rounds_seen += 1
            beat = 2 if rounds_seen == 1 else 5
        elif s.reducer == "create_mandate":
            beat = 4
        elif s.reducer == "attach_verdict" and round_one_closed and beat == 2:
            beat = 3
        beats.setdefault(beat, []).append(s)
        if s.reducer == "close_round" and rounds_seen == 1:
            round_one_closed = True
    return beats


def down_services(rows: list[dict]) -> list[str]:
    """Services the launcher reports DOWN or FAILED. SKIPPED is a choice the launcher already explained, so it does not block."""
    return [r["service"] for r in rows if r.get("label") in ("DOWN", "FAILED")]


def load_status_rows(run_dir: Path) -> list[dict]:
    """The launcher's own status logic (scripts/launch.py status), as rows. Empty means nothing was started."""
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import launch
    state = launch.PidFile(run_dir).load()
    if not state.get("services"):
        return []
    launch.web_note(state)
    return launch.status_rows(state)


def parse_delays(text: str) -> dict[int, float]:
    parts = [p.strip() for p in text.split(",")]
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"--delays needs five numbers of seconds, got {text!r}")
    if len(vals) != 5 or any(v < 0 for v in vals):
        raise ValueError(f"--delays needs five non-negative numbers (one per beat), got {text!r}")
    return dict(zip(range(1, 6), vals))


def make_say(out: Narrator) -> Callable[[Step], None]:
    def say(s: Step) -> None:
        if s.reducer == "set_floor":
            return
        who = "buyer" if s.actor == "buyer" else "referee" if s.actor == "referee" else s.actor.replace("seller:", "seller ")
        out.line(s.tag if s.tag in bridge.LIVE_TAGS else SIM, f"{who:<26}{s.reducer:<22}{s.say}")
    return say


def default_make_clients(args, steps: list[Step], out: Narrator) -> dict[str, Any]:
    """The same identities bridge.py uses: buyer and referee tokens, one seller identity per demo seller (owner assign_role)."""
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    from stdb import DB, Market
    tokens = bridge.find_tokens_dir(args.tokens_dir)
    out.note(f"tokens: {tokens}")
    seller_tokens = ROOT / ".tokens"
    seller_tokens.mkdir(exist_ok=True)
    clients: dict[str, Any] = {"buyer": Market(token_file=str(tokens / bridge.BUYER_TOKEN)),
                               "referee": Market(token_file=str(tokens / bridge.REFEREE_TOKEN))}
    seller_ids = sorted({s.actor.split(":", 1)[1] for s in steps if s.actor.startswith("seller:")})
    for sid in seller_ids:
        clients[f"seller:{sid}"] = Market(token_file=str(seller_tokens / f"bridge-{sid}.json"))
    if not args.no_assign_roles:
        import shutil
        spacetime = shutil.which("spacetime") or str(Path.home() / ".local" / "bin" / "spacetime")
        bridge.assign_seller_roles(seller_ids, clients, spacetime, args.server, DB)
    return clients


# ---------------------------------------------------------------- the show

def announce(out: Narrator, n: int, total: int, live_call: bool) -> None:
    out.blank()
    out.note("=" * 70)
    out.note(f"BEAT {n} of {total}: {TITLES[n]}")
    out.note(f"SAY THIS: {cue_for(n, live_call)}")
    if n == 4 and live_call:
        out.note("(the two-word code shows on /buyer; only if the market refuses it does it print below as SCREEN CODE)")
    out.note("=" * 70)


def report_round_one(clients: dict[str, Any], run: dict, out: Narrator) -> bool:
    """After round 1 closes: read the market's own ranking back (the bridge does the same after its run) and print it, so a
    different #1 shows as DIVERGENCE before the narrator reads the beat 4 cue. Returns True on a divergence. Reading back is a
    courtesy: a failure is one note, not a stop."""
    try:
        rows = clients["referee"].sql("SELECT * FROM round_result")
        lines = bridge.compare_to_db(rows, run)
    except Exception as e:
        out.note(f"could not read round_result back ({type(e).__name__})")
        return False
    for line in lines:
        out.note(line)
    return any(line.startswith("DIVERGENCE") for line in lines)


def play(beats: dict[int, list[Step]], clients: dict[str, Any], *, auto: bool, delays: dict[int, float], step_delay: float,
         approver: Optional[Callable[[Step], dict]], live_call: bool, out: Narrator, say: Callable[[Step], None],
         input_fn: Callable[[str], str], sleep: Callable[[float], None], clock: Callable[[], float],
         run: Optional[dict] = None, deal_gate: Optional[bridge.DealGate] = None) -> int:
    """Cue, then Enter (or the reading delay), then the beat. Returns 0 when every beat played, 1 when stopped.
    `deal_gate` makes beat 4's mandate when beat 4 starts, from the market's rank 1: a mandate lives 10 minutes, and the wait
    at the beat 1 to 3 prompts must not use it up. `run` turns on the round 1 read-back after beat 2."""
    total = max(beats)
    for n in sorted(beats):
        announce(out, n, total, live_call)
        if auto:
            if delays[n] > 0:
                sleep(delays[n])
        else:
            try:
                answer = input_fn(f"  Press Enter to play beat {n} (q to stop): ")
            except EOFError:
                out.note(f"STOPPED before beat {n}: no more input")
                return 1
            if answer.strip().lower() in ("q", "quit"):
                out.note(f"STOPPED before beat {n} (q)")
                return 1
        outcomes = bridge.execute(beats[n], clients, delay=step_delay, say=say, sleep=sleep, clock=clock,
                                  approver=approver, note=out.note, deal_gate=deal_gate)
        if outcomes and not outcomes[-1]["approved"]:
            out.blank()
            what = "no mandate was made" if outcomes[-1]["step"] == "build_mandate" else "the approval call did not approve"
            from pay.voice_cartesia import denial_line
            out.note(f"STOPPED at beat {n}: {what} ({outcomes[-1]['reason']}). {denial_line(outcomes[-1]['reason'])} "
                     "Run again to retake.")   # one "nothing was paid" sentence (#222)
            return 1
        if n == 2 and run is not None and report_round_one(clients, run, out) and auto:
            try:
                input_fn("  The market's #1 is not the demo's winner. Press Enter to continue anyway (Ctrl-C stops): ")
            except EOFError:
                pass
    return 0


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Play the five demo beats on the live screens, with a say-this cue per beat")
    ap.add_argument("--auto", action="store_true", help="no Enter: each beat starts after its reading delay (see --delays)")
    ap.add_argument("--delays", default=",".join(str(DEFAULT_DELAYS[n]) for n in range(1, 6)),
                    help="seconds between a beat's cue and the beat starting in --auto, five numbers (default %(default)s)")
    ap.add_argument("--step-delay", type=float, default=2.0, help="seconds between visible steps inside a beat (default 2)")
    ap.add_argument("--bid-window", type=bridge.bid_window_arg, default=None,
                    help="seconds each sealed round stays open, e.g. 20 for the video; steps inside run faster to fit")
    ap.add_argument("--live-call", action="store_true",
                    help="beat 4 places ONE real Cartesia phone call; approval and payment are recorded only if it approves")
    ap.add_argument("--env-file", type=Path, default=None, help="where the CARTESIA_* names are read from for --live-call")
    ap.add_argument("--force", action="store_true", help="start even if the launcher reports a service down")
    ap.add_argument("--dry-run", action="store_true", help="print the cues and the reducer calls only: no check, no reset, no market")
    ap.add_argument("--run-dir", type=Path, default=ROOT / ".run",
                    help="the launcher's pidfile folder (default: .run in this checkout; pass the live stack's when running from another)")
    ap.add_argument("--tokens-dir", help="folder with referee.json and buyer-vidyut.json (default: auto-detect)")
    ap.add_argument("--buyer-id", default=bridge.DB_BUYER_ID, help="DB buyer id (default vidyut, the id /buyer pairs with)")
    ap.add_argument("--no-assign-roles", action="store_true", help="skip the owner assign_role step for seller identities")
    ap.add_argument("--server", default=os.environ.get("SPACETIMEDB_SERVER", "local"))
    return ap


def main(argv: Optional[list] = None, *, status_rows: Optional[Callable[[Path], list]] = None,
         make_clients: Optional[Callable[..., dict]] = None, input_fn: Callable[[str], str] = input,
         sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> int:
    ap = make_parser()
    args = ap.parse_args(argv)
    try:
        delays = parse_delays(args.delays)
    except ValueError as e:
        ap.error(str(e))
    out = Narrator(True)
    say = make_say(out)

    run = run_all(say=Narrator(False))
    steps = bridge.plan(run, delay=args.step_delay, buyer_id=args.buyer_id, rounds=2, live_call=args.live_call,
                        bid_window=args.bid_window)
    beats = assign_beats(steps)

    out.note("Tech Bazaar stage runner: five beats, real lane code, existing SpacetimeDB reducers")
    out.note("Buyer: Vidyut. The goal, owned parts and payment are simulated. Tags: [MIRROR] real dated listing, [SIM] generated by us.")

    if args.dry_run:
        for n in sorted(beats):
            announce(out, n, len(beats), args.live_call)
            for s in beats[n]:
                say(s)
        out.blank()
        for g in bridge.NOT_BRIDGED:
            out.note("NOT BRIDGED: " + g)
        return 0

    rows = (status_rows or load_status_rows)(args.run_dir)
    down = down_services(rows)
    if not rows or down:
        out.blank()
        if not rows:
            out.note(f"NOT STARTING: the launcher has started nothing (no pids in {args.run_dir}). Run: python3 scripts/launch.py up")
        else:
            out.note(f"NOT STARTING: the launcher reports down: {', '.join(down)}. Fix them (python3 scripts/launch.py status), "
                     "or use --force to play anyway.")
        if not args.force:
            return 1
        out.note("FORCED: playing anyway, screens may be empty or stale.")
    else:
        out.note(f"services: {sum(r.get('label') == 'UP' for r in rows)}/{len(rows)} up")

    gate = bridge.DealGate(run)     # beat 4's mandate: made when beat 4 starts, from the market's own rank 1
    approver = None
    if args.live_call:
        # Startup only says where the call would go. The mandate the call judges is made when beat 4 starts (see play).
        approver, note = bridge.live_approver_for(args, run, gate, out)
        out.note(note)
    out.note(f"Pair /buyer as {args.buyer_id} (spacetime sql -s local tech-bazaar \"SELECT code FROM pair_code\") and open /market before you start.")

    try:
        clients = (make_clients or default_make_clients)(args, steps, out)
        out.note("reset_demo (referee): clearing the demo tables")
        clients["referee"].call("reset_demo")
        sleep(1)
        code = play(beats, clients, auto=args.auto, delays=delays, step_delay=args.step_delay, approver=approver,
                    live_call=args.live_call, out=out, say=say, input_fn=input_fn, sleep=sleep, clock=clock,
                    run=run, deal_gate=gate)
    except KeyboardInterrupt:
        out.blank()
        out.note("STOPPED (Ctrl-C). Nothing more will be written; run again to reset and retake.")
        return 130
    except RuntimeError as e:
        out.blank()
        out.note(f"STOPPED by the market: {e}")
        return 1
    except (OSError, subprocess.CalledProcessError) as e:
        out.blank()
        if isinstance(e, subprocess.CalledProcessError):
            err = (e.stderr or b"").decode(errors="replace").strip().splitlines()
            out.note(f"STOPPED: spacetime CLI failed: {err[0] if err else e}")
        else:
            out.note(f"STOPPED: market not reachable at {os.environ.get('SPACETIMEDB_HTTP', 'http://127.0.0.1:3000')} "
                     f"({type(e).__name__}). Start it with `python3 scripts/launch.py up`.")
        return 1
    if code == 0:
        out.blank()
        for g in bridge.NOT_BRIDGED:
            out.note("NOT BRIDGED: " + g)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
