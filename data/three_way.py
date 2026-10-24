"""Three-way match (Lane C, kickoff item c14): the purchase order, the listing page and claims, and the delivery check.

    three_way_match(po, listing, delivery, origin=None) -> {"result": "match"|"mismatch"|"unverified", "mismatches", "missing", ...}

A pure function: callers pass the results of the page read, the claim checks and the receiving check; nothing here touches
the network. "match" is never returned while a source is missing or unreadable. Wording is neutral ("sources disagree").
  po:       {"sku_spec", "condition", "price", "quantity"}   what the buyer approved
  listing:  {"url", "page": page_facts dict or None, "claims": [check_claim results]}
  delivery: {"condition", "quantity", "ok": bool, "reasons": [..]}   the receiving check
"""
from __future__ import annotations

from datetime import datetime, timezone


def _cond(v):
    return str(v).strip().lower().replace(" ", "-").replace("_", "-") if v not in (None, "") else None


def _show(c):
    return c.replace("-", " ")


def _qty(v):
    """A whole, non-negative number of units; a bool, a fraction, a negative or a string is not a quantity."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if v >= 0 and v == int(v) else None


def _price(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return None
    return float(v)


def three_way_match(po: dict, listing: dict, delivery: dict, origin: str | None = None) -> dict:
    mismatches, missing = [], []
    page = listing.get("page")
    claims = listing.get("claims") or []
    po_price, po_cond, po_qty = _price(po.get("price")), _cond(po.get("condition")), _qty(po.get("quantity"))

    if not isinstance(page, dict):
        missing.append("page")
    else:
        page_price, page_cond = _price(page.get("price")), _cond(page.get("condition"))
        if page_price is None:
            missing.append("page price")
        elif po_price is not None and abs(page_price - po_price) > 0.01:
            mismatches.append({"code": "price_differs", "sources": ["po", "page"],
                               "detail": f"sources disagree: PO says ${po_price:,.2f}, page says ${page_price:,.2f}"})
        if page_cond is None:
            missing.append("page condition")
        elif po_cond is not None and page_cond != po_cond:
            mismatches.append({"code": "condition_page", "sources": ["po", "page"],
                               "detail": f"sources disagree: page says {_show(page_cond)}"})
    if po_price is None:
        missing.append("po price")
    if po_cond is None:
        missing.append("po condition")
    if po_qty is None:
        missing.append("po quantity")

    for c in claims:
        if c.get("result") == "false":
            mismatches.append({"code": "claim_false", "sources": ["claim", "page"],
                               "detail": f"seller claim did not match the page: {c.get('reason')}"})
    if any(c.get("result") == "unverified" for c in claims):
        missing.append("claim check")

    d_cond, d_qty = _cond(delivery.get("condition")), _qty(delivery.get("quantity"))
    if d_cond is None:
        missing.append("delivery condition")
    elif po_cond is not None and d_cond != po_cond:
        mismatches.append({"code": "condition_delivered", "sources": ["po", "delivery"],
                           "detail": f"sources disagree: delivered {_show(d_cond)}, PO says {_show(po_cond)}"})
    if d_qty is None:
        missing.append("delivery quantity")
    elif po_qty is not None and d_qty != po_qty:
        mismatches.append({"code": "quantity_short" if d_qty < po_qty else "quantity_over", "sources": ["po", "delivery"],
                           "detail": f"delivered {d_qty} of {po_qty}"})
    if delivery.get("ok") is False:
        why = "; ".join(str(r) for r in delivery.get("reasons") or []) or "no reason given"
        mismatches.append({"code": "delivery_failed", "sources": ["delivery"], "detail": f"receiving check failed: {why}"})
    elif delivery.get("ok") is not True:
        missing.append("delivery check")

    result = "mismatch" if mismatches else "unverified" if missing else "match"
    return {"result": result, "mismatches": mismatches, "missing": sorted(set(missing)), "url": listing.get("url"),
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "origin": origin}
