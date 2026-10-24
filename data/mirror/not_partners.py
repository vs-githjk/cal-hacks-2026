"""Real stores we mirror that never joined Tech Bazaar (#333). Pure, no imports, safe for any lane.

Our agent may bid such a store's dated public listings (MIRROR) so the buyer can compare prices, but the store never
agreed to sell here: a bid for it is shown for comparison only and must never be ordered, put on a mandate, charged or
paid. Every money path refuses it (agents/advocate/checks.py veto, agents/buyer/hunt.py pick_best and orderable, the
buyer's eligible_for_order, conclude and on_requote). The registry is code-owned: a bid cannot opt itself out of it.
"""
from __future__ import annotations

# seller id -> the MIRROR label shown wherever the bid is shown (code-owned text, never taken from the bid)
SELLERS = {
    "central_computers_sf": ("MIRROR: real Central Computers listing captured Oct 24 21:12 UTC via Apify. "
                             "Central Computers is not a partner."),
}
# snapshot file prefixes of those stores (data/mirror/snapshots/<prefix>-<stamp>.json): kept out of retail medians
STORES = frozenset({"centralcomputers"})
NOT_ORDERABLE = "Shown for comparison, cannot be bought here."


def orderable(bid) -> bool:
    """False for any bid from a mirrored store that never joined, or any bid that marks itself not orderable.
    Fails closed: a non-dict bid is not orderable."""
    if not isinstance(bid, dict):
        return False
    ids = {bid.get("supplier_id"), bid.get("seller_id")}
    return not (ids & set(SELLERS)) and bid.get("orderable", True) is not False


def label(bid) -> str | None:
    """The code-owned MIRROR label for a bid from a store in SELLERS, else None."""
    if not isinstance(bid, dict):
        return None
    return SELLERS.get(bid.get("supplier_id")) or SELLERS.get(bid.get("seller_id"))
