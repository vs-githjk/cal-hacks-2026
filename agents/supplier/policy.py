"""Deterministic bid pricing. Prices come from here, never from an LLM."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load():
    return json.loads((Path(__file__).parent / "suppliers.json").read_text(encoding="utf-8"))


def make_bid(need: dict, supplier: dict, catalog: dict, now: datetime | None = None) -> dict | None:
    """Return a Bid for this supplier, or None if it can't fill the need as specified.
    `catalog` is the loaded suppliers.json (mirror prices + snapshot id)."""
    mirror = catalog.get("catalog", {})
    lines, notes, swaps, floor_ok = [], [], [], True
    for want in need["items"]:
        sku = want["sku_spec"]
        have = supplier["items"].get(sku)
        if not have or have["pack_size"] != want["pack_size"]:
            return None
        if have["grade"] != want["grade"]:
            if not supplier.get("spec_swapper"):
                return None
            swaps.append(f"{sku}: offered {have['grade']} instead of requested {want['grade']}")
        base = have.get("unit_price", mirror.get(sku, {}).get("unit_price"))
        price = round(base * (1 - supplier["discount"]), 2)
        floor = have.get("floor")
        if floor is not None and price < floor:
            notes.append(f"{sku} held at floor {floor:.2f}")
            price = floor
        if floor is None or price < floor:
            floor_ok = False
        lines.append({"sku_spec": sku, "unit_price": price, "quantity": want["quantity"]})

    total = round(sum(l["unit_price"] * l["quantity"] for l in lines) + supplier["delivery_fee"], 2)
    trace = (f"List price less {supplier['discount']:.0%} discount"
             + (f", {'; '.join(notes)}" if notes else "")
             + f", plus ${supplier['delivery_fee']:.2f} delivery = ${total:.2f}.")
    if swaps:
        trace += " SPEC SWAP: " + "; ".join(swaps) + "."
    now = now or datetime.now(timezone.utc)
    return {
        "id": f"bid-{need['id']}-{supplier['supplier_id']}",
        "need_id": need["id"],
        "supplier_id": supplier["supplier_id"],
        "persona": supplier["name"],
        "lines": lines,
        "total_landed_price": total,
        "perks": list(supplier["perks"]),
        "claims": list(supplier["claims"]),
        "floor_check_passed": floor_ok,
        "mirror_snapshot_id": catalog["mirror_snapshot_id"],
        "decision_trace": trace,
        "expires_at": (now + timedelta(seconds=need.get("auction_window_s", 60))).isoformat(),
        "source": "simulated",
    }
