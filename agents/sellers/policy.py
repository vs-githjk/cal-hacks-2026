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
    return seller_from_config({"id": name, **CATALOG["sellers"][name]})


def _lines_for(have: dict) -> list[dict]:
    """The primary condition line and any alternative condition lines of one listing."""
    primary = {k: have[k] for k in ("condition", "page_condition", "price", "floor", "listing_url")}
    return [primary, *have.get("alt_lines", [])]


def make_bid(need: dict, seller: dict, now: datetime | None = None) -> dict | None:
    """Bid on every need line this seller carries (partial bids are fine); None if it carries none.
    A listing with several condition lines bids all of them as alternatives (the market takes the cheapest allowed
    one per SKU), so the headline total counts only the cheapest line of each SKU.
    Need items' legacy grade/pack_size fields are ignored."""
    lines, notes, cheapest = [], [], []
    discount = seller["discount"]
    for want in need["items"]:
        sku = want["sku_spec"]
        have = seller["listings"].get(sku)
        if not have:
            continue
        prices = []
        for alt in _lines_for(have):
            price = round(alt["price"] * (1 - discount), 2)
            if price < alt["floor"]:
                notes.append(f"{sku} ({alt['condition']}) held at floor {alt['floor']:.2f}")
                price = alt["floor"]
            prices.append(price)
            lines.append({"sku_spec": sku, "unit_price": price, "quantity": want["quantity"],
                          "offered_condition": alt["condition"], "variant": have["variant"],
                          "listing_url": alt["listing_url"], "page_condition": alt["page_condition"],
                          "attrs": dict(have["attrs"]), "_floor": alt["floor"]})
        cheapest.append(min(prices) * want["quantity"])
    if not lines:
        return None

    floors_ok = all(l["unit_price"] >= l.pop("_floor") for l in lines)
    total = round(sum(cheapest) + seller["shipping"], 2)
    skipped = [w["sku_spec"] for w in need["items"] if w["sku_spec"] not in seller["listings"]]
    margin = seller.get("margin_pct")
    basis = f"Cost plus {margin:g}% margin" if margin is not None else f"List price less {discount:.0%} discount"
    trace = (basis
             + (f", {'; '.join(notes)}" if notes else "")
             + f", plus ${seller['shipping']:.2f} shipping = ${total:.2f}."
             + (" Several condition lines of one SKU are alternatives; the total uses the cheapest."
                if any(len(_lines_for(h)) > 1 for h in seller["listings"].values()) else "")
             + (f" Not carried: {', '.join(skipped)}." if skipped else ""))
    now = now or datetime.now(timezone.utc)
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
        "mirror_snapshot_id": CATALOG["mirror_snapshot_id"],
        "decision_trace": trace,
        "expires_at": (now + timedelta(seconds=need.get("auction_window_s", 60))).isoformat(),
        "origin": seller.get("origin", "SIM"),
        "source": "simulated" if seller.get("origin", "SIM") == "SIM" else f"seller-config:{seller['id']}",
    }
