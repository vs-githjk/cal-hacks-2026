"""Deterministic seller bid pricing. Prices come from here, never from an LLM."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

CATALOG = json.loads((Path(__file__).parent / "sellers.json").read_text(encoding="utf-8"))


def seller(name: str) -> dict:
    return {"id": name, **CATALOG["sellers"][name]}


def make_bid(need: dict, seller: dict, now: datetime | None = None) -> dict | None:
    """Bid on every need line this seller carries (partial bids are fine); None if it carries none.
    Need items' legacy grade/pack_size fields are ignored."""
    lines, notes = [], []
    for want in need["items"]:
        sku = want["sku_spec"]
        have = seller["listings"].get(sku)
        if not have:
            continue
        price = round(have["price"] * (1 - seller["discount"]), 2)
        if price < have["floor"]:
            notes.append(f"{sku} held at floor {have['floor']:.2f}")
            price = have["floor"]
        lines.append({"sku_spec": sku, "unit_price": price, "quantity": want["quantity"],
                      "offered_condition": have["condition"], "variant": have["variant"],
                      "listing_url": have["listing_url"], "page_condition": have["page_condition"],
                      "attrs": dict(have["attrs"])})
    if not lines:
        return None

    total = round(sum(l["unit_price"] * l["quantity"] for l in lines) + seller["shipping"], 2)
    skipped = [w["sku_spec"] for w in need["items"] if w["sku_spec"] not in seller["listings"]]
    trace = (f"List price less {seller['discount']:.0%} discount"
             + (f", {'; '.join(notes)}" if notes else "")
             + f", plus ${seller['shipping']:.2f} shipping = ${total:.2f}."
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
        "floor_check_passed": all(l["unit_price"] >= seller["listings"][l["sku_spec"]]["floor"] for l in lines),
        "mirror_snapshot_id": CATALOG["mirror_snapshot_id"],
        "decision_trace": trace,
        "expires_at": (now + timedelta(seconds=need.get("auction_window_s", 60))).isoformat(),
        "origin": "SIM",
        "source": "simulated",
    }
