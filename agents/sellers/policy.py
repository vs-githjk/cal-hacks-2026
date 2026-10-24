"""Deterministic seller bid pricing. Prices come from here, never from an LLM."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for factory

from factory import seller_from_config

CATALOG = json.loads((Path(__file__).parent / "sellers.json").read_text(encoding="utf-8"))


def seller(name: str) -> dict:
    """A catalog seller as the dict make_bid reads (checked against contracts/SellerConfig.schema.json)."""
    return seller_from_config({"id": name, **CATALOG["sellers"][name]}, catalog=True)


def mirror_seller(name: str, clearance_mm: int | None = None) -> dict | None:
    """A MIRROR seller (#283 T9): our agent bidding a real store's dated listings, labelled as such, never a partner.
    Built from data/mirror, not sellers.json. None when the store has no listing it may bid."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for data.*
    from data.mirror import central_computers
    sources = {central_computers.SELLER_ID: central_computers.seller}
    return sources[name](clearance_mm)


def _lines_for(have: dict) -> list[dict]:
    """The primary condition line and any alternative condition lines of one listing."""
    primary = {k: have[k] for k in ("condition", "page_condition", "price", "floor", "listing_url")}
    return [primary, *have.get("alt_lines", [])]


def _allowed_lines(want: dict, have: dict) -> list[dict]:
    """The lines of one listing the buyer's condition allows (allowed_conditions, else the one condition asked for).
    When none of this seller's lines is allowed, all of them (today's behaviour: the market judges the mismatch)."""
    lines = _lines_for(have)
    allowed = want.get("allowed_conditions") or ([want["condition"]] if want.get("condition") else [])
    return [l for l in lines if l["condition"] in allowed] or lines


def make_bid(need: dict, seller: dict, now: datetime | None = None) -> dict | None:
    """Bid on every need line this seller carries (partial bids are fine); None if it carries none.
    A listing with several condition lines bids all of them as alternatives (the market takes the cheapest allowed
    one per SKU), so the headline total counts only the cheapest line of each SKU. When the need allows some of a
    listing's conditions, only those lines are bid and priced, so the total never rests on a line the buyer excluded.
    Need items' legacy grade/pack_size fields are ignored."""
    lines, notes, cheapest = [], [], []
    discount = seller["discount"]
    for want in need["items"]:
        sku = want["sku_spec"]
        have = seller["listings"].get(sku)
        if not have:
            continue
        prices = []
        for alt in _allowed_lines(want, have):
            price = round(alt["price"] * (1 - discount), 2)
            if price < alt["floor"]:
                notes.append(f"{sku} ({alt['condition']}) held at floor {alt['floor']:.2f}")
                price = alt["floor"]
            prices.append(price)
            lines.append({"sku_spec": sku, "unit_price": price, "quantity": want["quantity"],
                          "offered_condition": alt["condition"], "variant": have["variant"],
                          "listing_url": alt["listing_url"], "page_condition": alt["page_condition"],
                          "attrs": dict(have["attrs"]), "_floor": alt["floor"],
                          **({"qty_available": have["qty_available"]} if "qty_available" in have else {})})
        cheapest.append(min(prices) * want["quantity"])
    if not lines:
        return None

    floors_ok = all(l["unit_price"] >= l.pop("_floor") for l in lines)
    total = round(sum(cheapest) + seller["shipping"], 2)
    skipped = [w["sku_spec"] for w in need["items"] if w["sku_spec"] not in seller["listings"]]
    margin = seller.get("margin_pct")
    basis = f"Cost plus {margin:g}% margin" if margin is not None else f"List price less {discount:.0%} discount"
    mirror = seller.get("origin") == "MIRROR"  # a real listing: no shipping figure was captured, so none is claimed
    trace = ((f"{seller['trace_prefix']} " if seller.get("trace_prefix") else "") + ("Listed price" if mirror else basis)
             + (f", {'; '.join(notes)}" if notes else "")
             + (f" = ${total:.2f} before delivery." if mirror else f", plus ${seller['shipping']:.2f} shipping = ${total:.2f}.")
             + (" Several condition lines of one SKU are alternatives; the total uses the cheapest."
                if len(lines) > len({l["sku_spec"] for l in lines}) else "")
             + (f" Not carried: {', '.join(skipped)}." if skipped else ""))
    now = now or datetime.now(timezone.utc)
    origin = seller.get("origin", "SIM")
    source = {"SIM": "simulated", "MIRROR": lines[0]["listing_url"]}.get(origin, f"seller-config:{seller['id']}")
    return {
        "id": f"bid-{need['id']}-{seller['id']}",
        "need_id": need["id"],
        "supplier_id": seller["id"],
        "persona": seller["name"],
        "lines": lines,
        "total_landed_price": total,
        "perks": list(seller["perks"]),
        "claims": list(seller["claims"]),
        "floor_check_passed": floors_ok,
        "mirror_snapshot_id": seller.get("mirror_snapshot_id", CATALOG["mirror_snapshot_id"]),
        "decision_trace": trace,
        "expires_at": (now + timedelta(seconds=need.get("auction_window_s", 60))).isoformat(),
        "origin": origin,
        "source": source,
        **({"mirror_label": seller["mirror_label"]} if seller.get("mirror_label") else {}),
        # cheaper or other in-stock lines the agent did not bid, with the fit reason (additive key, not seller text)
        **({"withheld_lines": [dict(w) for w in seller["withheld"]]} if seller.get("withheld") else {}),
    }
