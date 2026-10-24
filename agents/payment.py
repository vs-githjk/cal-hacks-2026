"""a5: agent side of the Payment Protocol. Pure rules, no I/O.
Invariant 1: no CommitPayment without an approval row for the same mandate hash; a mandate is used once."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from uagents_core.contrib.protocols.payment import CommitPayment, Funds, RequestPayment


def mandate_hash(deal_id: str, amount: float, payee: str, expiry: str, nonce: str) -> str:
    """Covers deal id, amount, payee, expiry and nonce (00-shared.md). Lane D's TAP signing and Stripe charge check it."""
    body = json.dumps([deal_id, round(amount, 2), payee, expiry, nonce], separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def make_mandate(deal_id: str, amount: float, payee: str, max_price: float, minutes: int = 15) -> dict:
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    nonce = secrets.token_hex(8)
    return {"id": f"mandate-{nonce}", "deal_id": deal_id, "amount": round(amount, 2), "payee": payee,
            "expiry": expiry, "nonce": nonce, "max_price": max_price,
            "hash": mandate_hash(deal_id, amount, payee, expiry, nonce)}


def payment_request(mandate: dict, recipient: str) -> RequestPayment:
    """What the seller sends; reference carries the mandate hash so both sides talk about one exact deal."""
    return RequestPayment(accepted_funds=[Funds(amount=f"{mandate['amount']:.2f}", currency="USD", payment_method="stripe")],
                          recipient=recipient, deadline_seconds=900, reference=mandate["hash"],
                          description=f"deal {mandate['deal_id']}")


def commit(req: RequestPayment, mandate: dict, approvals: dict, used: set, now: datetime | None = None) -> CommitPayment:
    """Return the CommitPayment, or raise PermissionError. `approvals`: mandate hash -> approval row (from Lane D).
    `used`: hashes already committed (replay guard)."""
    now = now or datetime.now(timezone.utc)
    h = mandate["hash"]
    funds = req.accepted_funds[0]
    if mandate_hash(mandate["deal_id"], mandate["amount"], mandate["payee"], mandate["expiry"], mandate["nonce"]) != h:
        raise PermissionError("mandate altered: hash does not match its fields")
    if req.reference != h:
        raise PermissionError("payment request is for a different mandate")
    if req.recipient != mandate["payee"]:
        raise PermissionError("payee differs from the approved mandate")
    if abs(float(funds.amount) - mandate["amount"]) > 0.005 or mandate["amount"] > mandate["max_price"]:
        raise PermissionError("amount differs from the approved mandate")
    if datetime.fromisoformat(mandate["expiry"]) < now:
        raise PermissionError("mandate expired")
    if approvals.get(h, {}).get("answer") != "approve":
        raise PermissionError("no approval row for this mandate hash")
    if h in used:
        raise PermissionError("mandate already used (replay)")
    used.add(h)
    # ponytail: transaction_id is the mandate hash until Lane D's Stripe charge returns its own id
    return CommitPayment(funds=funds, recipient=mandate["payee"], transaction_id=h, reference=h,
                         description=req.description)
