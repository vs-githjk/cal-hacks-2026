"""Recording a phone approval on the market: always through the REFEREE identity, then re-read through the BUYER's own view.

The market's record_approval reducer is referee-only (market.ts requireRole 'record_approval', ['referee']): the referee
relays what the phone call judged. The owner-chat path used to call it through the buyer client, which the live market
refuses ("record_approval needs referee; caller is buyer ..."), so an owner's approval in ASI:One could not be recorded.

Invariants kept here (nothing in this module approves anything; it only records a call result the caller already has):
  * it runs only after the call returned an approval record for this exact mandate (buyer_agent checks that first);
  * a payment still needs the market's own buyer-private row to show a voice_code approval for the same mandate hash,
    payee and amount, not retired (market_approval_matches), re-read through the buyer client after the referee writes.

Shape-compatible with the market bridge before and after #455: when record_approval takes a `code` (the word pair the
market issued for this call), the issued code is passed; when it does not, it is not. The code is kept in memory only,
never logged, printed or stored, and dropped once recorded.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from market_bridge import MarketBridgeError

METHOD = "voice_code"
ISSUED_CODES: dict[str, str] = {}  # mandate hash -> the code issued for its call. Memory only.


def remember_code(mandate_hash: str, code: str) -> None:
    if isinstance(mandate_hash, str) and isinstance(code, str) and code:
        if len(ISSUED_CODES) >= 64:  # a call lasts minutes: never grow without bound
            ISSUED_CODES.pop(next(iter(ISSUED_CODES)))
        ISSUED_CODES[mandate_hash] = code


def accepts_code(record_approval: Callable) -> bool:
    """True when the bridge's record_approval takes a `code` (or any keyword). Feature detection, not a version check."""
    try:
        params = inspect.signature(record_approval).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "code" or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


def referee_record(referee: Any, *, mandate_hash: str, buyer_id: str, voice_approval_id: str) -> Any:
    """The referee relays the call result. Passes the issued code only when the bridge takes one."""
    args = {"mandate_hash": mandate_hash, "method": METHOD, "approved_by": buyer_id, "voice_approval_id": voice_approval_id}
    code = ISSUED_CODES.get(mandate_hash)
    if code and accepts_code(referee.record_approval):
        args["code"] = code
    try:
        return referee.record_approval(**args)
    finally:
        ISSUED_CODES.pop(mandate_hash, None)  # one call, one code: never reused for another attempt


def record_owner_approval(referee: Any, buyer: Any, mandate: dict, buyer_id: str, voice_approval_id: str,
                          matches: Callable[[Any, dict], bool]) -> dict:
    """Owner chat: the referee records, the buyer re-reads. Raises MarketBridgeError unless the market's own row shows
    this exact mandate approved, so nothing downstream can pay on a failed or mismatched recording."""
    try:
        referee_record(referee, mandate_hash=mandate["hash"], buyer_id=buyer_id, voice_approval_id=voice_approval_id)
    except MarketBridgeError:
        # the write may have landed before the error (a retry): only the market's own row can say, and it must match
        status = buyer.purchase_status(mandate["hash"])
        if isinstance(status, dict) and status.get("approval_method") == METHOD and matches(status, mandate):
            return status
        raise
    status = buyer.purchase_status(mandate["hash"])
    if not isinstance(status, dict) or status.get("approval_method") != METHOD or not matches(status, mandate):
        raise MarketBridgeError("market_approval_readback_mismatch")
    return status


# ---- the market's own mandate for a chat purchase
#
# The market creates a mandate only through the referee, only for the closed round's rank 1 bid, named by the deal id
# "deal-<round>:<bid>" (market.ts bidIdOfDeal), paid to that bid's MARKET seller id ("seller-a"), never an agent address.
# The chat payment protocol (seller RequestPayment, MerchantSim, the seller agent) is bound to the seller's agent address
# as payee and to a local deal id, and stays exactly as it is. So a chat purchase holds two mandates for one deal: the
# local one (phone gate, payment protocol) and the market's (create, approval, payment record, settlement). They share
# the buyer, goal, amount and expiry; the market one is stored on the transaction as `market_mandate`. A web purchase
# has only one mandate, which is already the market's, so `market_view` falls back to it.

def market_view(transaction: dict) -> dict:
    return transaction.get("market_mandate") or transaction["mandate"]


def market_hash(transaction: dict) -> str:
    return market_view(transaction)["hash"]


def market_deal_id(round_id: str, bid_id: str) -> str:
    return f"deal-{round_id}:{bid_id}"


def build_market_mandate(make_mandate: Callable[..., dict], *, bid: dict, round_id: str, buyer_id: str, goal_id: str,
                         now: Any, market_sellers: dict) -> dict:
    """The market's mandate for the round's winner: its deal id, its market seller id as payee, its landed price."""
    seller = bid.get("market_seller_id")
    if not seller or market_sellers.get(seller) != bid.get("supplier_id"):
        raise MarketBridgeError("market_seller_missing")
    return make_mandate(deal_id=market_deal_id(round_id, bid["id"]), amount=bid["total_landed_price"], payee=seller,
                        buyer_id=buyer_id, within_allowance=False, goal_id=goal_id, now=now, origin=bid.get("origin", "SIM"))


def pending_matches(status: Any, mandate: dict) -> bool:
    """The buyer-private row after create_mandate: this exact mandate, its reservation held, not retired or settled."""
    from decimal import Decimal, InvalidOperation
    try:
        same_amount = Decimal(str(status.get("amount"))).quantize(Decimal("0.01")) == Decimal(str(mandate.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError, TypeError, ValueError):
        return False
    return (isinstance(status, dict) and status.get("mandate_hash") == mandate.get("hash") and status.get("payee") == mandate.get("payee")
            and same_amount and status.get("reservation_matches") is True and status.get("within_allowance") is False
            and status.get("retired") is False and status.get("settled") is not True)
