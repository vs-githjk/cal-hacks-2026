"""Pure buyer logic: sealed Need, auction decision, Order and payment mandate. No I/O."""
import uuid
from datetime import datetime, timedelta, timezone


def sealed(need: dict) -> dict:
    """What suppliers see: everything except the owner's spend limit."""
    return {k: v for k, v in need.items() if k != "spend_limit"}


def advice_need_for(need: dict, owned: dict, bids: list[dict]) -> dict:
    """What the advocate sees: the sealed Need, owned parts, and the ids (never amounts) of bids inside the cap."""
    out = dict(sealed(need), owned=owned)
    out["in_cap_bid_ids"] = [b["id"] for b in bids if b["total_landed_price"] <= need["spend_limit"]]
    return out


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
