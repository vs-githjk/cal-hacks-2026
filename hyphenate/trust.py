"""Sources that disagree: a fixed trust ranking per question, and the reason written down for every call.

The ranking is data, not a model call. `resolve` names which source it believed, which it did not, and why.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from pay.mandate import parse_ts

# Highest trust first, per question. Each entry says why that source sits there.
RANKING = {
    "cash_amount": [
        ("bank", "the bank (or Stripe test record) is an outside party that actually moved the money"),
        ("ledger", "our own books record what we meant to pay"),
        ("seller_claim", "the seller's statement is the interested party"),
    ],
    "goods_condition": [
        ("receiving", "we inspected the item ourselves, with serials, on the day it arrived"),
        ("claim_check", "an independent check of the listing page at a stated time"),
        ("seller_claim", "the seller's own listing or invoice is the interested party"),
    ],
    "goods_quantity": [
        ("receiving", "we counted what arrived"),
        ("ledger", "our books only know what receiving told them"),
        ("seller_claim", "the seller's invoice states what they say they shipped"),
    ],
    "agreed_price": [
        ("contract", "the approved PO is the price someone with authority agreed to"),
        ("seller_claim", "the invoice is the seller's request, not an agreement"),
        ("mirror", "a dated market listing says what others charge, not what we agreed"),
    ],
    "market_price": [
        ("mirror", "a dated listing from a real store is the nearest outside price evidence"),
        ("seller_claim", "the seller's own price is the interested party"),
    ],
    "remit_account": [
        ("vendor_master", "the vendor master was changed and verified by two different people"),
        ("seller_claim", "bank details on an invoice are the classic fraud channel"),
    ],
}
MIRROR_STALE_DAYS = 14


def resolve(field: str, observations: Iterable[dict], *, now: Optional[str] = None) -> dict:
    """observations: [{"source", "value", "ref", "as_of"?}]. Returns the believed value, the sources that disagree,
    any ignored as stale, and a sentence that says why."""
    ranking = RANKING[field]
    order = {s: i for i, (s, _) in enumerate(ranking)}
    why = dict(ranking)
    obs, stale = [], []
    for o in observations:
        if o["source"] not in order:
            raise ValueError(f"{o['source']} is not a source for {field}")
        if o["source"] == "mirror" and now and o.get("as_of"):
            age = (parse_ts(now) - parse_ts(o["as_of"])).days
            if age > MIRROR_STALE_DAYS:
                stale.append({**o, "age_days": age})
                continue
        obs.append(o)
    if not obs:
        return {"field": field, "trusted": None, "agreed": False, "disagreeing": [], "stale": stale,
                "reason": f"no usable source for {field}" + (" (the only reference is stale)" if stale else "")}
    obs.sort(key=lambda o: order[o["source"]])
    top = obs[0]
    others = [o for o in obs[1:] if o["value"] != top["value"]]
    if others:
        parts = " and ".join(f"{o['source']} ({o['value']})" for o in others)
        reason = f"For {field} I believed {top['source']} ({top['value']}) over {parts}, because {why[top['source']]}."
    else:
        reason = f"For {field} every usable source agrees on {top['value']} (most trusted: {top['source']})."
    if stale:
        reason += f" Ignored stale {stale[0]['source']} reading ({stale[0]['age_days']} days old)."
    return {"field": field, "trusted": top, "agreed": not others, "disagreeing": others, "stale": stale, "reason": reason}
