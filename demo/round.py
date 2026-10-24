"""One sealed round, end to end, used by beat 2 (round 1) and beat 5 (round 2).

Order, as the product defines it: sellers bid sealed; the referee checks floors and quantities; Shield screens
every seller's text before the advocate sees it; claims are checked against their pages; bids are scored on
quality-adjusted landed price of the cheapest allowed line; the advocate (REAL agents/advocate/checks.py, fit
checker and claim check) vetoes traps with a source; the
cheapest bid that survives wins. Pure and silent: printing is done by the caller from the returned dict.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from demo.adapters import claim_checker
from demo.common import SOURCE_OF, money, validate
from demo.pages import fixture_fetch
from demo.sellers import Seller, make_bid
from demo import advice
from demo.standins import market
from shield.core import screen
from shield.service import attack_type

ARRIVAL_STEP_MS = 900  # seller i seals its bid at 300 + i * 900 ms on the sim clock (SIM clock, no sleeping), up to what fits
FIRST_ARRIVAL_MS = 300
SNIPE_MARGIN_MS = 100  # ordinary bids end this far before the snipe window opens


def landed_note(seller: Seller, landed: float) -> str:
    """How to read a landed price. Tax is never included; shipping is only counted when the listing states it,
    and the words say so (the math uses 0 when it is not captured, the line never calls that free)."""
    ship = "shipping: not captured" if not seller.shipping_captured else \
        "shipping: free" if not seller.shipping else f"shipping: {money(seller.shipping)} included"
    return f"{money(landed)} before sales tax, {ship}"


def _fit_unknown(card: dict) -> bool:
    return any(w["kind"] == "fit_unknown" for w in card["warnings"]) or card["fit"]["verdict"] == "uncertain"


def pick_winner(ranked: list[dict], cards: list[dict]) -> Optional[dict]:
    """Buyer rule, demo; to move into the advocate (issue for Abhinav): the cheapest surviving bid wins, but a bid
    whose fit is not confirmed cannot win while a confirmed-fit bid is inside the cap (ranking only holds bids
    inside the cap). With no confirmed fit left, the cheapest unconfirmed one may still win, with its caution."""
    alive = [(r, c) for r, c in zip(ranked, cards) if c["recommendation"] != "veto"]
    sure = [(r, c) for r, c in alive if not _fit_unknown(c)]
    pick = sure or alive
    return pick[0][0] if pick else None


def _seller_text(seller: Seller, bid: dict) -> str:
    """Everything the seller wrote that another agent would read: its hosted page when it has one, else its
    claims, perks and decision trace. This is what Shield screens before the advocate sees the bid."""
    if seller.page_html:
        return seller.page_html
    return "\n".join([*bid["claims"], *bid["perks"], bid["decision_trace"]])


def shield_screen(seller: Seller, bid: dict, ctx_extra: Optional[dict] = None) -> dict:
    """REAL shield.screen on the seller's text, with the payee of record when we have one."""
    context = {"sender_role": "seller", **({"payee_of_record": seller.payee} if seller.payee else {}), **(ctx_extra or {})}
    v = screen(_seller_text(seller, bid), context)
    return {"seller_id": seller.id, "bid_id": bid["id"], "message_id": f"msg-{bid['id']}", "sender_agent": seller.id,
            "verdict": v["verdict"], "reasons": list(v["rule_ids"]), "attack_type": attack_type(v["rule_ids"]),
            "latency_ms": v["latency_ms"], "rule_ids": list(v["rule_ids"]), "severity": v["severity"],
            "evidence_spans": v["evidence_spans"], "version": v["version"], "request_id": v["request_id"]}


def run_claims(seller: Seller, bid: dict, now: datetime, check=None) -> list[dict]:
    check = check or claim_checker()[0]
    out = []
    for n, c in enumerate(seller.claims, 1):
        res = check({"evidence_url": c["evidence_url"], "field": c["field"], "value": c["value"]}, fetch=fixture_fetch)
        out.append(validate("Claim", {
            "id": f"claim-{bid['id']}-{n}", "bid_id": bid["id"], "text": c["text"], "kind": c["kind"], "check": res["result"],
            "evidence_url": c["evidence_url"], "checked_at": res["checked_at"], "method": res["method"],
            "evidence_hash": res["evidence_hash"], "source": SOURCE_OF[bid["origin"]], "origin": bid["origin"],
            "reason": res.get("reason", "")}))
    return out


def run_round(need: dict, sellers: list[Seller], owned_attrs: dict, cap: float, now: datetime, round_no: int = 1,
              strategies: Optional[dict] = None) -> dict:
    strategies = strategies or {}
    sealed_need = {k: v for k, v in need.items() if k != "spend_limit"}   # sellers never see the cap
    item = need["items"][0]
    check, label, real = claim_checker()
    by_id = {s.id: s for s in sellers}

    # 1. sealed bids, in arrival order on the sim clock
    clock = market.new_auction(need["id"], 0, need.get("auction_window_s", 12))
    bids, sealed_at, arrivals = [], {}, []
    # Ordinary sellers must all land before the snipe window so that only the learner's last-second bid extends the
    # deadline. With many sellers a fixed step walks late arrivals into the window, so the step shrinks to fit.
    ordinary = sum(1 for s in sellers if not s.learning)
    free_ms = clock.deadline_ms - clock.config.snipe_window_s * 1000 - FIRST_ARRIVAL_MS - SNIPE_MARGIN_MS
    step_ms = min(ARRIVAL_STEP_MS, free_ms // max(ordinary - 1, 1))
    for i, s in enumerate(sorted(sellers, key=lambda x: x.learning)):  # the learning seller bids last
        bid = make_bid(s, sealed_need, now, strategies.get(s.id))
        t_ms = FIRST_ARRIVAL_MS + i * step_ms
        if s.learning:  # a last-second bid: shows the capped anti-snipe extension
            t_ms = clock.deadline_ms - 1400
        ok, clock, extended, why = market.try_bid(clock, t_ms)
        arrivals.append({"seller_id": s.id, "at_ms": t_ms, "accepted": ok, "extended": extended, "reason": why,
                         "deadline_ms": clock.deadline_ms})
        if ok:
            bids.append(bid)
            sealed_at[bid["id"]] = t_ms
    close_ms = clock.deadline_ms
    visibility = {"before_close": {"public": len(market.visible_bids(bids, clock, ("public", None), close_ms - 1)),
                                   "buyer": len(market.visible_bids(bids, clock, ("buyer", None), close_ms - 1))},
                  "each_seller_sees": {s.id: len(market.visible_bids(bids, clock, ("seller", s.id), close_ms - 1)) for s in sellers},
                  "after_close": len(market.visible_bids(bids, clock, ("public", None), close_ms)), "bids_sealed": len(bids)}

    # 2. referee: floors and quantities (the market holds the floors; sellers never send them)
    qty = {item["sku_spec"]: item["quantity"]}
    referee, rejections = [], {}
    for bid in bids:
        s = by_id[bid["seller_id"]]
        floors = {market.floor_key(item["sku_spec"], l.condition): l.floor for l in s.lines}
        problems = market.check_floor(bid, floors, qty)
        bid["floor_check_passed"] = not problems
        referee.append({"bid_id": bid["id"], "seller_id": s.id, "passed": not problems, "reasons": problems})
        if problems:
            rejections[bid["id"]] = [f"referee: {p}" for p in problems]

    # 3. Shield on every seller's text before the advocate sees the bid
    shields = []
    for bid in bids:
        if bid["id"] in rejections:
            continue
        sv = shield_screen(by_id[bid["seller_id"]], bid)
        shields.append(sv)
        if sv["verdict"] != "allow":
            rejections[bid["id"]] = [f"shield {sv['verdict']}: " + ", ".join(sv["rule_ids"])]

    # 4. claims against their pages
    claims = {bid["id"]: run_claims(by_id[bid["seller_id"]], bid, now, check) for bid in bids if bid["id"] not in rejections}
    verified = {b: sum(1 for c in cs if c["check"] == "verified") for b, cs in claims.items()}

    # 5. score on quality-adjusted landed price
    meta = {s.id: {"shipping": s.shipping, "returns_days": s.returns_days, "record": s.record} for s in sellers}
    ranking = market.rank_bids(bids, item, cap, meta, sealed_at, rejections, verified)

    # 6. advocate: Lane A's real checks.advise on the picked line, plus false claims from the claim check; cheapest surviving bid wins
    bid_by_id = {b["id"]: b for b in bids}
    cards = []
    for r in ranking["ranked"]:
        cards.append(advice.advise(need, bid_by_id[r["bid_id"]], r, claims[r["bid_id"]], owned_attrs))
    for card in cards:
        validate("AdvocateCard", {k: card[k] for k in ("need_id", "bid_id", "warnings", "recommendation", "wait_until")})
    winner = pick_winner(ranking["ranked"], cards)
    for b in bids:
        validate("Bid", b)
    return {"round_id": f"round-{round_no}", "claim_check": {"label": label, "real": real}, "arrivals": arrivals,
            "clock": {"opened_ms": 0, "closed_ms": close_ms, "extensions": clock.extensions}, "visibility": visibility,
            "bids": bids, "referee": referee, "shield": shields, "claims": claims, "ranking": ranking, "cards": cards,
            "winner": winner, "winner_bid": bid_by_id[winner["bid_id"]] if winner else None}
