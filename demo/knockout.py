"""Sealed knockout stages for the demo (#337), the Python mirror of the market's close_stage (#336). SIM rules.

Each stage runs the same round as today (referee floors, Shield, claim checks, the advocate, the ranking). Every
rule-breaker goes out with its reason and source (a veto, a fit failure, over the cap, under the floor, a Shield
block), and so does the last-placed survivor. A bid whose fit is not confirmed ranks below every confirmed bid
(round.pick_winner's rule), so it is the first to go. Survivors answer "still in" with one improved sealed offer from
their tactic (agents/sellers/tactics.py), never under their floor. One survivor is champion at once; none means no
deal and nothing is paid; the final stage crowns its rank 1. The champion goes to the approval call exactly as today.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.sellers.tactics import next_offer  # noqa: E402
from demo.round import _fit_unknown, run_round  # noqa: E402
from demo.sellers import Seller, line_price  # noqa: E402

MAX_STAGES = 3
# Five sellers so stage 1 knocks out three for real reasons: an advocate veto with its source (Shady Sam), a fit
# failure (Bargain Bin, 336 mm in a 305 mm case) and last place (an eBay listing whose fit is not confirmed).
ROSTER = ("shady-sam", "bargain-bin", "ebay-235887", "best-buy", "gadget-grove")
NO_DEAL = "no deal: every seller was knocked out, nothing is paid"


def _out_entry(stage: int, sid: str, persona: str, rule_id: str, reason: str, source_url: str, offer) -> dict:
    return {"stage": stage, "seller_id": sid, "persona": persona, "status": "knocked_out", "rule_id": rule_id,
            "reason": reason, "source_url": source_url, "offer": offer}


def _classify(stage: int, res: dict, by_id: dict) -> tuple[list[dict], list[dict]]:
    """(knocked-out rule-breakers, the rest in rank order with confirmed fits first)."""
    out = []
    for d in res["ranking"]["disqualified"]:
        reason = "; ".join(d["reasons"])
        rule = "shield.block" if reason.startswith("shield") else "referee.floor" if d.get("kind") == "rejected" else "market.ineligible"
        out.append(_out_entry(stage, d["seller_id"], by_id[d["seller_id"]].name, rule, reason, "", d.get("landed")))
    alive = []
    for r, card in zip(res["ranking"]["ranked"], res["cards"]):
        why = card["call_reason"]
        if card["recommendation"] == "veto":
            out.append(_out_entry(stage, r["seller_id"], by_id[r["seller_id"]].name, why["rule_id"], why["summary"],
                                  why["source_url"], r["landed"]))
        else:
            alive.append({"rank": r, "card": card})
    sure = [a for a in alive if not _fit_unknown(a["card"])]
    return out, sure + [a for a in alive if _fit_unknown(a["card"])]


def _improved(seller: Seller, stage: int, offers: list[dict]) -> Seller:
    lines = []
    for ln in seller.lines:
        last, _ = line_price(ln)
        price, why = next_offer(seller.tactic, last, ln.floor)
        offers.append({"stage": stage, "seller_id": seller.id, "condition": ln.condition, "tactic": seller.tactic,
                       "price": price, "previous": last, "why": why})
        lines.append(replace(ln, offer=price))
    return replace(seller, lines=lines)


def run_knockout(need: dict, sellers: list[Seller], owned_attrs: dict, cap: float, now: datetime,
                 max_stages: int = MAX_STAGES) -> dict:
    if isinstance(max_stages, bool) or not isinstance(max_stages, int) or not 1 <= max_stages <= MAX_STAGES:
        raise ValueError(f"max_stages must be 1 to {MAX_STAGES}")
    by_id = {s.id: s for s in sellers}
    alive = list(sellers)
    offers = [{"stage": 1, "seller_id": s.id, "condition": ln.condition, "tactic": s.tactic, "price": line_price(ln)[0],
               "previous": None, "why": "first sealed offer"} for s in sellers for ln in s.lines]
    stages, champion = [], None
    for stage in range(1, max_stages + 1):
        res = run_round(need, alive, owned_attrs, cap, now)
        out, rest = _classify(stage, res, by_id)
        entries = list(out)
        if not rest:
            stages.append({"stage": stage, "entries": entries})
            break
        final = stage == max_stages or len(rest) == 1
        keep = rest[:1] if final else rest[:-1]
        for a in rest[len(keep):]:
            r = a["rank"]
            held = " (fit not confirmed, held back below every confirmed bid)" if _fit_unknown(a["card"]) else ""
            text = (f"ranked below the champion in the final stage{held}" if final
                    else f"last place in stage {stage}{held}")
            entries.append(_out_entry(stage, r["seller_id"], by_id[r["seller_id"]].name, "knockout.last_place", text,
                                      a["card"]["call_reason"]["source_url"], r["landed"]))
        done = len(keep) == 1
        for a in keep:
            r = a["rank"]
            entries.append({"stage": stage, "seller_id": r["seller_id"], "persona": by_id[r["seller_id"]].name,
                            "status": "champion" if done else "advancing", "rule_id": None, "reason": None,
                            "source_url": None, "offer": r["landed"]})
        stages.append({"stage": stage, "entries": entries})
        if done:
            r = keep[0]["rank"]
            champion = {"seller_id": r["seller_id"], "persona": by_id[r["seller_id"]].name, "stage": stage,
                        "landed": r["landed"], "condition": r["condition"], "bid_id": r["bid_id"],
                        "round": res}
            break
        alive = [_improved(by_id[a["rank"]["seller_id"]], stage + 1, offers) for a in keep]
    return {"stages": stages, "champion": champion, "offers": offers, "max_stages": max_stages,
            "result": f"champion {champion['persona']} after stage {champion['stage']}" if champion else NO_DEAL}


def loss_reports(result: dict) -> list[dict]:
    """One per knocked-out seller: the stage, the reason and its source, and only the seller's own offer."""
    return [{"seller_id": e["seller_id"], "stage": e["stage"], "rule_id": e["rule_id"], "reason": e["reason"],
             "source_url": e["source_url"], "own_offer": e["offer"]}
            for s in result["stages"] for e in s["entries"] if e["status"] == "knocked_out"]
