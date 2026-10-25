#!/usr/bin/env python3
"""A full PC build in the market (#345, phase 1): one goal, one sealed round per part, one call for the whole build.

    python3 demo/build.py --dry-run          # print the reducer calls and the plan, touch nothing
    python3 demo/build.py --live-call        # one real approval call for the whole build, only above the allowance

Driven like demo/bridge.py: every write goes through an EXISTING reducer with the role token it demands (the buyer posts the goal
and each part's need, the referee opens and closes rounds and moves the money records, each seller bids as itself). Nothing here
ranks a bid or picks a champion: the market's own rank 1 of a closed round is the part's champion.

The pieces:
  build_view(market_rows, plan_events, checks)   the pure BuildView the board reads (docs/changes/1650-D-build-board-shape.md)
  BuildRun                                       the driver: rounds, champions, live re-check, ONE call, mandates, receipts
  plan_from_planner(plan)                        the planner's plan() output (agents/buyer/planner.py, #344) as a BuildPlan

Money rules this module keeps:
  * the phone call is the only approval above the allowance, and it is ONE call for the whole build; there is no scripted approval;
  * a mandate is made for a part's rank 1 only (#240), after the call approved, so a part under the per-purchase limit can never be
    approved by the market's allowance rule while the build as a whole needed the call;
  * a champion that is held back, was never bid by this run, never joined the market (data.mirror.not_partners) or has no usable
    landed price is never mandated; a part with no eligible bid is `failed`, the build does not call and nothing is paid;
  * every price and event carries its label: LIVE, MIRROR or SIM.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.mirror import not_partners  # noqa: E402
from demo.common import LIVE, MIRROR, SIM, money  # noqa: E402

OUT_DIR = ROOT / "demo" / "out"
VIEW_FILE = "build-view.json"          # the latest BuildView, rewritten at every step
STEPS_FILE = "build-view.steps.jsonl"  # one BuildView per line, in order: the board can replay a run
PARTS = ("gpu", "cpu", "board", "ram", "ssd", "cooler", "psu", "case")
PLANNER_PART = {"gpu": "gpu", "cpu": "cpu", "motherboard": "board", "memory": "ram", "storage": "ssd", "cooler": "cooler",
                "psu": "psu", "case": "case"}   # the planner's part ids (agents/buyer/planner.py) -> the board's
DEFAULT_LABELS = {"gpu": "RTX 5070 Ti", "cpu": "8-core CPU", "board": "AM5 B650 board", "ram": "32 GB DDR5", "ssd": "2 TB NVMe",
                  "cooler": "Tower cooler", "psu": "750 W PSU", "case": "Case (305 mm GPU room)"}
CHECK_STATES = ("ok", "clash", "unknown")
ORIGINS = (SIM, MIRROR, LIVE)
HELD_BACK = "held back"                 # the market's own reason prefix on a rank 1 whose card is a caution (#240)
RECHECK_TIMEOUT_S = 45.0                # one bound for the whole parallel Bright Data re-check
MANDATE_MINUTES = 10


# ---------------------------------------------------------------- ids

def need_id(goal_id: str, part: str, n: int = 1) -> str:
    return f"need-{goal_id}-{part}" + (f"-{n}" if n > 1 else "")


def round_id(goal_id: str, part: str, n: int = 1) -> str:
    return f"round-{goal_id}-{part}" + (f"-{n}" if n > 1 else "")


# ---------------------------------------------------------------- BuildView (pure)

def _origin(v: Any) -> str:
    return v if v in ORIGINS else SIM


def _weakest(origins: list[str]) -> str:
    """The label of a whole: SIM if any part is SIM, else MIRROR if any is MIRROR, else LIVE."""
    got = {_origin(o) for o in origins}
    return SIM if (SIM in got or not got) else MIRROR if MIRROR in got else LIVE


def _cents_ok(landed: Any) -> bool:
    try:
        x = float(landed)
    except (TypeError, ValueError):
        return False
    return not isinstance(landed, bool) and math.isfinite(x) and x > 0 and abs(x * 100 - round(x * 100)) <= 1e-6


def champion_of(results: list[dict]) -> tuple[Optional[dict], str]:
    """(the round's eligible champion row, "") or (None, why there is none). Eligible = the market's rank 1 of a plain or won round, not held back, a seller
    that joined the market, and a landed price in whole cents. A held-back or vetoed bid is never a champion (#240)."""
    # #363 (knockout rounds): only a row whose status is "" (a plain round) or "champion" can win; a stage leader ("advancing") or a
    # knocked-out bid never can, whatever its rank
    first = [r for r in results if r.get("rank") == 1 and (r.get("status") or "") in ("", "champion")]
    if len(first) != 1:
        return None, "no eligible bid: the market ranked none" if not first else "no eligible bid: the market named two rank 1 bids"
    r = first[0]
    held = next((x for x in r.get("reasons") or [] if str(x).startswith(HELD_BACK)), None)
    if held is not None:
        return None, f"no eligible bid: the best bid is {held}"
    if not not_partners.orderable({"seller_id": r.get("sellerId")}):
        return None, f"no eligible bid: {r.get('persona') or r.get('sellerId')} is not a partner and cannot be bought from here"
    if not _cents_ok(r.get("landed")):
        return None, "no eligible bid: the best bid has no usable landed price"
    return r, ""


def _out_reason(results: list[dict]) -> str:
    """The market's first reason across a round's disqualified bids, for a failed part's line."""
    for r in results:
        if r.get("rank") == 0 and r.get("reasons"):
            return str(r["reasons"][0])
    return ""


def build_view(market_rows: dict, plan_events: list, checks: list) -> dict:
    """The BuildView the board reads (docs/changes/1650-D-build-board-shape.md), from rows only. Pure: nothing in the inputs changes.

    market_rows (camelCase, as the market tables name their columns, plus what the driver knows about its own writes):
      goal {id, buyerId, cap, origin}; goalItems [{part, label, skippedOwnedPartId, budget}] (owned parts have the id set), in board order;
      needs [{id, goalId, part, spendLimit, origin}] (a part's later need is its re-plan); rounds [{id, needId, state open|closed,
      openedAt, closedAt, origin}]; roundResults [{roundId, bidId, sellerId, persona, rank, landed, reasons, origin, sourceUrl}];
      mandates [{hash, dealId, amount, payee, part}]; payments [{mandateHash, paymentRef, amount, mode, at, text, part}];
      approval {state, method, reason, events [{at, kind, text, origin}]}; liveChecks {part: {state, price, fetchedAt, origin, quoted, at, text}}.
    plan_events: [{at, kind, text, parts, origin?}] from the planner (plan, clash, replan). checks: the fit lines, passed through."""
    goal = market_rows.get("goal") or {}
    rounds = {r["id"]: r for r in market_rows.get("rounds") or []}
    results: dict[str, list[dict]] = {}
    for r in market_rows.get("roundResults") or []:
        results.setdefault(r["roundId"], []).append(r)
    needs: dict[str, list[dict]] = {}
    for n in market_rows.get("needs") or []:
        needs.setdefault(n["part"], []).append(n)
    live = market_rows.get("liveChecks") or {}
    replans = [e for e in plan_events if e.get("kind") == "replan"]
    parts, champions = [], {}
    events = [{"at": e.get("at") or "", "kind": e["kind"], "text": e["text"], "parts": list(e.get("parts") or []), "origin": _origin(e.get("origin"))}
              for e in plan_events]
    for item in market_rows.get("goalItems") or []:
        part, label = item["part"], item["label"]
        if item.get("skippedOwnedPartId"):
            parts.append({"part": part, "label": label, "status": "owned", "budget": 0, "origin": SIM})
            continue
        mine = needs.get(part) or []
        entry: dict[str, Any] = {"part": part, "label": label, "status": "planned", "budget": float(mine[-1]["spendLimit"]) if mine else float(item.get("budget") or 0.0),
                                 "origin": _origin(mine[-1].get("origin")) if mine else SIM}
        if mine:
            cur = mine[-1]
            entry["needId"] = cur["id"]
            rnd = next((r for r in rounds.values() if r["needId"] == cur["id"]), None)
            if rnd is not None:
                entry["roundId"] = rnd["id"]
                rows = results.get(rnd["id"], [])
                events.append({"at": rnd.get("openedAt") or "", "kind": "round_open", "text": f"{label}: round open", "parts": [part],
                               "origin": _origin(rnd.get("origin"))})
                if rnd.get("state") == "open":
                    entry["status"] = "bidding"
                else:
                    at = rnd.get("closedAt") or ""
                    for r in sorted((x for x in rows if x.get("rank") == 0), key=lambda x: x["bidId"]):
                        why = (r.get("reasons") or ["out of the round"])[0]
                        events.append({"at": at, "kind": "knockout", "text": f"{label}: {r.get('persona') or r['sellerId']} out, {why}",
                                       "parts": [part], "origin": _origin(r.get("origin"))})
                    champ, why = champion_of(rows)
                    if champ is None:
                        entry["status"], entry["reason"] = "failed", why + (f" ({_out_reason(rows)})" if _out_reason(rows) else "")
                        events.append({"at": at, "kind": "knockout", "text": f"{label}: {why}. Nothing will be paid", "parts": [part],
                                       "origin": SIM})
                    else:
                        entry["status"] = "replanned" if len(mine) > 1 else "locked"
                        c = {"bidId": champ["bidId"], "sellerId": champ["sellerId"], "persona": champ.get("persona") or champ["sellerId"],
                             "landed": float(champ["landed"]), "origin": _origin(champ.get("origin")), "sourceUrl": champ.get("sourceUrl") or ""}
                        if part in live:
                            lv = live[part]
                            c["liveCheck"] = {k: lv.get(k) for k in ("state", "price", "fetchedAt", "origin", "quoted")}
                            c["liveCheck"]["origin"] = _origin(c["liveCheck"]["origin"])
                        entry["champion"], entry["origin"] = c, c["origin"]
                        champions[part] = c
                        if entry["status"] == "replanned":
                            said = [e for e in replans if part in (e.get("parts") or [])]
                            entry["reason"] = said[-1]["text"] if said else "The earlier pick was swapped"
                        events.append({"at": at, "kind": "locked", "text": f"{label}: {c['persona']} locked at {money(c['landed'])}",
                                       "parts": [part], "origin": c["origin"]})
        parts.append(entry)
    buying = [p for p in parts if p["status"] != "owned"]
    total = round(sum(c["landed"] for c in champions.values()), 2)
    sellers = len({c["sellerId"] for c in champions.values()})
    if buying and all(p["status"] in ("locked", "replanned") for p in buying):
        done = max((r.get("closedAt") or "" for r in rounds.values()), default="")
        events.append({"at": done, "kind": "locked", "text": f"Build ready: {len(buying)} parts, {sellers} sellers, {money(total)}",
                       "parts": [], "origin": _weakest([c["origin"] for c in champions.values()])})
    for part, lv in live.items():
        if lv.get("text"):
            events.append({"at": lv.get("at") or "", "kind": "locked", "text": lv["text"], "parts": [part], "origin": _origin(lv.get("origin"))})
    ap = market_rows.get("approval") or {}
    mandates = [{"sellerId": m["payee"], "amount": float(m["amount"]), "mandateHash": m["hash"], "part": m.get("part", "")}
                for m in market_rows.get("mandates") or []]
    paid = {p["mandateHash"] for p in market_rows.get("payments") or []}
    state = ap.get("state") or "waiting"
    if state == "approved" and mandates and all(m["mandateHash"] in paid for m in mandates):
        state = "paid"
    approval: dict[str, Any] = {"state": state, "total": total, "sellers": sellers, "mandates": mandates}
    for k in ("method", "reason"):
        if ap.get(k):
            approval[k] = ap[k]
    for e in ap.get("events") or []:
        events.append({"at": e.get("at") or "", "kind": e["kind"], "text": e["text"], "parts": list(e.get("parts") or []),
                       "origin": _origin(e.get("origin"))})
    for p in market_rows.get("payments") or []:
        events.append({"at": p.get("at") or "", "kind": "receipt", "text": p.get("text") or f"Payment recorded: {p['paymentRef']}",
                       "parts": [p["part"]] if p.get("part") else [],
                       "origin": LIVE if p.get("mode") == "stripe_test" else SIM})
    events.sort(key=lambda e: e["at"])   # stable: same-time events keep the order they were added in (the plan first)
    lines = []
    for c in checks or []:
        lines.append({"a": c["a"], "b": c["b"], "rule": c["rule"], "state": c["state"] if c.get("state") in CHECK_STATES else "unknown",
                      "detail": c.get("detail", ""), "source": c.get("source", "")})
    return {"goalId": goal.get("id", ""), "buyerId": goal.get("buyerId", ""), "budget": float(goal.get("cap") or 0),
            "spent": float(round(sum(c["landed"] for p in buying if p["status"] in ("locked", "replanned") for c in [p["champion"]]), 2)),
            "origin": _weakest([p["origin"] for p in buying]) if buying else _origin(goal.get("origin")),
            "parts": parts, "checks": lines, "events": events, "approval": approval}


# ---------------------------------------------------------------- the plan

@dataclass
class PartSpec:
    part: str
    label: str
    budget: float          # dollars: the ceiling of this part's round (the need's spend limit)

    @property
    def sku(self) -> str:
        return self.label.lower()


@dataclass
class BuildPlan:
    goal_id: str
    buyer_id: str
    cap: float
    parts: list[PartSpec]
    owned: list[PartSpec] = field(default_factory=list)   # no round: the buyer already has them (budget is 0)
    deadline: str = ""


def _money_cents(cents: Any, what: str) -> float:
    if isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0:
        raise ValueError(f"{what} must be a positive whole number of cents, got {cents!r}")
    return cents / 100


def plan_from_planner(plan: dict, *, goal_id: str = "goal-build-1", buyer_id: str = "vidyut", labels: Optional[dict] = None,
                      deadline: Optional[str] = None) -> BuildPlan:
    """The planner's plan() output (agents/buyer/planner.py: cap_cents, owned, parts [{part, budget_cents}]) as a BuildPlan.
    A part id the board does not know, a bad budget, or budgets above the cap raise ValueError: nothing is bid on a plan we cannot read."""
    names = {**DEFAULT_LABELS, **(labels or {})}
    cap = _money_cents(plan.get("cap_cents"), "cap_cents")
    parts, seen = [], set()
    for p in plan.get("parts") or []:
        part = PLANNER_PART.get(p.get("part"))
        if part is None or part in ("psu", "case"):
            raise ValueError(f"unknown part to buy: {p.get('part')!r}")
        if part in seen:
            raise ValueError(f"part {p.get('part')!r} is in the plan twice")
        seen.add(part)
        parts.append(PartSpec(part, names[part], _money_cents(p.get("budget_cents"), f"{p.get('part')} budget_cents")))
    if not parts:
        raise ValueError("the plan has no part to buy")
    if round(sum(p.budget for p in parts), 2) > cap + 0.005:
        raise ValueError(f"the part budgets add up to more than the cap {money(cap)}")
    owned = []
    for key, info in (plan.get("owned") or {}).items():
        part = PLANNER_PART.get(key)
        if part is None:
            raise ValueError(f"unknown owned part: {key!r}")
        name = info.get("name") if isinstance(info, dict) else None
        owned.append(PartSpec(part, name if isinstance(name, str) and name.strip() else names[part], 0.0))
    return BuildPlan(goal_id, buyer_id, cap, parts, owned, deadline or "")


def demo_plan(*, goal_id: str = "goal-build-1", buyer_id: str = "vidyut") -> BuildPlan:
    """SIM: six parts to buy, PSU and case owned, a $2,100 cap. The GPU budget ($1,300) is the cap of the demo's own GPU goal, so the real
    GPU round (demo.round, the bridge's cast) has confirmed-fit bids inside it; the others are the board sample's numbers."""
    budgets = {"gpu": 1300.0, "cpu": 285.0, "board": 170.0, "ram": 100.0, "ssd": 120.0, "cooler": 55.0}
    return BuildPlan(goal_id, buyer_id, 2100.0, [PartSpec(p, DEFAULT_LABELS[p], b) for p, b in budgets.items()],
                     [PartSpec("psu", DEFAULT_LABELS["psu"], 0.0), PartSpec("case", DEFAULT_LABELS["case"], 0.0)])


# ---------------------------------------------------------------- the sellers (SIM, plus the real MIRROR listings where data/ has them)

SIM_SELLERS = (("gadget-grove", "Gadget Grove (SIM)"), ("fair-price-pc", "Fair Price PC (SIM)"), ("bargain-bin", "Bargain Bin Hardware (SIM)"))
PRICE_FACTORS = (0.93, 0.96, 0.99)   # of the part's budget; rotated per part, so the cheapest seller changes from part to part
CASE_CLEARANCE_MM = 305              # the owned case's GPU room (the buyer shares it with sellers, never the cap)
TRAP_LENGTH_MM = 336                 # the SIM GPU line too long for that case: the advocate vetoes it, with the fit rule


def default_catalog(spec: PartSpec, index: int, *, mirror: bool = True) -> list:
    """The sellers that bid on one part. SIM sellers for every part, priced inside the part's budget, with a rotating cheapest one;
    for the GPU, with `mirror`, the bridge's own cast (demo.sellers.all_sellers: the real dated MIRROR listings in data/mirror/snapshots
    plus the planted SIM sellers), judged by the real demo round; without it, a SIM GPU line too long for the owned case. data/ holds no
    other part's listings, so every other part is SIM and says so. Central Computers (not a partner) never bids here."""
    from demo.sellers import Line, Seller
    sellers = []
    for j, (sid, name) in enumerate(SIM_SELLERS):
        price = round(spec.budget * PRICE_FACTORS[(j + index) % 3], 2)
        url = f"https://example.com/sim/{sid}/{spec.part}"
        attrs = {"category": spec.part}
        if spec.part == "gpu":
            attrs["length_mm"] = TRAP_LENGTH_MM if sid == "bargain-bin" else 303
        if spec.part == "gpu" and sid == "bargain-bin":
            price = round(spec.budget * 0.88, 2)      # the cheapest card is the trap
        line = Line("new", price, round(price * 0.9, 2), url, SIM, page_condition="new", attrs=attrs,
                    basis=f"SIM listing priced inside the {spec.label} budget")
        sellers.append(Seller(sid, name, SIM, [line], 0.0, 30, payee=f"{sid}@pay.example.test", shipping_captured=True,
                              claims=[{"text": "New, retail box", "kind": "spec", "field": "condition", "value": "new", "evidence_url": url}]))
    if mirror and spec.part == "gpu":
        from demo.sellers import all_sellers
        # the bridge's own cast: the real dated MIRROR listings plus the planted SIM sellers (a liar, a too-long card, a rogue under its floor)
        return [x for x in all_sellers()[0] if not not_partners.label({"seller_id": x.id})]
    return sellers


def advocate_card(spec: PartSpec, bid: dict, clearance_mm: int = CASE_CLEARANCE_MM) -> dict:
    """The advocate's card on one bid (the market applies it at the close). A GPU line longer than the owned case has room for is
    vetoed with the fit rule and the listing it read; everything else is a buy. The planner (#344) owns the full fit logic in phase 2."""
    line = min(bid["lines"], key=lambda l: l["unit_price"])
    length = (line.get("attrs") or {}).get("length_mm")
    if spec.part == "gpu" and isinstance(length, (int, float)) and length > clearance_mm:
        return {"bid_id": bid["id"], "recommendation": "veto",
                "call_reason": {"rule_id": "fit.gpu_length", "summary": f"{int(length)} mm card, {clearance_mm} mm case",
                                "source_url": line["listing_url"]}}
    return {"bid_id": bid["id"], "recommendation": "buy",
            "call_reason": {"rule_id": "advocate.ok", "summary": "No problems found in the checks", "source_url": line["listing_url"]}}


# ---------------------------------------------------------------- the steps (pure: a plan -> reducer calls, like demo/bridge.plan)

WINDOW_S = 12


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def goal_steps(plan: BuildPlan, allowance: Optional[dict] = None) -> list:
    """The goal (type "build_by_date", one goal_item per part; an owned part is skipped with its owned id) and the buyer's allowance."""
    from demo.bridge import Step
    items = [{"sku_spec": o.sku, "condition": "new", "variant": "retail", "quantity": 1, "skipped_owned_part_id": f"owned-{o.part}"}
             for o in plan.owned]
    items += [{"sku_spec": p.sku, "condition": "new", "variant": "retail", "quantity": 1, "skipped_owned_part_id": ""} for p in plan.parts]
    steps = [Step("buyer", "post_goal", {"id": plan.goal_id, "buyer_id": plan.buyer_id, "type": "build_by_date", "cap": plan.cap,
                                         "deadline": plan.deadline, "po_number": "", "origin": SIM, "items": items},
                  pause=True, say=f"{plan.buyer_id} sets a build goal: {len(plan.parts)} parts to buy, "
                                  f"{len(plan.owned)} owned, cap {money(plan.cap)} (SIM)")]
    if allowance:
        steps.append(Step("referee", "set_allowance", {"buyer_id": plan.buyer_id, "per_purchase_limit": allowance["per_purchase_limit"],
                                                       "period_limit": allowance["period_limit"], "period": allowance["period"]},
                          pause=True, say=f"allowance: {money(allowance['per_purchase_limit'])} per buy, {money(allowance['period_limit'])} "
                                          f"a {allowance['period']}; a build above it needs the one call"))
    return steps


def _cheapest(bid: dict) -> int:
    return min(range(len(bid["lines"])), key=lambda i: bid["lines"][i]["unit_price"])


def _simple_round(spec: PartSpec, sellers: list, nid: str, now: datetime) -> dict:
    """A part's round inputs for the SIM parts: one sealed bid per seller, Shield on its text, the advocate card from advocate_card()."""
    from demo.round import shield_screen
    from demo.sellers import make_bid
    sealed = {"id": nid, "items": [{"sku_spec": spec.sku, "quantity": 1}], "auction_window_s": WINDOW_S}   # sellers never see the budget
    bids = [make_bid(s, sealed, now) for s in sellers]
    by_id = {s.id: s for s in sellers}
    return {"bids": bids, "cards": [advocate_card(spec, b) for b in bids], "claims": {},
            "shield": [shield_screen(by_id[b["seller_id"]], b) for b in bids],
            "ranking": {"ranked": [{"seller_id": b["seller_id"], "bid_id": b["id"], "line": _cheapest(b)} for b in bids], "disqualified": []},
            "need_item": {"sku_spec": spec.sku, "condition": "new", "allowed_conditions": [], "variant": "retail", "quantity": 1, "unit": "each"}}


def _demo_gpu_round(spec: PartSpec, sellers: list, nid: str, now: datetime) -> dict:
    """The GPU's round inputs from the bridge's own pipeline: demo.round.run_round on the demo's GPU need (new or open-box, fits the
    owned case), so Shield, the claim check against the sellers' pages and the real advocate (agents/advocate/checks.py) judge every bid."""
    from demo import beats, goal as G
    from demo.round import run_round
    owned = G.vidyut_owned_parts(now)
    need = {**G.need_from_goal(G.build_goal(G.GOAL_TEXT, owned, now)), "id": nid, "spend_limit": spec.budget}
    res = run_round(need, sellers, beats.owned_attrs(owned), spec.budget, now, 1)
    claims = {b: [{"text": c["text"], "check": c["check"], "evidence_url": c["evidence_url"], "origin": c["origin"]} for c in cs]
              for b, cs in res["claims"].items()}
    n = need["items"][0]
    return {"bids": res["bids"], "cards": res["cards"], "claims": claims, "shield": res["shield"], "ranking": res["ranking"],
            "need_item": {"sku_spec": n["sku_spec"], "condition": n["condition"], "allowed_conditions": list(n.get("allowed_conditions") or []),
                          "variant": n["variant"], "quantity": n["quantity"], "unit": n["unit"]}}


def part_steps(plan: BuildPlan, spec: PartSpec, index: int, sellers: list, *, now: datetime, delay: float,
               bid_window: Optional[int] = None, real_gpu_round: bool = False) -> tuple[list, dict]:
    """One part's need and sealed round: post_need, then bridge.round_steps (open, every seller's bid, Shield and advocate results, close).
    With `real_gpu_round` the GPU runs the bridge's own round (_demo_gpu_round) and `sellers` must be demo.sellers' cast.
    Returns (steps, ledger) where the ledger maps each bid id to what this run placed (seller, persona, origin, listing, snapshot date,
    the advocate card, None when the round did not judge it): the driver only mandates a champion it can find here."""
    from demo import bridge
    nid, rid = need_id(plan.goal_id, spec.part), round_id(plan.goal_id, spec.part)
    r = (_demo_gpu_round if real_gpu_round and spec.part == "gpu" else _simple_round)(spec, sellers, nid, now)
    by_id = {s.id: s for s in sellers}
    steps = [bridge.Step("buyer", "post_need",
                         {"id": nid, "buyer_id": plan.buyer_id, "goal_id": plan.goal_id, "delivery_window": f"by {plan.deadline}",
                          "spend_limit": spec.budget, "consent": True, "auction_window_s": WINDOW_S, "origin": SIM, "items": [r["need_item"]]},
                         pause=True, say=f"{spec.label}: the need goes to sellers, budget {money(spec.budget)} kept from them")]
    steps += bridge.round_steps(
        round_no=1, need_id=nid, bids=r["bids"], ranking=r["ranking"],
        sellers={s.id: {"lines": [{"floor": l.floor} for l in s.lines]} for s in sellers}, shield=r["shield"], claims=r["claims"],
        cards=r["cards"], delay=delay, pace=0.5, window_s=bid_window, round_id=rid, label=f"{spec.label} round")
    cards = {c["bid_id"]: c for c in r["cards"]}
    ledger = {}
    for b in r["bids"]:
        line = by_id[b["seller_id"]].lines[_cheapest(b)]
        ledger[b["id"]] = {"sellerId": b["seller_id"], "persona": b["persona"], "origin": b["origin"], "listingUrl": line.listing_url,
                           "snapshotDate": line.snapshot_date, "card": cards.get(b["id"])}
    return steps, ledger


# ---------------------------------------------------------------- the driver

def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def result_dicts(rows: list, ledger: dict, round_ids: set) -> list[dict]:
    """round_result rows (id, round_id, bid_id, seller_id, persona, rank, landed, reasons, lines, origin, source, ...) as the dicts
    build_view reads, for the given rounds only. sourceUrl comes from what this run placed, and only for a real MIRROR listing."""
    out = []
    for r in rows:
        if r[1] not in round_ids:
            continue
        placed = ledger.get(r[2]) or {}
        origin = _origin(r[9]) if len(r) > 9 else _origin(placed.get("origin"))
        out.append({"roundId": r[1], "bidId": r[2], "sellerId": r[3], "persona": r[4], "rank": r[5], "landed": float(r[6]),
                    "reasons": [str(x) for x in r[7]] if len(r) > 7 and isinstance(r[7], (list, tuple)) else [], "origin": origin,
                    "status": str(r[14]) if len(r) > 14 and r[14] is not None else "",   # #363: '' | knocked_out | advancing | champion
                    "sourceUrl": placed.get("listingUrl", "") if origin == MIRROR else ""})
    return out


class BuildRun:
    """Drives one build in the market. Pieces that touch the outside are injected so tests run on fakes (no market, no call, no network):
      clients  {"buyer", "referee", "seller:<id>"} with .call(reducer, **args) and .sql(query), as demo/bridge.py uses them
      catalog  (spec, index) -> [Seller]                 price_check  (listing) -> recheck result (demo.sponsors_live.price_recheck)
      crs_check (payee) -> CRS result                    cartesia     a pay.voice_cartesia.CartesiaClient, or None (no call can be placed)
    Order: goal, then one need and sealed round per part (each closed before the next opens), then `settle`: champions, live re-check,
    the allowance rule, ONE call or no call, one mandate per part's rank 1, one payment and receipt per part."""

    def __init__(self, plan: BuildPlan, clients: dict, *, catalog: Optional[Callable] = None, allowance: Optional[dict] = None,
                 price_check: Optional[Callable[[dict], dict]] = None, crs_check: Optional[Callable[[str], dict]] = None,
                 cartesia: Any = None, secret: Optional[str] = None, buyer_name: str = "Vidyut", use_stripe: bool = False,
                 env: Optional[dict] = None, stripe_test: Optional[Callable] = None, out_dir: Optional[Path] = OUT_DIR,
                 say: Callable = lambda step: None, note: Callable[[str], None] = lambda text: None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc), delay: float = 2.0, bid_window: Optional[int] = None,
                 plan_events: Optional[list] = None, checks: Optional[list] = None, on_code: Optional[Callable[[str], None]] = None,
                 recheck_timeout: float = RECHECK_TIMEOUT_S, call_timing: Optional[dict] = None, real_gpu_round: bool = True):
        self.plan, self.clients, self.allowance = plan, clients, allowance
        self.catalog = catalog or default_catalog
        self.price_check, self.crs_check, self.cartesia, self.secret = price_check, crs_check, cartesia, secret
        self.buyer_name, self.use_stripe, self.env, self.stripe_test = buyer_name, use_stripe, env or {}, stripe_test
        self.out_dir, self._say, self.note, self.sleep, self.clock, self.now = out_dir, say, note, sleep, clock, now
        self.delay, self.bid_window, self.on_code = delay, bid_window, on_code
        self.recheck_timeout, self.call_timing, self.real_gpu_round = recheck_timeout, call_timing or {}, real_gpu_round
        self.plan_events = list(plan_events or [])
        self.checks = list(checks or [])
        self.ledger: dict[str, dict] = {}
        self.needs: list[dict] = []
        self.rounds: list[dict] = []
        self.results: list[dict] = []
        self.mandates: list[dict] = []
        self.payments: list[dict] = []
        self.live: dict[str, dict] = {}
        self.approval: dict[str, Any] = {"state": "waiting", "events": []}
        self._full: list[dict] = []   # the full pay.mandate dicts behind self.mandates
        self._verified: set[str] = set()   # mandate hashes whose approval was read back from the market
        self.goal_posted = False
        self.step_no = 0
        self._warned = False

    # ---- the view

    def snapshot(self) -> dict:
        """market_rows for build_view: what this run wrote to the market and read back from it (round_result is the market's own)."""
        p = self.plan
        items = [{"part": o.part, "label": o.label, "skippedOwnedPartId": f"owned-{o.part}", "budget": 0.0} for o in p.owned]
        items += [{"part": s.part, "label": s.label, "skippedOwnedPartId": "", "budget": s.budget} for s in p.parts]
        return {"goal": {"id": p.goal_id, "buyerId": p.buyer_id, "cap": p.cap, "origin": SIM, "type": "build_by_date"}, "goalItems": items,
                "needs": self.needs, "rounds": self.rounds, "roundResults": self.results, "mandates": self.mandates, "approvals": [],
                "payments": self.payments, "approval": self.approval, "liveChecks": self.live}

    def view(self) -> dict:
        return build_view(self.snapshot(), self.plan_events, self.checks)

    def publish(self) -> dict:
        """Write the latest BuildView to out_dir/build-view.json (atomic) and one line to build-view.steps.jsonl. A failed write is one note."""
        v = self.view()
        if self.out_dir is not None:
            try:
                self.out_dir.mkdir(parents=True, exist_ok=True)
                tmp = self.out_dir / (VIEW_FILE + ".tmp")
                tmp.write_text(json.dumps(v, indent=1, sort_keys=True), encoding="utf-8")
                os.replace(tmp, self.out_dir / VIEW_FILE)
                with open(self.out_dir / STEPS_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(v, sort_keys=True, separators=(",", ":")) + "\n")
            except OSError as e:
                if not self._warned:
                    self._warned = True
                    self.note(f"BuildView not written to {self.out_dir} ({type(e).__name__}); the run goes on")
        self.step_no += 1
        return v

    def _hook(self, step) -> None:
        """Called by bridge.execute before each reducer call: the console line, then the view as it stands."""
        self._say(step)
        at = _stamp(self.now())
        if step.reducer == "post_goal":
            self.goal_posted = True
            self._start_steps_file()
            if not any(e.get("kind") == "plan" for e in self.plan_events):   # the planner's own plan line (phase 2) wins
                self.plan_events.append({"at": at, "kind": "plan", "text": self._plan_line(), "parts": [], "origin": SIM})
        elif step.reducer == "post_need":
            a = step.args
            part = next(s.part for s in self.plan.parts if need_id(self.plan.goal_id, s.part) == a["id"])
            self.needs.append({"id": a["id"], "goalId": a["goal_id"], "part": part, "spendLimit": a["spend_limit"], "origin": SIM})
        elif step.reducer == "open_round":
            self.rounds.append({"id": step.args["round_id"], "needId": step.args["need_id"], "state": "open", "openedAt": at,
                                "closedAt": "", "origin": SIM})
        self.publish()

    def _start_steps_file(self) -> None:
        """A new run starts the replay file over; the latest-view file is rewritten at every step anyway."""
        if self.out_dir is not None:
            try:
                self.out_dir.mkdir(parents=True, exist_ok=True)
                (self.out_dir / STEPS_FILE).write_text("", encoding="utf-8")
            except OSError:
                pass   # publish() says so once

    def _plan_line(self) -> str:
        owned = [o.part.upper() if len(o.part) <= 3 else o.part for o in self.plan.owned]
        return (f"Plan: {len(self.plan.parts)} parts to buy" + (f", {_and(owned)} owned" if owned else "")
                + f", budget ${self.plan.cap:,.0f}")

    # ---- rounds

    def _execute(self, steps: list) -> None:
        from demo import bridge
        bridge.execute(steps, self.clients, delay=self.delay, say=self._hook, sleep=self.sleep, clock=self.clock, note=self.note)

    def _run_part(self, index: int, spec: PartSpec) -> None:
        steps, ledger = part_steps(self.plan, spec, index, self.catalog(spec, index), now=self.now(), delay=self.delay,
                                   bid_window=self.bid_window, real_gpu_round=self.real_gpu_round)
        self.ledger.update(ledger)
        self._execute(steps)
        rid = round_id(self.plan.goal_id, spec.part)
        results, closed = self._read_results({rid})
        self.results = [r for r in self.results if r["roundId"] != rid] + results
        for r in self.rounds:
            if r["id"] == rid and rid in closed:   # closed only when the market says so: a close that did not happen is not a result
                r["state"], r["closedAt"] = "closed", _stamp(self.now())
        self.publish()

    def _read_results(self, round_ids: set) -> tuple[list[dict], set]:
        """(the round_result rows of closed rounds as dicts, the ids of the rounds the market reports closed). Rows of a round that is not
        closed are dropped: nothing in an open round is a champion."""
        referee = self.clients["referee"]
        closed = {r[0] for r in referee.sql("SELECT * FROM round") if r[0] in round_ids and len(r) > 5 and r[5] == "closed"}
        rows = referee.sql("SELECT * FROM round_result")
        return result_dicts(rows, self.ledger, closed), closed

    def run(self) -> dict:
        """The whole build. Returns {"status": "paid" | "denied" | "failed", "reason", "view"}. A reducer refusal raises RuntimeError with the
        market's own message, after the view is written."""
        try:
            self._execute(goal_steps(self.plan, self.allowance))
            for i, spec in enumerate(self.plan.parts):
                self._run_part(i, spec)
            return self.settle()
        finally:
            self.publish()

    # ---- champions

    def champions(self) -> tuple[dict, dict]:
        """({part: champion row}, {part: why none}) from the market's rank 1 of each part's closed round. A champion this run did not
        bid, held back, vetoed, or from a seller that never joined is never one."""
        got, bad = {}, {}
        for spec in self.plan.parts:
            rid = round_id(self.plan.goal_id, spec.part)
            row = next((r for r in self.rounds if r["id"] == rid), None)
            champ, why = (None, "no eligible bid: its round is not closed") if row is None or row["state"] != "closed" else \
                champion_of([r for r in self.results if r["roundId"] == rid])
            if champ is not None and champ["bidId"] not in self.ledger:
                champ, why = None, f"no eligible bid: {champ['persona']}'s bid was not placed by this build"
            if champ is None:
                bad[spec.part] = why
            else:
                got[spec.part] = champ
        return got, bad

    def _event(self, kind: str, text: str, parts: Optional[list] = None, origin: str = SIM) -> None:
        self.approval["events"].append({"at": _stamp(self.now()), "kind": kind, "text": text, "parts": parts or [], "origin": origin})

    def _deny(self, reason: str, line: str) -> dict:
        self.approval.update(state="denied", reason=line)
        self._event("denied", line)
        self.note(line)
        self.publish()
        return {"status": "denied", "reason": reason, "view": self.view()}

    # ---- the live re-check (Bright Data), one per MIRROR champion, in parallel and bounded

    def recheck(self, champs: dict) -> dict:
        """{part: result} for the champions on a real MIRROR listing. SIM champions have no listing to read and are not checked. Every
        read is bounded by one shared timeout; a failed, slow or empty read keeps the dated price and the event text says so."""
        from demo import sponsors_live as S
        todo = {}
        for part, c in champs.items():
            placed = self.ledger[c["bidId"]]
            if self.price_check is not None and c["origin"] == MIRROR and str(placed["listingUrl"]).startswith("http"):
                todo[part] = {"url": placed["listingUrl"], "price": float(c["landed"])}
        out: dict[str, dict] = {}
        if not todo:
            return out
        pool = cf.ThreadPoolExecutor(max_workers=len(todo))
        futs = {part: pool.submit(self.price_check, listing) for part, listing in todo.items()}
        end = time.monotonic() + self.recheck_timeout
        for part, fut in futs.items():
            try:
                out[part] = fut.result(timeout=max(0.0, end - time.monotonic()))
            except cf.TimeoutError:
                out[part] = {"state": "slow", "price": None, "fetched_at": None, "origin": MIRROR, "detail": f"over {self.recheck_timeout:g} s"}
            except Exception as e:  # noqa: BLE001  (never a crash and never a made-up LIVE price)
                out[part] = {"state": "empty", "price": None, "fetched_at": None, "origin": MIRROR, "detail": type(e).__name__}
        pool.shutdown(wait=False, cancel_futures=True)
        label = {s.part: s.label for s in self.plan.parts}
        for part, res in out.items():
            quoted = todo[part]["price"]
            date = str(self.ledger[champs[part]["bidId"]].get("snapshotDate") or "")[:10]
            text = f"{label[part]}: {S.price_note(res, quoted)}"
            if not S.is_live(res):
                text += f" (dated listing{' of ' + date if date else ''})"
            self.live[part] = {"state": res.get("state"), "price": res.get("price"), "fetchedAt": res.get("fetched_at"),
                               "origin": LIVE if S.is_live(res) else MIRROR, "quoted": quoted, "at": _stamp(self.now()), "text": text}
        self.publish()
        return out

    def _stop_reasons(self, checks: dict, champs: dict) -> list[str]:
        from demo import recheck as R
        label = {s.part: s for s in self.plan.parts}
        stops = []
        for part, res in checks.items():
            why = R.stop_reason(res, float(champs[part]["landed"]), label[part].budget)
            if why:
                stops.append(f"{label[part].label}: {why}")
        return stops

    # ---- settle: one call (or none) for the whole build

    def _crs(self, champs: dict) -> dict:
        """{seller id: crs_check_id or None}. A business payee needs a fresh verified CRS check (#257); any failure holds the payee gate."""
        from pay.crs_gate import check_id, payee_ok
        out: dict[str, Optional[str]] = {}
        if self.crs_check is None:
            self.note("CRS: no check function given, so no seller identity was checked")
            return out
        for sid in sorted({c["sellerId"] for c in champs.values()}):
            try:
                res = self.crs_check(sid)
                business = bool(res["business"])
                verdict = payee_ok(res.get("check"), business=business, seller_id=sid)
            except Exception as e:  # noqa: BLE001  (an unreadable profile, a timeout, an odd answer: all hold the gate)
                raise _Refused("crs_gate", f"CRS check failed ({type(e).__name__}), so the payee gate holds for {sid}") from None
            if not verdict:
                raise _Refused("crs_gate", f"CRS: {verdict.detail} ({verdict.reason}), so the payee gate holds for {sid}")
            out[sid] = check_id(res["check"]) if business else None
        return out

    def settle(self) -> dict:
        from demo.goal import needs_call
        label = {s.part: s.label for s in self.plan.parts}
        champs, bad = self.champions()
        if bad:
            return self._deny("no_eligible_bid", "No call: " + "; ".join(f"{label[p]}: {w}" for p, w in bad.items()) + ". Nothing was paid.")
        checks = self.recheck(champs)
        stops = self._stop_reasons(checks, champs)
        if stops:
            return self._deny("price_recheck", f"No call: {stops[0]}. Nothing was paid.")
        try:
            crs_ids = self._crs(champs)
        except _Refused as e:
            return self._deny(e.code, f"No call: {e}. Nothing was paid.")
        total = round(sum(float(c["landed"]) for c in champs.values()), 2)
        sellers = len({c["sellerId"] for c in champs.values()})
        # the buyer's allowance as the market holds it (its spent this period counts, and a limit the buyer tightened stays tightened), read
        # before any call or mandate. There is no fallback to the plan's numbers: an allowance that cannot be read cannot be put back.
        allowance = self._market_allowance()
        if allowance is None:
            return self._deny("allowance_unreadable", "No call: the buyer's allowance could not be read, so it could not be put back after "
                                                      "a call. Nothing was paid.")
        self._allowance_before = allowance
        call, why = needs_call(allowance, total)
        voice_id: Optional[str] = None
        if call:
            out = self._call(champs, checks, total, sellers)
            if isinstance(out, dict):
                return out
            voice_id = out
            denied = self._mandates_zeroed(champs, crs_ids, voice_id, allowance)
        else:
            self._mandates(champs, crs_ids, None)
            denied = None
        denied = denied or self._verify_approvals(voice_id)
        if denied:
            return denied
        if voice_id is None:
            self._event("approved", f"Inside your allowance: {money(total)} for {len(champs)} parts, no call", origin=SIM)
            self.approval.update(state="approved", method="allowance")
        self._pay()
        return {"status": "paid", "reason": "", "view": self.view()}

    # ---- the market's allowance, and approvals read back

    def _market_allowance(self) -> Optional[dict]:
        """The buyer's allowance row, read as the BUYER through the my_allowance view (the referee cannot read the private table, HTTP 400),
        or None when it cannot be read."""
        try:
            for r in self.clients["buyer"].sql("SELECT * FROM my_allowance"):
                if r[0] == self.plan.buyer_id:
                    return {"per_purchase_limit": float(r[2]), "period_limit": float(r[3]), "period": str(r[4]), "spent_this_period": float(r[5])}
        except (RuntimeError, OSError, ValueError, TypeError, IndexError):
            return None
        return None

    def _set_per_buy(self, original: dict, per: float) -> None:
        self.clients["referee"].call("set_allowance", buyer_id=self.plan.buyer_id, per_purchase_limit=per,
                                     period_limit=original["period_limit"], period=original["period"])

    def _mandates_zeroed(self, champs: dict, crs_ids: dict, voice_id: str, original: dict) -> Optional[dict]:
        """Make the per-part mandates after the call approved, with the buyer's per-purchase limit at $0 for the duration: the market
        approves any mandate at or under that limit by itself (method allowance, no voice id) and swallows the voice approval after it,
        so a part under the limit would be paid on the allowance instead of on the call. At $0 the market's own rule says "call" for every
        mandate. `original` is the row read before the call; the limit is restored to it in a `finally`; a restore that fails (or a hard kill
        between the zero and the restore) leaves it at $0, which fails closed, and says so. None, or a _deny dict."""
        if float(original["per_purchase_limit"]) <= 0:
            self._mandates(champs, crs_ids, voice_id)
            return None
        self._set_per_buy(original, 0.0)
        try:
            self._mandates(champs, crs_ids, voice_id)
        finally:
            try:
                self._set_per_buy(original, float(original["per_purchase_limit"]))
            except RuntimeError as e:
                self.note(f"WARNING: the buyer's per-purchase allowance could not be restored ({e}); it stays at $0, so every buy calls")
        return None

    def _approval_state(self) -> tuple[Optional[dict], Optional[dict]]:
        """(approvals by mandate hash {method, id} from the buyer's my_deals view, methods by mandate hash from the public floor events).
        Each is None when it cannot be read. my_deals: r[0] mandate hash, r[8] approval method, r[9] VoiceApproval id ('' for an allowance)."""
        referee = self.clients["referee"]
        rows = events = None
        try:
            rows = {r[0]: {"method": str(r[8]), "id": str(r[9])} for r in self.clients["buyer"].sql("SELECT * FROM my_deals")}
        except (RuntimeError, OSError, ValueError, TypeError, IndexError):
            pass
        try:
            label = {"Approved by voice code": "voice_code", "Approved within the allowance": "allowance"}
            events = {r[3]: label[r[5]] for r in referee.sql("SELECT * FROM floor_event") if r[1] == "approval_recorded" and r[5] in label}
        except (RuntimeError, OSError, ValueError, TypeError, IndexError):
            pass
        return rows, events

    def _verify_approvals(self, voice_id: Optional[str]) -> Optional[dict]:
        """Before any payment: every mandate must carry the approval this build expects, read back from the market. After the call that is a
        voice_code row with the call's VoiceApproval id; inside the allowance, an allowance row. Anything else (a part the market approved on
        the allowance, a swallowed approval, a table that cannot be read at all) denies the build visibly, releases the held units and pays
        nothing. The buyer's my_deals view gives method and id; if it cannot be read the public floor events give the method alone."""
        want = "voice_code" if voice_id else "allowance"
        rows, events = self._approval_state()
        bad = []
        for m in self.mandates:
            h = m["hash"]
            if rows is not None:
                got = rows.get(h)
                ok = got is not None and got["method"] == want and (want != "voice_code" or got["id"] == voice_id)
            elif events is not None:
                ok = events.get(h) == want
            else:
                ok = False
            if not ok:
                bad.append(m["part"])
        if not bad:
            self._verified = {m["hash"] for m in self.mandates}
            return None
        referee = self.clients["referee"]
        for m in self.mandates:
            try:
                referee.call("deny_approval", mandate_hash=m["hash"], reason="the build was not approved on every mandate")
            except RuntimeError:
                pass   # an already approved mandate cannot be denied; the unit hold ends by itself
        unreadable = rows is None and events is None
        what = "the call's voice approval" if voice_id else "an allowance approval"
        line = (f"No payment: the market's approvals could not be read back, so {what} on every mandate is unconfirmed. Nothing was paid." if unreadable
                else f"No payment: the market did not record {what} on every mandate ({', '.join(bad)}). Nothing was paid.")
        return self._deny("approval_unverified" if unreadable else "approval_missing", line)

    def _call(self, champs: dict, checks: dict, total: float, sellers: int):
        """The ONE approval call for the whole build. Returns the VoiceApproval id when it approved, else the _deny result dict."""
        import secrets as _secrets
        from pay.approval import ApprovalService
        from pay.mandate import can_charge, new_mandate
        from pay.replay import NonceStore
        from pay.voice_cartesia import CALL_CODE_TTL_S, denial_line, run_approval_call
        gid = self.plan.goal_id
        agg = new_mandate(deal_id=f"build-{gid}", buyer_id=self.plan.buyer_id, amount=total, payee=f"build-{gid}", goal_id=gid,
                          within_allowance=False, origin=_weakest([c["origin"] for c in champs.values()]))
        if self.cartesia is None:
            return self._deny("not_configured", f"{denial_line('not_configured')} The phone call is the only approval above the allowance.")
        self.approval["state"] = "calling"
        self._event("call", f"Calling {self.buyer_name} for the whole build: {len(champs)} parts from {sellers} sellers, {money(total)}")
        self.publish()
        store = NonceStore()
        service = ApprovalService(secret=self.secret or _secrets.token_hex(16), store=store, code_ttl_seconds=CALL_CODE_TTL_S)
        deal: dict[str, Any] = {"parts": len(champs), "sellers": sellers}
        if checks:
            deal["price"] = "live" if all(r.get("origin") == LIVE and r.get("price") is not None for r in checks.values()) else "mirror"
        res = run_approval_call(agg, self._why(), self.cartesia, service, deal=deal, buyer_name=self.buyer_name,
                                on_code=self.on_code or (lambda code: self.note(f"approval code for the call (read it, then say approve): {code}")),
                                **self.call_timing)
        if not res.approved:
            return self._deny(res.reason or "denied", f"{denial_line(res.reason)} No mandate was made.")
        voice_id = str((res.record or {}).get("id") or "").strip()
        if not voice_id:   # #240 keeps the VoiceApproval id on every approval row; an approval with none is not recorded
            return self._deny("no_voice_approval_id", "The call approved but left no VoiceApproval record, so nothing was paid.")
        try:
            now_results, _closed = self._read_results({round_id(gid, s.part) for s in self.plan.parts})
            before, self.results = self.results, now_results
            again, bad = self.champions()
            self.results = before
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, IndexError) as e:
            return self._deny("market_unreadable", f"The market could not be read after the call ({type(e).__name__}), so nothing was paid.")
        if bad or {p: c["bidId"] for p, c in again.items()} != {p: c["bidId"] for p, c in champs.items()}:
            return self._deny("market_changed", "The market's winners changed during the call, so nothing was paid.")
        now_total = round(sum(float(c["landed"]) for c in again.values()), 2)
        guard = can_charge(agg, deal_id=agg["deal_id"], amount=now_total, payee=agg["payee"], store=store)
        if not guard:
            return self._deny(f"can_charge: {guard.reason}", f"The approval does not match the market ({guard.reason}), so nothing was paid.")
        self.approval.update(state="approved", method="voice_code")
        self._event("approved", f"Approved on the call: {len(champs)} parts from {sellers} sellers, {money(total)}")
        self.publish()
        return voice_id

    def _why(self) -> dict:
        """The call's why-answer: the advocate's first veto in this build (the cheaper bid it kept out, with its fit rule and source),
        else the plain 'no problems found'."""
        for spec in self.plan.parts:
            for bid_id, p in self.ledger.items():
                if bid_id.startswith(f"bid-{need_id(self.plan.goal_id, spec.part)}-") and (p["card"] or {}).get("recommendation") == "veto":
                    return dict(p["card"]["call_reason"])
        return {"rule_id": "advocate.ok", "summary": "No problems found in the checks", "source_url": ""}

    def _mandates(self, champs: dict, crs_ids: dict, voice_id: Optional[str]) -> None:
        """One create_mandate per part's rank 1 (#240: the winning seller as payee, the landed price as amount), made only after the
        build was approved. After a call each mandate also gets the call's approval (voice_code, with the VoiceApproval id)."""
        from pay.mandate import new_mandate
        referee = self.clients["referee"]
        for spec in self.plan.parts:
            c = champs[spec.part]
            m = new_mandate(deal_id=f"deal-{c['bidId']}", buyer_id=self.plan.buyer_id, amount=float(c["landed"]), payee=c["sellerId"],
                            goal_id=self.plan.goal_id, within_allowance=voice_id is None, origin=_origin(c["origin"]),
                            crs_check_id=crs_ids.get(c["sellerId"]))
            referee.call("create_mandate", hash=m["hash"], id=m["id"], deal_id=m["deal_id"], buyer_id=m["buyer_id"], amount=m["amount"],
                         payee=m["payee"], expiry_minutes=MANDATE_MINUTES, nonce=m["nonce"], requested_by="", origin=m["origin"])
            self._full.append(m)
            self.mandates.append({"hash": m["hash"], "dealId": m["deal_id"], "amount": m["amount"], "payee": m["payee"], "part": spec.part})
            if voice_id is not None:
                referee.call("record_approval", mandate_hash=m["hash"], method="voice_code", approved_by=self.plan.buyer_id,
                             voice_approval_id=voice_id)
            self.publish()

    def _pay(self) -> None:
        """One payment and one receipt per part, through the same charger the bridge uses (the SIM stub, or a Stripe TEST charge)."""
        from demo.approval_flow import charge_or_stub
        referee = self.clients["referee"]
        for m, row in zip(self._full, self.mandates):
            if m["hash"] not in self._verified:   # never charge (a Stripe TEST charge included) what the market has not approved
                raise RuntimeError(f"no confirmed approval for the {row['part']} mandate; nothing was charged")
            ch, why = charge_or_stub(m, self.env, self.use_stripe, self.stripe_test)
            if why:
                self.note(why)
            test = ch["mode"] == "Stripe test mode"
            cents = int(round(m["amount"] * 100))
            try:
                referee.call("record_payment", mandate_hash=m["hash"], payment_ref=ch["id"], amount=m["amount"],
                             mode="stripe_test" if test else "sim")
            except RuntimeError as e:
                self.approval.update(state="denied", reason=f"the market refused a payment: {e}")
                self._event("denied", f"The market refused the payment for {row['part']}: {e}", [row["part"]])
                self.publish()
                raise
            self.payments.append({"mandateHash": m["hash"], "paymentRef": ch["id"], "amount": m["amount"], "mode": "stripe_test" if test else "sim",
                                  "at": _stamp(self.now()), "part": row["part"],
                                  "text": f"{'stripe_test' if test else 'SIM'} payment confirmed for deal {m['deal_id']}: "
                                          f"${cents // 100}.{cents % 100:02d}, reference {ch['id']}, mandate {m['hash'][:12]}."})
            self.publish()


class _Refused(Exception):
    def __init__(self, code: str, text: str):
        super().__init__(text)
        self.code = code


# ---------------------------------------------------------------- the CLI

def preview_steps(plan: BuildPlan, allowance: Optional[dict], *, catalog: Optional[Callable] = None, delay: float = 2.0,
                  bid_window: Optional[int] = None, now: Optional[datetime] = None, real_gpu_round: bool = True) -> list:
    """Every reducer call of the goal and the rounds, in order, without a market (the settle step needs the market's ranking)."""
    now = now or datetime.now(timezone.utc)
    catalog = catalog or default_catalog
    steps = goal_steps(plan, allowance)
    for i, spec in enumerate(plan.parts):
        steps += part_steps(plan, spec, i, catalog(spec, i), now=now, delay=delay, bid_window=bid_window, real_gpu_round=real_gpu_round)[0]
    return steps


def main(argv: Optional[list] = None) -> int:
    import argparse
    from demo import bridge
    from demo.common import Narrator
    ap = argparse.ArgumentParser(description="Drive a full PC build in the market: a round per part, one call for the whole build, a receipt per part")
    ap.add_argument("--step-delay", type=float, default=2.0, help="seconds between visible steps (default 2)")
    ap.add_argument("--dry-run", action="store_true", help="print the reducer calls only")
    ap.add_argument("--reset", action="store_true", help="call reset_demo first (referee): wipes needs, goals, rounds; keeps roles and pair codes")
    ap.add_argument("--live-call", action="store_true", help="above the allowance, place ONE real Cartesia approval call; also turns the Bright Data re-check on")
    ap.add_argument("--recheck", action="store_true", help="re-check each MIRROR champion's price live with Bright Data (one scrape each, inside its call budget)")
    ap.add_argument("--stripe", action="store_true", help="with --live-call only: one Stripe TEST charge per part (sk_test_ key only) after the call approves")
    ap.add_argument("--per-buy", type=float, default=250.0, help="the buyer's per-purchase allowance (default 250, SIM)")
    ap.add_argument("--period-limit", type=float, default=500.0, help="the buyer's allowance per month (default 500, SIM)")
    ap.add_argument("--env-file", type=Path, default=None, help="where the CARTESIA_* and sponsor names are read from")
    ap.add_argument("--tokens-dir", help="folder with referee.json and buyer-vidyut.json (default: auto-detect)")
    ap.add_argument("--buyer-id", default=bridge.DB_BUYER_ID)
    ap.add_argument("--goal-id", default="goal-build-1")
    ap.add_argument("--no-assign-roles", action="store_true", help="skip the owner assign_role step for seller identities")
    ap.add_argument("--server", default=None, help="spacetime -s server (default from the env or the Lane D env file)")
    ap.add_argument("--bid-window", type=bridge.bid_window_arg, default=None, help="seconds each part's sealed round stays open")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR, help="where build-view.json is written at every step")
    args = ap.parse_args(argv)
    if args.stripe and not args.live_call:
        ap.error("--stripe needs --live-call: a Stripe test charge runs only after a real phone call approves (there is no scripted approval)")
    plan = demo_plan(goal_id=args.goal_id, buyer_id=args.buyer_id)
    plan.deadline = _stamp(datetime.now(timezone.utc) + timedelta(days=7))
    allowance = {"per_purchase_limit": args.per_buy, "period_limit": args.period_limit, "period": "month"}
    out = Narrator(True)
    out.note("Tech Bazaar build: one goal, a sealed round per part, one call for the whole build (#345)")
    out.note("Sellers: SIM, plus the real dated MIRROR listings for the GPU. Payment is the SIM stub unless --live-call --stripe. Tags: [MIRROR] [SIM] [LIVE].")

    def say(s) -> None:
        if s.reducer == "set_floor":
            return
        who = "buyer" if s.actor == "buyer" else "referee" if s.actor == "referee" else s.actor.replace("seller:", "seller ")
        out.line(s.tag if s.tag in bridge.LIVE_TAGS else SIM, f"{who:<26}{s.reducer:<22}{s.say}")

    steps = preview_steps(plan, allowance, delay=args.step_delay, bid_window=args.bid_window)
    if args.dry_run:
        for s in steps:
            say(s)
        out.blank()
        out.note(f"then, once every part has a champion: re-check prices, and above {money(args.per_buy)} ONE call for the whole build "
                 f"(inside it: no call, method allowance), a mandate per part's rank 1, a payment and a receipt per part")
        return 0
    from demo import market_target
    from demo.run_demo import DEFAULT_ENV_FILE
    approver_env = args.env_file or DEFAULT_ENV_FILE
    cartesia, price_check = None, None
    if args.live_call or args.recheck:
        from demo import sponsors_live as S
        S.load_sponsor_env(approver_env)
        price_check = S.price_recheck
    buyer_name = "Vidyut"
    secret = None
    if args.live_call:
        from pay import voice_cartesia as vc
        env = vc.load_env(approver_env)
        buyer_name, secret = env.get(vc.NAME_ENV) or vc.DEFAULT_BUYER_NAME, env.get(vc.SECRET_ENV)
        try:
            cartesia = vc.CartesiaClient.from_env(env)
            out.note(f"live call: ONE call to {vc.mask_number(cartesia.approval_call_to)} for the whole build, only above the allowance")
        except vc.CartesiaError as e:
            out.note(f"live call: Cartesia NOT configured ({e}), so a build above the allowance is DENIED and nothing is paid")
    else:
        out.note("No --live-call: a build above the allowance stops before any call. Nothing is paid.")
    target = bridge.live_target(args)
    out.note(market_target.describe(target))
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    try:
        from stdb import Market
        tokens = bridge.find_tokens_dir(args.tokens_dir, target)
        seller_tokens = market_target.tokens_dir(target)
        seller_tokens.mkdir(parents=True, exist_ok=True)
        clients: dict[str, Any] = {"buyer": Market(token_file=str(tokens / bridge.BUYER_TOKEN)),
                                   "referee": Market(token_file=str(tokens / bridge.REFEREE_TOKEN))}
        seller_ids = sorted({s.actor.split(":", 1)[1] for s in steps if s.actor.startswith("seller:")})
        for sid in seller_ids:
            clients[f"seller:{sid}"] = Market(token_file=str(seller_tokens / f"bridge-{sid}.json"))
        if not args.no_assign_roles:
            import shutil
            spacetime = shutil.which("spacetime") or str(Path.home() / ".local" / "bin" / "spacetime")
            bridge.assign_seller_roles(seller_ids, clients, spacetime, target["server"], target["db"])
        if args.reset:
            out.note("reset_demo (referee): clearing the demo tables")
            clients["referee"].call("reset_demo")
            time.sleep(1)
        from demo.run_demo import stripe_env
        run = BuildRun(plan, clients, allowance=allowance, price_check=price_check, crs_check=bridge.default_crs_check, cartesia=cartesia,
                       secret=secret, buyer_name=buyer_name, use_stripe=args.stripe,
                       env={**os.environ, **stripe_env(DEFAULT_ENV_FILE)} if args.stripe else {}, out_dir=args.out_dir, say=say,
                       note=out.note, delay=args.step_delay, bid_window=args.bid_window)
        res = run.run()
    except RuntimeError as e:
        out.blank()
        out.note(f"STOPPED by the market: {e}")
        return 1
    except (OSError, subprocess.CalledProcessError) as e:
        out.blank()
        out.note(f"STOPPED: the market is not reachable or a tool failed ({type(e).__name__}). Start it with `python3 scripts/launch.py up`.")
        return 1
    out.blank()
    v = res["view"]
    out.note(f"build {res['status']}: {v['approval']['total']:,.2f} for {len([p for p in v['parts'] if p['status'] != 'owned'])} parts from "
             f"{v['approval']['sellers']} sellers; BuildView in {args.out_dir / VIEW_FILE}")
    return 0 if res["status"] == "paid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
