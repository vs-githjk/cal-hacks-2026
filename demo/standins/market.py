"""SIM stand-in for Lane B's market rules (origin/lane-b-market-floor, market/rules/*.ts; not merged here).

Mirrors, rule for rule:
  sealing.ts  sealed bids, a deadline, a capped anti-snipe extension, sellers see only their own bid
  floor.ts    no line below the seller's floor, every quantity finite and above 0, equal to the need
  scoring.ts  rank by landed price less perks value, lowest first; ties go to more verified claims, then
              the earlier sealed bid, then the bid id; a line whose condition differs from the goal is out;
              the market fee is never read
Where this runner differs on purpose (the LOCKED seller model, Fri 22:36): a bid carries SEVERAL condition
lines for one SKU, so floors are keyed by sku and condition, the score is per line, and a bid ranks on its
best eligible line. Lane B's checkLineSpec still assumes one condition per need line. The advocate's
quality adjustment (condition, returns, seller record) is applied here as SIM weights.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class SealConfig:
    extend_s: int = 5
    snipe_window_s: int = 3
    max_extensions: int = 2


@dataclass(frozen=True)
class AuctionClock:
    need_id: str
    opened_ms: int
    deadline_ms: int
    extensions: int = 0
    closed_ms: Optional[int] = None
    config: SealConfig = SealConfig()


def new_auction(need_id: str, opened_ms: int, window_s: int, config: SealConfig = SealConfig()) -> AuctionClock:
    return AuctionClock(need_id, opened_ms, opened_ms + window_s * 1000, 0, None, config)


def is_closed(a: AuctionClock, now_ms: int) -> bool:
    return a.closed_ms is not None or now_ms >= a.deadline_ms


def try_bid(a: AuctionClock, now_ms: int) -> tuple[bool, AuctionClock, bool, str]:
    """(accepted, auction, extended, reason). A bid inside the snipe window extends the deadline, at most
    `max_extensions` times."""
    if is_closed(a, now_ms):
        return False, a, False, "auction closed: bid arrived after the deadline"
    if a.deadline_ms - now_ms <= a.config.snipe_window_s * 1000 and a.extensions < a.config.max_extensions:
        return True, replace(a, deadline_ms=a.deadline_ms + a.config.extend_s * 1000, extensions=a.extensions + 1), True, ""
    return True, a, False, ""


def visible_bids(bids: list[dict], a: AuctionClock, viewer: tuple[str, Optional[str]], now_ms: int) -> list[dict]:
    """viewer = ("seller", id) | ("buyer", None) | ("public", None). Sellers only ever see their own bid;
    everyone else sees nothing until the auction closes."""
    kind, who = viewer
    if kind == "seller":
        return [b for b in bids if b["seller_id"] == who]
    return list(bids) if is_closed(a, now_ms) else []


def _positive(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def floor_key(sku: str, condition: str) -> str:
    return f"{sku}|{condition}"


def check_floor(bid: dict, floors: dict[str, float], need_qty: dict[str, int]) -> list[str]:
    """Referee rule. Empty list means the bid passes."""
    reasons = []
    for ln in bid["lines"]:
        sku, cond = ln["sku_spec"], ln["offered_condition"]
        if not _positive(ln["quantity"]):
            reasons.append(f"{sku}: quantity {ln['quantity']} is not a number above 0")
        elif sku in need_qty and ln["quantity"] != need_qty[sku]:
            reasons.append(f"{sku}: quantity {ln['quantity']}, the need asks for {need_qty[sku]}")
        if not _positive(ln["unit_price"]):
            reasons.append(f"{sku} {cond}: price {ln['unit_price']} is not a positive number")
            continue
        floor = floors.get(floor_key(sku, cond))
        if floor is not None and ln["unit_price"] < floor:
            reasons.append(f"{sku} {cond}: ${ln['unit_price']:,.2f} is below this seller's floor")
    return reasons


# SIM weights for the advocate's quality adjustment (the real weights are Lane A's). Fractions of landed price.
CONDITION_ADJ = {"new": 0.0, "open-box": 0.04, "refurbished": 0.08, "used": 0.15, "unknown": 0.0}
NO_RETURNS_ADJ = 0.02
CAUTION_RECORD_ADJ = 0.03


def quality_adjusted(landed: float, condition: str, returns_days: int, record: str) -> float:
    adj = CONDITION_ADJ.get(condition, 0.0) + (0.0 if returns_days >= 30 else NO_RETURNS_ADJ) \
        + (CAUTION_RECORD_ADJ if record != "good" else 0.0)
    return round(landed * (1 + adj), 2)


def line_problems(line: dict, landed: float, need_item: dict, cap: float) -> list[str]:
    """Why a line cannot win on the goal alone (condition and cap). Fit, claims and Shield come later."""
    out = []
    allowed = need_item.get("allowed_conditions") or [need_item["condition"]]
    cond = line["offered_condition"]
    if cond not in allowed:
        out.append(f"condition: offered {cond}, the goal allows {'/'.join(allowed)}"
                   + (" (the snapshot states no condition and the advocate will not guess)" if cond == "unknown" else ""))
    if line["sku_spec"] != need_item["sku_spec"]:
        out.append(f"variant: offered {line['sku_spec']}, the goal asks for {need_item['sku_spec']}")
    if landed > cap + 1e-9:
        out.append(f"price: landed ${landed:,.2f} is over the goal cap")
    return out


def rank_bids(bids: list[dict], need_item: dict, cap: float, meta: dict[str, dict], sealed_at: dict[str, int],
              rejections: Optional[dict[str, list[str]]] = None, verified: Optional[dict[str, int]] = None) -> dict:
    """-> {"ranked": [...], "disqualified": [...]}. Each ranked entry names the best eligible line of that bid."""
    rejections, verified = rejections or {}, verified or {}
    ranked, out = [], []
    for bid in bids:
        sid = bid["seller_id"]
        if rejections.get(bid["id"]):
            out.append({"bid_id": bid["id"], "seller_id": sid, "reasons": list(rejections[bid["id"]]), "kind": "rejected"})
            continue
        best, why = None, []
        for i, ln in enumerate(bid["lines"]):
            landed = round(ln["unit_price"] * ln["quantity"] + meta[sid]["shipping"], 2)
            problems = line_problems(ln, landed, need_item, cap)
            if problems:
                why.append({"line": i, "condition": ln["offered_condition"], "landed": landed, "reasons": problems})
                continue
            adj = quality_adjusted(landed, ln["offered_condition"], meta[sid]["returns_days"], meta[sid]["record"])
            if best is None or adj < best["adjusted"]:
                best = {"line": i, "condition": ln["offered_condition"], "landed": landed, "adjusted": adj}
        if best is None:
            cheapest = min(why, key=lambda w: w["landed"]) if why else {"line": 0, "condition": "", "landed": 0.0, "reasons": ["no line"]}
            out.append({"bid_id": bid["id"], "seller_id": sid, "reasons": cheapest["reasons"], "kind": "ineligible",
                        "line": cheapest["line"], "landed": cheapest["landed"], "condition": cheapest["condition"]})
            continue
        ranked.append({"bid_id": bid["id"], "seller_id": sid, **best, "verified": verified.get(bid["id"], 0),
                       "sealed_at": sealed_at.get(bid["id"], 0)})
    ranked.sort(key=lambda r: (r["adjusted"], -r["verified"], r["sealed_at"], r["bid_id"]))
    for n, r in enumerate(ranked, 1):
        r["rank"] = n
    return {"ranked": ranked, "disqualified": out}
