#!/usr/bin/env python3
"""Screen bridge: play the demo beats (real lane code, demo/run_demo.py) into the running SpacetimeDB market,
step by step, so /buyer and /market on the web app show Vidyut's round live.

    python3 demo/bridge.py                       # one run, 2 s between steps, against the local market
    python3 demo/bridge.py --step-delay 3 --reset  # slower, and wipe the demo tables first (reset_demo)
    python3 demo/bridge.py --dry-run             # print the reducer calls, touch nothing
    python3 demo/bridge.py --live-call           # beat 4 places one real approval phone call; pays only if it approves
    python3 demo/bridge.py --two-buyers          # then a second buyer (buyer-2, SIM) goes for the same single units: sold out to an earlier round

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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.common import MIRROR, SIM, Narrator, money  # noqa: E402

DB_BUYER_ID = "vidyut"          # the id /buyer pairs with (web DEMO_BUYER) and the only one with a pairing code
SECOND_BUYER_ID = "buyer-2"     # --two-buyers: a SIM buyer after the same single units (it has no screen and no pairing code)
SECOND_ACTOR = "buyer2"
BUYER_TOKEN, REFEREE_TOKEN = "buyer-vidyut.json", "referee.json"
MANDATE_MINUTES = 10           # the market keeps the mandate as long as pay.mandate does (10 minute quote TTL)
MIN_WINDOW_S = 6
MIN_BID_WINDOW_S = 15          # --bid-window floor: 9 s for the steps, 6 s of margin before the close (snipe window is 3 s)
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
                claims: dict, cards: list[dict], delay: float, pace: float, window_s: Optional[int] = None) -> list[Step]:
    """open_round, every seller's floor and sealed bid in arrival order, then the Shield, claim-check and advocate results.
    A bid carries ALL its condition lines (alternatives for one SKU); the market picks the cheapest allowed one.
    `window_s` (stage pacing, #183) sets the sealed window; the steps inside the round are paced faster so every bid and
    check still lands at least 6 s before the deadline. Only the timing changes, never what the referee decides."""
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
    open_pace = pace
    if window_s is not None and window_s < window:
        window = max(MIN_BID_WINDOW_S, int(window_s))
        inside = (paused + pace) * delay                  # the opener's own pause runs inside the window too
        scale = min(1.0, (window - 6) / inside) if inside > 0 else 1.0
        for s in (*seller_steps, *check_steps):
            s.pace *= scale
        open_pace = pace * scale
    opener = Step("referee", "open_round", {"round_id": round_id, "need_id": need_id, "window_s": window}, window_s=window,
                  tag=SIM, pause=True, pace=open_pace, say=f"round {round_no} opens sealed for {window} s")
    closer = Step("referee", "close_round", {"round_id": round_id}, close=True, tag=SIM, pause=True, pace=pace,
                  say=f"round {round_no} closes at its deadline: the market ranks and reveals every bid")
    return [opener, *seller_steps, *check_steps, closer]


def plan(run: dict, *, delay: float = 2.0, buyer_id: str = DB_BUYER_ID, rounds: int = 1,
         mandate: Optional[dict] = None, live_call: bool = False, two_buyers: bool = False,
         bid_window: Optional[int] = None) -> list[Step]:
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
                         claims=b2["claims"], cards=b2["cards"], delay=delay, pace=1.0, window_s=bid_window)

    # beat 3: Shield blocks Shady Sam's injected re-post (after the close, as in the demo; Sam is already out on his claims)
    inj = b["3"]["injected"]
    sam = next(x for x in b2["bids"] if x["seller_id"] == inj["seller_id"])
    steps.append(Step("referee", "attach_verdict",
                      {"bid_id": bid_id(sam, 1), "verdict": inj["verdict"], "rule_ids": list(inj["rule_ids"]), "origin": SIM},
                      pause=True, say=f"Bazaar Shield BLOCKS {sam['persona']}'s injected listing re-post "
                                      f"({len(inj['rule_ids'])} rules, {inj['latency_ms']} ms)"))

    # beat 4: mandate, approval, payment (the deal is above the allowance set in beat 1, so it needs the call)
    m, win = (mandate if mandate is not None else b["4"]["mandate"]), b2["winner"]
    wbid = next(x for x in b2["bids"] if x["id"] == win["bid_id"])
    steps.append(Step("referee", "create_mandate",
                      {"hash": m["hash"], "id": m["id"], "deal_id": m["deal_id"], "buyer_id": buyer_id, "amount": m["amount"],
                       "payee": m["payee"], "expiry_minutes": MANDATE_MINUTES, "nonce": m["nonce"], "requested_by": "",
                       "origin": m["origin"]},
                      tag=m["origin"], pause=True, gate="build_mandate",
                      say=f"mandate for the market's #1, made when beat 4 starts (the demo expects {wbid['persona']}, "
                          f"{money(m['amount'])} to {m['payee']}, a SIM test address)"))
    # Only a real call is a voice approval. The scripted story is method sim_script, and its payment is always the SIM stub,
    # even if the run's own beat 4 made a Stripe test charge (#193). With --live-call, execute's charger replaces the stub.
    steps.append(Step("referee", "record_approval",
                      {"mandate_hash": m["hash"], "method": "voice_code" if live_call else "sim_script", "approved_by": buyer_id},
                      pause=True, gate="approval_call",
                      say=("a real phone call: the buyer says the code from the screen and 'approve'; the referee relays the verified code"
                           if live_call else
                           "SIM scripted approval, no phone call: the runner types the three tries (wrong code, no 'approve', then right)")))
    ref = "ch_sim_" + m["hash"][:12]
    pay = {"mandate_hash": m["hash"], "payment_ref": ref, "amount": m["amount"], "mode": "sim"}
    steps.append(Step("referee", "record_payment", dict(pay), pause=True, tag=SIM,
                      say=f"payment recorded: {ref} (SIM stub, no money moved)"))
    steps.append(Step("referee", "record_payment", dict(pay),
                      pause=True, say="the same payment again: the market's own idempotency refuses it and shows the refusal"))

    # beat 5: round 2 with the learning seller's lowered price (loss reports have no reducer: NOT BRIDGED)
    if rounds >= 2:
        r2 = b["5"]["round2"]
        steps += round_steps(round_no=2, need_id=need["id"], bids=r2["bids"], ranking=r2["ranking"], sellers=sellers,
                             shield=b2["shield"], claims=b2["claims"], cards=r2["cards"], delay=delay, pace=0.5, window_s=bid_window)
    if two_buyers:
        steps += second_buyer_steps(goal, need, b2, delay=delay, round_no=3 if rounds >= 2 else 2, bid_window=bid_window)
    return steps


def second_buyer_steps(goal: dict, need: dict, b2: dict, *, delay: float, round_no: int, bid_window: Optional[int] = None) -> list[Step]:
    """--two-buyers (SIM): after Vidyut's deal, buyer-2 sets the same goal and the same sealed round runs again with the same sellers.
    Every seller states one unit, so the unit Vidyut's round won is held or sold: that line is skipped with the market's own reason
    'sold out to an earlier round' and the next best bid wins. Nothing here fakes the result; the market decides at the close."""
    g_id, n_id = f"{goal['id']}-{SECOND_BUYER_ID}", f"{need['id']}-{SECOND_BUYER_ID}"
    items = [{"sku_spec": i["sku_spec"], "condition": " or ".join(goal["items"][0].get("allowed_conditions") or [goal["items"][0]["condition"]])
              if i["part"] == "gpu" else i["condition"],
              "variant": i["variant"], "quantity": i["quantity"], "skipped_owned_part_id": ""} for i in goal["items"]]
    n = need["items"][0]
    sellers = {s["id"]: s for s in b2["sellers"]}
    steps = [
        Step(SECOND_ACTOR, "post_goal",
             {"id": g_id, "buyer_id": SECOND_BUYER_ID, "type": goal["type"], "cap": goal["cap"], "deadline": goal["deadline"],
              "po_number": "", "origin": SIM, "items": items},
             pause=True, say=f"a second buyer ({SECOND_BUYER_ID}, SIM) sets the same goal: one unit of the same part"),
        Step(SECOND_ACTOR, "post_need",
             {"id": n_id, "buyer_id": SECOND_BUYER_ID, "goal_id": g_id, "delivery_window": need["delivery_window"],
              "spend_limit": need["spend_limit"], "consent": need["consent"], "auction_window_s": need["auction_window_s"], "origin": SIM,
              "items": [{"sku_spec": n["sku_spec"], "condition": n["condition"], "allowed_conditions": list(n.get("allowed_conditions") or []),
                         "variant": n["variant"], "quantity": n["quantity"], "unit": n["unit"]}]},
             pause=True, say="the second need goes to the same sellers, who each have one unit"),
    ]
    steps += round_steps(round_no=round_no, need_id=n_id, bids=b2["bids"], ranking=b2["ranking"], sellers=sellers, shield=b2["shield"],
                         claims=b2["claims"], cards=b2["cards"], delay=delay, pace=0.5, window_s=bid_window)
    return steps


def second_buyer_report(rows: list, round_id: str) -> list[str]:
    """Console lines from the second buyer's round_result rows (id, round_id, bid_id, seller_id, persona, rank, landed, reasons, ...):
    who was skipped as sold out, and who won instead."""
    mine = [r for r in rows if r[1] == round_id]
    out = []
    for r in sorted(mine, key=lambda r: r[4]):
        reasons = r[7] if len(r) > 7 and isinstance(r[7], list) else []
        if any("sold out to an earlier round" in x for x in reasons):
            out.append(f"{SECOND_BUYER_ID}'s round: {r[4]} is out: sold out to an earlier round")
    ranked = sorted((r for r in mine if r[5]), key=lambda r: r[5])
    out.append(f"{SECOND_BUYER_ID}'s round winner: {ranked[0][4]} {money(ranked[0][6])}" if ranked else f"{SECOND_BUYER_ID}'s round: no bid was ranked")
    return out


# What the market cannot take today (printed at the end of every run; mirrored in demo/README.md for Lane B).
NOT_BRIDGED = [
    "loss reports (contracts/LossReport): no table or reducer, so beat 5 (reports, the learner's price step) is console only; `--rounds 2` replays round 2 and the learner's lower open-box price now ranks, but the loss report itself is not on screen.",
    "goal state (HUNTING, HOLD_FOR_CALL, DONE): no set_goal_state reducer; the goal stays ACTIVE and reserved_amount stays 0.",
    "denied approval attempts (wrong code, no 'approve'): record_approval only logs a second approval; the denied tries are console only.",
    "buyer name and seller personas: /buyer is hardcoded to the id vidyut and prints 'Buyer: Vidyut'; persona rows come only "
    "from seed_demo (Seller A to C), so the 3D floor has no personas for the demo sellers.",
    "seller floors per condition: the market keeps one floor per SKU, so a seller with several condition lines gets its lowest floor "
    "(issue #18 asks for a floor per seller, SKU and condition).",
]


# ---------------------------------------------------------------- the live part

def execute(steps: list[Step], clients: dict, *, delay: float, say: Callable[[Step], None],
            sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
            approver: Optional[Callable[[Step], dict]] = None, note: Callable[[str], None] = lambda text: None,
            charger: Optional[Callable[[Step], dict]] = None, deal_gate: Optional["DealGate"] = None) -> list[dict]:
    """Run the steps in order. A reducer refusal stops the run with the market's own message.
    With an `approver`, the approval step runs only after it returns approved; a denial skips the approval and every payment
    step and ends the run there (the mandate stays pending, nothing is charged). Returns the approval outcomes.
    A `charger` (make_charger) runs once, at the first payment step, and only after the approver said approved AND the market
    recorded the approval; its payment ref and mode replace the SIM stub's. Without an approver it never runs.
    A `deal_gate` (DealGate) builds beat 4's mandate when its create_mandate step comes up, from the market's own rank 1, and every
    money step that follows uses that mandate. No readable rank 1 ends the run there: no mandate, no approval, no payment."""
    deadline: Optional[float] = None
    outcomes: list[dict] = []
    mandate_hash = ""
    approved_and_recorded, paid = False, None
    lag = 0.0   # seconds the reducer calls took since the last pause: the next pause is shortened by it (#183)
    for s in steps:
        if s.gate == "build_mandate" and deal_gate is not None and "referee" in clients:
            try:
                deal_gate.prepare(clients["referee"])
            except (GateRefused, RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
                why = "crs_gate" if isinstance(e, CrsRefused) else "no_market_winner"
                outcomes.append({"step": "build_mandate", "approved": False, "reason": f"{why}: {e}", "call_id": None})
                note(f"beat 4 STOPPED: no mandate was made ({e}). No approval and no payment are recorded; nothing was paid")
                break
            note(deal_gate.crs_note())
        if deal_gate is not None and deal_gate.mandate is not None:
            s = deal_gate.bind(s)
        if s.reducer == "record_payment" and charger is not None and approver is not None and approved_and_recorded:
            first = paid is None
            if first:
                paid = charger(s)
                if paid.get("note"):
                    note(paid["note"])
            s = replace(s, args={**s.args, **paid["args"]}, tag=paid["tag"], say=paid["say"] if first else s.say)
        say(s)
        if s.reducer == "create_mandate" and s.actor in clients:
            mandate_hash = s.args.get("hash", "")
        if s.gate == "approval_call" and approver is not None:
            outcome = approver(s)
            outcomes.append(outcome)
            if not outcome["approved"]:
                from pay.voice_cartesia import denial_line
                line = denial_line(outcome["reason"])
                note(f"live call DENIED ({outcome['reason']}): {line} No approval and no payment are recorded; the mandate stays pending")
                if mandate_hash and "referee" in clients:
                    try:   # /buyer shows "Approval denied: <line>"; the held unit goes back on sale at once
                        clients["referee"].call("deny_approval", mandate_hash=mandate_hash, reason=line.rstrip("."))
                        note("deny_approval recorded: the unit held for this deal is released")
                    except RuntimeError as e:
                        note(f"deny_approval not recorded ({e}); the hold expires by itself after 2 minutes")
                break
            note(f"live call APPROVED (call {outcome['call_id']}): the referee records the approval, then the payment")
        client = clients[s.actor]
        t_call = clock()
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
        if s.gate == "approval_call" and approver is not None:
            approved_and_recorded = True    # the approver said approved and the market took the approval row
        lag += clock() - t_call
        if s.window_s:
            deadline = clock() + s.window_s
            lag = 0.0
        if s.close:
            lag = 0.0          # the close waited for the deadline; pacing starts over
        if s.pause and delay > 0:
            want = delay * s.pace - lag
            if want > 0:
                sleep(want)
            lag = max(0.0, -want)
    return outcomes


MARKET_MODULE = ROOT / "market" / "spacetimedb" / "src" / "index.ts"


def market_has_typed_approval(module: Path = MARKET_MODULE) -> bool:
    """True while the market module still exports approve_typed (a typed-code approval, issue #191 item 2), or when that
    cannot be read. The code then stays off /buyer: on /buyer it would arm typed approval, which the phone-only rule forbids."""
    try:
        return "approve_typed" in module.read_text(encoding="utf-8")
    except OSError:
        return True


def default_crs_check(payee: str) -> dict:
    """#257: agents/crs.py check_payee for the winning payee (one request per payee, cached for its TTL). A payee with no
    business CRS profile is a SIM seller and makes no request; CRS keys come from the environment and are never printed."""
    import asyncio
    import importlib.util
    from datetime import datetime, timezone
    mod = sys.modules.get("lane_d_crs")
    if mod is None:
        spec = importlib.util.spec_from_file_location("lane_d_crs", ROOT / "agents" / "crs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules["lane_d_crs"] = mod
    return asyncio.run(mod.check_payee(payee, datetime.now(timezone.utc)))


class GateRefused(RuntimeError):
    """Beat 4 cannot name a deal from the market's own ranking, so no mandate is made."""


class CrsRefused(GateRefused):
    """#257: the payee's CRS check did not clear it; no mandate, no call, no charge."""


def market_winner(rows: list, round_id: str = "round-1") -> Optional[dict]:
    """The market's rank 1 in `round_id` from round_result rows (id, round_id, bid_id, seller_id, persona, rank, landed, ...)."""
    first = [r for r in rows if r[1] == round_id and r[5] == 1]
    if len(first) != 1:
        return None
    r = first[0]
    return {"bid_id": r[2], "seller_id": r[3], "persona": r[4], "landed": float(r[6])}


class DealGate:
    """Beat 4's deal comes from the market, not from the demo's own ranking (#194). When the create_mandate step comes up the
    referee reads round_result, takes rank 1, and a fresh pending mandate (10 minute TTL) is made for exactly that bid's deal,
    landed amount and seller's payee. After the call, `expect_now` reads the market again, so can_charge compares the mandate
    with the market's rank 1, never with itself. `show_code` puts the call's code on /buyer through issue_approval_code."""

    def __init__(self, run: dict, round_id: str = "round-1"):
        b1, b2 = run["beats"]["1"], run["beats"]["2"]
        self.goal, self.round_id = b1["goal"], round_id
        self.sellers = {x["id"]: x for x in b2["sellers"]}
        self.bids = {x["id"]: x for x in b2["bids"]}
        self.cards = {c["bid_id"]: c for c in b2["cards"]}
        self.lines = {e["seller_id"]: e.get("line", 0) for e in [*b2["ranking"]["ranked"], *b2["ranking"]["disqualified"]]}
        self.demo_winner, self.veto_reason = b2["winner"], b2["veto_reason"]
        self.mandate: Optional[dict] = None
        self.winner: Optional[dict] = None
        self._referee: Any = None
        self.typed_approval_present: Callable[[], bool] = market_has_typed_approval
        self.crs_check: Callable[[str], dict] = default_crs_check   # #257: the payee's CRS check, injectable in tests
        self.crs: Optional[dict] = None

    def expectations(self, rows: list) -> dict:
        w = market_winner(rows, self.round_id)
        if w is None:
            raise GateRefused(f"the market has no single rank 1 in {self.round_id}")
        seller, bid = self.sellers.get(w["seller_id"]), self.bids.get(w["bid_id"])
        if seller is None or bid is None or bid["seller_id"] != w["seller_id"]:
            raise GateRefused(f"the market's rank 1 ({w['persona'] or w['seller_id']}) is not a bid this run placed, so there is no payee")
        if not (math.isfinite(w["landed"]) and w["landed"] > 0):
            raise GateRefused("the market's rank 1 has no usable landed price")
        return {**w, "deal_id": f"deal-{w['bid_id']}", "amount": round(w["landed"], 2), "payee": seller["payee"], "origin": bid["origin"]}

    def prepare(self, referee: Any) -> dict:
        from pay.crs_gate import check_id, payee_ok
        from pay.mandate import new_mandate
        self._referee = referee
        w = self.expectations(referee.sql("SELECT * FROM round_result"))
        self.winner = w
        # #257: one CRS check of the payee before the call and the charge. A business payee needs a verified check,
        # bound into the mandate; an error, a timeout, "not configured" or a failed check holds the payee gate.
        try:
            self.crs = self.crs_check(w["seller_id"])   # CRS profiles are keyed by the seller being paid
            business = bool(self.crs["business"])
            verdict = payee_ok(self.crs.get("check"), business=business, seller_id=w["seller_id"])
        except Exception as e:  # noqa: BLE001  (an unreadable profile file, a timeout, an odd answer: all hold the gate)
            raise CrsRefused(f"CRS check failed ({type(e).__name__}: {str(e)[:80]}), so the payee gate holds") from None
        if not verdict:
            raise CrsRefused(f"CRS: {verdict.detail} ({verdict.reason}), so the payee gate holds")
        self.mandate = new_mandate(deal_id=w["deal_id"], buyer_id=self.goal["buyer_id"], amount=w["amount"], payee=w["payee"],
                                   goal_id=self.goal["id"], within_allowance=False, origin=w["origin"],
                                   crs_check_id=check_id(self.crs["check"]) if business else None)
        return self.mandate

    def crs_note(self) -> str:
        """The console line for the CRS result (#257)."""
        if self.crs is None or self.winner is None:
            return "CRS: no check was made"
        seller = self.winner["persona"] or self.winner["seller_id"]
        if not self.crs.get("business"):
            return f"CRS: {seller} is a SIM seller (no business CRS profile), so its identity was not checked"
        c = self.crs["check"]
        cached = ", reused from the last 10 minutes" if self.crs.get("cached") else ""
        return (f"CRS: {seller} identity verified ({c['origin'].lower()}{cached}), check {self.mandate['crs_check_id']} "
                f"bound into the mandate")

    def expect_now(self) -> dict:
        """The market's rank 1 read again (after the call): what the charge must match."""
        if self._referee is None:
            raise GateRefused("the market was never read")
        return self.expectations(self._referee.sql("SELECT * FROM round_result"))

    def bind(self, s: Step) -> Step:
        """The beat 4 step with this gate's mandate in place of the planned one."""
        m, w = self.mandate, self.winner
        if s.reducer == "create_mandate":
            return replace(s, args={**s.args, "hash": m["hash"], "id": m["id"], "deal_id": m["deal_id"], "amount": m["amount"],
                                    "payee": m["payee"], "nonce": m["nonce"], "origin": m["origin"], "expiry_minutes": MANDATE_MINUTES},
                           tag=m["origin"], say=f"mandate for the market's #1, {w['persona']}: {money(m['amount'])} to {m['payee']} "
                                                f"(a SIM test address), {MANDATE_MINUTES} minutes")
        if s.reducer == "record_approval":
            return replace(s, args={**s.args, "mandate_hash": m["hash"]})
        if s.reducer == "record_payment":
            ref = s.args["payment_ref"] if not s.args["payment_ref"].startswith("ch_sim_") else "ch_sim_" + m["hash"][:12]
            return replace(s, args={**s.args, "mandate_hash": m["hash"], "amount": m["amount"], "payment_ref": ref},
                           say=s.say.replace(s.args["payment_ref"], ref))
        return s

    def reason(self) -> dict:
        """The why-answer for the call: the veto that beat the cheaper bid when the market agrees with the demo, else that bid's own card."""
        w = self.winner
        if w["seller_id"] == self.demo_winner["seller_id"] and self.veto_reason:
            return self.veto_reason
        card = self.cards.get(w["bid_id"])
        bid = self.bids[w["bid_id"]]
        return card["call_reason"] if card else {"rule_id": "advocate.ok", "summary": "No problems found in the checks",
                                                 "source_url": bid["lines"][0]["listing_url"]}

    def facts(self) -> dict:
        w = self.winner
        bid, seller = self.bids[w["bid_id"]], self.sellers[w["seller_id"]]
        line = bid["lines"][min(self.lines.get(w["seller_id"], 0), len(bid["lines"]) - 1)]
        crs = "verified" if self.crs and self.crs.get("business") else "sim_seller"
        return {"item": line.get("attrs", {}).get("chipset") or line["sku_spec"].upper(), "condition": line["offered_condition"],
                "seller": seller["name"], "crs": crs}

    def show_code(self, code: str) -> Optional[str]:
        """issue_approval_code for this mandate: the code shows on the buyer's own /buyer screen. None when it did, else why not."""
        if self._referee is None or self.mandate is None:
            return "no mandate on the market"
        if self.typed_approval_present():
            return "the market still has approve_typed (typed-code approval, #191), so the code is kept off /buyer"
        try:
            self._referee.call("issue_approval_code", mandate_hash=self.mandate["hash"], code=code)
            return None
        except (RuntimeError, OSError) as e:
            return f"issue_approval_code refused ({str(e)[:120]})"


def make_live_approver(gate: DealGate, client: Any, *, unconfigured: Optional[str] = None, buyer_name: str = "Vidyut",
                       on_code: Callable[[str, Optional[str]], None] = lambda code, why_not_on_screen: None,
                       secret: Optional[str] = None, **timing) -> Callable[[Step], dict]:
    """The approval gate for --live-call: one real approval call for the gate's mandate (pay.voice_cartesia.run_approval_call).
    The code goes to /buyer (gate.show_code), and `on_code(code, why_not)` hears whether it got there; the call judges that same
    code. Default deny: no mandate, no client (not configured), a failed dial, silence, a wrong code, an expired mandate, an
    unreadable market after the call, or a pay.mandate.can_charge refusal against the market's rank 1 all deny."""
    import secrets as _secrets
    from pay.approval import ApprovalService
    from pay.mandate import can_charge
    from pay.replay import NonceStore
    from pay.voice_cartesia import CALL_CODE_TTL_S, run_approval_call

    def outcome(approved: bool, reason: Optional[str], call_id: Optional[str] = None) -> dict:
        return {"step": "approval_call", "approved": approved, "reason": reason, "call_id": call_id}

    def to_screen(code: str) -> None:
        on_code(code, gate.show_code(code))

    def approve(step: Step) -> dict:
        mandate = gate.mandate
        if mandate is None:
            return outcome(False, "no_mandate: the market's rank 1 was not read")
        if client is None:
            return outcome(False, f"not_configured: {unconfigured or 'no Cartesia client'}")
        store = NonceStore()
        service = ApprovalService(secret=secret or _secrets.token_hex(16), store=store, code_ttl_seconds=CALL_CODE_TTL_S)
        res = run_approval_call(mandate, gate.reason(), client, service, deal=gate.facts(), buyer_name=buyer_name, on_code=to_screen,
                                **timing)
        if not res.approved:
            return outcome(False, res.reason or "denied", res.call_id)
        try:
            expect = gate.expect_now()
        except (GateRefused, RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
            return outcome(False, f"market_unreadable: {e}", res.call_id)
        guard = can_charge(mandate, deal_id=expect["deal_id"], amount=expect["amount"], payee=expect["payee"], store=store)
        if not guard:
            return outcome(False, f"can_charge: {guard.reason}", res.call_id)
        if gate.crs is not None:   # #257: the payee's CRS check is still the one bound into the mandate
            from pay.crs_gate import bound_ok
            crs_ok = bound_ok(mandate, gate.crs.get("check"), business=bool(gate.crs.get("business")), seller_id=expect["seller_id"])
            if not crs_ok:
                return outcome(False, f"crs: {crs_ok.reason}", res.call_id)
        return outcome(True, None, res.call_id)

    return approve


def make_charger(gate: DealGate, env: Any, *, use_stripe: bool, stripe_test: Optional[Callable] = None) -> Callable[[Step], dict]:
    """The --live-call --stripe payment: one Stripe TEST PaymentIntent for the mandate the call approved (sk_test_ key only),
    else the SIM stub with a note saying why. execute() calls it only behind the approval gate; it never runs before a call."""
    from demo.approval_flow import charge_or_stub

    def charge(step: Optional[Step]) -> dict:
        ch, why = charge_or_stub(gate.mandate, env, use_stripe, stripe_test)
        live = ch["mode"] == "Stripe test mode"
        return {"args": {"payment_ref": ch["id"], "mode": "stripe_test" if live else "sim"}, "tag": "LIVE" if live else SIM,
                "say": f"payment recorded: {ch['id']} ({ch['mode']}" + (", no money moved)" if not live else ", Visa test card, no real money)"),
                "note": why}

    return charge


def bid_window_arg(text: str) -> int:
    """argparse type for --bid-window: whole seconds, at least MIN_BID_WINDOW_S."""
    try:
        v = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be whole seconds") from None
    if v < MIN_BID_WINDOW_S:
        raise argparse.ArgumentTypeError(f"must be at least {MIN_BID_WINDOW_S} s")
    return v


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
                   f"Beat 4 follows the market: its mandate is for the market's #1.")
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


def assign_buyer_role(buyer_id: str, client: Any, spacetime: str, server: str, db: str) -> None:
    """Owner step for --two-buyers: the SIM second buyer's own identity gets the buyer role for its own id only."""
    subprocess.run([spacetime, "call", "-s", server, db, "assign_role", f'"0x{client.identity}"', '"buyer"', f'"{buyer_id}"'],
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
    ap.add_argument("--stripe", action="store_true",
                    help="with --live-call only: ONE Stripe TEST charge (sk_test_ key only) after the call approves")
    ap.add_argument("--live-call", action="store_true",
                    help="beat 4 places ONE real Cartesia phone call to APPROVAL_CALL_TO; approval and payment are recorded only if the call approves")
    ap.add_argument("--env-file", type=Path, default=None,
                    help="where the CARTESIA_* names are read from for --live-call (default: pay.voice_cartesia.DEFAULT_ENV_FILE)")
    ap.add_argument("--two-buyers", action="store_true",
                    help=f"after the run, a second SIM buyer ({SECOND_BUYER_ID}) goes for the same single units: its round skips a unit an earlier round won")
    ap.add_argument("--tokens-dir", help="folder with referee.json and buyer-vidyut.json (default: auto-detect)")
    ap.add_argument("--buyer-id", default=DB_BUYER_ID, help="DB buyer id (default vidyut, the id /buyer pairs with)")
    ap.add_argument("--no-assign-roles", action="store_true", help="skip the owner assign_role step for seller identities")
    ap.add_argument("--server", default=os.environ.get("SPACETIMEDB_SERVER", "local"))
    ap.add_argument("--bid-window", type=bid_window_arg, default=None,
                    help=f"seconds each sealed round stays open (at least {MIN_BID_WINDOW_S}); steps inside run faster to fit")
    args = ap.parse_args(argv)
    if args.stripe and not args.live_call:
        ap.error("--stripe needs --live-call: a Stripe test charge runs only after a real phone call approves (the scripted approval is SIM)")

    from demo.run_demo import run_all, stripe_env, DEFAULT_ENV_FILE
    run = run_all(say=Narrator(False))       # never a Stripe call here: this run builds the plan, before any round or call
    gate = DealGate(run)                     # beat 4's mandate is made from the market's rank 1 when beat 4 starts
    steps = plan(run, delay=args.step_delay, buyer_id=args.buyer_id, rounds=args.rounds, live_call=args.live_call,
                 two_buyers=args.two_buyers, bid_window=args.bid_window)
    out = Narrator(True)
    out.note("Tech Bazaar screen bridge: demo beats (real lane code) -> existing SpacetimeDB reducers")
    out.note(f"{len(steps)} reducer calls, {args.step_delay} s between visible steps. Open /buyer (pair as {args.buyer_id}) and /market.")
    out.note("Buyer: Vidyut. The goal, owned parts and payment are simulated. Tags: [MIRROR] real dated listing, [SIM] generated by us.")

    def say(s: Step) -> None:
        who = "buyer" if s.actor == "buyer" else "referee" if s.actor == "referee" else s.actor.replace("seller:", "seller ")
        if s.reducer == "set_floor":
            return
        out.line(s.tag if s.tag in LIVE_TAGS else SIM, f"{who:<26}{s.reducer:<22}{s.say}")

    approver, client_note, charger = None, "", None
    if args.live_call:
        approver, client_note = live_approver_for(args, run, gate, out)
        out.note(client_note)
    if args.stripe:
        charger = make_charger(gate, {**os.environ, **stripe_env(DEFAULT_ENV_FILE)}, use_stripe=True)
        out.note("Stripe: ONE test-mode charge (sk_test_ key only) after the call approves and the market records the approval; "
                 "a denied, silent or failed call charges nothing")
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
        return _run_live(args, steps, run, out, say, approver, charger, gate)
    except (OSError, subprocess.CalledProcessError) as e:
        out.blank()
        if isinstance(e, subprocess.CalledProcessError):
            err = (e.stderr or b"").decode(errors="replace").strip().splitlines()
            out.note(f"STOPPED: spacetime CLI failed: {err[0] if err else e}")
        else:
            out.note(f"STOPPED: market not reachable at {os.environ.get('SPACETIMEDB_HTTP', 'http://127.0.0.1:3000')} "
                     f"({type(e).__name__}). Start it with `python3 scripts/launch.py up` or check SPACETIMEDB_HTTP.")
        return 1


def live_approver_for(args, run: dict, gate: DealGate, out) -> tuple[Callable[[Step], dict], str]:
    """The --live-call gate for this run, plus one console line saying where the call would go. A missing or bad Cartesia
    setup is not a crash: the gate denies at the approval beat (nothing is dialled, nothing is paid). The deal, the why-answer
    and the code's screen all come from `gate` when beat 4 starts."""
    from pay import voice_cartesia as vc
    env = vc.load_env(args.env_file or vc.DEFAULT_ENV_FILE)
    buyer_name = env.get(vc.NAME_ENV) or vc.DEFAULT_BUYER_NAME

    def show(code: str, why_not: Optional[str]) -> None:
        if why_not is None:
            out.note("approval code: on /buyer now (issue_approval_code); it is not printed here. The buyer reads it, then says approve")
        else:
            out.note(f"SCREEN CODE: {code}   (/buyer could not show it: {why_not}. Say it, then say approve)")

    try:
        client = vc.CartesiaClient.from_env(env)
        where = f"live call: ONE call to {vc.mask_number(client.approval_call_to)} at the approval beat (Cartesia configured)"
        unconfigured = None
    except vc.CartesiaError as e:
        client, unconfigured = None, str(e)
        where = f"live call: Cartesia NOT configured ({unconfigured}; names {', '.join(vc.ENV_NAMES[:3])}), so the approval beat will be DENIED and nothing is paid"
    return make_live_approver(gate, client, unconfigured=unconfigured, buyer_name=buyer_name, on_code=show,
                              secret=env.get(vc.SECRET_ENV)), where


def _run_live(args, steps, run, out, say, approver=None, charger=None, gate=None) -> int:
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
    if any(s.actor == SECOND_ACTOR for s in steps):
        clients[SECOND_ACTOR] = Market(token_file=str(seller_tokens / f"bridge-{SECOND_BUYER_ID}.json"))
    if not args.no_assign_roles:
        spacetime = shutil.which("spacetime") or str(Path.home() / ".local" / "bin" / "spacetime")
        from stdb import DB
        assign_seller_roles(seller_ids, clients, spacetime, args.server, DB)
        if SECOND_ACTOR in clients:
            assign_buyer_role(SECOND_BUYER_ID, clients[SECOND_ACTOR], spacetime, args.server, DB)
    if args.reset:
        out.note("reset_demo (referee): clearing the demo tables")
        clients["referee"].call("reset_demo")
        time.sleep(1)
    try:
        execute(steps, clients, delay=args.step_delay, say=say, approver=approver, note=out.note, charger=charger, deal_gate=gate)
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
        if args.two_buyers:
            second = next(s.args["round_id"] for s in steps if s.reducer == "open_round" and s.args["need_id"].endswith(SECOND_BUYER_ID))
            for line in second_buyer_report(rows, second):
                out.note(line)
    except Exception as e:  # reading back is a courtesy; the run itself succeeded
        out.note(f"could not read round_result back ({type(e).__name__})")
    out.blank()
    for g in NOT_BRIDGED:
        out.note("NOT BRIDGED: " + g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
