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
import heapq
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.mirror import not_partners  # noqa: E402
from demo.common import LIVE, MIRROR, SIM, money, shield_mode_line  # noqa: E402

OUT_DIR = ROOT / "demo" / "out"
VIEW_FILE = "build-view.json"          # the latest BuildView, rewritten at every step
STEPS_FILE = "build-view.steps.jsonl"  # one BuildView per line, in order: the board can replay a run
PARTS = ("gpu", "cpu", "board", "ram", "ssd", "cooler", "psu", "case")
PLANNER_PART = {"gpu": "gpu", "cpu": "cpu", "motherboard": "board", "memory": "ram", "storage": "ssd", "cooler": "cooler",
                "psu": "psu", "case": "case"}   # the planner's part ids (agents/buyer/planner.py) -> the board's
DEFAULT_LABELS = {"gpu": "RTX 5070 Ti", "cpu": "8-core CPU", "board": "ATX motherboard", "ram": "32 GB DDR5", "ssd": "2 TB NVMe",
                  "cooler": "Tower cooler", "psu": "750 W PSU", "case": "Case (305 mm GPU room)"}
CHECK_KEY = {v: k for k, v in PLANNER_PART.items()}   # the board's part ids -> data.fit_checker.build_check's category keys
# data.fit_checker rule id -> (the board's rule, part a, part b). Rules outside the board's five (RAM form and slots, storage) are not shown.
FIT_RULES = {"fit.cpu_socket": ("socket", "cpu", "board"), "fit.cooler_socket": ("socket", "cpu", "cooler"), "fit.ram_type": ("ddr", "board", "ram"),
             "fit.gpu_length": ("case_room", "gpu", "case"), "fit.form_factor": ("case_room", "board", "case"),
             "fit.psu_form_factor": ("case_room", "psu", "case"), "fit.psu_wattage": ("power", "gpu", "psu"),
             "fit.gpu_connectors": ("power", "gpu", "psu"), "fit.cooler_height": ("cooler_height", "cooler", "case")}
FIT_STATE = {"pass": "ok", "fail": "clash", "uncertain": "unknown"}
CHECK_STATES_BAD = {"ok": 0, "unknown": 1, "clash": 2}   # which of two states for one line wins: the worse
# what the buyer already owns, in the planner's shape (the specs the fit checker reads): #358's OWNED in agents/buyer/build_plan_demo.py
DEMO_OWNED = {"psu": {"name": "750 W PSU", "wattage": 750, "form_factor": "ATX", "pcie_16pin": 1},
              "case": {"name": "Case (305 mm GPU room)", "max_gpu_length_mm": 305, "max_cooler_height_mm": 160,
                       "motherboard_form_factors": ["ATX", "Micro ATX"], "psu_form_factors": ["ATX"]}}
PLANNER_CAP_CENTS = 210_000   # the demo's $2,100 cap: the planner's 1250/1975 GPU share is about $1,329, above the real GPU listings' $1,300
STAGGER_S = 2.0               # default gap between part rounds opening: six parts open within 10 s
CLOSE_GAP_S = 1.0             # staggered rounds close at least this far apart, in part order
CLOSE_RETRIES = 11            # a refused close_stage is retried this often, one second apart (bridge.execute's own count)
CLOSE_MARGIN_S = 0.5         # a close is scheduled this long after its deadline (the market's clock starts when its open call lands)
REPLAN_WINDOW_S = 20          # a re-plan round is short: the demo beat is 90 s
STAGE_BID_S = 1.0             # a knockout stage's improved offers go in this long after the stage opens
MAX_STAGES = 3
MIN_STAGE_WINDOW_S = 15       # bridge.MIN_BID_WINDOW_S: the shortest sealed window the steps fit in
STAGE_DROP = 0.97             # a survivor's improved offer: 3 percent under its last one, never under its floor
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


def fit_checks(owned: list, picks: dict) -> list[dict]:
    """The BuildView's `checks`: data.fit_checker.build_check (Lane C, #342) over the parts the buyer owns and the locked champions.
    `owned` is [PartSpec] (its attrs are the specs the buyer gave); `picks` is {part: {"name", "attrs"}} for the parts that have a champion.
    One line per rule that ran, between the two parts it compares: state ok (pass), clash (fail) or unknown (the checker could not judge:
    never ok), detail the checker's reason, source its rule id. Nothing here decides a fit."""
    from data.fit_checker.build_check import check_build
    if not picks:
        return []
    cards: dict[str, Any] = {CHECK_KEY[o.part]: {"name": o.label, **o.attrs} for o in owned}
    cards.update({CHECK_KEY[part]: {"name": p["name"], **p["attrs"]} for part, p in picks.items()})
    if "storage" in cards:
        cards["storage"] = [cards["storage"]]
    lines: dict[tuple, dict] = {}
    for c in check_build(cards)["checks"]:
        rule = FIT_RULES.get(c["rule_id"])
        if rule is None:
            continue
        line = {"a": rule[1], "b": rule[2], "rule": rule[0], "state": FIT_STATE.get(c["verdict"], "unknown"),
                "detail": str(c.get("reason") or ""), "source": c["rule_id"]}
        key = (line["a"], line["b"], line["rule"])   # two checker rules can speak for one pair (PSU watts and 16-pin): one line, the worse state
        old = lines.get(key)
        if old is None or CHECK_STATES_BAD[line["state"]] > CHECK_STATES_BAD[old["state"]]:
            lines[key] = line
        elif line["state"] == old["state"]:
            old["detail"] += "; " + line["detail"]
    return list(lines.values())


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
    attrs: dict = field(default_factory=dict)   # an owned part's specs, as the buyer gave them (the fit checker reads them)

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
    plan_line: str = ""    # the planner's own one-line plan (its first "plan" step), shown as the plan event when it has one


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
        info = info if isinstance(info, dict) else {}
        name = info.get("name")
        owned.append(PartSpec(part, name if isinstance(name, str) and name.strip() else names[part], 0.0,
                              {k: v for k, v in info.items() if k != "name"}))
    line = next((s.get("line") for s in plan.get("steps") or [] if isinstance(s, dict) and s.get("kind") == "plan" and isinstance(s.get("line"), str)), "")
    return BuildPlan(goal_id, buyer_id, cap, parts, owned, deadline or "", line or "")


def demo_plan(*, goal_id: str = "goal-build-1", buyer_id: str = "vidyut") -> BuildPlan:
    """SIM: six parts to buy, PSU and case owned, a $2,100 cap. The GPU budget ($1,300) is the cap of the demo's own GPU goal, so the real
    GPU round (demo.round, the bridge's cast) has confirmed-fit bids inside it; the others are the board sample's numbers."""
    budgets = {"gpu": 1300.0, "cpu": 285.0, "board": 170.0, "ram": 100.0, "ssd": 120.0, "cooler": 55.0}
    owned = [PartSpec(PLANNER_PART[k], DEFAULT_LABELS[PLANNER_PART[k]], 0.0, {a: v for a, v in info.items() if a != "name"})
             for k, info in DEMO_OWNED.items()]
    return BuildPlan(goal_id, buyer_id, 2100.0, [PartSpec(p, DEFAULT_LABELS[p], b) for p, b in budgets.items()], owned)


class GoalNotFound(ValueError):
    """The buyer has no active build_by_date goal the runner can read (or it cannot be turned into a plan)."""


GOALS_SQL = "SELECT id, buyer_id, type, cap, deadline, state, created_at FROM my_goals"
GOAL_ITEMS_SQL = "SELECT goal_id, sku_spec, condition, variant, quantity, skipped_owned_part_id FROM my_goal_items"
# which board part a goal item's sku_spec names (the first match wins; "Tower cooler" is a cooler, "Case (305 mm GPU room)" a case)
SKU_PART = (("psu", r"\bpsu\b|power supply"), ("cooler", r"cooler|\baio\b|heatsink"), ("case", r"\bcase\b|tower|chassis"),
            ("board", r"motherboard|mobo|\bboard\b"), ("cpu", r"\bcpu\b|processor|ryzen|core i\d|core ultra"),
            ("gpu", r"\bgpu\b|graphics|\brtx\b|\bgtx\b|\brx \d"), ("ram", r"\bram\b|ddr\d|memory"), ("ssd", r"\bssd\b|nvme|storage|m\.2"))
SPLIT_BASE = {"gpu": 1300.0, "cpu": 285.0, "board": 170.0, "ram": 100.0, "ssd": 120.0, "cooler": 55.0}   # demo_plan's budgets: the SIM split


def _iso(value: Any) -> str:
    """A SpacetimeDB timestamp cell ([micros], micros, {"__timestamp_micros_since_unix_epoch__": micros}) or an ISO string, as an ISO UTC stamp."""
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, dict) and set(value) == {"__timestamp_micros_since_unix_epoch__"}:
        value = value["__timestamp_micros_since_unix_epoch__"]
    if isinstance(value, bool):
        raise GoalNotFound("the goal's deadline is not a time")
    if isinstance(value, int):
        return _stamp(datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value))
    if isinstance(value, str):
        try:
            return _stamp(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise GoalNotFound("the goal's deadline is not a time")


def read_buyer_goal(client: Any, buyer_id: str) -> tuple[dict, list[dict]]:
    """X's latest ACTIVE build_by_date goal and its goal_items, read with the buyer's own client through the my_goals and my_goal_items views.
    Only the buyer's own identity sees its goals (the tables are private and the views answer the caller's buyer role only: the referee reads
    none), so a client that is not this buyer's finds nothing and the error says so."""
    rows = [r for r in client.sql(GOALS_SQL) if len(r) >= 7]
    mine = [r for r in rows if r[1] == buyer_id]
    if rows and not mine:
        raise GoalNotFound(f"the goals this client can read belong to {rows[0][1]}, not {buyer_id}: pass the identity token of {buyer_id} with --buyer-token")
    live = sorted((r for r in mine if r[2] == "build_by_date" and r[5] == "ACTIVE"), key=lambda r: _iso(r[6]), reverse=True)
    if not live:
        why = "this client can read no goal at all (only the buyer's own identity can)" if not rows else "it has no ACTIVE build_by_date goal"
        raise GoalNotFound(f"no goal to build from for {buyer_id}: {why}")
    g = live[0]
    items = [{"sku_spec": str(r[1]), "condition": str(r[2]), "variant": str(r[3]), "quantity": r[4], "skipped_owned_part_id": str(r[5])}
             for r in client.sql(GOAL_ITEMS_SQL) if r[0] == g[0]]
    return {"id": g[0], "buyer_id": g[1], "type": g[2], "cap": float(g[3]), "deadline": _iso(g[4])}, items


def plan_from_goal(goal: dict, items: list[dict]) -> tuple[BuildPlan, list[str]]:
    """The BuildPlan of a buyer's own goal row: the cap and deadline as posted, a round for every item that is not skipped as owned, the owned
    items as owned. The goal row holds no per-part budget, so the budgets are the demo plan's split, scaled down when they would exceed the
    cap (SIM, said in the plan line). -> (plan, warnings). A goal this runner cannot build raises ValueError (nothing is bid on a guess)."""
    cap = float(goal["cap"])
    if not cap > 0:
        raise GoalNotFound("the goal's cap must be above zero")
    buy, own = [], []
    for it in items:
        sku = str(it.get("sku_spec") or "")
        part = next((p for p, rx in SKU_PART if re.search(rx, sku, re.I)), None)
        if part is None:
            raise GoalNotFound(f"cannot tell which part {sku!r} is")
        if it.get("quantity") != 1:
            raise GoalNotFound(f"{sku!r}: the build runner buys one of each part, the goal asks for {it.get('quantity')!r}")
        if part in [p for p, _ in buy] + [p for p, _ in own]:
            raise GoalNotFound(f"{part} is in the goal twice")
        (own if it.get("skipped_owned_part_id") else buy).append((part, sku))
    if not buy:
        raise GoalNotFound("the goal has nothing to buy: every part is marked as owned")
    for part, sku in buy:
        if part not in SPLIT_BASE:
            raise GoalNotFound(f"{sku!r}: the build runner cannot buy a {part} yet (it is built around the PSU and case you already own)")
    base = {p: SPLIT_BASE[p] for p, _ in buy}
    scale = min(1.0, cap / sum(base.values()))
    specs = [PartSpec(p, DEFAULT_LABELS[p], math.floor(b * scale * 100) / 100) for p, b in base.items()]
    from demo.bridge import DB_BUYER_ID
    owned_attrs = DEMO_OWNED if goal["buyer_id"] == DB_BUYER_ID else {}   # the demo's owned parts are Vidyut's; another buyer's specs are unknown, not invented
    owned = [PartSpec(p, DEFAULT_LABELS[p], 0.0, {a: v for a, v in (owned_attrs.get(p) or {}).items() if a != "name"}) for p, _ in own]
    warnings = []
    gpu = next((s for p, s in buy if p == "gpu"), None)
    if gpu is not None and gpu.strip().lower() != DEFAULT_LABELS["gpu"].lower():
        warnings.append(f"the goal names {gpu!r}; the GPU round runs on the demo's {DEFAULT_LABELS['gpu']} listings (data/ holds no other card)")
    line = (f"Plan from {goal['buyer_id']}'s own goal {goal['id']}: {len(specs)} parts to buy, {len(owned)} owned, cap ${cap:,.0f}; "
            f"part budgets are a SIM split of the cap (a goal stores none)")
    return BuildPlan(goal["id"], goal["buyer_id"], cap, specs, owned, goal["deadline"], line), warnings


def planned_build(*, planner: Any = "auto", note: Callable[[str], None] = lambda text: None, goal_id: str = "goal-build-1",
                  buyer_id: str = "vidyut") -> tuple[BuildPlan, str]:
    """(the plan the build runs, "planner" or "default"). With `planner` "auto" the planner of #358 (agents.buyer.planner.plan) is used when it
    is importable; a main without it, or a planner whose output cannot be read, gives the default demo plan and says why. The adapter reads
    the planner's documented output (plan_from_planner); nothing of the planner is copied here."""
    fn = planner
    if planner == "auto":
        try:
            from agents.buyer.planner import plan as fn   # noqa: F811
        except ImportError:
            note("planner: agents.buyer.planner is not on this branch, so the default plan runs")
            fn = None
    if fn is None:
        return demo_plan(goal_id=goal_id, buyer_id=buyer_id), "default"
    try:
        owned = {k: dict(v) for k, v in DEMO_OWNED.items()}
        return plan_from_planner(fn(PLANNER_CAP_CENTS, owned), goal_id=goal_id, buyer_id=buyer_id), "planner"
    except (ValueError, KeyError, TypeError) as e:
        note(f"planner: its plan could not be used ({type(e).__name__}: {e}), so the default plan runs")
        return demo_plan(goal_id=goal_id, buyer_id=buyer_id), "default"


# ---------------------------------------------------------------- the sellers (SIM, plus the real MIRROR listings where data/ has them)

SIM_SELLERS = (("gadget-grove", "Gadget Grove (SIM)"), ("fair-price-pc", "Fair Price PC (SIM)"), ("bargain-bin", "Bargain Bin Hardware (SIM)"))
PRICE_FACTORS = (0.93, 0.96, 0.99)   # of the part's budget; rotated per part, so the cheapest seller changes from part to part
CASE_CLEARANCE_MM = 305              # the owned case's GPU room (the buyer shares it with sellers, never the cap)
TRAP_LENGTH_MM = 336                 # the SIM GPU line too long for that case: the advocate vetoes it, with the fit rule


AM5_BOARD = {"socket": "AM5", "memory_type": "DDR5", "memory_form": "DIMM", "memory_slots": 4, "form_factor": "ATX", "m2_slots": 2}
# the specs a SIM listing states, in the fit checker's names (a real listing's specs would come from its page; data/ holds none but the GPU's)
SIM_FIT_ATTRS = {"gpu": {"chipset": "RTX 5070 Ti"}, "cpu": {"socket": "AM5", "tdp_w": 105, "vendor": "AMD"}, "board": AM5_BOARD,
                 "ram": {"type": "DDR5", "memory_type": "DDR5", "memory_form": "DIMM", "modules": 2},
                 "ssd": {"interface": "NVMe"}, "cooler": {"height_mm": 155, "sockets": ["AM5"]}}
TRAP_SOCKET = "LGA1700"      # the cheapest SIM board is an Intel LGA1700 board: right size and price, wrong socket for the CPU the build locked


def default_catalog(spec: PartSpec, index: int, *, mirror: bool = True, trap: bool = True) -> list:
    """The sellers that bid on one part. SIM sellers for every part, priced inside the part's budget, with a rotating cheapest one;
    for the GPU, with `mirror`, the bridge's own cast (demo.sellers.all_sellers: the real dated MIRROR listings in data/mirror/snapshots
    plus the planted SIM sellers), judged by the real demo round; without it, a SIM GPU line too long for the owned case. data/ holds no
    other part's listings, so every other part is SIM and says so. Central Computers (not a partner) never bids here.
    With `trap` the cheapest SIM board is an LGA1700 board: the advocate has no CPU to compare it with while the rounds run side by side, so
    it wins its round and the fit check finds the clash once the CPU is locked (the re-plan). A re-plan round (default_replan_catalog) has no trap."""
    from demo.sellers import Line, Seller
    sellers = []
    for j, (sid, name) in enumerate(SIM_SELLERS):
        price = round(spec.budget * PRICE_FACTORS[(j + index) % 3], 2)
        url = f"https://example.com/sim/{sid}/{spec.part}"
        attrs = {"category": spec.part, **SIM_FIT_ATTRS.get(spec.part, {})}
        if spec.part == "gpu":
            attrs["length_mm"] = TRAP_LENGTH_MM if sid == "bargain-bin" else 303
        if spec.part == "gpu" and sid == "bargain-bin":
            price = round(spec.budget * 0.88, 2)      # the cheapest card is the trap
        if spec.part == "board" and sid == "bargain-bin" and trap:
            attrs["socket"] = TRAP_SOCKET
            price = round(spec.budget * 0.88, 2)      # the cheapest board is the trap
        line = Line("new", price, round(price * 0.9, 2), url, SIM, page_condition="new", attrs=attrs,
                    basis=f"SIM listing priced inside the {spec.label} budget")
        sellers.append(Seller(sid, name, SIM, [line], 0.0, 30, payee=f"{sid}@pay.example.test", shipping_captured=True,
                              claims=[{"text": "New, retail box", "kind": "spec", "field": "condition", "value": "new", "evidence_url": url}]))
    if mirror and spec.part == "gpu":
        from demo.sellers import all_sellers
        # the bridge's own cast: the real dated MIRROR listings plus the planted SIM sellers (a liar, a too-long card, a rogue under its floor)
        return [x for x in all_sellers()[0] if not not_partners.label({"seller_id": x.id})]
    return sellers


def default_replan_catalog(spec: PartSpec, index: int, clash: dict) -> list:
    """The sellers of a re-plan round: the same SIM sellers, now bidding on the part the need describes (the new need names what must fit), so
    no seller carries the trap. The clash line is what the planner asked about; the default catalog needs nothing from it."""
    return default_catalog(spec, index, mirror=False, trap=False)


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
               bid_window: Optional[int] = None, real_gpu_round: bool = False, attempt: int = 1, knockout: bool = False,
               max_stages: int = MAX_STAGES) -> tuple[list, dict]:
    """One part's need and sealed round: post_need, then bridge.round_steps (open, every seller's bid, Shield and advocate results, close).
    With `real_gpu_round` the GPU runs the bridge's own round (_demo_gpu_round) and `sellers` must be demo.sellers' cast.
    `attempt` 2 is the re-plan: a second need and round (ids end in -2) for the same part. With `knockout` (the market has #363's reducers)
    the round opens with open_knockout_round (stage_window_s = the sealed window, max_stages) and its stage 1 closes with close_stage; the
    later stages are driven by the BuildRun from the market's own results (stage_steps).
    Returns (steps, ledger) where the ledger maps each bid id to what this run placed (seller, persona, origin, listing, snapshot date,
    the advocate card, None when the round did not judge it, and what a later stage needs: the bid, its floor, the Shield verdict, the
    listing's specs): the driver only mandates a champion it can find here."""
    from demo import bridge
    nid, rid = need_id(plan.goal_id, spec.part, attempt), round_id(plan.goal_id, spec.part, attempt)
    r = (_demo_gpu_round if real_gpu_round and spec.part == "gpu" else _simple_round)(spec, sellers, nid, now)
    by_id = {s.id: s for s in sellers}
    steps = [bridge.Step("buyer", "post_need",
                         {"id": nid, "buyer_id": plan.buyer_id, "goal_id": plan.goal_id, "delivery_window": f"by {plan.deadline}",
                          "spend_limit": spec.budget, "consent": True, "auction_window_s": WINDOW_S, "origin": SIM, "items": [r["need_item"]]},
                         pause=True, say=f"{spec.label}: the need goes to sellers, budget {money(spec.budget)} kept from them")]
    steps += bridge.round_steps(
        round_no=1, need_id=nid, bids=r["bids"], ranking=r["ranking"],
        sellers={s.id: {"lines": [{"floor": l.floor} for l in s.lines]} for s in sellers}, shield=r["shield"], claims=r["claims"],
        cards=_cards_for_market(r["cards"], knockout), delay=delay, pace=0.5, window_s=bid_window, round_id=rid, label=f"{spec.label} round")
    if knockout:
        steps = [_knockout_step(s, max_stages) for s in steps]
    cards = {c["bid_id"]: c for c in r["cards"]}
    verdicts = {v["bid_id"]: v for v in r["shield"]}
    ledger = {}
    for b in r["bids"]:
        line = by_id[b["seller_id"]].lines[_cheapest(b)]
        ledger[b["id"]] = {"sellerId": b["seller_id"], "persona": b["persona"], "origin": b["origin"], "listingUrl": line.listing_url,
                           "snapshotDate": line.snapshot_date, "card": cards.get(b["id"]), "bid": b, "floor": min(l.floor for l in by_id[b["seller_id"]].lines),
                           "shield": verdicts.get(b["id"]), "attrs": {k: v for k, v in line.attrs.items() if k != "category"}, "part": spec.part,
                           "label": spec.label}
    return steps, ledger


def _cards_for_market(cards: list, knockout: bool) -> list:
    """The advocate cards as the market is sent them. A plain round holds a `caution` back by itself (#240). #363's closeStageInner ranks by price and
    never fills heldBack, so a cautioned bid (an unknown fit) would lead a knockout stage and could be crowned: in a knockout round a caution is
    sent as a veto worded "held back (caution)", which the market knocks out with that reason, visibly. The ledger keeps the real card."""
    if not knockout:
        return cards
    out = []
    for c in cards:
        if c["recommendation"] == "caution":
            why = c["call_reason"]
            c = {**c, "recommendation": "veto", "call_reason": {**why, "summary": f"held back (caution): {why['summary']}"}}
        out.append(c)
    return out


def _knockout_step(s, max_stages: int):
    """A sealed round's opener and closer as #363's reducers (docs/changes/1633-B-knockout-rounds.md): open_knockout_round(round_id, need_id,
    stage_window_s, max_stages) and close_stage(round_id). Every other step is the plain round's."""
    if s.reducer == "open_round":
        return replace(s, reducer="open_knockout_round", args={"round_id": s.args["round_id"], "need_id": s.args["need_id"],
                                                               "stage_window_s": s.args["window_s"], "max_stages": max_stages},
                       say=s.say.replace("opens sealed for", "opens as a knockout, stage 1 sealed for"))
    if s.reducer == "close_round":
        return replace(s, reducer="close_stage", say=s.say.replace("closes at its deadline", "closes stage 1 at its deadline"))
    return s


def stage_steps(placed: dict, survivors: list, rid: str, stage: int, *, delay: float) -> list:
    """The steps of knockout stage `stage` (2 or 3): each surviving seller's improved sealed offer (strictly below its own last one, never below
    its floor; none when it has no room, and the market then keeps its last offer), the same Shield verdict and advocate card on the new bid,
    then close_stage. `placed` is the run's ledger, `survivors` the bid ids the market marked advancing in the stage before."""
    from demo import bridge
    steps = []
    for bid_id in sorted(survivors):
        p = placed[bid_id]
        b = p["bid"]
        i = _cheapest(b)
        line = b["lines"][i]
        last = float(placed[bid_id].get("last", line["unit_price"]))
        new = round(max(float(p["floor"]), last * STAGE_DROP), 2)
        if new >= last:
            continue
        nid_ = f"{b['id']}-s{stage}"
        placed[nid_] = {**p, "last": new, "bidId": nid_}
        sku = line["sku_spec"]
        steps.append(bridge.Step(f"seller:{b['seller_id']}", "place_bid",
                                 {"id": nid_, "round_id": rid, "persona": b["persona"],
                                  "lines": [{"sku_spec": sku, "offered_spec": "", "offered_condition": line["offered_condition"], "unit_price": new,
                                             "quantity": line["quantity"]}],
                                  "stated_total": new * line["quantity"], "perks": list(b["perks"]), "claims": list(b["claims"]),
                                  "origin": b["origin"], "source": line["listing_url"]},
                                 tag=b["origin"], pause=True, pace=0.5,
                                 say=f"{b['persona']} improves its sealed offer for stage {stage}: {money(new)}"))
        if p.get("shield"):
            v = p["shield"]
            steps.append(bridge.Step("referee", "attach_verdict", {"bid_id": nid_, "verdict": v["verdict"], "rule_ids": list(v["rule_ids"]), "origin": SIM},
                                     tag=SIM, pause=False, say=f"Bazaar Shield on {b['persona']}'s stage {stage} offer: {v['verdict']}"))
        if p.get("card"):
            c = _cards_for_market([p["card"]], True)[0]
            why = c["call_reason"]
            steps.append(bridge.Step("referee", "attach_advocate_card",
                                     {"bid_id": nid_, "recommendation": c["recommendation"], "rule_id": why["rule_id"], "text": why["summary"],
                                      "source_url": why["source_url"], "origin": b["origin"]},
                                     tag=b["origin"], pause=False, say=f"advocate on {b['persona']}'s stage {stage} offer: {c['recommendation'].upper()}"))
    steps.append(bridge.Step("referee", "close_stage", {"round_id": rid}, close=True, tag=SIM, pause=True,
                             say=f"stage {stage} closes at its deadline: the market knocks out the last place and every rule-breaker"))
    return steps


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
        reasons = [str(x) for x in r[7]] if len(r) > 7 and isinstance(r[7], (list, tuple)) else []
        card = placed.get("card") or {}
        if card.get("recommendation") in ("caution", "veto") and r[5] >= 1 and not any(x.startswith(HELD_BACK) for x in reasons):
            # the market's knockout close (#363, closeStageInner) never fills heldBack, so it can crown a bid the advocate only cautioned
            # (an unknown fit): this run read that card itself, and a bid it cautioned or vetoed is held back here, never a champion
            why = card.get("call_reason") or {}
            reasons = [f"{HELD_BACK}: advocate {card['recommendation']} ({why.get('rule_id', '')}: {why.get('summary', '')})", *reasons]
        out.append({"roundId": r[1], "bidId": r[2], "sellerId": r[3], "persona": r[4], "rank": r[5], "landed": float(r[6]),
                    "reasons": reasons, "origin": origin,
                    "status": str(r[14]) if len(r) > 14 and r[14] is not None else "",   # #363: '' | knocked_out | advancing | champion
                    "sourceUrl": placed.get("listingUrl", "") if origin == MIRROR else ""})
    return out


def default_plan_line(plan: BuildPlan) -> str:
    owned = [o.part.upper() if len(o.part) <= 3 else o.part for o in plan.owned]
    return f"Plan: {len(plan.parts)} parts to buy" + (f", {_and(owned)} owned" if owned else "") + f", budget ${plan.cap:,.0f}"


@dataclass
class _Round:
    """One part's round in the timeline: its stage (a knockout round goes on to 2 and 3) and sealed window (the stage window)."""
    spec: PartSpec
    index: int
    attempt: int        # 1, or 2 for the re-plan
    rid: str
    window: int
    stage: int = 1


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
                 recheck_timeout: float = RECHECK_TIMEOUT_S, call_timing: Optional[dict] = None, real_gpu_round: bool = True,
                 stagger: Optional[float] = None, knockout: bool = False, max_stages: int = MAX_STAGES, replan: bool = True,
                 replan_catalog: Optional[Callable] = None, publisher: Optional[Callable[[str, str], None]] = None,
                 publish_interval: float = 1.0, relay_signals: Optional[Callable[[], Any]] = None, no_call_reason: str = "not_configured",
                 agent_addresses: Optional[dict] = None, reuse_goal: bool = False):
        self.plan, self.clients, self.allowance = plan, clients, allowance
        self.reuse_goal = reuse_goal   # the buyer's own goal is already in the market (plan_from_goal): the run never posts a second one
        self.agent_addresses = agent_addresses or {}   # the Fetch tile's agents: with them, a value this run really fetched is posted as a LIVE line
        self._proof_posted: set[str] = set()
        self.no_call_reason = no_call_reason   # why `cartesia` is None: "not_configured" (no setup) or "no_phone" (this buyer has no number)
        self.catalog = catalog or default_catalog
        self.replan_catalog = replan_catalog or default_replan_catalog
        self.stagger, self.knockout, self.max_stages, self.replan = stagger, knockout, min(MAX_STAGES, max(1, int(max_stages))), replan
        self.publisher, self.publish_interval = publisher, publish_interval
        self._last_sent = None
        self.schedule_s = 0.0          # the timeline's last scheduled second (virtual: the plan of the pacing, not what the clock read)
        self._last_close = None        # the previous part's close second, so staggered rounds close in part order
        self._need_part: dict[str, str] = {}
        self._stage: dict[str, int] = {}      # round id -> the stage a knockout round is in
        self._latest: dict[str, tuple] = {}   # part -> (need id, round id, attempt) of its newest round
        self._replans: dict[str, dict] = {}
        self._heap: list = []
        self._seq = 0
        self._t0 = 0.0
        self.price_check, self.crs_check, self.cartesia, self.secret = price_check, crs_check, cartesia, secret
        self.buyer_name, self.use_stripe, self.env, self.stripe_test = buyer_name, use_stripe, env or {}, stripe_test
        self.out_dir, self._say, self.note, self.sleep, self.clock, self.now = out_dir, say, note, sleep, clock, now
        self.delay, self.bid_window, self.on_code = delay, bid_window, on_code
        self.recheck_timeout, self.call_timing, self.real_gpu_round = recheck_timeout, call_timing or {}, real_gpu_round
        self.relay_signals = relay_signals   # demo/crs_relay.py, run right before each round opens (best effort); None in tests
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

    def _send(self, v: dict, throttled: bool) -> None:
        """Hand the view to the publisher (the market's publish_build_view, for the hosted board), at most once per `publish_interval` seconds
        for the per-step views; every other view (a champion, the call, a mandate, a receipt, the end) always goes. A publisher never raises into the run."""
        if self.publisher is None:
            return
        now = self.clock()
        if throttled and self._last_sent is not None and now - self._last_sent < self.publish_interval:
            return
        self._last_sent = now
        try:
            self.publisher(v["goalId"], json.dumps(public_view(v), sort_keys=True, separators=(",", ":")))   # no money or identity leaves this Mac
        except Exception as e:  # noqa: BLE001  (the board's copy is optional: nothing here may stop a build)
            self.note(f"BuildView not published ({type(e).__name__}); the run goes on")

    def publish(self, throttled: bool = False) -> dict:
        """Write the latest BuildView to out_dir/build-view.json (atomic) and one line to build-view.steps.jsonl, and hand it to the publisher
        when there is one. A failed write is one note."""
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
        self._send(v, throttled)
        self.step_no += 1
        return v

    def _hook(self, step) -> None:
        """Called by bridge.execute before each reducer call: the console line, then the view as it stands."""
        self._say(step)
        at = _stamp(self.now())
        if step.reducer == "post_goal":
            self.goal_posted = True
            self._start_steps_file()
            if not any(e.get("kind") == "plan" for e in self.plan_events):   # the planner's own plan line wins
                self.plan_events.append({"at": at, "kind": "plan", "text": self.plan.plan_line or self._plan_line(), "parts": [], "origin": SIM})
        elif step.reducer == "post_need":
            a = step.args
            self.needs.append({"id": a["id"], "goalId": a["goal_id"], "part": self._need_part[a["id"]], "spendLimit": a["spend_limit"], "origin": SIM})
        elif step.reducer in ("open_round", "open_knockout_round"):
            self.rounds.append({"id": step.args["round_id"], "needId": step.args["need_id"], "state": "open", "openedAt": at,
                                "closedAt": "", "origin": SIM})
        self.publish(throttled=True)

    def _goal_reused(self) -> None:
        """What _hook does for a post_goal step, for a goal that was already posted by the buyer: the run's clock starts and the plan line shows."""
        self.goal_posted = True
        self._start_steps_file()
        if not any(e.get("kind") == "plan" for e in self.plan_events):
            self.plan_events.append({"at": _stamp(self.now()), "kind": "plan", "text": self.plan.plan_line or self._plan_line(), "parts": [],
                                     "origin": SIM})
        self.publish(throttled=True)

    def _start_steps_file(self) -> None:
        """A new run starts the replay file over; the latest-view file is rewritten at every step anyway."""
        if self.out_dir is not None:
            try:
                self.out_dir.mkdir(parents=True, exist_ok=True)
                (self.out_dir / STEPS_FILE).write_text("", encoding="utf-8")
            except OSError:
                pass   # publish() says so once

    def _plan_line(self) -> str:
        return default_plan_line(self.plan)

    # ---- rounds

    def _execute(self, steps: list, delay: Optional[float] = None) -> None:
        from demo import bridge
        bridge.execute(steps, self.clients, delay=self.delay if delay is None else delay, say=self._hook, sleep=self.sleep, clock=self.clock,
                       note=self.note, before_round=self.relay_signals)

    # ---- the timeline: every part's steps at their scheduled second
    #
    # With `stagger` the part rounds open `stagger` seconds apart (six parts open within 10 s at the default 2 s) and close in part order, each
    # at least CLOSE_GAP_S after the one before; without it each part runs after the one before it (phase 1). Either way the reducer calls
    # are made one at a time, in time order, so the market sees exactly the calls the sequential run makes, only interleaved.

    def _at(self, t: float, fn: Callable[[float], None]) -> None:
        heapq.heappush(self._heap, (t, self._seq, fn))
        self._seq += 1

    def _times(self, steps: list, t0: float, deadline: Optional[float] = None) -> list[tuple[float, Any]]:
        """[(second, step)]: bridge.execute's own pacing (a pause after a paused step, a close waits for the round's deadline), as a schedule."""
        t, out = t0, []
        for s in steps:
            if s.close and deadline is not None:
                t = max(t, deadline + CLOSE_MARGIN_S)
            out.append((t, s))
            if s.window_s:
                deadline = t + s.window_s
            if s.pause and self.delay > 0:
                t += self.delay * s.pace
        return out

    def _schedule(self, timed: list) -> None:
        for t, s in timed:
            self._at(t, lambda _t, step=s: self._run_step(step))

    def _run_step(self, step) -> None:
        if step.reducer == "close_stage":
            return self._close_stage(step)
        self._execute([step], delay=0)

    def _stage_closed(self, rid: str, stage: int) -> bool:
        """True when the market has closed `stage` of round `rid` (the round is closed, or it has results for that stage): its own deadline
        scheduler (closeRoundOnDeadline -> closeStageInner) does this at the deadline, usually before the referee's call arrives."""
        referee = self.clients["referee"]
        if any(r[0] == rid and len(r) > 5 and r[5] == "closed" for r in referee.sql("SELECT * FROM round")):
            return True
        return any(r[1] == rid and len(r) > 13 and isinstance(r[13], int) and r[13] >= stage for r in referee.sql("SELECT * FROM round_result"))

    def _close_stage(self, step) -> None:
        """close_stage for a knockout stage. The real market closes a stage by itself at its deadline, so the referee's call can be refused
        ("round is still open until its deadline" once the next stage has opened, "round already closed" after the last): that is not a failure
        when the market's own rows show the stage closed. A refusal while the stage is really still open is retried a few times, then raised."""
        rid = step.args["round_id"]
        stage = self._stage.get(rid, 1)
        try:
            self._execute([replace(step, close=False)], delay=0)
            return
        except RuntimeError as e:
            err = e
        for _ in range(CLOSE_RETRIES):
            msg = str(err)
            if "already closed" in msg:
                return
            if "still open" not in msg:
                raise err
            if self._stage_closed(rid, stage):
                return
            self.sleep(1.0)
            try:
                self.clients["referee"].call("close_stage", round_id=rid)
                return
            except RuntimeError as e:
                err = e
        if "already closed" in str(err) or self._stage_closed(rid, stage):
            return
        raise err

    def _begin_round(self, spec: PartSpec, index: int, attempt: int, t: float, clash: Optional[dict] = None) -> None:
        sellers = self.catalog(spec, index) if attempt == 1 else self.replan_catalog(spec, index, clash or {})
        window = self.bid_window if attempt == 1 else min(self.bid_window or REPLAN_WINDOW_S, REPLAN_WINDOW_S)
        if window is None and self.knockout:
            window = MIN_STAGE_WINDOW_S    # three stages must fit the beat: each is a short sealed window
        steps, ledger = part_steps(self.plan, spec, index, sellers, now=self.now(), delay=self.delay, bid_window=window,
                                   real_gpu_round=self.real_gpu_round and attempt == 1, attempt=attempt, knockout=self.knockout,
                                   max_stages=self.max_stages)
        timed = self._times(steps, t)
        close_t = timed[-1][0]
        if self.stagger is not None and attempt == 1 and self._last_close is not None and close_t < self._last_close + CLOSE_GAP_S:
            extra = math.ceil(self._last_close + CLOSE_GAP_S - close_t)   # a longer window, so this round closes after the one before it
            opener = steps[1]
            key = "stage_window_s" if self.knockout else "window_s"
            wide = opener.args[key] + extra
            steps[1] = replace(opener, args={**opener.args, key: wide}, window_s=wide, say=re.sub(r"for \d+ s", f"for {wide} s", opener.say))
            timed = self._times(steps, t)
            close_t = timed[-1][0]
        if attempt == 1:
            self._last_close = close_t
        nid, rid = need_id(self.plan.goal_id, spec.part, attempt), round_id(self.plan.goal_id, spec.part, attempt)
        self._need_part[nid] = spec.part
        self._stage[rid] = 1
        self._latest[spec.part] = (nid, rid, attempt)
        self.ledger.update(ledger)
        ps = _Round(spec, index, attempt, rid, steps[1].window_s)
        self._schedule(timed)
        self._at(close_t, lambda t_, ps=ps: self._closed(ps, t_))

    def _start_part(self, index: int, t: float) -> None:
        if index >= len(self.plan.parts):
            return
        self._begin_round(self.plan.parts[index], index, 1, t)
        if self.stagger is not None and index + 1 < len(self.plan.parts):
            self._at((index + 1) * self.stagger, lambda t_, j=index + 1: self._start_part(j, t_))

    def _part_done(self, ps: "_Round", t: float) -> None:
        if self.stagger is None:
            self._start_part(ps.index + 1, t)

    def _closed(self, ps: "_Round", t: float) -> None:
        """A round's last step ran: read what the market made of it. A knockout round the market still reports open goes on to its next stage."""
        rid = ps.rid
        results, closed = self._read_results({rid})
        self.results = [r for r in self.results if r["roundId"] != rid] + results
        if self.knockout and rid not in closed and ps.stage < self.max_stages:
            return self._next_stage(ps, t)
        for r in self.rounds:
            if r["id"] == rid and rid in closed:   # closed only when the market says so: a close that did not happen is not a result
                r["state"], r["closedAt"] = "closed", _stamp(self.now())
        self.publish()
        self._finished(ps, t)

    def _next_stage(self, ps: "_Round", t: float) -> None:
        """Stage k+1 of a knockout round: the survivors the market marked advancing make their improved sealed offers, then the next close_stage."""
        rows = self.clients["referee"].sql("SELECT * FROM round_result")
        alive = [r[2] for r in rows if r[1] == ps.rid and len(r) > 14 and r[13] == ps.stage and r[14] == "advancing" and r[2] in self.ledger]
        ps.stage += 1
        self._stage[ps.rid] = ps.stage
        steps = stage_steps(self.ledger, alive, ps.rid, ps.stage, delay=self.delay)
        timed = self._times(steps, t + STAGE_BID_S, deadline=t + ps.window)
        self._schedule(timed)
        self._at(timed[-1][0], lambda t_, ps=ps: self._closed(ps, t_))

    def _picks(self) -> dict:
        """{part: {"name", "attrs", "champion"}} for each part whose newest round is closed with an eligible champion this run bid."""
        got = {}
        for spec in self.plan.parts:
            rid = self._rid(spec.part)
            row = next((r for r in self.rounds if r["id"] == rid), None)
            if row is None or row["state"] != "closed":
                continue
            champ, _why = champion_of([r for r in self.results if r["roundId"] == rid])
            if champ is not None and champ["bidId"] in self.ledger:
                placed = self.ledger[champ["bidId"]]
                got[spec.part] = {"name": placed["label"], "attrs": placed["attrs"], "champion": champ}
        return got

    def _rid(self, part: str) -> str:
        return self._latest[part][1] if part in self._latest else round_id(self.plan.goal_id, part)

    def _plan_event(self, kind: str, text: str, parts: list, origin: str = SIM) -> None:
        self.plan_events.append({"at": _stamp(self.now()), "kind": kind, "text": text, "parts": parts, "origin": _origin(origin)})

    def _finished(self, ps: "_Round", t: float) -> None:
        """A part's round is closed: re-run the fit check on everything locked so far (the owned parts count). A clash on this part's pick
        opens ONE re-plan, a second need and round for the part; a green re-check after a swap is an event of its own."""
        part = ps.spec.part
        picks = self._picks()
        lines = fit_checks(self.plan.owned, picks)
        self.checks = lines
        self.publish()
        if part in picks:
            clash = [c for c in lines if c["state"] == "clash" and part in (c["a"], c["b"])]
            if clash and ps.attempt == 1 and self.replan:
                return self._replan(ps, clash[0], picks, t)
            if not clash and ps.attempt == 2:
                rule = self._replans[part]["rule"]
                other = self._replans[part]["other"]
                for c in lines:
                    if c["rule"] == rule and part in (c["a"], c["b"]) and c["state"] == "ok":
                        self._plan_event("locked", f"{ps.spec.label}: fit re-check green, {c['detail']}", [part, other], picks[part]["champion"]["origin"])
                self.publish()
        self._part_done(ps, t)

    def _replan(self, ps: "_Round", clash: dict, picks: dict, t: float) -> None:
        """The pick breaks a fit rule against a part already locked: say so (red), swap by opening a new need and round for the part that names
        what must fit (green after it locks). The market still decides the winner of the new round."""
        part, spec = ps.spec.part, ps.spec
        other = clash["b"] if clash["a"] == part else clash["a"]
        every = {x.part: x for x in [*self.plan.owned, *self.plan.parts]}
        other_label = every[other].label
        other_attrs = picks[other]["attrs"] if other in picks else every[other].attrs
        champ = picks[part]["champion"]
        socket = other_attrs.get("socket") if clash["rule"] == "socket" else None
        wants = f"{spec.label} for {socket}" if socket else f"{spec.label} that fits the {other_label}"
        nid2 = need_id(self.plan.goal_id, part, 2)
        self._plan_event("clash", f"Clash: {champ['persona']}'s {spec.label} vs the {other_label}: {clash['detail']}", [part, other], champ["origin"])
        self.publish()   # red: the pick is locked in and the check says no
        self._plan_event("replan", f"Re-plan: {spec.label}: {champ['persona']} is out, a new round for {wants} ({nid2})", [part], champ["origin"])
        self._replans[part] = {"rule": clash["rule"], "other": other, "need": nid2}
        self._begin_round(PartSpec(part, wants, spec.budget), ps.index, 2, t, clash)

    def _read_results(self, round_ids: set) -> tuple[list[dict], set]:
        """(the round_result rows of closed rounds as dicts, the ids of the rounds the market reports closed). Rows of a round that is not
        closed are dropped: nothing in an open round is a champion."""
        referee = self.clients["referee"]
        closed = {r[0] for r in referee.sql("SELECT * FROM round") if r[0] in round_ids and len(r) > 5 and r[5] == "closed"}
        rows = referee.sql("SELECT * FROM round_result")
        return result_dicts(rows, self.ledger, closed), closed

    def run_rounds(self) -> None:
        """The goal, then every part's need and sealed round (and the re-plan of a part whose pick does not fit), in time order. Nothing is
        bought here: this is everything before the settle step, and what `--dry-run` runs on the in-memory market."""
        steps = goal_steps(self.plan, self.allowance)
        if self.reuse_goal:
            steps = [s for s in steps if s.reducer != "post_goal"]
            self._goal_reused()
        self._execute(steps)
        self._t0 = self.clock()
        self._at(0.0, lambda t: self._start_part(0, t))
        while self._heap:
            t, _seq, fn = heapq.heappop(self._heap)
            wait = t - (self.clock() - self._t0)
            if wait > 0:
                self.sleep(wait)
            self.schedule_s = max(self.schedule_s, t)
            fn(t)

    def run(self) -> dict:
        """The whole build. Returns {"status": "paid" | "denied" | "failed", "reason", "view"}. A reducer refusal raises RuntimeError with the
        market's own message, after the view is written."""
        try:
            self.run_rounds()
            return self.settle()
        finally:
            self.publish()

    # ---- champions

    def champions(self) -> tuple[dict, dict]:
        """({part: champion row}, {part: why none}) from the market's rank 1 of each part's newest closed round (a re-plan's second round
        replaces the first). A champion this run did not bid, held back, vetoed, or from a seller that never joined is never one."""
        got, bad = {}, {}
        for spec in self.plan.parts:
            rid = self._rid(spec.part)
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
        self.post_proof_events()
        self.publish()
        return out

    def post_proof_events(self) -> None:
        """Each part whose price this run read live (self.live origin LIVE) becomes one LIVE referee event on the buyer agent's Fetch tile,
        once. A part that kept its dated MIRROR price, or a SIM part, posts nothing. Best effort: it never stops a build."""
        if not self.agent_addresses or "referee" not in self.clients:
            return
        from demo import bridge
        label = {s.part: s.label for s in self.plan.parts}
        steps = []
        for part, v in self.live.items():
            res = {"state": v.get("state"), "price": v.get("price"), "fetched_at": v.get("fetchedAt"), "origin": v.get("origin")}
            for s in bridge.live_proof_steps(self.agent_addresses, price=res, quoted=float(v.get("quoted") or 0)):
                text = f"{label.get(part, part)}: {s.args['text']}"
                if text not in self._proof_posted:
                    self._proof_posted.add(text)
                    steps.append(replace(s, args={**s.args, "text": text}))
        bridge.post_proof_steps(self.clients["referee"], steps, self.note)

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
            self._post_crs_proof(sid, res)
        return out

    def _post_crs_proof(self, sid: str, res: dict) -> None:
        """A CRS band read from the sandbox in this run (never a cached or SIM one) is one LIVE line on the buyer agent's tile, once per seller."""
        if not self.agent_addresses or "referee" not in self.clients:
            return
        from demo import bridge
        steps = [s for s in bridge.live_proof_steps(self.agent_addresses, crs=res, seller=sid) if s.args["text"] not in self._proof_posted]
        self._proof_posted.update(s.args["text"] for s in steps)
        bridge.post_proof_steps(self.clients["referee"], steps, self.note)

    def settle(self) -> dict:
        from demo.goal import needs_call
        label = {s.part: s.label for s in self.plan.parts}
        champs, bad = self.champions()
        if bad:
            return self._deny("no_eligible_bid", "No call: " + "; ".join(f"{label[p]}: {w}" for p, w in bad.items()) + ". Nothing was paid.")
        self.checks = fit_checks(self.plan.owned, self._picks())   # the picks as they stand now: a part that still does not fit stops the build
        clash = next((c for c in self.checks if c["state"] == "clash"), None)
        if clash is not None:
            return self._deny("fit_clash", f"No call: the picked parts do not fit ({clash['detail']}). Nothing was paid.")
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
            denied = self._mandates_zeroed(champs, crs_ids, voice_id)
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

    def _mandates_zeroed(self, champs: dict, crs_ids: dict, voice_id: str) -> Optional[dict]:
        """Make the per-part mandates after the call approved, with the buyer's per-purchase limit at $0 for the duration: the market
        approves any mandate at or under that limit by itself (method allowance, no voice id) and swallows the voice approval after it,
        so a part under the limit would be paid on the allowance instead of on the call. At $0 the market's own rule says "call" for every
        mandate. The allowance is read again here, right after the call approved: the call is the longest window in the run, and a buyer who
        tightened their limit during it must get that limit back, not the one read before the call. The limit is restored in a `finally`; a
        restore that fails (or a hard kill between the zero and the restore) leaves it at $0, which fails closed, and says so.
        None, or a _deny dict."""
        original = self._market_allowance()
        if original is None:
            return self._deny("allowance_unreadable", "The buyer's allowance could not be read after the call, so it could not be put back. "
                                                      "No mandate was made and nothing was paid.")
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
            return self._deny(self.no_call_reason, f"{denial_line(self.no_call_reason)} The phone call is the only approval above the allowance.")
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
            now_results, _closed = self._read_results({self._rid(s.part) for s in self.plan.parts})
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


# ---------------------------------------------------------------- publishing the view for the hosted board

MARKET_INDEX = ROOT / "market" / "spacetimedb" / "src" / "index.ts"


def market_has_reducer(name: str, module: Path = MARKET_INDEX) -> bool:
    """True when the market module exports reducer `name` (bridge.market_has_typed_approval reads the module the same way). Feature detection
    for reducers a later market adds (open_knockout_round of #363, publish_build_view): an unreadable module says no."""
    try:
        text = Path(module).read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(rf"export\s+const\s+{re.escape(name)}\s*=\s*spacetimedb\.reducer\b", text) is not None


def deployed_has_reducer(client: Any, name: str, **probe_args: Any) -> bool:
    """True when the DEPLOYED market has reducer `name`, probed with a call that cannot do anything (arguments naming no real row, so a market
    that has the reducer refuses with its own message): an HTTP 404 "No such procedure" means the module was not republished. The module
    SOURCE can be ahead of Maincloud; this asks the one that will actually take the calls. An unreachable market says no."""
    try:
        client.call(name, **probe_args)
    except RuntimeError as e:
        msg = str(e)
        return not ("(404)" in msg or "No such procedure" in msg or "no such procedure" in msg)
    except OSError:
        return False
    return True


def resolve_knockout(mode: str, clients: dict, note: Callable[[str], None], module: Path = MARKET_INDEX) -> bool:
    """Whether the rounds are sealed knockouts. "on"/"off" are taken as given. "auto" needs the module source to have open_knockout_round AND the
    deployed market to answer close_stage (probed as the referee): otherwise the build runs plain one-stage rounds and says so, instead of
    stopping after the goal on a 404."""
    if mode != "auto":
        return mode == "on"
    if not market_has_reducer("open_knockout_round", module):
        return False
    if not deployed_has_reducer(clients["referee"], "close_stage", round_id="probe-no-such-round"):
        note("knockout: the module source has open_knockout_round but the deployed market does not (not republished), so the rounds are plain one-stage rounds")
        return False
    return True


def public_view(v: dict) -> dict:
    """The copy of a BuildView that goes to the hosted board. Admins and other users never see a buyer's spend or payment details, so it
    carries no mandate, hash, payee, amount, buyer id, budget or total: parts (status, origin, a champion's persona, landed price and source
    after the round closed), the fit checks, the events that are not about money (plan without its budgets, rounds, knockouts, locks, clash,
    re-plan) and `approval.state`. demo/out keeps the full view locally."""
    parts = []
    for p in v.get("parts") or []:
        q = {k: p[k] for k in ("part", "label", "status", "origin", "needId", "roundId", "reason") if k in p}
        if p.get("champion"):
            q["champion"] = {k: p["champion"][k] for k in ("persona", "landed", "origin", "sourceUrl") if k in p["champion"]}
        parts.append(q)
    buying = [p for p in parts if p["status"] != "owned"]
    events = []
    for e in v.get("events") or []:
        if e["kind"] not in PUBLIC_EVENT_KINDS or (e["kind"] == "locked" and not e.get("parts")):
            continue   # the call, the approval, receipts, a denial's reason and "Build ready" (the total) are spend and payment details
        text = e["text"]
        if e["kind"] == "plan":
            text = f"Plan: {len(buying)} parts to buy" + (f", {len(parts) - len(buying)} owned" if len(parts) > len(buying) else "")
        events.append({**{k: e[k] for k in ("at", "kind", "parts", "origin")}, "text": text})
    return {"goalId": v.get("goalId", ""), "origin": v.get("origin", SIM), "parts": parts, "checks": list(v.get("checks") or []), "events": events,
            "approval": {"state": (v.get("approval") or {}).get("state", "waiting")}}


PUBLIC_EVENT_KINDS = ("plan", "round_open", "knockout", "locked", "clash", "replan")


class ViewPublisher:
    """Sends each BuildView to the market's referee reducer publish_build_view(goal_id, json), so a hosted board can read it from the public
    build_view table (docs/changes/1800-D-publish-build-view.md). Optional: a market without the reducer never gets a call (make_publisher),
    and a failing one is noted once and dropped after MAX_FAILURES, never an error in the build. The view carries no secret: it is the
    same object demo/out/build-view.json holds."""
    MAX_FAILURES = 3

    def __init__(self, referee: Any, *, note: Callable[[str], None] = lambda text: None):
        self.referee, self.note, self.failures = referee, note, 0

    def __call__(self, goal_id: str, text: str) -> None:
        if self.failures >= self.MAX_FAILURES:
            return
        try:
            self.referee.call("publish_build_view", goal_id=goal_id, json=text)
        except (RuntimeError, OSError) as e:
            self.failures += 1
            if self.failures == 1:
                self.note(f"publish_build_view failed ({e}); the hosted board's copy may be stale and the build goes on. "
                          f"It stops asking after {self.MAX_FAILURES} failures.")


def make_publisher(clients: dict, *, note: Callable[[str], None] = lambda text: None, module: Path = MARKET_INDEX) -> Optional[ViewPublisher]:
    """A ViewPublisher when the market module has publish_build_view, else None (the files in demo/out are then the only copy)."""
    return ViewPublisher(clients["referee"], note=note) if market_has_reducer("publish_build_view", module) else None


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


def _buyer_client(args) -> Any:
    """The buyer identity's market client (its token file, default buyer-vidyut.json), for reading the buyer's own goal before the run starts."""
    from demo import bridge
    target = bridge.live_target(args)
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    from stdb import Market
    tokens = bridge.find_tokens_dir(args.tokens_dir, target)
    return Market(token_file=str(args.buyer_token or tokens / bridge.BUYER_TOKEN))


def cartesia_for(buyer_id: str, env: dict, note: Callable[[str], None]) -> tuple[Any, str]:
    """(the Cartesia client for this buyer's approval phone, "") or (None, why): "no_phone" for a buyer with no number (the call is the only
    approval, so a build above the allowance is denied), "not_configured" for a setup that is missing or wrong. One masked note either way."""
    from pay import voice_cartesia as vc
    try:
        client = vc.client_for_buyer(buyer_id, env)
    except vc.NoPhone as e:
        note(f"live call: {e}, so a build above the allowance is DENIED: no call, no mandate, nothing is paid")
        return None, "no_phone"
    except vc.CartesiaError as e:
        note(f"live call: Cartesia NOT configured ({e}), so a build above the allowance is DENIED and nothing is paid")
        return None, "not_configured"
    note(f"live call: ONE call to {vc.mask_number(client.approval_call_to)} for the whole build, only above the allowance")
    return client, ""


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
    ap.add_argument("--per-buy", type=float, default=None,
                    help="the buyer's per-purchase allowance the runner sets (default 250, SIM; when building from another buyer's own goal the "
                         "runner leaves their allowance alone unless this or --period-limit is given)")
    ap.add_argument("--period-limit", type=float, default=None, help="the buyer's allowance per month the runner sets (default 500, SIM)")
    ap.add_argument("--env-file", type=Path, default=None, help="where the CARTESIA_* and sponsor names are read from")
    ap.add_argument("--tokens-dir", help="folder with referee.json and buyer-vidyut.json (default: auto-detect)")
    ap.add_argument("--buyer-id", default=None,
                    help=f"the buyer the build is for (default {bridge.DB_BUYER_ID}, the demo plan). With --buyer-id and no --goal-id and no --plan, "
                         "the build is made from this buyer's own latest ACTIVE build_by_date goal in the market, which is reused (no second goal)")
    ap.add_argument("--goal-id", default=None, help="post the plan as a new goal with this id (default goal-build-1); with --buyer-id, builds the demo plan under it")
    ap.add_argument("--plan", type=Path, default=None,
                    help="a planner.plan() JSON file (cap_cents, owned, parts) through plan_from_planner, posted as a new goal; wins over the buyer's own goal")
    ap.add_argument("--buyer-token", type=Path, default=None,
                    help="the buyer identity token file (default buyer-vidyut.json in the tokens dir). A self-serve buyer's own token lives in their "
                         "browser: export it to a file to build from their goal; the referee cannot read it (goals are private to the buyer)")
    ap.add_argument("--no-assign-roles", action="store_true", help="skip the owner assign_role step for seller identities")
    ap.add_argument("--server", default=None, help="spacetime -s server (default from the env or the Lane D env file)")
    ap.add_argument("--bid-window", type=bridge.bid_window_arg, default=None, help="seconds each part's sealed round stays open")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="where build-view.json and build-view.steps.jsonl are written at every step (default demo/out; a dry run writes nothing unless given)")
    ap.add_argument("--stagger", type=float, default=STAGGER_S,
                    help=f"seconds between part rounds opening, so a six-part build fits a 90 s beat: all open within 5 x this (default {STAGGER_S:g}); "
                         "rounds close in part order")
    ap.add_argument("--sequential", action="store_true", help="one part's round at a time (phase 1 pacing), no stagger")
    ap.add_argument("--planner", choices=("auto", "default"), default="auto",
                    help="auto: use agents.buyer.planner.plan (#358) when it is on this branch; default: the built-in demo plan")
    ap.add_argument("--knockout", choices=("auto", "on", "off"), default="auto",
                    help="sealed knockout stages (#363, max 3): auto = when the market module has open_knockout_round; off = one-stage rounds")
    ap.add_argument("--no-publish", action="store_true", help="never send the BuildView to the market's publish_build_view reducer")
    args = ap.parse_args(argv)
    if args.stripe and not args.live_call:
        ap.error("--stripe needs --live-call: a Stripe test charge runs only after a real phone call approves (there is no scripted approval)")
    out = Narrator(True)
    out.note("Tech Bazaar build: one goal, a sealed round per part, one call for the whole build (#345)")
    out.note("Sellers: SIM, plus the real dated MIRROR listings for the GPU. Payment is the SIM stub unless --live-call --stripe. Tags: [MIRROR] [SIM] [LIVE].")
    out.note(shield_mode_line())
    from_goal = args.buyer_id is not None and args.goal_id is None and args.plan is None   # #253: build from this buyer's own goal row
    args.buyer_id = args.buyer_id or bridge.DB_BUYER_ID
    args.goal_id = args.goal_id or "goal-build-1"
    own_allowance = args.per_buy is not None or args.period_limit is not None
    args.per_buy = 250.0 if args.per_buy is None else args.per_buy
    args.period_limit = 500.0 if args.period_limit is None else args.period_limit
    reuse = False
    try:
        if args.plan is not None:
            plan = plan_from_planner(json.loads(args.plan.read_text(encoding="utf-8")), goal_id=args.goal_id, buyer_id=args.buyer_id)
            source = f"plan file {args.plan.name}"
        elif from_goal:
            if args.dry_run:
                print("error: --dry-run runs on an in-memory market and cannot read a buyer's goal; use --plan FILE to dry-run a plan", file=sys.stderr)
                return 1
            goal, items = read_buyer_goal(_buyer_client(args), args.buyer_id)
            plan, warnings = plan_from_goal(goal, items)
            for w in warnings:
                out.note(f"note: {w}")
            reuse, source = True, f"buyer's own goal {goal['id']} (read from the market, reused: no second goal is posted)"
        else:
            plan, source = planned_build(planner="auto" if args.planner == "auto" else None, note=out.note, goal_id=args.goal_id, buyer_id=args.buyer_id)
    except (ValueError, OSError, RuntimeError) as e:   # GoalNotFound, a bad plan file, an unreadable market: one line, nothing was posted or bid
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not plan.deadline:
        plan.deadline = _stamp(datetime.now(timezone.utc) + timedelta(days=7))
    # another buyer's own allowance stays theirs: the runner only sets one for the default buyer, or when asked with --per-buy / --period-limit
    allowance = (None if reuse and args.buyer_id != bridge.DB_BUYER_ID and not own_allowance
                 else {"per_purchase_limit": args.per_buy, "period_limit": args.period_limit, "period": "month"})
    knockout = market_has_reducer("open_knockout_round") if args.knockout == "auto" else args.knockout == "on"
    stagger = None if args.sequential else args.stagger
    out.note(f"plan from the {source}: {plan.plan_line or default_plan_line(plan)}")
    out.note(f"rounds: {'sealed knockout, up to ' + str(MAX_STAGES) + ' stages' if knockout else 'one sealed stage'}; "
             f"{'staggered ' + format(stagger, 'g') + ' s apart, closing in part order' if stagger is not None else 'one part at a time'}")
    clock_of: dict[str, Any] = {"run": None}

    def say(s) -> None:
        if s.reducer == "set_floor":
            return
        who = "buyer" if s.actor == "buyer" else "referee" if s.actor == "referee" else s.actor.replace("seller:", "seller ")
        run = clock_of["run"]
        at = f"+{run.schedule_s:5.1f}s " if run is not None and run.goal_posted else ""
        out.line(s.tag if s.tag in bridge.LIVE_TAGS else SIM, f"{at}{who:<26}{s.reducer:<22}{s.say}")

    if args.dry_run:
        return _dry_run(args, plan, allowance, knockout, stagger, out, say, clock_of)
    steps = preview_steps(plan, allowance, delay=args.step_delay, bid_window=args.bid_window)   # only to learn the seller ids
    out_dir = args.out_dir or OUT_DIR
    from demo import market_target
    from demo.run_demo import DEFAULT_ENV_FILE
    approver_env = args.env_file or DEFAULT_ENV_FILE
    cartesia, price_check, no_call_reason = None, None, "not_configured"
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
        cartesia, no_call_reason = cartesia_for(args.buyer_id, env, out.note)
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
        clients: dict[str, Any] = {"buyer": Market(token_file=str(args.buyer_token or tokens / bridge.BUYER_TOKEN)),
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
        from demo import crs_relay
        from demo.run_demo import stripe_env
        knockout = resolve_knockout(args.knockout, clients, out.note)   # the deployed market must answer close_stage, not only the source say so
        publisher = None if args.no_publish else make_publisher(clients, note=out.note)
        out.note("BuildView: " + (f"also sent to the market's publish_build_view for the hosted board, and written to {out_dir / VIEW_FILE}" if publisher
                                  else f"written to {out_dir / VIEW_FILE}; the market has no publish_build_view reducer, so no hosted copy"))
        run = BuildRun(plan, clients, relay_signals=lambda: crs_relay.relay_best_effort(clients["referee"], note=out.note), allowance=allowance,
                       price_check=price_check, crs_check=bridge.default_crs_check, cartesia=cartesia,
                       secret=secret, buyer_name=buyer_name, use_stripe=args.stripe,
                       env={**os.environ, **stripe_env(DEFAULT_ENV_FILE)} if args.stripe else {}, out_dir=out_dir, say=say,
                       note=out.note, delay=args.step_delay, bid_window=args.bid_window, stagger=stagger, knockout=knockout,
                       publisher=publisher, no_call_reason=no_call_reason, agent_addresses=bridge.demo_agent_addresses(), reuse_goal=reuse)
        clock_of["run"] = run
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
             f"{v['approval']['sellers']} sellers; BuildView in {out_dir / VIEW_FILE}")
    return 0 if res["status"] == "paid" else 1


def crs_payee_lines(champs: dict, now: datetime) -> list[tuple[str, str]]:
    """#398: (origin, text) per payee of the champions, from agents/crs.py payee_status (local files only, never the sandbox).
    The tag is the seller's own origin; the text says its CRS status. A recorded band is never LIVE, and nothing here is a pass."""
    from demo import bridge
    crs = bridge.crs_module()
    payees = {}
    for c in champs.values():
        payees.setdefault(c["sellerId"], c)
    lines = []
    for sid in sorted(payees):
        c, s = payees[sid], crs.payee_status(sid, now)
        who = f"{c['persona']} ({sid}): "
        if s["state"] == "unknown":
            text = f"CRS unknown, {s['reason']}; a business payee would hold the payee gate"
        elif s["state"] == "sim":
            text = f"no CRS profile: {s['reason']}; identity not checked (the payee gate asks CRS only about a business profile)"
        elif s["band"] is None:
            text = f"business CRS profile ({s['persona_ref']}), not checked: a dry run makes no CRS call; a live run checks it at the payee gate"
        else:
            text = (f"business CRS profile ({s['persona_ref']}), CRS band {s['band']}, recorded {s['checked_at']}, not checked in this run"
                    + ("" if s["band"] == "verified_stable" else "; the payee gate would hold"))
        lines.append((c["origin"], who + text))
    return lines


def _dry_run(args, plan: BuildPlan, allowance: dict, knockout: bool, stagger: Optional[float], out, say, clock_of: dict) -> int:
    """Everything before the call, on demo.build_sim's in-memory market (no market, no network, no call, nothing paid): the goal, a sealed
    round per part on the timeline, the fit checks after each lock, the re-plan, and the BuildView at the end."""
    from demo.build_sim import SimMarket, make_clients
    run = BuildRun(plan, make_clients(SimMarket()), allowance=allowance, out_dir=args.out_dir, say=say, note=out.note, delay=args.step_delay,
                   bid_window=args.bid_window, stagger=stagger, knockout=knockout, sleep=lambda s: None, clock=lambda: 0.0)
    clock_of["run"] = run
    run.run_rounds()
    v = run.publish()
    out.blank()
    out.note("BuildView after the rounds (dry run, in-memory market):")
    for p in v["parts"]:
        if p["status"] == "owned":
            out.line(SIM, f"{p['label']:<30}owned")
        else:
            c = p.get("champion")
            out.line(c["origin"] if c else SIM, f"{p['label']:<30}{p['status']:<10}"
                     + (f"{c['persona']} {money(c['landed'])}" + (f"  ({p['reason']})" if p.get("reason") else "") if c else p.get("reason", "")))
    out.blank()
    out.note(f"fit checks (data.fit_checker.build_check over the locked parts and what you own): {len(v['checks'])}")
    for c in v["checks"]:
        out.line(SIM, f"{c['a']:>7} / {c['b']:<7}{c['rule']:<14}{c['state']:<8}{c['source']:<20}{c['detail']}")
    out.blank()
    out.note("event log:")
    for e in v["events"]:
        if e["kind"] in ("plan", "clash", "replan", "knockout") or (e["kind"] == "locked" and e["parts"]):
            out.line(e["origin"], f"{e['kind']:<10}{e['text']}")
    out.blank()
    out.note("CRS per payee (#398; the local profile file and recorded results only: a dry run makes no CRS call):")
    for origin, text in crs_payee_lines(run.champions()[0], datetime.now(timezone.utc)):
        out.line(origin, text)
    out.blank()
    out.note(f"pacing: the rounds are scheduled over {run.schedule_s:.0f} s ("
             + (f"parts open {stagger:g} s apart, all within {stagger * (len(plan.parts) - 1):g} s, and close in order" if stagger is not None
                else "one part at a time") + ")")
    out.note(f"then, once every part has a champion: re-check prices, and above {money(args.per_buy)} ONE call for the whole build "
             f"(inside it: no call, method allowance), a mandate per part's rank 1, a payment and a receipt per part. No call was placed: dry run, nothing was paid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
