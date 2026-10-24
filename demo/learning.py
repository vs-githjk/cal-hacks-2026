"""Beat 5: a loss report for every losing seller, then a second round where one learning seller adjusts.

SIM stand-in for Lane B's LossReport (contract: demo/contracts_pending until Lane B merges) and for Lane A's
seller strategy update. Reports carry a banded gap (within5, within10, within20, over20), a reason category and
the cited source; never a threshold and never a rival's price. The strategy update is deterministic and stays
above the seller's floor (the referee checks the floor again in round 2). "What to change" is a fixed template
here; in the product Claude writes that one line from the report alone.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from demo.beats import owned_attrs
from demo.common import MIRROR, SIM, money, utc_iso, validate
from demo.round import run_round
from demo.sellers import Seller, all_sellers
from demo.standins.market import quality_adjusted

BANDS = (("within5", 5.0), ("within10", 10.0), ("within20", 20.0))
STEP_BY_BAND = {"within5": 0.03, "within10": 0.07, "within20": 0.15, "over20": 0.25}  # SIM learning rule
BAND_TEXT = {"within5": "less than 5 percent", "within10": "less than 10 percent", "within20": "less than 20 percent", "over20": "more than 20 percent"}


def gap_band(pct: float) -> str:
    for name, top in BANDS:
        if pct <= top:
            return name
    return "over20"


def _adjusted(entry: dict, seller: Seller) -> float:
    return entry.get("adjusted") or quality_adjusted(entry["landed"], entry["condition"], seller.returns_days, seller.record)


def loss_reports(res: dict, sellers: dict[str, Seller], now: datetime) -> tuple[list[dict], list[str]]:
    """One LossReport per losing seller of the round; also the notes for sellers the referee turned away."""
    win = res["winner"]
    ranked = {r["seller_id"]: r for r in res["ranking"]["ranked"]}
    cards = {c["bid_id"]: c for c in res["cards"]}
    out, notes = [], []
    entries = {**{d["seller_id"]: d for d in res["ranking"]["disqualified"]}, **ranked}
    bids = {b["seller_id"]: b for b in res["bids"]}
    for sid, e in entries.items():
        if sid == win["seller_id"]:
            continue
        s = sellers[sid]
        if e.get("kind") == "rejected":
            notes.append(f"{s.name}: no loss report, the referee rejected the bid before the round ({e['reasons'][0]})")
            continue
        gap = max(0.0, (_adjusted(e, s) - win["adjusted"]) / win["adjusted"] * 100)
        line_url = bids[sid]["lines"][e["line"]]["listing_url"]
        if e.get("kind") == "ineligible":
            reason = "price" if any(r.startswith("price") for r in e["reasons"]) else "condition"
            source = line_url
        else:
            card = cards[e["bid_id"]]
            if card["recommendation"] == "veto":
                cr = card["call_reason"]
                reason = "fit" if cr["rule_id"].startswith("fit") else "advocate_veto"
                source = cr["source_url"]
            else:
                reason, source = "price", line_url
        out.append(validate("LossReport", {"id": f"lr-{res['round_id']}-{sid}", "round_id": res["round_id"], "seller_id": sid,
                                           "won": False, "gap_band": gap_band(gap), "reason": reason, "source_url": source,
                                           "created_at": utc_iso(now)}))
    return out, notes


def update_strategy(strategy: dict, report: dict) -> tuple[dict, dict]:
    """Deterministic, inspectable: a price loss lowers the price step by the band's step. Nothing else moves."""
    new = dict(strategy)
    if report["reason"] == "price":
        new["price_step"] = STEP_BY_BAND[report["gap_band"]]
    diff = {k: {"from": strategy[k], "to": new[k]} for k in new if new[k] != strategy[k]}
    return new, diff


def what_to_change(report: dict, diff: dict) -> str:
    if "price_step" in diff:
        return (f"You lost on price by {BAND_TEXT[report['gap_band']]}. Lower your price by about "
                f"{diff['price_step']['to']:.0%}, and keep it above your floor.")
    return f"You lost on {report['reason'].replace('_', ' ')}. Review the cited source."


def run_beat5(b1: dict, b2: dict, now: datetime, say) -> dict:
    sellers_list, _ = all_sellers()
    sellers = {s.id: s for s in sellers_list}
    reports, notes = loss_reports(b2, sellers, now)
    say.header(5, "Loss reports and a learning seller",
               "SIM stand-ins for Lane B LossReport and Lane A strategy update; round 2 reuses the beat 2 pipeline (real fit checker, Shield)")
    say.line(SIM, f"{b2['round_id']} loss reports (banded gap, reason, cited source; never a threshold or a rival's price):")
    for r in reports:
        tag = MIRROR if sellers[r["seller_id"]].origin == MIRROR else SIM
        say.line(tag, f"{sellers[r['seller_id']].name}: lost, gap {r['gap_band']}, reason {r['reason']}", 1)
        say.line(tag, f"source: {r['source_url']}", 3)
    for n in notes:
        say.line(SIM, n)
    learner = next(s for s in sellers_list if s.learning)
    control = next(s for s in sellers_list if s.control)
    rep = next(r for r in reports if r["seller_id"] == learner.id)
    strategy0 = {"price_step": 0.0}
    strategy1, diff = update_strategy(strategy0, rep)
    line = what_to_change(rep, diff)
    say.blank()
    say.line(SIM, f"learning seller: {learner.name}, report {rep['gap_band']} / {rep['reason']}")
    say.line(SIM, "strategy diff (inspectable): " + ", ".join(f"{k} {v['from']:.0%} -> {v['to']:.0%}" for k, v in diff.items()), 1)
    say.line(SIM, f"what to change (SIM template, Claude writes this line in the product): \"{line}\"", 1)

    res2 = run_round(b1["need"], sellers_list, owned_attrs(b1["owned_parts"]), b1["goal"]["cap"], now, 2,
                     strategies={learner.id: strategy1})
    bids1 = {b["seller_id"]: b for b in b2["bids"]}
    bids2 = {b["seller_id"]: b for b in res2["bids"]}
    p1, p2 = bids1[learner.id]["lines"][0]["unit_price"], bids2[learner.id]["lines"][0]["unit_price"]
    floor = learner.lines[0].floor
    c1, c2 = bids1[control.id]["lines"][0]["unit_price"], bids2[control.id]["lines"][0]["unit_price"]
    ref2 = next(r for r in res2["referee"] if r["seller_id"] == learner.id)
    reports2, _ = loss_reports(res2, sellers, now)
    say.blank()
    say.line(SIM, "round-2 (same goal, same sealed pipeline; every seller static except the learner; the control repeats its round-1 bid):")
    say.line(SIM, f"{learner.name}: {money(p1)} -> {money(p2)}, referee floor check {'passed' if ref2['passed'] and p2 >= floor else 'FAILED'} (never below its floor)", 1)
    say.line(SIM, f"{control.name} (static control): {money(c1)} -> {money(c2)}", 1)
    w2 = sellers[res2["winner"]["seller_id"]]
    say.line(SIM, f"round-2 winner: {w2.name} at {money(res2['winner']['landed'])}; vetoes unchanged: "
                  + ", ".join(sellers[next(b["seller_id"] for b in res2["bids"] if b["id"] == c["bid_id"])].name
                            for c in res2["cards"] if c["recommendation"] == "veto"))
    ctrl2 = next((r for r in reports2 if r["seller_id"] == control.id), None)
    if ctrl2:
        say.line(SIM, f"{control.name} now gets its own report: gap {ctrl2['gap_band']}, reason {ctrl2['reason']}", 1)
    closed = res2["winner"]["seller_id"] == learner.id and res2["winner"]["adjusted"] < b2["winner"]["adjusted"]
    say.line(SIM, f"gap closed by the learner: {closed}. Honest limit: one seller, one round, SIM sellers. This shows the mechanism, not a trend.")
    return {"round1_loss_reports": reports, "referee_notes": notes, "learning_seller": learner.id, "control_seller": control.id,
            "strategy": {"before": strategy0, "after": strategy1, "diff": diff}, "what_to_change": line,
            "what_to_change_origin": "SIM template", "round2": {"round_id": res2["round_id"], "bids": res2["bids"],
            "ranking": res2["ranking"], "cards": res2["cards"], "winner": res2["winner"], "loss_reports": reports2,
            "referee": res2["referee"]},
            "learner": {"round1_price": p1, "round2_price": p2, "floor": floor, "above_floor": p2 >= floor},
            "control": {"round1_price": c1, "round2_price": c2, "unchanged": c1 == c2}, "gap_closed": closed, "origin": SIM}
