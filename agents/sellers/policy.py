"""Deterministic seller bids from labelled SIM catalog lines and normalized MIRROR snapshots."""
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for factory
_REPO = str(Path(__file__).resolve().parents[2])
if _REPO not in sys.path:  # repo root, for data.* (mirror sellers); added once, at import
    sys.path.insert(0, _REPO)

from factory import seller_from_config

CATALOG = json.loads((Path(__file__).parent / "sellers.json").read_text(encoding="utf-8"))
ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "data" / "mirror" / "snapshots"
CONDITIONS = {"new", "open-box", "refurbished", "used"}
QUOTE_TTL_S = 600


def _mirror_listings(name: str) -> list[dict]:
    stores = CATALOG.get("mirror_assignments", {}).get(name, {})
    rows = []
    for path in sorted(SNAPSHOTS.glob("*.json")):
        if "sold" in path.name.lower():
            continue
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
    """A catalog seller as the dict make_bid reads (checked against contracts/SellerConfig.schema.json)."""
    return {**seller_from_config({"id": name, **CATALOG["sellers"][name]}, catalog=True),
            "mirror_listings": _mirror_listings(name),
            "mirror_inputs": CATALOG.get("mirror_inputs", {}).get(name, {})}


def _term(value: dict, key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, dict) or item.get("origin") != "MIRROR":
        return False
    amount = item.get("value")
    source = item.get("source")
    observed_at = item.get("observed_at")
    try:
        if not isinstance(source, str) or len(source) > 2048:
            return False
        parsed = urlsplit(source)
        hostname = parsed.hostname
        port = parsed.port
        when = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        return (isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount)
                and amount >= 0 and parsed.scheme in ("http", "https") and isinstance(hostname, str)
                and hostname and not any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7f for char in hostname)
                and parsed.username is None and parsed.password is None
                and (port is None or 1 <= port <= 65535)
                and not any(ord(char) <= 0x20 or ord(char) == 0x7f for char in source)
                and when.tzinfo is not None and when.utcoffset() is not None)
    except (AttributeError, TypeError, ValueError, OverflowError):
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


def mirror_seller(name: str, clearance_mm: int | None = None) -> dict | None:
    """A MIRROR seller (#283 T9): our agent bidding a real store's dated listings, labelled as such, never a partner.
    Built from data/mirror, not sellers.json. None for an unknown name or when the store has no listing it may bid.
    Its bids are shown for comparison and are never orderable (#333, data.mirror.not_partners)."""
    from data.mirror import central_computers
    sources = {central_computers.SELLER_ID: central_computers.seller}
    build = sources.get(name)
    return build(clearance_mm) if build else None


def _lines_for(have: dict) -> list[dict]:
    """The primary condition line and any alternative condition lines of one listing."""
    primary = {k: have[k] for k in ("condition", "page_condition", "price", "floor", "listing_url")}
    return [primary, *have.get("alt_lines", [])]


def _allowed_lines(want: dict, have: dict) -> list[dict]:
    """The lines of one listing the buyer's condition allows (allowed_conditions, else the one condition asked for).
    When none of this seller's lines is allowed, all of them (the market judges the mismatch)."""
    lines = _lines_for(have)
    allowed = _allowed(want)
    return [l for l in lines if l["condition"] in allowed] or lines


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def make_bid(need: dict, seller: dict, now: datetime | None = None) -> dict | None:
    """Bid only on known allowed lines. MIRROR asks need dated floor and shipping evidence before they can rank.
    A SIM or owner-supplied listing with several condition lines bids all allowed ones as alternatives (the market takes
    the cheapest allowed one per SKU), so the headline total counts only the cheapest line of each SKU."""
    lines, notes, origins, cheapest = [], [], set(), []
    mirror_inputs = seller.get("mirror_inputs", {})
    own_origin = seller.get("origin", "SIM")
    own_source = "simulated" if own_origin == "SIM" else f"seller-config:{seller['id']}"
    # A listing-based MIRROR seller (data/mirror, e.g. Central Computers) bids a real store's listing as captured:
    # its page may not state a condition, so "unknown" is a valid line there (never shown as new, #308).
    listing_mirror = own_origin == "MIRROR"
    line_conditions = CONDITIONS | {"unknown"} if listing_mirror else CONDITIONS
    discount = seller.get("discount")
    for want in need["items"]:
        sku = want["sku_spec"]
        allowed = _allowed(want)
        have = seller["listings"].get(sku)
        quantity = want.get("quantity")
        valid_quantity = _num(quantity) and quantity > 0
        if have and valid_quantity and _num(discount) and discount < 1:
            prices = []
            for index, alt in enumerate(_allowed_lines(want, have)):
                if not (alt.get("condition") in line_conditions and _num(alt.get("price")) and _num(alt.get("floor"))):
                    continue
                stock = have.get("qty_available")
                if stock is not None and not (_num(stock) and quantity <= stock):
                    continue  # #333: never bid more units than the listing has
                price = round(alt["price"] * (1 - discount), 2)
                if price < alt["floor"]:
                    notes.append(f"{sku} pricing constraint applied")
                    price = alt["floor"]
                prices.append(price)
                listing_id = have.get("listing_id", f"SIM:{seller['id']}:{sku}")
                lines.append({"sku_spec": sku, "unit_price": price, "quantity": want["quantity"],
                              "offered_condition": alt["condition"], "variant": have["variant"],
                              "listing_id": listing_id if index == 0 else f"{listing_id}:{alt['condition']}",
                              "listing_url": alt["listing_url"], "page_condition": alt["page_condition"],
                              "attrs": dict(have["attrs"]), "origin": own_origin, "source": own_source,
                              **({"qty_available": have["qty_available"]} if "qty_available" in have else {})})
                if listing_mirror:  # the real listing is the source; its store is the seller of record, not a payee
                    lines[-1].update(source=alt["listing_url"], shipping=float(seller.get("shipping", 0.0)),
                                     seller_of_record=seller.get("seller_of_record", seller["name"]),
                                     snapshot_id=seller["mirror_snapshot_id"],
                                     snapshot_date=seller.get("mirror_snapshot_date", ""))
                origins.add(own_origin)
            if prices:
                cheapest.append(min(prices) * want["quantity"])

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
                          "listing_id": card["id"], "listing_url": card["source"],
                          "attrs": dict(card.get("attrs") or {}),
                          "origin": "MIRROR", "source": card["source"], "seller_of_record": card["seller_of_record"],
                          "model_number": card.get("model_number"),
                          "snapshot_id": card["snapshot_id"], "snapshot_date": card["snapshot_date"],
                          "floor_evidence": {k: inputs["floor"][k] for k in ("origin", "source", "observed_at")},
                          "shipping_evidence": {key: inputs["shipping"][key]
                                                for key in ("origin", "source", "observed_at")}})
            origins.add("MIRROR")
    if not lines or len(origins) != 1:
        return None
    origin = origins.pop()
    if origin != "MIRROR":
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
        total = round(sum(cheapest) + seller["shipping"], 2)
    skipped = [w["sku_spec"] for w in need["items"] if not any(l["sku_spec"] == w["sku_spec"] for l in lines)]
    if origin == "MIRROR":
        snapshot_id = lines[0]["snapshot_id"]
        seller_of_record = lines[0]["seller_of_record"]
        trace = (f"{seller['trace_prefix']} Listed price = ${total:.2f} before delivery."
                 if listing_mirror and seller.get("trace_prefix") else
                 f"MIRROR asking prices from {snapshot_id}; seller of record: {seller_of_record}; "
                 "shipping and floor are sourced inputs.")
    else:
        snapshot_id = CATALOG["mirror_snapshot_id"]
        margin = seller.get("margin_pct")
        basis = f"Cost plus {margin:g}% margin" if margin is not None else f"List price less {discount:.0%} discount"
        trace = (basis
                 + (f", {'; '.join(notes)}" if notes else "")
                 + f", plus ${seller['shipping']:.2f} shipping = ${total:.2f}.")
    if origin != "MIRROR" and len(lines) > len({l["sku_spec"] for l in lines}):
        trace += " Several condition lines of one SKU are alternatives; the total uses the cheapest."
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
        # The bid submission cutoff is the auction window. Review and approval happen afterward;
        # keep the quote live for the shared 600-second review/call allowance.
        "expires_at": (now + timedelta(seconds=QUOTE_TTL_S)).isoformat(),
        "origin": origin, "source": lines[0]["source"],
        **({"mirror_label": seller["mirror_label"]} if seller.get("mirror_label") else {}),
        # #333: a real store that never joined is shown for comparison only; nothing may order or pay it
        **({"orderable": False} if seller.get("orderable") is False else {}),
        # cheaper or other in-stock lines the agent did not bid, with the fit reason (additive key, not seller text)
        **({"withheld_lines": [dict(w) for w in seller["withheld"]]} if seller.get("withheld") else {}),
    }
