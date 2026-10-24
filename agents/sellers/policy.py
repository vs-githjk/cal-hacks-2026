"""Deterministic seller bids from labelled SIM catalog lines and normalized MIRROR snapshots."""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

CATALOG = json.loads((Path(__file__).parent / "sellers.json").read_text(encoding="utf-8"))
ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "data" / "mirror" / "snapshots"
CONDITIONS = {"new", "open-box", "refurbished", "used"}


def _mirror_listings(name: str) -> list[dict]:
    stores = CATALOG.get("mirror_assignments", {}).get(name, {})
    rows = []
    for path in sorted(SNAPSHOTS.glob("*.json")):
        store = path.name.split("-")[0]
        seller_of_record = stores.get(store)
        if not seller_of_record:
            continue
        for card in json.loads(path.read_text(encoding="utf-8")):
            listing = card.get("listing") or {}
            if (card.get("origin") != "MIRROR" or card.get("category") != "gpu" or card.get("price") is None
                    or card.get("condition") == "unknown" or listing.get("stock") is False):
                continue
            rows.append({**card, "seller_of_record": seller_of_record})
    return rows


def seller(name: str) -> dict:
    return {"id": name, **CATALOG["sellers"][name], "mirror_listings": _mirror_listings(name),
            "mirror_inputs": CATALOG.get("mirror_inputs", {}).get(name, {})}


def _term(value: dict, key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, dict) or item.get("origin") != "MIRROR":
        return False
    amount = item.get("value")
    source = item.get("source")
    observed_at = item.get("observed_at")
    try:
        parsed = urlsplit(source)
        when = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        return (isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount)
                and amount >= 0 and parsed.scheme in ("http", "https") and parsed.hostname is not None
                and parsed.username is None and parsed.password is None and when.tzinfo is not None)
    except (AttributeError, TypeError, ValueError):
        return False


def _allowed(want: dict) -> set[str]:
    values = set(want.get("allowed_conditions") or [want.get("condition", "new")])
    return values & CONDITIONS


def _in_stock(card: dict) -> bool:
    stock = (card.get("listing") or {}).get("stock")
    if stock is True:
        return True
    if not isinstance(stock, str):
        return False
    state = stock.lower()
    return ("out of stock" not in state and "unavailable" not in state and "not available" not in state
            and "sold out" not in state and ("in stock" in state or "remaining" in state or "available" in state))


def make_bid(need: dict, seller: dict, now: datetime | None = None) -> dict | None:
    """Bid only on known allowed lines. MIRROR asks need dated floor and shipping evidence before they can rank."""
    lines, notes, origins = [], [], set()
    mirror_inputs = seller.get("mirror_inputs", {})
    for want in need["items"]:
        sku = want["sku_spec"]
        allowed = _allowed(want)
        have = seller["listings"].get(sku)
        quantity = want.get("quantity")
        valid_quantity = (isinstance(quantity, (int, float)) and not isinstance(quantity, bool)
                          and math.isfinite(quantity) and quantity > 0)
        if (have and valid_quantity and have.get("condition") in CONDITIONS and have["condition"] in allowed
                and isinstance(have.get("price"), (int, float)) and not isinstance(have.get("price"), bool)
                and math.isfinite(have["price"]) and have["price"] >= 0
                and isinstance(have.get("floor"), (int, float)) and not isinstance(have.get("floor"), bool)
                and math.isfinite(have["floor"]) and have["floor"] >= 0
                and isinstance(seller.get("discount"), (int, float)) and not isinstance(seller.get("discount"), bool)
                and math.isfinite(seller["discount"]) and 0 <= seller["discount"] < 1):
            price = round(have["price"] * (1 - seller["discount"]), 2)
            if price < have["floor"]:
                notes.append(f"{sku} held at floor {have['floor']:.2f}")
                price = have["floor"]
            lines.append({"sku_spec": sku, "unit_price": price, "quantity": want["quantity"],
                          "offered_condition": have["condition"], "variant": have["variant"],
                          "listing_url": have["listing_url"], "page_condition": have["page_condition"],
                          "attrs": dict(have["attrs"]), "origin": "SIM", "source": "simulated"})
            origins.add("SIM")

        if need.get("source") not in ("live", "mirror"):
            continue
        matches = [c for c in seller.get("mirror_listings", [])
                   if isinstance(c.get("attrs", {}).get("chipset"), str)
                   and c["attrs"]["chipset"].lower() == sku.lower()
                   and c.get("condition") in allowed]
        for card in matches:
            inputs = mirror_inputs.get(card["id"], {})
            price = card.get("price")
            if (not isinstance(quantity, (int, float)) or isinstance(quantity, bool) or not math.isfinite(quantity)
                    or quantity <= 0 or not isinstance(price, (int, float)) or isinstance(price, bool)
                    or not math.isfinite(price) or price < 0
                    or not (_in_stock(card) and _term(inputs, "floor") and _term(inputs, "shipping"))):
                continue
            price, floor = float(price), float(inputs["floor"]["value"])
            if price < floor:
                continue
            line_shipping = float(inputs["shipping"]["value"])
            lines.append({"sku_spec": sku, "unit_price": price, "quantity": want["quantity"],
                          "shipping": line_shipping,
                          "offered_condition": card["condition"], "variant": card.get("variant", "retail"),
                          "listing_url": card["source"], "attrs": dict(card.get("attrs") or {}),
                          "origin": "MIRROR", "source": card["source"], "seller_of_record": card["seller_of_record"],
                          "listing_id": card["id"],
                          "model_number": card.get("model_number"),
                          "snapshot_id": card["snapshot_id"], "snapshot_date": card["snapshot_date"],
                          "floor_evidence": dict(inputs["floor"]), "shipping_evidence": dict(inputs["shipping"])})
            origins.add("MIRROR")
    if not lines or len(origins) != 1:
        return None
    origin = origins.pop()
    if origin == "SIM":
        # SIM catalog shipping is a fixed basket fee. Allocate it once, on the first
        # carried line, so a market consumer summing lines sees the same landed total.
        lines[0]["shipping"] = seller["shipping"]
        for line in lines[1:]:
            line["shipping"] = 0.0
    if origin == "MIRROR":
        if len({l["sku_spec"] for l in lines}) != 1:
            return None
        if len({(l["seller_of_record"], l["snapshot_id"]) for l in lines}) != 1:
            return None
        total = round(min(l["unit_price"] * l["quantity"] + l["shipping"] for l in lines), 2)
    else:
        total = round(sum(l["unit_price"] * l["quantity"] for l in lines) + seller["shipping"], 2)
    skipped = [w["sku_spec"] for w in need["items"] if not any(l["sku_spec"] == w["sku_spec"] for l in lines)]
    if origin == "MIRROR":
        snapshot_id = lines[0]["snapshot_id"]
        seller_of_record = lines[0]["seller_of_record"]
        trace = f"MIRROR asking prices from {snapshot_id}; seller of record: {seller_of_record}; shipping and floor are sourced inputs."
    else:
        snapshot_id = CATALOG["mirror_snapshot_id"]
        trace = (f"List price less {seller['discount']:.0%} discount"
                 + (f", {'; '.join(notes)}" if notes else "")
                 + f", plus ${seller['shipping']:.2f} shipping = ${total:.2f}.")
    if skipped:
        trace += f" Not carried: {', '.join(skipped)}."
    now = now or datetime.now(timezone.utc)
    return {
        "id": f"bid-{need['id']}-{seller['id']}", "need_id": need["id"],
        "supplier_id": seller["id"], "seller_id": seller["id"], "persona": seller["name"],
        "lines": lines, "total_landed_price": total,
        **({"seller_of_record": seller_of_record} if origin == "MIRROR" else {}),
        "perks": [] if origin == "MIRROR" else list(seller["perks"]),
        "claims": ["MIRROR listing provenance attached per line; no merchant payment is enabled."]
                  if origin == "MIRROR" else list(seller["claims"]),
        "floor_check_passed": True, "mirror_snapshot_id": snapshot_id, "decision_trace": trace,
        "expires_at": (now + timedelta(seconds=need.get("auction_window_s", 60))).isoformat(),
        "origin": origin, "source": lines[0]["source"],
    }
