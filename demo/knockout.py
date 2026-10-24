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
from demo.common import utc_iso, validate  # noqa: E402
from demo.learning import gap_band  # noqa: E402
from demo.round import _fit_unknown, run_round  # noqa: E402
from demo.sellers import Seller, line_price  # noqa: E402

MAX_STAGES = 3
# Five sellers so stage 1 knocks out three for real reasons: an advocate veto with its source (Shady Sam), a fit
# failure (Bargain Bin, 336 mm in a 305 mm case) and last place (an eBay listing whose fit is not confirmed).
ROSTER = ("shady-sam", "bargain-bin", "ebay-235887", "best-buy", "gadget-grove")
NO_DEAL = "no deal: every seller was knocked out, nothing is paid"


def _out_entry(stage: int, sid: str, persona: str, rule_id: str, reason: str, source_url: str, offer, adjusted=None) -> dict:
    return {"stage": stage, "seller_id": sid, "persona": persona, "status": "knocked_out", "rule_id": rule_id,
            "reason": reason, "source_url": source_url, "offer": offer, "adjusted": adjusted}


def _classify(stage: int, res: dict, by_id: dict) -> tuple[list[dict], list[dict]]:
    """(knocked-out rule-breakers, the rest in rank order with confirmed fits first)."""
    out = []
    for d in res["ranking"]["disqualified"]:
        reason = "; ".join(d["reasons"])
        rule = "shield.block" if reason.startswith("shield") else "referee.floor" if d.get("kind") == "rejected" else "market.ineligible"
        out.append(_out_entry(stage, d["seller_id"], by_id[d["seller_id"]].name, rule, reason, "", d.get("landed"), d.get("adjusted")))
    alive = []
    for r, card in zip(res["ranking"]["ranked"], res["cards"]):
        why = card["call_reason"]
        if card["recommendation"] == "veto":
            out.append(_out_entry(stage, r["seller_id"], by_id[r["seller_id"]].name, why["rule_id"], why["summary"],
                                  why["source_url"], r["landed"], r["adjusted"]))
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
            stages.append({"stage": stage, "entries": entries, "round": res})
            break
        final = stage == max_stages or len(rest) == 1
        keep = rest[:1] if final else rest[:-1]
        for a in rest[len(keep):]:
            r = a["rank"]
            held = " (fit not confirmed, held back below every confirmed bid)" if _fit_unknown(a["card"]) else ""
            text = (f"ranked below the champion in the final stage{held}" if final
                    else f"last place in stage {stage}{held}")
            entries.append(_out_entry(stage, r["seller_id"], by_id[r["seller_id"]].name, "knockout.last_place", text,
                                      a["card"]["call_reason"]["source_url"], r["landed"], r["adjusted"]))
        done = len(keep) == 1
        for a in keep:
            r = a["rank"]
            entries.append({"stage": stage, "seller_id": r["seller_id"], "persona": by_id[r["seller_id"]].name,
                            "status": "champion" if done else "advancing", "rule_id": None, "reason": None,
                            "source_url": None, "offer": r["landed"], "adjusted": r["adjusted"]})
        stages.append({"stage": stage, "entries": entries, "round": res})
        if done:
            r = keep[0]["rank"]
            champion = {"seller_id": r["seller_id"], "persona": by_id[r["seller_id"]].name, "stage": stage,
                        "landed": r["landed"], "adjusted": r["adjusted"], "condition": r["condition"], "bid_id": r["bid_id"]}
            break
        alive = [_improved(by_id[a["rank"]["seller_id"]], stage + 1, offers) for a in keep]
    return {"stages": stages, "champion": champion, "offers": offers, "max_stages": max_stages,
            "result": f"champion {champion['persona']} after stage {champion['stage']}" if champion else NO_DEAL}


def _loss_reason(e: dict) -> str:
    rule = e["rule_id"] or ""
    if rule.startswith("fit") or "fit not confirmed" in (e["reason"] or ""):
        return "fit"
    if rule.startswith("advocate.condition") or (rule == "market.ineligible" and "condition" in (e["reason"] or "")):
        return "condition"
    if rule.startswith("advocate") or rule.startswith("shield"):
        return "advocate_veto"
    return "price"


def loss_reports(result: dict, now: datetime, round_id: str = "round-1") -> list[dict]:
    """One LossReport per knocked-out seller, with the stage it went out in. A banded gap to the champion, the reason
    and its source; never a price, a rival's or its own. A seller the referee rejected (floor) gets none, as today."""
    champ = result["champion"]
    out = []
    for st in result["stages"]:
        for e in st["entries"]:
            if e["status"] != "knocked_out" or e["rule_id"] == "referee.floor":
                continue
            gap = (max(0.0, (e["adjusted"] - champ["adjusted"]) / champ["adjusted"] * 100)
                   if champ and isinstance(e.get("adjusted"), (int, float)) else 100.0)
            out.append(validate("LossReport", {
                "id": f"lr-{round_id}-s{e['stage']}-{e['seller_id']}", "round_id": round_id, "seller_id": e["seller_id"],
                "won": False, "gap_band": gap_band(gap), "reason": _loss_reason(e), "source_url": e["source_url"] or "",
                "created_at": utc_iso(now), "stage": e["stage"]}))
    return out
