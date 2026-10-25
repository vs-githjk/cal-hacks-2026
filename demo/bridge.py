#!/usr/bin/env python3
"""Screen bridge: play the demo beats (real lane code, demo/run_demo.py) into the running SpacetimeDB market,
step by step, so /buyer and /market on the web app show Vidyut's round live.

    python3 demo/bridge.py                       # one run, 2 s between steps; ends at beat 4's approval gate (no scripted approval)
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

from demo.common import LIVE, MIRROR, SIM, Narrator, money, shield_mode_line  # noqa: E402

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
                claims: dict, cards: list[dict], delay: float, pace: float, window_s: Optional[int] = None,
                round_id: Optional[str] = None, label: str = "") -> list[Step]:
    """open_round, every seller's floor and sealed bid in arrival order, then the Shield, claim-check and advocate results.
    A bid carries ALL its condition lines (alternatives for one SKU); the market picks the cheapest allowed one.
    `window_s` (stage pacing, #183) sets the sealed window; the steps inside the round are paced faster so every bid and
    check still lands at least 6 s before the deadline. Only the timing changes, never what the referee decides.
    `round_id` and `label` (#345, one round per part of a build) name the round and its console lines; bid ids stay as `round_no` makes them."""
    round_id = round_id or f"round-{round_no}"
    label = label or f"round {round_no}"
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
                                say=f"Smell Test (real shield.screen) on {bid['persona']}: {v['verdict']}"))
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
                  tag=SIM, pause=True, pace=open_pace, say=f"{label} opens sealed for {window} s")
    closer = Step("referee", "close_round", {"round_id": round_id}, close=True, tag=SIM, pause=True, pace=pace,
                  say=f"{label} closes at its deadline: the market ranks and reveals every bid")
    return [opener, *seller_steps, *check_steps, closer]


BUYER_NAME = "Vidyut"
# #216: the names the Fetch tile shows for the demo's agents (#259); their lines in a stage run are the demo's, so SIM
AGENT_NAMES = {"buyer": "Tech Bazaar Buyer", "advocate": "Bazaar Advocate", "shield": "Bazaar Shield"}


def demo_agent_addresses() -> dict:
    """The agent1q addresses of the buyer, advocate and Shield agents, from agents/common (the same seeds the agents run
    with). {} when agents/ cannot be loaded (no uagents): the Fetch tile then gets no rows and the run says so."""
    # Loaded by path under its own name: a top-level "common" may already be demo/common.py when the stage runs as a
    # script, and agents/ on sys.path would shadow other top-level names. Its import reads agents/.env (setdefault only).
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("tech_bazaar_agents_common", ROOT / "agents" / "common.py")
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        return {role: common.address(role) for role in AGENT_NAMES}
    except Exception:  # noqa: BLE001
        return {}


def _event(role: str, addresses: dict, text: str, origin: str = SIM) -> Optional[Step]:
    """One line on the Fetch tile. SIM unless the caller read the value in this run (live_proof_steps): LIVE is never the default."""
    if role not in addresses:
        return None
    return Step("referee", "record_agent_event",
                {"agent_name": AGENT_NAMES[role], "address": addresses[role], "text": text, "ts": "", "origin": origin},
                say=f"{AGENT_NAMES[role]} ({origin} line on the Fetch tile): {text}", tag=origin)


_CRS_BANDS = {"CRS_IDENTITY_VERIFIED": "verified and stable", "CRS_STEP_UP_REQUIRED": "caution (step-up required)",
              "CRS_IDENTITY_NOT_VERIFIED": "not verified"}   # agents/crs.py REASON_CODES: the three answers a real sandbox response maps to


def live_proof_steps(addresses: dict, *, price: Optional[dict] = None, quoted: float = 0.0, tiger: Optional[dict] = None, round_id: str = "",
                     crs: Optional[dict] = None, seller: str = "") -> list[Step]:
    """The sponsor proof lines a run can really stand behind, as LIVE referee events on the buyer agent's tile. Each line needs a value this run
    fetched: a Bright Data price read (state ok, origin LIVE), a Tiger Data write that stored rows, a CRS sandbox band from a request made now
    (origin SANDBOX, not served from the cache, one of the three real bands). A result that is MIRROR, cached, simulated, empty, slow, not
    configured or an error posts nothing: there is no simulated proof line here and nothing is promoted to LIVE."""
    from demo import sponsors_live as S
    out: list[Optional[Step]] = []
    if price is not None and S.is_live(price):
        out.append(_event("buyer", addresses, "Bright Data re-check: " + S.price_note(price, quoted), LIVE))
    if tiger is not None and tiger.get("state") == "written" and int(tiger.get("n") or 0) > 0:
        out.append(_event("buyer", addresses, f"Tiger Data: stored {int(tiger['n'])} bid prices for {round_id or 'the round'}", LIVE))
    check = crs.get("check") if isinstance(crs, dict) else None
    if (isinstance(check, dict) and crs.get("business") and not crs.get("cached") and check.get("origin") == "SANDBOX"
            and len(check.get("reason_codes") or []) == 1 and check["reason_codes"][0] in _CRS_BANDS):
        out.append(_event("buyer", addresses, f"CRS sandbox: {seller or check.get('seller_id')} identity {_CRS_BANDS[check['reason_codes'][0]]}", LIVE))
    return [s for s in out if s is not None]


def post_proof_steps(referee: Any, steps: list[Step], note: Callable[[str], None]) -> int:
    """Send proof steps through the referee, best effort: a refusal is one note and never stops the run. Returns how many went in."""
    sent = 0
    for s in steps:
        try:
            referee.call(s.reducer, **s.args)
            sent += 1
        except (RuntimeError, OSError) as e:
            note(f"Fetch tile: a proof line was not posted ({type(e).__name__}); the run goes on")
    return sent


def plan(run: dict, *, delay: float = 2.0, buyer_id: str = DB_BUYER_ID, rounds: int = 1,
         mandate: Optional[dict] = None, live_call: bool = False, two_buyers: bool = False,
         bid_window: Optional[int] = None, agent_addresses: Optional[dict] = None) -> list[Step]:
    """Map a demo run (demo.run_demo.run_all) to reducer calls, in the order the stage story tells it.
    `mandate` (with `live_call`) replaces the run's beat-4 mandate with the pending one the real call will judge.
    `agent_addresses` ({role: agent1q...}) adds the Fetch tile lines; None or {} adds none."""
    addresses = agent_addresses or {}
    events: list[Optional[Step]] = []
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
    # #216: the name /buyer shows (SIM: the demo's buyer), and the buyer agent's line on the Fetch tile
    steps.append(Step("referee", "set_buyer_profile", {"buyer_id": buyer_id, "display_name": BUYER_NAME},
                      say=f"/buyer shows the buyer's name: {BUYER_NAME} (SIM)"))
    events.append(_event("buyer", addresses, f"Goal posted for {n['sku_spec']}; the need went to sellers, the cap stays sealed"))
    steps += [e for e in events if e]
    events.clear()

    # beat 2: the sealed round (Shield and claim checks attach before the close; the market ranks)
    steps += round_steps(round_no=1, need_id=need["id"], bids=b2["bids"], ranking=b2["ranking"], sellers=sellers, shield=b2["shield"],
                         claims=b2["claims"], cards=b2["cards"], delay=delay, pace=1.0, window_s=bid_window)

    vetoes = sum(1 for c in b2["cards"] if c.get("recommendation") == "veto")
    events.append(_event("advocate", addresses, f"Reviewed {len(b2['cards'])} bids: {vetoes} vetoed, each with a cited source"))
    steps += [e for e in events if e]
    events.clear()

    # beat 3: Shield blocks Shady Sam's injected re-post (after the close, as in the demo; Sam is already out on his claims)
    inj = b["3"]["injected"]
    sam = next(x for x in b2["bids"] if x["seller_id"] == inj["seller_id"])
    steps.append(Step("referee", "attach_verdict",
                      {"bid_id": bid_id(sam, 1), "verdict": inj["verdict"], "rule_ids": list(inj["rule_ids"]), "origin": SIM},
                      pause=True, say=f"Smell Test BLOCKS {sam['persona']}'s injected listing re-post "
                                      f"({len(inj['rule_ids'])} rules, {inj['latency_ms']} ms)"))
    events.append(_event("shield", addresses, f"Blocked {sam['persona']}'s injected listing re-post ({len(inj['rule_ids'])} rules)"))
    steps += [e for e in events if e]
    events.clear()

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
    # #251: only a real call is an approval; there is no scripted one. The step names the call's method, and execute runs it only
    # after the live approver says approved (it fills in the VoiceApproval id). Without --live-call execute stops at this gate.
    # The payment is the SIM stub unless --live-call --stripe's charger replaces it after an approved call (#193).
    steps.append(Step("referee", "record_approval",
                      {"mandate_hash": m["hash"], "method": "voice_code", "approved_by": buyer_id,
                       "voice_approval_id": "", "code": ""},   # #240: the call's VoiceApproval id; #449 item 3: the code the call checked. Both filled in by execute after an approved call
                      pause=True, gate="approval_call",
                      say=("a real phone call: the buyer says the code from the screen and 'approve'; the referee relays the verified code"
                           if live_call else
                           f"{NO_CALL_LINE}: the run stops at this gate, no approval and no payment are recorded")))
    ref = "ch_sim_" + m["hash"][:12]
    pay = {"mandate_hash": m["hash"], "payment_ref": ref, "amount": m["amount"], "mode": "sim"}
    steps.append(Step("referee", "record_payment", dict(pay), pause=True, tag=SIM,
                      say=f"payment recorded: {ref} (SIM stub, no money moved)"))
    steps.append(Step("referee", "record_payment", dict(pay),
                      pause=True, say="the same payment again: the market's own idempotency refuses it and shows the refusal"))

    # beat 5 (#216): round 1's loss reports (banded gap, reason, cited source; the learner's strategy step and line). The
    # reports come from the demo's own ranking, a SIM stand-in for the market's rules, so every row is SIM.
    b5 = b["5"]
    diff = [{"key": k, "from": str(v["from"]), "to": str(v["to"])} for k, v in ((b5.get("strategy") or {}).get("diff") or {}).items()]
    for lr in b5.get("round1_loss_reports") or []:
        learner = lr["seller_id"] == b5.get("learning_seller")
        steps.append(Step("referee", "record_loss_report",
                          {"id": lr["id"], "round_id": lr["round_id"], "seller_id": lr["seller_id"], "won": bool(lr["won"]),
                           "gap_band": lr["gap_band"], "reason": lr["reason"], "source_url": lr["source_url"],
                           "strategy_diff": diff if learner else [], "what_to_change": b5.get("what_to_change", "") if learner else "",
                           "what_to_change_origin": SIM if learner else "", "origin": SIM},
                          pause=learner, tag=SIM,
                          say=f"loss report for {sellers.get(lr['seller_id'], {}).get('name', lr['seller_id'])}: {lr['gap_band']}, "
                              f"{lr['reason']}" + (f"; what to change: {b5.get('what_to_change', '')}" if learner else "")))

    # beat 5: round 2 with the learning seller's lowered price
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


NO_CALL_LINE = "approval needs the real phone call (--live-call); nothing was paid"
NO_CALL_REASON = "no_live_call: " + NO_CALL_LINE

# What the market cannot take today (printed at the end of every run; mirrored in demo/README.md for Lane B).
NOT_BRIDGED = [
    "goal state (HUNTING, HOLD_FOR_CALL, DONE): no set_goal_state reducer; the goal stays ACTIVE and reserved_amount stays 0.",
    "denied approval attempts (wrong code, no 'approve'): record_approval only logs a second approval; the denied tries are console only.",
    "seller personas: persona rows come only from seed_demo (Seller A to C), so the 3D floor has no personas for the demo sellers.",
    "seller floors per condition: the market keeps one floor per SKU, so a seller with several condition lines gets its lowest floor "
    "(issue #18 asks for a floor per seller, SKU and condition).",
]


# ---------------------------------------------------------------- the live part

def execute(steps: list[Step], clients: dict, *, delay: float, say: Callable[[Step], None],
            sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
            approver: Optional[Callable[[Step], dict]] = None, note: Callable[[str], None] = lambda text: None,
            charger: Optional[Callable[[Step], dict]] = None, deal_gate: Optional["DealGate"] = None,
            before_round: Optional[Callable[[], None]] = None) -> list[dict]:
    """Run the steps in order. A `before_round` hook (the CRS relay, demo/crs_relay.py) runs right before each open_round and
    is best effort: whatever it raises is one note, and the round opens anyway. A reducer refusal stops the run with the market's own message.
    With an `approver`, the approval step runs only after it returns approved; a denial skips the approval and every payment
    step and ends the run there (the mandate stays pending, nothing is charged). Returns the approval outcomes.
    Without an `approver` there is no approval at all (#251: no scripted approval): the run ends at the approval gate with the
    outcome reason `no_live_call`, no record_approval and no payment, and the mandate's held unit is released.
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
            for line in deal_gate.drain_notes():
                note(line)
            post_proof_steps(clients["referee"], deal_gate.proof_steps(), note)   # a real Tiger write and a fresh CRS band, as LIVE tile lines
        if s.reducer in ("open_round", "open_knockout_round") and before_round is not None:
            try:
                before_round()
            except Exception as e:  # noqa: BLE001  (a relay problem never stops a round)
                note(f"CRS relay skipped ({type(e).__name__}); the round opens anyway")
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
        if s.gate == "approval_call":
            no_call = approver is None
            outcome = ({"step": "approval_call", "approved": False, "reason": NO_CALL_REASON, "call_id": None} if no_call
                       else approver(s))
            outcomes.append(outcome)
            for line in (deal_gate.drain_notes() if deal_gate is not None else []):
                note(line)
            if deal_gate is not None and "referee" in clients:
                post_proof_steps(clients["referee"], deal_gate.proof_steps(), note)   # the Bright Data re-check ran right before the call
            if not outcome["approved"]:
                from pay.voice_cartesia import denial_line
                line = denial_line(outcome["reason"])
                if no_call:
                    line = "Approval needs the real phone call."
                    note(f"beat 4 STOPPED at the approval gate: {NO_CALL_LINE}. No approval and no payment are recorded; the mandate stays pending")
                else:
                    note(f"live call DENIED ({outcome['reason']}): {line} No approval and no payment are recorded; the mandate stays pending")
                if mandate_hash and "referee" in clients:
                    try:   # /buyer shows "Approval denied: <line>"; the held unit goes back on sale at once
                        clients["referee"].call("deny_approval", mandate_hash=mandate_hash, reason=line.rstrip("."))
                        note("deny_approval recorded: the unit held for this deal is released")
                    except RuntimeError as e:
                        note(f"deny_approval not recorded ({e}); the hold expires by itself after 2 minutes")
                break
            note(f"live call APPROVED (call {outcome['call_id']}): the referee records the approval, then the payment")
            s = replace(s, args={**s.args, "voice_approval_id": outcome.get("voice_approval_id") or "", "code": outcome.get("code") or ""})
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
            try:
                client.call(s.reducer, **s.args)
            except RuntimeError:
                if s.reducer == "record_payment" and s.args.get("mode") == "stripe_test":   # #208
                    note(f"the market refused record_payment after Stripe test charge {s.args.get('payment_ref')}: "
                         "find it in the Stripe test dashboard (it is idempotent on the mandate hash)")
                raise
        if s.reducer == "record_loss_report" and deal_gate is not None:
            deal_gate.note_loss(s.args)     # #260: written to Tiger Data in one batch once the run's steps are done
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
    if deal_gate is not None:
        for line in deal_gate.flush_losses():     # #260: after the payment, so a slow or failed Tiger never touches the money path
            note(line)
    return outcomes


MARKET_MODULE = ROOT / "market" / "spacetimedb" / "src" / "index.ts"


def market_has_typed_approval(module: Path = MARKET_MODULE) -> bool:
    """True while the market module still exports approve_typed (a typed-code approval, issue #191 item 2), or when that
    cannot be read. The code then stays off /buyer: on /buyer it would arm typed approval, which the phone-only rule forbids."""
    try:
        return "approve_typed" in module.read_text(encoding="utf-8")
    except OSError:
        return True


def crs_module():
    """agents/crs.py, loaded once as lane_d_crs so every caller shares one sign-in state and one payee cache."""
    import importlib.util
    mod = sys.modules.get("lane_d_crs")
    if mod is None:
        spec = importlib.util.spec_from_file_location("lane_d_crs", ROOT / "agents" / "crs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules["lane_d_crs"] = mod
    return mod


def default_crs_check(payee: str) -> dict:
    """#257: agents/crs.py check_payee for the winning payee (one request per payee, cached for its TTL). A payee with no
    business CRS profile is a SIM seller and makes no request; CRS keys come from the environment and are never printed."""
    import asyncio
    from datetime import datetime, timezone
    return asyncio.run(crs_module().check_payee(payee, datetime.now(timezone.utc)))


class GateRefused(RuntimeError):
    """Beat 4 cannot name a deal from the market's own ranking, so no mandate is made."""


class CrsRefused(GateRefused):
    """#257: the payee's CRS check did not clear it; no mandate, no call, no charge."""


def market_winner(rows: list, round_id: str = "round-1") -> Optional[dict]:
    """The market's rank 1 in `round_id` from round_result rows (id, round_id, bid_id, seller_id, persona, rank, landed,
    reasons, lines, ...). `reasons` are the market's own reason strings for the row, [] when it has none (#251: the market writes
    'held back: advocate caution (...)' on rank 1 when every bid carries a caution). `lines` are the lines the market picked (#216),
    [] when the row has none."""
    first = [r for r in rows if r[1] == round_id and r[5] == 1]
    if len(first) != 1:
        return None
    r = first[0]
    reasons = [str(x) for x in r[7]] if len(r) > 7 and isinstance(r[7], (list, tuple)) else []
    lines = r[8] if len(r) > 8 and isinstance(r[8], list) else []
    return {"bid_id": r[2], "seller_id": r[3], "persona": r[4], "landed": float(r[6]), "lines": lines, "reasons": reasons}


def _picked(cell: Any) -> Optional[tuple]:
    """(offered_condition, unit_price) of one picked BidLine as SpacetimeDB returns it: a positional array
    [sku_spec, offered_spec, offered_condition, unit_price, quantity] or an object. None when unreadable."""
    try:
        if isinstance(cell, dict):
            cond = cell.get("offeredCondition", cell.get("offered_condition"))
            price = cell.get("unitPrice", cell.get("unit_price"))
        else:
            cond, price = cell[2], cell[3]
        if not isinstance(cond, str) or not cond:
            return None   # an empty condition means the need's; the demo's own line is the safe fallback
        return cond, float(price)
    except (TypeError, ValueError, IndexError, KeyError):
        return None


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
        # #269, set by main on --live-call: the Bright Data re-check before the call and the Tiger Data write of the round
        self.price_check: Optional[Callable[[dict], dict]] = None
        self.tiger_writer: Optional[Callable[[list], dict]] = None
        # #260: the loss reports the referee recorded, written to Tiger Data in one batch after the payment (never on the money path)
        self.tiger_loss_writer: Optional[Callable[[list], dict]] = None
        self._round_rows: list = []
        self._losses: list[dict] = []
        self.price: Optional[dict] = None
        self._notes: list[str] = []
        # the Fetch tile's agent addresses ({} = no proof lines) and what this run really fetched, for live_proof_steps
        self.addresses: dict = {}
        self.price_quoted = 0.0
        self.tiger_result: Optional[dict] = None
        self._proof_posted: set[str] = set()

    def proof_steps(self) -> list[Step]:
        """The LIVE sponsor proof lines this gate has real results for and has not handed out yet (each value once)."""
        seller = (self.winner or {}).get("persona") or (self.winner or {}).get("seller_id") or ""
        steps = live_proof_steps(self.addresses, price=self.price, quoted=self.price_quoted, tiger=self.tiger_result, round_id=self.round_id,
                                 crs=self.crs, seller=seller)
        fresh = [s for s in steps if s.args["text"] not in self._proof_posted]
        self._proof_posted.update(s.args["text"] for s in fresh)
        return fresh

    def note_loss(self, report: dict) -> None:
        """A record_loss_report step the market accepted; kept for flush_losses."""
        if self.tiger_loss_writer is not None:
            self._losses.append(dict(report))

    def flush_losses(self) -> list[str]:
        """Write the kept loss reports to Tiger Data (best effort, bounded by the writer) and return the console line.
        A failure is a line, never an exception: the round and its payment are already done."""
        if self.tiger_loss_writer is None or not self._losses:
            return []
        from demo import sponsors_live as S
        reports, self._losses = self._losses, []
        try:
            res = self.tiger_loss_writer(S.loss_rows(reports, self._round_rows, self.goal["items"][0]["sku_spec"]))
        except Exception as e:  # noqa: BLE001
            res = {"state": "error", "detail": type(e).__name__}
        return [S.tiger_note(res, self.round_id, "loss reports")]

    def expectations(self, rows: list) -> dict:
        w = market_winner(rows, self.round_id)
        if w is None:
            raise GateRefused(f"the market has no single rank 1 in {self.round_id}")
        seller, bid = self.sellers.get(w["seller_id"]), self.bids.get(w["bid_id"])
        if seller is None or bid is None or bid["seller_id"] != w["seller_id"]:
            raise GateRefused(f"the market's rank 1 ({w['persona'] or w['seller_id']}) is not a bid this run placed, so there is no payee")
        held = next((x for x in w["reasons"] if "held back" in x), None)
        if held is not None:   # #251: every bid carries a caution, so the market's #1 is only the least bad; the agent buys nothing
            raise GateRefused(f"the market's rank 1 ({w['persona'] or w['seller_id']}) is {held}: every bid carries a caution, "
                              "so the agent will not buy it")
        if not (math.isfinite(w["landed"]) and w["landed"] > 0):
            raise GateRefused("the market's rank 1 has no usable landed price")
        if abs(w["landed"] * 100 - round(w["landed"] * 100)) > 1e-6 or round(w["landed"], 2) != w["landed"]:
            # #240 wants the mandate at the landed price exactly, and the call reads the amount back in whole cents
            raise GateRefused(f"the market's rank 1 landed price {w['landed']!r} is not a whole number of cents")
        # #240: the mandate pays the winning seller id, at the winning landed price exactly (the market compares to 1e-9)
        return {**w, "deal_id": f"deal-{w['bid_id']}", "amount": w["landed"], "payee": w["seller_id"], "origin": bid["origin"]}

    def prepare(self, referee: Any) -> dict:
        from pay.crs_gate import check_id, payee_ok
        from pay.mandate import new_mandate
        self._referee = referee
        rows = referee.sql("SELECT * FROM round_result")
        self._round_rows = [r for r in rows if r[1] == self.round_id]
        if self.tiger_writer is not None:   # #269: the round's prices to Tiger Data, even when the round has no payable winner
            from demo import sponsors_live as S
            try:
                res = self.tiger_writer(S.round_ticks(self._round_rows, self.goal["items"][0]["sku_spec"]))
            except Exception as e:  # noqa: BLE001
                res = {"state": "error", "detail": type(e).__name__}
            self.tiger_result = res
            self._notes.append(S.tiger_note(res, self.round_id))
        w = self.expectations(rows)
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
            why = self.crs.get("sim_reason") or "no business CRS profile"
            return f"CRS: {seller} is a SIM seller ({why}), so its identity was not checked"
        c = self.crs["check"]
        cached = ", reused from the last 10 minutes" if self.crs.get("cached") else ""
        return (f"CRS: {seller} identity verified ({c['origin'].lower()}{cached}), check {self.mandate['crs_check_id']} "
                f"bound into the mandate")
    def drain_notes(self) -> list[str]:
        out, self._notes = self._notes, []
        return out

    def listing(self) -> tuple[dict, float, float]:
        """The winner's listing for the live re-check: ({url, price}, quoted unit price, the goal's cap)."""
        w = self.winner
        bid = self.bids[w["bid_id"]]
        line = bid["lines"][min(self.lines.get(w["seller_id"], 0), len(bid["lines"]) - 1)]
        return {"url": line["listing_url"], "price": line["unit_price"]}, float(line["unit_price"]), float(self.goal["cap"])

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
                           tag=m["origin"], say=f"mandate for the market's #1, {w['persona']}: {money(m['amount'])} to seller "
                                                f"{m['payee']} (SIM payee, no real merchant is paid), {MANDATE_MINUTES} minutes")
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
        picked = _picked(w["lines"][0]) if w.get("lines") else None
        if picked is not None:   # #216: the line the market picked, so the spoken condition matches the landed amount
            line = next((x for x in bid["lines"] if x["offered_condition"] == picked[0]
                         and abs(float(x["unit_price"]) - picked[1]) <= 0.005), line)
        facts = {"item": line.get("attrs", {}).get("chipset") or line["sku_spec"].upper(), "condition": line["offered_condition"],
                 "seller": seller["name"], "crs": "verified" if self.crs and self.crs.get("business") else "sim_seller"}
        if self.price is not None:
            from demo.sponsors_live import is_live
            facts["price"] = "live" if is_live(self.price) else "mirror"
        return facts

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

    issued: dict = {}   # #449 item 3 RT-11: the code this call issued; record_approval repeats it. In memory, never printed.

    def outcome(approved: bool, reason: Optional[str], call_id: Optional[str] = None, voice_approval_id: Optional[str] = None) -> dict:
        return {"step": "approval_call", "approved": approved, "reason": reason, "call_id": call_id,
                "voice_approval_id": voice_approval_id, "code": issued.get("code", "") if approved else ""}

    def to_screen(code: str) -> None:
        issued["code"] = code
        on_code(code, gate.show_code(code))

    def approve(step: Step) -> dict:
        mandate = gate.mandate
        if mandate is None:
            return outcome(False, "no_mandate: the market's rank 1 was not read")
        if client is None:
            if (unconfigured or "").startswith("no_phone"):
                return outcome(False, unconfigured)
            return outcome(False, f"not_configured: {unconfigured or 'no Cartesia client'}")
        if gate.price_check is not None:   # #269: the winner's price, read live right before the call
            from demo import recheck as R
            from demo.sponsors_live import price_note
            listing, quoted, cap = gate.listing()
            gate.price_quoted = quoted
            try:
                gate.price = gate.price_check(listing)
            except Exception as e:  # noqa: BLE001
                gate.price = {"state": "empty", "price": None, "fetched_at": None, "origin": "MIRROR", "detail": type(e).__name__}
            gate._notes.append(price_note(gate.price, quoted))
            stop = R.stop_reason(gate.price, quoted, cap)
            if stop:
                return outcome(False, f"price_recheck: {stop}")
        store = NonceStore()
        service = ApprovalService(secret=secret or _secrets.token_hex(16), store=store, code_ttl_seconds=CALL_CODE_TTL_S)
        res = run_approval_call(mandate, gate.reason(), client, service, deal=gate.facts(), buyer_name=buyer_name, on_code=to_screen,
                                **timing)
        if not res.approved:
            return outcome(False, res.reason or "denied", res.call_id)
        voice_id = str((res.record or {}).get("id") or "").strip()
        if not voice_id:   # #240 keeps the VoiceApproval id on the approval row; an approval with none is not recorded
            return outcome(False, "no_voice_approval_id: the call approved but left no VoiceApproval record", res.call_id)
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
        return outcome(True, None, res.call_id, voice_id)

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


def find_tokens_dir(explicit: Optional[str], target: Optional[dict] = None) -> Path:
    """The referee and buyer tokens for this market. A market that is not local (#295) uses only its own folder,
    .tokens/<db>@<host>/, so a local identity never signs a call on the shared market."""
    from demo import market_target
    if target is not None and not target["local"]:
        own = market_target.tokens_dir(target)
        if explicit and Path(explicit).resolve() != own.resolve():
            raise SystemExit(f"--tokens-dir {explicit} is not this market's own folder {own}: "
                             "local tokens are never used for another market")
        if (own / REFEREE_TOKEN).exists() and (own / BUYER_TOKEN).exists():
            return own
        raise SystemExit(f"no {REFEREE_TOKEN} and {BUYER_TOKEN} for {market_target.describe(target)} in {own} "
                         "(scripts/deploy_maincloud.sh creates them; local tokens are never used for another market)")
    cands = [Path(explicit)] if explicit else [Path(os.environ["BRIDGE_TOKENS_DIR"])] if os.environ.get("BRIDGE_TOKENS_DIR") else []
    cands += [ROOT / ".tokens", ROOT.parent / "lane-d-launcher" / ".tokens", ROOT.parent / "lane-d" / ".tokens"]
    shared = [c for c in cands if market_target.is_market_tokens_dir(c)]
    if shared:   # a shared market's tokens never sign a call on the local market either
        raise SystemExit(f"{shared[0]} holds a shared market's tokens; the local market uses .tokens/")
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
    ap.add_argument("--server", default=None, help="spacetime -s server (default SPACETIMEDB_SERVER from the env or the Lane D env file, else local)")
    ap.add_argument("--bid-window", type=bid_window_arg, default=None,
                    help=f"seconds each sealed round stays open (at least {MIN_BID_WINDOW_S}); steps inside run faster to fit")
    args = ap.parse_args(argv)
    if args.stripe and not args.live_call:
        ap.error("--stripe needs --live-call: a Stripe test charge runs only after a real phone call approves (there is no scripted approval)")

    from demo.run_demo import run_all, stripe_env, DEFAULT_ENV_FILE
    run = run_all(say=Narrator(False))       # never a Stripe call here: this run builds the plan, before any round or call
    gate = DealGate(run)                     # beat 4's mandate is made from the market's rank 1 when beat 4 starts
    addresses = demo_agent_addresses()
    gate.addresses = addresses               # the LIVE sponsor proof lines go to the same Fetch tile as the SIM ones
    steps = plan(run, delay=args.step_delay, buyer_id=args.buyer_id, rounds=args.rounds, live_call=args.live_call,
                 two_buyers=args.two_buyers, bid_window=args.bid_window, agent_addresses=addresses)
    out = Narrator(True)
    out.note("Fish Market screen bridge: demo beats (real lane code) -> existing SpacetimeDB reducers")
    out.note(f"{len(steps)} reducer calls, {args.step_delay} s between visible steps. Open /buyer (pair as {args.buyer_id}) and /market.")
    out.note("Buyer: Vidyut. The goal, owned parts and payment are simulated. Tags: [MIRROR] real dated listing, [SIM] generated by us.")
    out.note(shield_mode_line())

    def say(s: Step) -> None:
        who = "buyer" if s.actor == "buyer" else "referee" if s.actor == "referee" else s.actor.replace("seller:", "seller ")
        if s.reducer == "set_floor":
            return
        out.line(s.tag if s.tag in LIVE_TAGS else SIM, f"{who:<26}{s.reducer:<22}{s.say}")

    approver, client_note, charger = None, "", None
    if args.live_call:   # #269: Bright Data and Tiger Data keys from the same env file as the call; values never printed
        from pay import voice_cartesia as vc
        from demo import sponsors_live as S
        S.load_sponsor_env(args.env_file or vc.DEFAULT_ENV_FILE)
        gate.price_check = S.price_recheck
        gate.tiger_writer = S.write_round_ticks
        gate.tiger_loss_writer = S.write_loss_reports
        approver, client_note = live_approver_for(args, run, gate, out)
        out.note(client_note)
    elif os.environ.get("TIGER_DATA_SERVICE_URL"):   # #260: round history is written on any run when Tiger is configured
        from demo import sponsors_live as S
        gate.tiger_writer = S.write_round_ticks
        gate.tiger_loss_writer = S.write_loss_reports
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

    if not args.live_call:
        out.note(f"No --live-call: the run ends at beat 4's approval gate. {NO_CALL_LINE[0].upper()}{NO_CALL_LINE[1:]}")
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


def _referee_sql(args) -> Callable[[str], Any]:
    """sql(query) as the referee identity, opened lazily on the first query (nothing is opened for the default buyer). No referee token
    on disk, or any setup problem, raises RuntimeError (the lookups turn that into None); it never mints an identity."""
    state: dict[str, Any] = {}

    def sql(query: str) -> Any:
        if "market" not in state:
            try:
                tokens = find_tokens_dir(getattr(args, "tokens_dir", None), live_target(args))
            except SystemExit as e:   # a setup problem here is a missing phone (fail closed), not a crash of the approver
                raise RuntimeError("market tokens unavailable") from e
            token = tokens / REFEREE_TOKEN
            if not token.exists():
                raise RuntimeError("no referee token")
            sys.path.insert(0, str(ROOT / "market" / "scripts"))
            from stdb import Market   # reads SPACETIMEDB_HTTP and SPACETIMEDB_DB, exported by live_target
            state["market"] = Market(token_file=str(token))
        return state["market"].sql(query)

    return sql


def referee_phone_lookup(args) -> Callable[[str], Optional[str]]:
    """H3: a lookup of one buyer's own approval phone in the market's agent-only agent_buyer_contact view, read as the referee.
    Any failure is None (the caller then fails closed with NoPhone); the number is never printed."""
    from pay import voice_cartesia as vc
    return vc.phone_lookup_from_sql(_referee_sql(args))


def referee_name_lookup(args) -> Callable[[str], Optional[str]]:
    """H3: a lookup of one buyer's own display_name from the same view, to greet them by (never the default buyer's name)."""
    from pay import voice_cartesia as vc
    return vc.name_lookup_from_sql(_referee_sql(args))


def live_approver_for(args, run: dict, gate: DealGate, out) -> tuple[Callable[[Step], dict], str]:
    """The --live-call gate for this run, plus one console line saying where the call would go. A missing or bad Cartesia
    setup is not a crash: the gate denies at the approval beat (nothing is dialled, nothing is paid). The deal, the why-answer
    and the code's screen all come from `gate` when beat 4 starts."""
    from pay import voice_cartesia as vc
    env = vc.load_env(args.env_file or vc.DEFAULT_ENV_FILE)
    buyer_id = getattr(args, "buyer_id", DB_BUYER_ID)
    # APPROVAL_BUYER_NAME is the default buyer's name only; any other buyer is greeted by their own display_name, else "there" (H3)
    buyer_name = vc.greeting_name(buyer_id, env, referee_name_lookup(args))

    def show(code: str, why_not: Optional[str]) -> None:
        if why_not is None:
            out.note("approval code: on /buyer now (issue_approval_code); it is not printed here. The buyer reads it, then says approve")
        else:
            out.note(f"SCREEN CODE: {code}   (/buyer could not show it: {why_not}. Say it, then say approve)")

    try:
        # #374 + H3: this buyer's own phone, never another buyer's (a web buyer's comes from the market's agent-only contact view)
        client = vc.client_for_buyer(buyer_id, env, lookup=referee_phone_lookup(args))
        where = f"live call: ONE call to {vc.mask_number(client.approval_call_to)} at the approval beat (Cartesia configured)"
        unconfigured = None
    except vc.NoPhone as e:
        client, unconfigured = None, f"no_phone: {e}"
        where = f"live call: NO PHONE on file ({e}), so the approval beat will be DENIED: no call, nothing is paid"
    except vc.CartesiaError as e:
        client, unconfigured = None, str(e)
        where = f"live call: Cartesia NOT configured ({unconfigured}; names {', '.join(vc.ENV_NAMES[:3])}), so the approval beat will be DENIED and nothing is paid"
    return make_live_approver(gate, client, unconfigured=unconfigured, buyer_name=buyer_name, on_code=show,
                              secret=env.get(vc.SECRET_ENV)), where


def live_target(args) -> dict:
    """#295: the market this run talks to, from --server, the env and the Lane D env file; exported for stdb.py."""
    from demo import market_target
    from demo.run_demo import DEFAULT_ENV_FILE
    if getattr(args, "server", None):
        os.environ["SPACETIMEDB_SERVER"] = args.server
    try:
        target = market_target.resolve(DEFAULT_ENV_FILE)
    except market_target.TargetError as e:
        raise SystemExit(f"market target refused: {e}") from None
    if getattr(args, "server", None) and target["server"] != args.server:   # the env file wins, so a flag that differs is a conflict
        raise SystemExit(f"--server {args.server} but the Lane D env file names {market_target.describe(target)}: "
                         "change SPACETIMEDB_SERVER there, or drop --server")
    market_target.export(target)
    args.server = target["server"]
    return target


def _run_live(args, steps, run, out, say, approver=None, charger=None, gate=None) -> int:
    from demo import market_target
    target = live_target(args)
    out.note(market_target.describe(target))
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    from stdb import Market   # the market's own bridge; reads SPACETIMEDB_HTTP and SPACETIMEDB_DB (set above)
    tokens = find_tokens_dir(args.tokens_dir, target)
    out.note(f"tokens: {tokens}")
    seller_tokens = market_target.tokens_dir(target)
    seller_tokens.mkdir(parents=True, exist_ok=True)
    clients: dict[str, Any] = {"buyer": Market(token_file=str(tokens / BUYER_TOKEN)),
                               "referee": Market(token_file=str(tokens / REFEREE_TOKEN))}
    seller_ids = sorted({s.actor.split(":", 1)[1] for s in steps if s.actor.startswith("seller:")})
    for sid in seller_ids:
        clients[f"seller:{sid}"] = Market(token_file=str(seller_tokens / f"bridge-{sid}.json"))
    if any(s.actor == SECOND_ACTOR for s in steps):
        clients[SECOND_ACTOR] = Market(token_file=str(seller_tokens / f"bridge-{SECOND_BUYER_ID}.json"))
    if not args.no_assign_roles:
        spacetime = shutil.which("spacetime") or str(Path.home() / ".local" / "bin" / "spacetime")
        assign_seller_roles(seller_ids, clients, spacetime, target["server"], target["db"])
        if SECOND_ACTOR in clients:
            assign_buyer_role(SECOND_BUYER_ID, clients[SECOND_ACTOR], spacetime, target["server"], target["db"])
    if args.reset:
        out.note("reset_demo (referee): clearing the demo tables")
        clients["referee"].call("reset_demo")
        time.sleep(1)
    try:
        from demo import crs_relay
        outcomes = execute(steps, clients, delay=args.step_delay, say=say, approver=approver, note=out.note, charger=charger,
                           deal_gate=gate,
                           before_round=lambda: crs_relay.relay_best_effort(clients["referee"], note=out.note))
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
    return 1 if any(not o["approved"] for o in outcomes) else 0   # a run that ended at the gate is not a clean run


if __name__ == "__main__":
    raise SystemExit(main())
