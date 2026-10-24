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
import re
import sys
import threading
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
    """(the round's eligible champion row, "") or (None, why there is none). Eligible = the market's rank 1, not held back, a seller
    that joined the market, and a landed price in whole cents. A held-back or vetoed bid is never a champion (#240)."""
    first = [r for r in results if r.get("rank") == 1]
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
    parts, events, champions = [], [], {}
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
    for part, lv in live.items():
        if lv.get("text"):
            events.append({"at": lv.get("at") or "", "kind": "locked", "text": lv["text"], "parts": [part], "origin": _origin(lv.get("origin"))})
    buying = [p for p in parts if p["status"] != "owned"]
    total = round(sum(c["landed"] for c in champions.values()), 2)
    sellers = len({c["sellerId"] for c in champions.values()})
    if buying and all(p["status"] in ("locked", "replanned") for p in buying):
        done = max((r.get("closedAt") or "" for r in rounds.values()), default="")
        events.append({"at": done, "kind": "locked", "text": f"Build ready: {len(buying)} parts, {sellers} sellers, {money(total)}",
                       "parts": [], "origin": _weakest([c["origin"] for c in champions.values()])})
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
    for e in plan_events:
        events.append({"at": e.get("at") or "", "kind": e["kind"], "text": e["text"], "parts": list(e.get("parts") or []),
                       "origin": _origin(e.get("origin"))})
    events.sort(key=lambda e: e["at"])   # stable: same-time events keep the order they were added in
    lines = []
    for c in checks or []:
        lines.append({"a": c["a"], "b": c["b"], "rule": c["rule"], "state": c["state"] if c.get("state") in CHECK_STATES else "unknown",
                      "detail": c.get("detail", ""), "source": c.get("source", "")})
    return {"goalId": goal.get("id", ""), "buyerId": goal.get("buyerId", ""), "budget": float(goal.get("cap") or 0),
            "spent": float(round(sum(c["landed"] for p in buying if p["status"] in ("locked", "replanned") for c in [p["champion"]]), 2)),
            "origin": _weakest([p["origin"] for p in buying]) if buying else _origin(goal.get("origin")),
            "parts": parts, "checks": lines, "events": events, "approval": approval}
