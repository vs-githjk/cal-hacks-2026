"""a4/a5 pure hunt rules: goal states, step-event throttle, retry, quote TTL, payment settle. No I/O."""
from datetime import datetime, timezone

from uagents_core.contrib.protocols.payment import RejectPayment, RequestPayment

import payment

THROTTLE_S = 600  # one step event per class per goal per 10 minutes
EVENTS = ("deal found", "bid in", "veto", "progress to goal")
RETRY_S = 60  # re-run the round this often while no round produced an eligible bid
MAX_ATTEMPTS = 3  # failed rounds before the goal goes PAUSED
QUOTE_TTL_S = 600  # a quote is good for 10 minutes
QUOTE_DRIFT = 0.02  # more than 2% price change restarts the card
BUY_PUBLIC_IF_NO_BID = False  # ruling 12, not confirmed: when False we only name the best public listing
OPEN = ("ACTIVE", "HUNTING", "HOLD_FOR_CALL")  # states the deadline can still expire


def pick_best(bids: list[dict], cards: dict) -> int | None:
    """1-based index of the winning bid, or None. Vetoed bids never win. Among the rest, a bid offering a
    different condition than asked ("spec" warning) only wins if nothing else is left; then "buy" beats
    "caution"; then the lower price."""
    def rank(nb):
        card = cards.get(nb[1]["id"], {})
        kinds = {w["kind"] for w in card.get("warnings", [])}
        return ("spec" in kinds, card.get("recommendation") != "buy", nb[1]["total_landed_price"])
    ok = [(n, b) for n, b in enumerate(bids, 1) if cards.get(b["id"], {}).get("recommendation") != "veto"]
    return min(ok, key=rank)[0] if ok else None


def should_emit(last_sent: dict, cls: str, now: float) -> bool:
    """last_sent: event class -> time it was last sent for this goal."""
    return cls in EVENTS and now - last_sent.get(cls, float("-inf")) >= THROTTLE_S


def expired(goal: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    deadline = datetime.fromisoformat(goal["deadline"].replace("Z", "+00:00"))
    return goal["state"] in OPEN and now > deadline


def after_failed_round(attempts: int) -> str:
    """attempts counts this failure too. Returns the goal's next state."""
    return "PAUSED" if attempts >= MAX_ATTEMPTS else "HUNTING"


def quote_still_good(old_total: float, new_total: float, quoted_at: float, now: float) -> bool:
    if now - quoted_at > QUOTE_TTL_S:
        return False
    return abs(new_total - old_total) <= QUOTE_DRIFT * old_total


def public_hint(need: dict, baseline: dict) -> str:
    """Ruling 12 text when no seller bid. Never a purchase."""
    parts = [f"{i['sku_spec']} about ${baseline[i['sku_spec']]['unit_price']:.2f} ({baseline[i['sku_spec']]['source_url']})"
             for i in need["items"] if i["sku_spec"] in baseline]
    if not parts:
        return "No seller bid, and I know no public listing for this. Nothing bought."
    return f"No seller bid; the best public listing would be {', '.join(parts)}. Nothing bought."


def settle(req: RequestPayment, mandate: dict | None, approvals: dict, used: set):
    """The buyer's one code path for a RequestPayment: a CommitPayment, or a RejectPayment with the reason."""
    if mandate is None:
        return RejectPayment(reason="no open mandate")
    try:
        return payment.commit(req, mandate, approvals, used)
    except PermissionError as e:
        return RejectPayment(reason=str(e))
