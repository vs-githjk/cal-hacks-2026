"""Total cost of ownership for the Advocate: what a bid really costs once warranty, returns, condition and the
seller's record are priced in. Pure, deterministic, ADVISORY. It never vetoes, never moves a card's recommendation
and never changes the referee's ranking (the lowest landed price among unvetoed bids stays the rule).

The weights below are our own assumptions, written down so a reviewer can argue with them. They are shares of the
landed price. A term the bid does not state (no warranty, no return window) earns no credit and is listed as
missing; a seller with fewer than MIN_DELIVERIES receiving events is called thin, never guessed.

Track record shape (contracts/QualityRecord.schema.json subset, plus optional loss-report counts):
    {seller_id: {"deliveries": int, "rejects": int, "on_time_rate": 0..1, "wins": int, "losses": int}}
`wins` and `losses` come from loss reports. They are shown in the note and do not change the cost: losing rounds
says a seller is dear, not that its goods are worse.
"""
from __future__ import annotations

import json
import math
import re

CONDITION_RISK = {"new": 0.0, "open box": 0.03, "refurbished": 0.06, "used": 0.10}  # hassle share of landed price
UNKNOWN_CONDITION_RISK = 0.06  # a condition nobody states costs like a refurbished one, and is listed as missing
WARRANTY_PER_MONTH, WARRANTY_CAP_MONTHS = 0.001, 36
RETURN_PER_DAY, RETURN_CAP_DAYS = 0.0005, 30
REJECT_COST_SHARE = 0.25  # a rejected delivery costs about a quarter of the price in time, shipping and waiting
LATE_COST_SHARE = 0.05  # a late delivery costs about 5 percent of the price
MIN_DELIVERIES = 5
TRACK_KEYS = {"deliveries": int, "rejects": int, "on_time_rate": float, "wins": int, "losses": int}
ASSUMPTIONS = ("Weights are assumptions: condition hassle 0 to 10 percent, warranty 0.1 percent a month up to 36, "
               "returns 0.05 percent a day up to 30, a reject costs 25 percent and a late delivery 5 percent of the price.")


def _num(v, minimum=0.0):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < minimum:
        return None
    return float(v)


def _seller(sid) -> str:
    return f"Seller {sid}" if re.fullmatch(r"seller_\d{1,3}", str(sid)) else "This seller"


def _norm(s) -> str:
    return " ".join(str(s or "").lower().replace("-", " ").replace("_", " ").split())


def load_track(path) -> dict:
    """A track-record file (JSON, closed keys, seller ids matching our pattern). Anything else is ignored."""
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for sid, rec in (raw.items() if isinstance(raw, dict) else ()):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(sid)) or not isinstance(rec, dict):
            continue
        row = {}
        for key, kind in TRACK_KEYS.items():
            v = rec.get(key)
            if kind is int and isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                row[key] = v
            elif kind is float and _num(v) is not None and v <= 1:
                row[key] = float(v)
        if row.keys() >= {"deliveries", "rejects"} and row["rejects"] <= row["deliveries"]:
            out[sid] = row
    return out


def _terms(bid):
    """Worst case over the bid's lines: the shortest warranty, the shortest return window, the riskiest condition."""
    lines = [l for l in bid.get("lines", []) if isinstance(l, dict)]
    warranty = [_num(l.get("warranty_months")) for l in lines]
    window = [_num(l.get("return_window_days")) for l in lines]
    conds = [_norm(l.get("offered_condition")) for l in lines]
    risks = [CONDITION_RISK.get(c) for c in conds]
    return {"warranty_months": None if not lines or None in warranty else min(warranty),
            "return_window_days": None if not lines or None in window else min(window),
            "condition": None if not lines or None in risks else max(conds, key=lambda c: CONDITION_RISK[c]),
            "risk": UNKNOWN_CONDITION_RISK if not lines or None in risks else max(risks)}


def score(bid: dict, track: dict) -> dict:
    landed = _num(bid.get("total_landed_price")) or 0.0
    sid = bid.get("supplier_id") or bid.get("seller_id") or ""
    t = _terms(bid)
    rec = track.get(sid)
    deliveries = rec["deliveries"] if rec else 0
    thin = deliveries < MIN_DELIVERIES
    reject_rate = 0.0 if thin else rec["rejects"] / deliveries
    late_rate = 0.0 if thin or "on_time_rate" not in rec else 1.0 - rec["on_time_rate"]
    comp = {"condition_risk": round(landed * t["risk"], 2),
            "reject_risk": round(landed * reject_rate * REJECT_COST_SHARE, 2),
            "late_risk": round(landed * late_rate * LATE_COST_SHARE, 2),
            "warranty_credit": round(landed * WARRANTY_PER_MONTH * min(t["warranty_months"] or 0.0, WARRANTY_CAP_MONTHS), 2),
            "return_credit": round(landed * RETURN_PER_DAY * min(t["return_window_days"] or 0.0, RETURN_CAP_DAYS), 2)}
    total = landed + comp["condition_risk"] + comp["reject_risk"] + comp["late_risk"] - comp["warranty_credit"] - comp["return_credit"]
    missing = [name for name, v in (("warranty", t["warranty_months"]), ("return window", t["return_window_days"]),
                                    ("condition", t["condition"])) if v is None]
    return {"bid_id": bid.get("id"), "seller_id": sid, "seller": _seller(sid), "landed": round(landed, 2),
            "tco": round(total, 2), "components": comp, "missing": missing, "thin_record": thin,
            "deliveries": deliveries, "wins": (rec or {}).get("wins"), "losses": (rec or {}).get("losses"),
            "terms": {"warranty_months": t["warranty_months"], "return_window_days": t["return_window_days"],
                      "condition": t["condition"]}}


def _terms_text(row) -> str:
    t = row["terms"]
    w = f"{t['warranty_months']:g} month warranty" if t["warranty_months"] is not None else "warranty not stated"
    r = f"{t['return_window_days']:g} day returns" if t["return_window_days"] is not None else "return window not stated"
    return f"{w}, {r}, {t['condition'] or 'condition not stated'}"


def _record_text(row) -> str:
    if row["deliveries"] == 0:
        return f"no track record on file for {row['seller']}"
    if row["thin_record"]:
        return f"{row['seller']} has a thin track record ({row['deliveries']} deliveries), so it is not priced in"
    extra = f", won {row['wins']} of {row['wins'] + row['losses']} rounds" if row["wins"] is not None and row["losses"] is not None else ""
    return f"{row['seller']} has {row['deliveries']} deliveries on record{extra}"


def rank(need: dict, bids: list[dict], cards: list[dict], track: dict | None = None) -> dict:
    """Rank the unvetoed bids by total cost. `cards` are the Advocate's cards: a veto removes a bid from the ranking."""
    track = track or {}
    vetoed = {c["bid_id"] for c in cards if c.get("recommendation") == "veto"}
    rows = [score(b, track) for b in bids]
    ranked = sorted((r for r in rows if r["bid_id"] not in vetoed), key=lambda r: (r["tco"], r["landed"], str(r["bid_id"])))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    excluded = [r["bid_id"] for r in rows if r["bid_id"] in vetoed]
    if not ranked:
        return {"ranking": [], "excluded": excluded, "advisory": True,
                "note": "No bid is left to rank on total cost: every bid was vetoed. Advisory only; the referee's ranking by landed price stays the rule."}
    top = ranked[0]
    cheapest = min(ranked, key=lambda r: (r["landed"], str(r["bid_id"])))
    head = (f"Best total cost: {top['seller']} at ${top['landed']:.2f} landed, about ${top['tco']:.2f} all in "
            f"({_terms_text(top)}).")
    if cheapest["bid_id"] == top["bid_id"]:
        head += " It is also the lowest landed price."
    else:
        head += (f" That is ${top['landed'] - cheapest['landed']:.2f} more than the lowest landed price "
                 f"({cheapest['seller']}, ${cheapest['landed']:.2f}) but ${cheapest['tco'] - top['tco']:.2f} cheaper all in.")
    notes = [_record_text(top)] + ([f"{top['seller']}: {', '.join(top['missing'])} not stated, so no credit was given"]
                                   if top["missing"] else [])
    return {"ranking": ranked, "excluded": excluded, "advisory": True,
            "note": f"{head} {'. '.join(n[0].upper() + n[1:] for n in notes)}. Advisory only: the referee's ranking by landed price stays the rule."}
