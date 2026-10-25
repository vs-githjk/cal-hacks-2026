"""What the Buyer bought for you, remembered as owned parts, so it never quietly buys the same thing twice.

`record` runs once a purchase has settled and writes one OwnedPart (source "bought_here") per bought line into the
Buyer's existing private state (state.remember_owned). It never raises: a memory write must not disturb a settled
purchase. `apply_all` runs when a new goal arrives:
  * a line for the exact SKU you already bought here is skipped, citing the purchase, unless you said upgrade,
    replace, another, second or extra;
  * a line for a different model of a part you bought here is kept, with a heads-up (it may be a real upgrade);
  * parts you told the Buyer about keep their old rule (goal.apply_owned).
Owned parts are stored with the category as the first word of sku_spec ("gpu rtx 4070 super 12gb"), the key the
Advocate's fit checks and goal.owned_attrs already read.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import catalog
import goal as G
import state as buyer_state

AGAIN = re.compile(r"\b(?:upgrade|replace|another|second|extra|two|spare)\w*\b", re.I)
VALID_CONDITIONS = {"new", "open-box", "refurbished", "used"}


def _stored_sku(category: str, sku: str) -> str:
    return sku if sku.split()[0] == category else f"{category} {sku}"


def sku_of(part: dict) -> str:
    """The catalog SKU of a bought part (undoing the category prefix added when it was stored)."""
    stored = part["sku_spec"]
    head, _, rest = stored.partition(" ")
    return rest if rest and catalog.category_of(rest) == head else stored


def part_names(bid: dict) -> str:
    """Plain names of the catalog lines of a bid ('RTX 4070 Super 12GB'), for the receipt the owner reads in chat."""
    names = []
    for line in (bid or {}).get("lines", []):
        sku = line.get("sku_spec")
        if isinstance(sku, str) and sku.strip() and catalog.category_of(sku) is not None:
            names.append(catalog.label(sku))
    return ", ".join(names) or "your order"


def record(db, buyer_id: str, bids: list, tx: dict, now: datetime | None = None) -> list[dict]:
    """Remember the lines of a settled purchase. Returns what was stored; any failure returns [] (never raises)."""
    try:
        bid = next((b for b in bids or [] if b.get("id") == tx.get("bid_id")), None)
        if bid is None:
            return []
        today = (now or datetime.now(timezone.utc)).date().isoformat()
        parts = []
        for line in bid.get("lines", []):
            sku = line.get("sku_spec")
            cat = catalog.category_of(sku) if isinstance(sku, str) else None
            if cat is None:
                continue  # not a catalog part: nothing safe to remember
            cond = line.get("condition")
            parts.append({"id": f"owned-{uuid.uuid4().hex[:8]}", "buyer_id": buyer_id, "sku_spec": _stored_sku(cat, sku),
                          "item_name": catalog.label(sku), "condition": cond if cond in VALID_CONDITIONS else "unknown",
                          "acquired_on": today, "source": "bought_here", "attrs": catalog.attrs_of(sku),
                          "notes": f"bought through me on {today} for ${bid.get('total_landed_price', 0):,.2f}"})
        return buyer_state.remember_owned(db, buyer_id, parts) if parts else []
    except Exception:
        return []


def told_only(owned: list[dict]) -> list[dict]:
    return [o for o in owned if o.get("source") != "bought_here"]


def apply_all(goal: dict, owned: list[dict]) -> tuple[dict, list[str]]:
    """goal.apply_owned for told parts, plus the bought-here duplicate rule. Returns (goal, heads-up lines)."""
    goal = G.apply_owned(goal, told_only(owned))
    notes = []
    again = bool(AGAIN.search(goal.get("notes", "")))
    for item in goal["items"]:
        if item.get("skipped_owned_part_id"):
            continue
        for o in owned:
            if o.get("source") != "bought_here" or o["sku_spec"].split()[0] != item.get("part"):
                continue
            bought = sku_of(o)
            if bought == item["sku_spec"] and not again:
                item["skipped_owned_part_id"] = o["id"]
            elif bought == item["sku_spec"]:
                notes.append(f"You bought a {catalog.label(bought)} through me on {o['acquired_on']}; "
                             "you asked for another, so I am shopping it again.")
            else:
                notes.append(f"Heads up: you bought a {catalog.label(bought)} through me on {o['acquired_on']}. "
                             f"I am still shopping the {catalog.label(item['sku_spec'])} because it is a different model. "
                             "Reply CANCEL if you did not mean to.")
    from common import validate
    return validate("Goal", goal), notes
