"""a5: agent side of the Payment Protocol. Pure rules, no I/O.
Invariant 1: no CommitPayment without an approval row for the same mandate hash; a mandate is used once.
Mandates follow contracts/Mandate.schema.json."""
import secrets
from datetime import datetime, timedelta, timezone

from uagents_core.contrib.protocols.payment import CommitPayment, Funds, RequestPayment

import common  # noqa: F401  (puts the repo root on sys.path for pay.*)
from pay.mandate import MAX_TTL_SECONDS as TTL_S, TS_FORMAT as TS, mandate_hash  # Lane D owns the hash


def make_mandate(deal_id: str, amount: float, payee: str, buyer_id: str, within_allowance: bool,
                 goal_id: str | None = None, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    m = {"id": f"mandate-{secrets.token_hex(8)}", "deal_id": deal_id, "buyer_id": buyer_id,
         "amount": round(amount, 2), "currency": "USD", "payee": payee, "tier_price": None,
         "nonce": secrets.token_hex(16), "created_at": now.strftime(TS),
         "expires_at": (now + timedelta(seconds=TTL_S)).strftime(TS), "within_allowance": within_allowance,
         "status": "pending", "approval_id": None, "tap_signature": None, "origin": "SIM"}
    if goal_id:
        m["goal_id"] = goal_id
    m["hash"] = mandate_hash(m)
    return common.validate("Mandate", m)


def payment_request(mandate: dict, recipient: str) -> RequestPayment:
    """What the seller sends; reference carries the mandate hash so both sides talk about one exact deal."""
    return RequestPayment(accepted_funds=[Funds(amount=f"{mandate['amount']:.2f}", currency="USD", payment_method="stripe")],
                          recipient=recipient, deadline_seconds=TTL_S, reference=mandate["hash"],
                          description=f"deal {mandate['deal_id']}")


def commit(req: RequestPayment, mandate: dict, approvals: dict, used: set, now: datetime | None = None) -> CommitPayment:
    """Return the CommitPayment, or raise PermissionError. `approvals`: mandate hash -> approval row.
    `used`: hashes already committed (replay guard)."""
    now = now or datetime.now(timezone.utc)
    h = mandate["hash"]
    funds = req.accepted_funds[0]
    if mandate_hash(mandate) != h:
        raise PermissionError("mandate altered: hash does not match its fields")
    if req.reference != h:
        raise PermissionError("payment request is for a different mandate")
    if req.recipient != mandate["payee"]:
        raise PermissionError("payee differs from the approved mandate")
    if abs(float(funds.amount) - mandate["amount"]) > 0.005 or funds.currency != mandate["currency"]:
        raise PermissionError("amount differs from the approved mandate")
    if datetime.strptime(mandate["expires_at"], TS).replace(tzinfo=timezone.utc) < now:
        raise PermissionError("mandate expired")
    if approvals.get(h, {}).get("answer") != "approve":
        raise PermissionError("no approval row for this mandate hash")
    if h in used:
        raise PermissionError("mandate already used (replay)")
    used.add(h)
    # ponytail: transaction_id is the mandate hash until Lane D's Stripe charge returns its own id
    return CommitPayment(funds=funds, recipient=mandate["payee"], transaction_id=h, reference=h,
                         description=req.description)
