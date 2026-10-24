"""Pure buyer logic: forecast -> Need, auction decision, Order and payment mandate. No I/O."""
import math
import uuid
from datetime import datetime, timedelta, timezone


def need_from_forecast(forecasts: list[dict], on_hand: dict, owner: dict) -> dict:
    """forecasts: Forecast dicts plus grade, pack_size, pack_qty (units per pack) and unit.
    on_hand: sku_spec -> units already in stock. Quantity is in whole packs, rounded up."""
    items = []
    for f in forecasts:
        short = f["predicted_quantity"] - on_hand.get(f["sku_spec"], 0)
        packs = math.ceil(short / f["pack_qty"]) if short > 0 else 0
        if packs:
            items.append({"sku_spec": f["sku_spec"], "grade": f["grade"], "pack_size": f["pack_size"],
                          "quantity": packs, "unit": "pack"})
    return {"id": f"need-{uuid.uuid4().hex[:8]}", "buyer_id": owner["buyer_id"], "items": items,
            "delivery_window": owner["delivery_window"], "spend_limit": owner["spend_limit"],
            "consent": owner.get("consent", True), "auction_window_s": owner.get("auction_window_s", 12),
            "source": "simulated"}


def sealed(need: dict) -> dict:
    """What suppliers see: everything except the owner's spend limit."""
    return {k: v for k, v in need.items() if k != "spend_limit"}


def decide(need: dict, best_bid: dict, auto_limit: float) -> str:
    total = best_bid["total_landed_price"]
    if total <= auto_limit and total <= need["spend_limit"]:
        return "auto_order"
    if total <= need["spend_limit"]:
        return "needs_approval"
    return "over_limit"


def make_order(need: dict, bid: dict, approved_by: str, approval_id: str) -> dict:
    return {"id": f"order-{uuid.uuid4().hex[:8]}", "need_id": need["id"], "bid_id": bid["id"],
            "amount": bid["total_landed_price"], "approved_by": approved_by, "approval_id": approval_id,
            "limit_checked": True, "idempotency_key": uuid.uuid4().hex, "payment_ref": "", "status": "approved"}


def mandate(order: dict, supplier_id: str) -> dict:
    """Single-use spending authority handed to the payment lane; caps the charge at the order amount."""
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    return {"amount_cap": order["amount"], "payee": supplier_id, "expires_at": expires.isoformat(),
            "single_use": True, "idempotency_key": order["idempotency_key"]}
