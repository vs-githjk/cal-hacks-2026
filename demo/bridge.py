#!/usr/bin/env python3
"""Screen bridge: play the demo beats (real lane code, demo/run_demo.py) into the running SpacetimeDB market,
step by step, so /buyer and /market on the web app show Vidyut's round live.

    python3 demo/bridge.py                       # one run, 2 s between steps, against the local market
    python3 demo/bridge.py --step-delay 3 --reset  # slower, and wipe the demo tables first (reset_demo)
    python3 demo/bridge.py --dry-run             # print the reducer calls, touch nothing
    python3 demo/bridge.py --live-call           # beat 4 places one real approval phone call; pays only if it approves

Every write goes through an EXISTING reducer with the role token that reducer demands: the buyer token posts the
goal and the need, the referee token opens and closes rounds and attaches Shield, claim-check and advocate results and moves
the money records, and each seller line bids with its own seller identity. No role gate is bypassed. The only owner
action is setup: `assign_role` (what market/scripts/setup_roles.py does) for the demo's seller identities.

What the market has no reducer or column for is NOT faked: the console prints it as NOT BRIDGED at the end and
demo/README.md lists the gaps for Lane B. Pure mapping (run -> steps) is `plan`; the live part is `execute`.
"""
from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.common import MIRROR, SIM, Narrator, money  # noqa: E402

DB_BUYER_ID = "vidyut"          # the id /buyer pairs with (web DEMO_BUYER) and the only one with a pairing code
BUYER_TOKEN, REFEREE_TOKEN = "buyer-vidyut.json", "referee.json"
MANDATE_MINUTES = 30
MIN_WINDOW_S = 6
LIVE_TAGS = {"MIRROR", "SIM", "LIVE"}


@dataclass
class Step:
    actor: str                       # "buyer", "referee" or "seller:<seller_id>"
    reducer: str
    args: dict = field(default_factory=dict)
    say: str = ""
    tag: str = SIM
    pause: bool = False              # wait --step-delay after this call (the step shows on screen)
    pace: float = 1.0                # multiplier on the delay (round 2 runs faster)
    close: bool = False              # wait for the round deadline, then close it
    window_s: int = 0                # open_round only: the window this step asked for
    gate: str = ""                   # "approval_call": with an approver this step runs only if the live call approved


# ---------------------------------------------------------------- the mapping (pure, tested with a fake client)

def _line(bid: dict, index: int, sku: str) -> dict:
    l = bid["lines"][index]
    return {"sku_spec": sku, "offered_spec": "", "offered_condition": l["offered_condition"],
            "unit_price": l["unit_price"], "quantity": l["quantity"]}


def _entries(ranking: dict) -> dict:
    """seller_id -> the ranking entry (ranked or disqualified) carrying the picked line index."""
    return {e["seller_id"]: e for e in [*ranking["ranked"], *ranking["disqualified"]]}


def bid_id(bid: dict, round_no: int) -> str:
    return bid["id"] if round_no == 1 else f"{bid['id']}-r{round_no}"


def round_steps(*, round_no: int, need_id: str, bids: list[dict], ranking: dict, sellers: dict, shield: list[dict],
                claims: dict, cards: list[dict], delay: float, pace: float) -> list[Step]:
    """open_round, every seller's floor and sealed bid in arrival order, then the Shield, claim-check and advocate results.
    A bid carries ALL its condition lines (alternatives for one SKU); the market picks the cheapest allowed one."""
    round_id = f"round-{round_no}"
    sku = bids[0]["lines"][0]["sku_spec"]
    entry = _entries(ranking)
    seller_steps: list[Step] = []
    for bid in bids:
        sid = bid["seller_id"]
        idx = entry.get(sid, {}).get("line", 0)
        seller = sellers[sid]
        placed = bid["lines"][idx]                       # the line the demo picked: its price and listing are the bid's headline
        floor = min(l["floor"] for l in seller["lines"])   # the market keeps one floor per SKU; the lowest never blocks a line
        alts = f" (alternatives, the market picks the cheapest allowed: " + " | ".join(
            f"{l['offered_condition']} {l['unit_price']:,.2f}" for l in bid["lines"]) + ")" if len(bid["lines"]) > 1 else ""
        seller_steps.append(Step(f"seller:{sid}", "set_floor", {"sku_spec": sku, "floor": floor}, tag=bid["origin"],
                                 say=f"{bid['persona']} sets a private floor"))
        seller_steps.append(Step(
            f"seller:{sid}", "place_bid",
            {"id": bid_id(bid, round_no), "round_id": round_id, "persona": bid["persona"],
             "lines": [_line(bid, i, sku) for i in range(len(bid["lines"]))],
             "stated_total": placed["unit_price"] * placed["quantity"], "perks": list(bid["perks"]), "claims": list(bid["claims"]),
             "origin": bid["origin"], "source": placed["listing_url"]},
            tag=bid["origin"], pause=True, pace=pace,
            say=f"{bid['persona']} seals a bid: {placed['offered_condition']} {money(placed['unit_price'])}{alts}"))
    rejected = {e["bid_id"] for e in ranking["disqualified"] if e.get("kind") == "rejected"}   # floor: never screened
    check_steps: list[Step] = []
    for v in shield:
        if v["bid_id"] in rejected:
            continue
        bid = next(b for b in bids if b["id"] == v["bid_id"])
        check_steps.append(Step("referee", "attach_verdict",
                                {"bid_id": bid_id(bid, round_no), "verdict": v["verdict"], "rule_ids": list(v["rule_ids"]), "origin": SIM},
                                tag=SIM, pause=True, pace=pace,
                                say=f"Bazaar Shield (real shield.screen) on {bid['persona']}: {v['verdict']}"))
    for bid in bids:
        for c in claims.get(bid["id"], []):
            check_steps.append(Step("referee", "attach_claim_check",
                                    {"bid_id": bid_id(bid, round_no), "claim": c["text"], "check": c["check"],
                                     "evidence_url": c["evidence_url"], "origin": c["origin"]},
                                    tag=c["origin"], pause=True, pace=pace,
                                    say=f"claim check (real data.claim_check) on {bid['persona']}: {c['check']}: {c['text']}"))
    bid_of = {b["id"]: b for b in bids}
    for c in cards:        # the advocate's real card for every bid it judged; a veto disqualifies it at the close
        bid = bid_of[c["bid_id"]]
        why = c["call_reason"]
        check_steps.append(Step("referee", "attach_advocate_card",
                                {"bid_id": bid_id(bid, round_no), "recommendation": c["recommendation"], "rule_id": why["rule_id"],
                                 "text": why["summary"], "source_url": why["source_url"], "origin": bid["origin"]},
                                tag=bid["origin"], pause=c["recommendation"] == "veto", pace=pace,
                                say=f"advocate (Lane A checks.advise) on {bid['persona']}: {c['recommendation'].upper()} "
                                    f"{why['rule_id']}: {why['summary']}"))
    paused = sum(s.pace for s in [*seller_steps, *check_steps] if s.pause)
    window = max(MIN_WINDOW_S, math.ceil(paused * delay) + 6)
    opener = Step("referee", "open_round", {"round_id": round_id, "need_id": need_id, "window_s": window}, window_s=window,
                  tag=SIM, pause=True, pace=pace, say=f"round {round_no} opens sealed for {window} s")
    closer = Step("referee", "close_round", {"round_id": round_id}, close=True, tag=SIM, pause=True, pace=pace,
                  say=f"round {round_no} closes at its deadline: the market ranks and reveals every bid")
    return [opener, *seller_steps, *check_steps, closer]


def fresh_pending_mandate(m: dict) -> dict:
    """A new pending mandate for the demo deal (same deal, amount and payee as the run's, which beat 4 already spent).
    A real call needs a pending mandate that is still unexpired when the phone rings."""
    from pay.mandate import new_mandate
    return new_mandate(deal_id=m["deal_id"], buyer_id=m["buyer_id"], amount=m["amount"], payee=m["payee"],
                       goal_id=m.get("goal_id"), within_allowance=False, origin=m["origin"])


def plan(run: dict, *, delay: float = 2.0, buyer_id: str = DB_BUYER_ID, rounds: int = 1,
         mandate: Optional[dict] = None, live_call: bool = False) -> list[Step]:
    """Map a demo run (demo.run_demo.run_all) to reducer calls, in the order the stage story tells it.
    `mandate` (with `live_call`) replaces the run's beat-4 mandate with the pending one the real call will judge."""
    b = run["beats"]
    goal, need, b2 = b["1"]["goal"], b["1"]["need"], b["2"]
    sellers = {s["id"]: s for s in b2["sellers"]}
    steps: list[Step] = []

    # beat 1: Vidyut's goal and need (the buyer token posts both, for its own buyer id)
    conds = goal["items"][0].get("allowed_conditions") or [goal["items"][0]["condition"]]
    items = [{"sku_spec": i["sku_spec"], "condition": " or ".join(conds) if i["part"] == "gpu" else i["condition"],
              "variant": i["variant"], "quantity": i["quantity"], "skipped_owned_part_id": i.get("skipped_owned_part_id", "")}
             for i in goal["items"]]
    steps.append(Step("buyer", "post_goal",
                      {"id": goal["id"], "buyer_id": buyer_id, "type": goal["type"], "cap": goal["cap"], "deadline": goal["deadline"],
                       "po_number": "", "origin": SIM, "items": items},
                      pause=True, say=f"Vidyut (DB buyer id {buyer_id}) sets a goal: {b['1']['goal_text']}"))
    al = b["1"]["allowance"]      # SIM: Vidyut's standing allowance; the referee sets it (a buyer can only lower their own)
    steps.append(Step("referee", "set_allowance",
                      {"buyer_id": buyer_id, "per_purchase_limit": al["per_purchase_limit"], "period_limit": al["period_limit"],
                       "period": al["period"]},
                      pause=True, say=f"Vidyut's allowance is set: {money(al['per_purchase_limit'])} per buy, "
                                      f"{money(al['period_limit'])} a {al['period']}; above it the agent calls"))
    n = need["items"][0]
    steps.append(Step("buyer", "post_need",
                      {"id": need["id"], "buyer_id": buyer_id, "goal_id": goal["id"], "delivery_window": need["delivery_window"],
                       "spend_limit": need["spend_limit"], "consent": need["consent"], "auction_window_s": need["auction_window_s"],
                       "origin": SIM,
                       "items": [{"sku_spec": n["sku_spec"], "condition": n["condition"],
                                  "allowed_conditions": list(n.get("allowed_conditions") or []), "variant": n["variant"],
                                  "quantity": n["quantity"], "unit": n["unit"]}]},
                      pause=True, say=f"the need goes to sellers: {n['sku_spec']}, {' or '.join(n.get('allowed_conditions') or [n['condition']])}; the cap is withheld from them"))

    # beat 2: the sealed round (Shield and claim checks attach before the close; the market ranks)
    steps += round_steps(round_no=1, need_id=need["id"], bids=b2["bids"], ranking=b2["ranking"], sellers=sellers, shield=b2["shield"],
                         claims=b2["claims"], cards=b2["cards"], delay=delay, pace=1.0)

    # beat 3: Shield blocks Shady Sam's injected re-post (after the close, as in the demo; Sam is already out on his claims)
    inj = b["3"]["injected"]
    sam = next(x for x in b2["bids"] if x["seller_id"] == inj["seller_id"])
    steps.append(Step("referee", "attach_verdict",
                      {"bid_id": bid_id(sam, 1), "verdict": inj["verdict"], "rule_ids": list(inj["rule_ids"]), "origin": SIM},
                      pause=True, say=f"Bazaar Shield BLOCKS {sam['persona']}'s injected listing re-post "
                                      f"({len(inj['rule_ids'])} rules, {inj['latency_ms']} ms)"))

    # beat 4: mandate, approval, payment (the deal is above the allowance set in beat 1, so it needs the call)
    m, ch, win = (mandate if mandate is not None else b["4"]["mandate"]), b["4"]["charge"], b2["winner"]
    wbid = next(x for x in b2["bids"] if x["id"] == win["bid_id"])
    steps.append(Step("referee", "create_mandate",
                      {"hash": m["hash"], "id": m["id"], "deal_id": m["deal_id"], "buyer_id": buyer_id, "amount": m["amount"],
                       "payee": m["payee"], "expiry_minutes": MANDATE_MINUTES, "nonce": m["nonce"], "requested_by": "",
                       "origin": m["origin"]},
                      tag=m["origin"], pause=True,
                      say=f"mandate for {wbid['persona']}: {money(m['amount'])} to {m['payee']} (a SIM test address)"))
    steps.append(Step("referee", "record_approval", {"mandate_hash": m["hash"], "method": "voice_code", "approved_by": buyer_id},
                      pause=True, gate="approval_call",
                      say=("a real phone call: the buyer says the code from the screen and 'approve'; the referee relays the verified code"
                           if live_call else
                           "the call approves on the third try (wrong code, no 'approve', then right): the referee relays the verified code")))
    pay_mode = "stripe_test" if ch["mode"] == "Stripe test mode" else "sim"
    ref = "ch_sim_" + m["hash"][:12] if live_call and pay_mode == "sim" else ch["id"]
    pay = {"mandate_hash": m["hash"], "payment_ref": ref, "amount": m["amount"], "mode": pay_mode}
    steps.append(Step("referee", "record_payment", dict(pay), pause=True, tag="LIVE" if pay_mode == "stripe_test" else SIM,
                      say=f"payment recorded: {ref} ({ch['mode']})"))
    steps.append(Step("referee", "record_payment", dict(pay),
                      pause=True, say="the same payment again: the market's own idempotency refuses it and shows the refusal"))

    # beat 5: round 2 with the learning seller's lowered price (loss reports have no reducer: NOT BRIDGED)
    if rounds >= 2:
        r2 = b["5"]["round2"]
        steps += round_steps(round_no=2, need_id=need["id"], bids=r2["bids"], ranking=r2["ranking"], sellers=sellers,
                             shield=b2["shield"], claims=b2["claims"], cards=r2["cards"], delay=delay, pace=0.5)
    return steps


# What the market cannot take today (printed at the end of every run; mirrored in demo/README.md for Lane B).
NOT_BRIDGED = [
    "loss reports (contracts/LossReport): no table or reducer, so beat 5 (reports, the learner's price step) is console only; `--rounds 2` replays round 2 and the learner's lower open-box price now ranks, but the loss report itself is not on screen.",
    "goal state (HUNTING, HOLD_FOR_CALL, DONE): no set_goal_state reducer; the goal stays ACTIVE and reserved_amount stays 0.",
    "denied approval attempts (wrong code, no 'approve'): record_approval only logs a second approval; the denied tries are console only.",
    "the one-time approval code on /buyer: no reducer or table carries it (notifications are written only by the market's own reducers), "
    "so with --live-call the code prints on the operator console as SCREEN CODE; Lane B needs a buyer-scoped show_approval_code.",
    "buyer name and seller personas: /buyer is hardcoded to the id vidyut and prints 'Buyer: Vidyut'; persona rows come only "
    "from seed_demo (Seller A to C), so the 3D floor has no personas for the demo sellers.",
    "seller floors per condition: the market keeps one floor per SKU, so a seller with several condition lines gets its lowest floor "
    "(issue #18 asks for a floor per seller, SKU and condition).",
]


# ---------------------------------------------------------------- the live part

def execute(steps: list[Step], clients: dict, *, delay: float, say: Callable[[Step], None],
            sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
            approver: Optional[Callable[[Step], dict]] = None, note: Callable[[str], None] = lambda text: None) -> list[dict]:
    """Run the steps in order. A reducer refusal stops the run with the market's own message.
    With an `approver`, the approval step runs only after it returns approved; a denial skips the approval and every payment
    step and ends the run there (the mandate stays pending, nothing is charged). Returns the approval outcomes."""
    deadline: Optional[float] = None
    outcomes: list[dict] = []
    for s in steps:
        say(s)
        if s.gate == "approval_call" and approver is not None:
            outcome = approver(s)
            outcomes.append(outcome)
            if not outcome["approved"]:
                note(f"live call DENIED ({outcome['reason']}): no approval and no payment are recorded; the mandate stays pending")
                break
            note(f"live call APPROVED (call {outcome['call_id']}): the referee records the approval, then the payment")
        client = clients[s.actor]
        if s.close:
            for attempt in range(12):
                if deadline is not None and clock() < deadline:
                    sleep(deadline - clock())
                try:
                    client.call(s.reducer, **s.args)
                    break
                except RuntimeError as e:
                    msg = str(e)
                    if "already closed" in msg:
                        break
                    if "still open" in msg and attempt < 11:
                        sleep(1.0)    # an anti-snipe extension moved the deadline
                        continue
                    raise
        else:
            client.call(s.reducer, **s.args)
        if s.window_s:
            deadline = clock() + s.window_s
        if s.pause and delay > 0:
            sleep(delay * s.pace)
    return outcomes


def make_live_approver(mandate: dict, advocate_reason: Any, client: Any, *, unconfigured: Optional[str] = None,
                       buyer_name: str = "Vidyut", deal: Any = None, on_code: Callable[[str], None] = lambda code: None,
                       secret: Optional[str] = None, **timing) -> Callable[[Step], dict]:
    """The approval gate for --live-call: one real approval call for `mandate` (pay.voice_cartesia.run_approval_call).
    The code goes only to `on_code` (the screen); the call judges that same code. Default deny: no client (not configured),
    a failed dial, silence, a wrong code, an expired mandate, or a pay.mandate.can_charge refusal after the call all deny."""
    import secrets as _secrets
    from pay.approval import ApprovalService
    from pay.mandate import can_charge
    from pay.replay import NonceStore
    from pay.voice_cartesia import CALL_CODE_TTL_S, run_approval_call

    def outcome(approved: bool, reason: Optional[str], call_id: Optional[str] = None) -> dict:
        return {"step": "approval_call", "approved": approved, "reason": reason, "call_id": call_id}

    def approve(step: Step) -> dict:
        if client is None:
            return outcome(False, f"not_configured: {unconfigured or 'no Cartesia client'}")
        store = NonceStore()
        service = ApprovalService(secret=secret or _secrets.token_hex(16), store=store, code_ttl_seconds=CALL_CODE_TTL_S)
        res = run_approval_call(mandate, advocate_reason, client, service, deal=deal, buyer_name=buyer_name, on_code=on_code, **timing)
        if not res.approved:
            return outcome(False, res.reason or "denied", res.call_id)
        guard = can_charge(mandate, deal_id=mandate["deal_id"], amount=mandate["amount"], payee=mandate["payee"], store=store)
        if not guard:
            return outcome(False, f"can_charge: {guard.reason}", res.call_id)
        return outcome(True, None, res.call_id)

    return approve


def compare_to_db(rows: list, run: dict) -> list[str]:
    """Lines saying whether the market's round-1 ranking matches the demo's. Rows are round_result rows in table order:
    id, round_id, bid_id, seller_id, persona, rank, landed, reasons, ... (round-1 only)."""
    b2 = run["beats"]["2"]
    demo_win = next(s for s in b2["sellers"] if s["id"] == b2["winner"]["seller_id"])["name"]
    r1 = sorted((r for r in rows if r[1] == "round-1"), key=lambda r: (r[5] or 99, r[4]))
    ranked = [r for r in r1 if r[5]]
    out = [f"market ranking (round 1): " + ", ".join(f"#{r[5]} {r[4]} {money(r[6])}" for r in ranked)]
    for r in (r for r in r1 if not r[5]):
        reasons = r[7] if len(r) > 7 and isinstance(r[7], list) else []
        out.append(f"market OUT: {r[4]} {money(r[6])}: " + ("; ".join(reasons) or "no reason given"))
    if ranked and ranked[0][3] != b2["winner"]["seller_id"]:
        out.append(f"DIVERGENCE: the demo's winner is {demo_win}; the market ranks {ranked[0][4]} first. "
                   f"The mandate that follows is the demo's winner, not the market's #1.")
    elif not ranked:
        out.append("DIVERGENCE: the market ranked no bid.")
    else:
        out.append(f"market and demo agree on the winner: {demo_win}")
    return out


def assign_seller_roles(seller_ids: list[str], clients: dict, spacetime: str, server: str, db: str) -> None:
    """Owner step, the same call market/scripts/setup_roles.py makes: one seller identity per demo seller."""
    for sid in seller_ids:
        ident = clients[f"seller:{sid}"].identity
        subprocess.run([spacetime, "call", "-s", server, db, "assign_role", f'"0x{ident}"', '"seller"', f'"{sid}"'],
                       check=True, capture_output=True)


def find_tokens_dir(explicit: Optional[str]) -> Path:
    cands = [Path(explicit)] if explicit else [Path(os.environ["BRIDGE_TOKENS_DIR"])] if os.environ.get("BRIDGE_TOKENS_DIR") else []
    cands += [ROOT / ".tokens", ROOT.parent / "lane-d-launcher" / ".tokens", ROOT.parent / "lane-d" / ".tokens"]
    for c in cands:
        if (c / REFEREE_TOKEN).exists() and (c / BUYER_TOKEN).exists():
            return c
    raise SystemExit("no tokens dir with referee.json and buyer-vidyut.json (run market/scripts/setup_roles.py, or pass --tokens-dir)")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Play the demo beats into the running SpacetimeDB market so /buyer and /market show them")
    ap.add_argument("--step-delay", type=float, default=2.0, help="seconds between visible steps (default 2)")
    ap.add_argument("--rounds", type=int, choices=[1, 2], default=1,
                    help="2 also plays beat 5's round 2 (default 1)")
    ap.add_argument("--reset", action="store_true", help="call reset_demo first (referee): wipes needs, goals, rounds; keeps roles and pair codes")
    ap.add_argument("--dry-run", action="store_true", help="print the reducer calls only")
    ap.add_argument("--stripe", action="store_true", help="Stripe TEST charge in beat 4 (sk_test_ key only), as run_demo.py --stripe")
    ap.add_argument("--live-call", action="store_true",
                    help="beat 4 places ONE real Cartesia phone call to APPROVAL_CALL_TO; approval and payment are recorded only if the call approves")
    ap.add_argument("--env-file", type=Path, default=None,
                    help="where the CARTESIA_* names are read from for --live-call (default: pay.voice_cartesia.DEFAULT_ENV_FILE)")
    ap.add_argument("--tokens-dir", help="folder with referee.json and buyer-vidyut.json (default: auto-detect)")
    ap.add_argument("--buyer-id", default=DB_BUYER_ID, help="DB buyer id (default vidyut, the id /buyer pairs with)")
    ap.add_argument("--no-assign-roles", action="store_true", help="skip the owner assign_role step for seller identities")
    ap.add_argument("--server", default=os.environ.get("SPACETIMEDB_SERVER", "local"))
    args = ap.parse_args(argv)
    if args.live_call and args.stripe:
        ap.error("--live-call and --stripe cannot be combined: the Stripe test charge runs before the round and must never run before a call approves")

    from demo.run_demo import run_all, stripe_env, DEFAULT_ENV_FILE
    env = {**os.environ, **stripe_env(DEFAULT_ENV_FILE)} if args.stripe else None
    run = run_all(say=Narrator(False), use_stripe=args.stripe, env=env)
    live_mandate = fresh_pending_mandate(run["beats"]["4"]["mandate"]) if args.live_call else None
    steps = plan(run, delay=args.step_delay, buyer_id=args.buyer_id, rounds=args.rounds, mandate=live_mandate, live_call=args.live_call)
    out = Narrator(True)
    out.note("Tech Bazaar screen bridge: demo beats (real lane code) -> existing SpacetimeDB reducers")
    out.note(f"{len(steps)} reducer calls, {args.step_delay} s between visible steps. Open /buyer (pair as {args.buyer_id}) and /market.")
    out.note("Buyer: Vidyut. The goal, owned parts and payment are simulated. Tags: [MIRROR] real dated listing, [SIM] generated by us.")

    def say(s: Step) -> None:
        who = "buyer" if s.actor == "buyer" else "referee" if s.actor == "referee" else s.actor.replace("seller:", "seller ")
        if s.reducer == "set_floor":
            return
        out.line(s.tag if s.tag in LIVE_TAGS else SIM, f"{who:<26}{s.reducer:<22}{s.say}")

    approver, client_note = None, ""
    if args.live_call:
        approver, client_note = live_approver_for(args, run, live_mandate, out)
        out.note(client_note)
    if args.dry_run:
        for s in steps:
            say(s)
        out.blank()
        for g in NOT_BRIDGED:
            out.note("NOT BRIDGED: " + g)
        return 0

    if not args.stripe:
        out.note("Payment is the SIM stub: /market labels it 'SIM stub, no money moved'. Use --stripe for a Stripe TEST charge.")
    try:
        return _run_live(args, steps, run, out, say, approver)
    except (OSError, subprocess.CalledProcessError) as e:
        out.blank()
        if isinstance(e, subprocess.CalledProcessError):
            err = (e.stderr or b"").decode(errors="replace").strip().splitlines()
            out.note(f"STOPPED: spacetime CLI failed: {err[0] if err else e}")
        else:
            out.note(f"STOPPED: market not reachable at {os.environ.get('SPACETIMEDB_HTTP', 'http://127.0.0.1:3000')} "
                     f"({type(e).__name__}). Start it with `python3 scripts/launch.py up` or check SPACETIMEDB_HTTP.")
        return 1


def live_approver_for(args, run: dict, mandate: dict, out) -> tuple[Callable[[Step], dict], str]:
    """The --live-call gate for this run, plus one console line saying where the call would go. A missing or bad Cartesia
    setup is not a crash: the gate denies at the approval beat (nothing is dialled, nothing is paid)."""
    from pay import voice_cartesia as vc
    b2 = run["beats"]["2"]
    bid, win = b2["winner_bid"], b2["winner"]
    seller = next(x for x in b2["sellers"] if x["id"] == win["seller_id"])
    line = bid["lines"][0]
    reason = b2["veto_reason"] or {"rule_id": "advocate.ok", "summary": "No problems found in the checks", "source_url": line["listing_url"]}
    facts = {"item": line.get("attrs", {}).get("chipset") or line["sku_spec"].upper(), "condition": win["condition"], "seller": seller["name"]}
    env = vc.load_env(args.env_file or vc.DEFAULT_ENV_FILE)
    buyer_name = env.get(vc.NAME_ENV) or vc.DEFAULT_BUYER_NAME

    def show(code: str) -> None:
        out.note(f"SCREEN CODE: {code}   (the approval notification text; /buyer cannot show it yet, see NOT BRIDGED. Say it, then say approve)")

    try:
        client = vc.CartesiaClient.from_env(env)
        where = f"live call: ONE call to {vc.mask_number(client.approval_call_to)} at the approval beat (Cartesia configured)"
        unconfigured = None
    except vc.CartesiaError as e:
        client, unconfigured = None, str(e)
        where = f"live call: Cartesia NOT configured ({unconfigured}; names {', '.join(vc.ENV_NAMES[:3])}), so the approval beat will be DENIED and nothing is paid"
    return make_live_approver(mandate, reason, client, unconfigured=unconfigured, buyer_name=buyer_name, deal=facts,
                              on_code=show, secret=env.get(vc.SECRET_ENV)), where


def _run_live(args, steps, run, out, say, approver=None) -> int:
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    from stdb import Market   # the market's own bridge; reads SPACETIMEDB_HTTP and SPACETIMEDB_DB
    tokens = find_tokens_dir(args.tokens_dir)
    out.note(f"tokens: {tokens}")
    seller_tokens = ROOT / ".tokens"
    seller_tokens.mkdir(exist_ok=True)
    clients: dict[str, Any] = {"buyer": Market(token_file=str(tokens / BUYER_TOKEN)),
                               "referee": Market(token_file=str(tokens / REFEREE_TOKEN))}
    seller_ids = sorted({s.actor.split(":", 1)[1] for s in steps if s.actor.startswith("seller:")})
    for sid in seller_ids:
        clients[f"seller:{sid}"] = Market(token_file=str(seller_tokens / f"bridge-{sid}.json"))
    if not args.no_assign_roles:
        spacetime = shutil.which("spacetime") or str(Path.home() / ".local" / "bin" / "spacetime")
        from stdb import DB
        assign_seller_roles(seller_ids, clients, spacetime, args.server, DB)
    if args.reset:
        out.note("reset_demo (referee): clearing the demo tables")
        clients["referee"].call("reset_demo")
        time.sleep(1)
    try:
        execute(steps, clients, delay=args.step_delay, say=say, approver=approver, note=out.note)
    except RuntimeError as e:
        out.blank()
        out.note(f"STOPPED by the market: {e}")
        if "already exists" in str(e):
            out.note("hint: this need or round is already in the database; run again with --reset")
        return 1
    out.blank()
    try:
        rows = clients["referee"].sql("SELECT * FROM round_result")
        for line in compare_to_db(rows, run):
            out.note(line)
    except Exception as e:  # reading back is a courtesy; the run itself succeeded
        out.note(f"could not read round_result back ({type(e).__name__})")
    out.blank()
    for g in NOT_BRIDGED:
        out.note("NOT BRIDGED: " + g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
