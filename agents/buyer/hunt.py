"""a4/a5 pure hunt rules: goal states, step-event throttle, retry, quote TTL, payment settle. No I/O."""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from uagents_core.contrib.protocols.payment import RejectPayment, RequestPayment

import payment

_REPO = str(Path(__file__).resolve().parents[2])
if _REPO not in sys.path:  # repo root, for data.* (added once, at import)
    sys.path.insert(0, _REPO)
from data.mirror.not_partners import orderable  # noqa: E402  (#333: a store that never joined is never orderable)

THROTTLE_S = 600  # one step event per class per goal per 10 minutes
EVENTS = ("deal found", "bid in", "veto", "progress to goal")
RETRY_S = 60  # re-run the round this often while no round produced an eligible bid
MAX_ATTEMPTS = 3  # failed rounds before the goal goes PAUSED
QUOTE_TTL_S = 600  # a quote is good for 10 minutes
QUOTE_DRIFT = 0.02  # more than 2% price change restarts the card
BUY_PUBLIC_IF_NO_BID = False  # ruling 12, not confirmed: when False we only name the best public listing
OPEN = ("ACTIVE", "HUNTING", "HOLD_FOR_CALL")  # states the deadline can still expire


def command(text: str):
    """("approve", n) or ("cancel",) only when that is the whole message (leading @mentions allowed),
    so an approval word inside a longer text, such as an assistant's recap, never counts. Else None."""
    t = re.sub(r"^(?:@\S+\s+)+", "", text.strip()).strip().rstrip(".!").strip()
    if m := re.fullmatch(r"(?i)approve\s+#?(\d+)", t):
        return ("approve", int(m.group(1)))
    if re.fullmatch(r"(?i)cancel", t):
        return ("cancel",)
    return None


def pick_best(bids: list[dict], cards: dict, eligible_suppliers: set[str]) -> int | None:
    """1-based index of the winning bid, or None. Vetoed bids never win. Among the rest, a bid offering a
    different condition than asked ("spec" warning) only wins if nothing else is left; then "buy" beats
    "caution"; then the lower price. A bid from a mirrored store that never joined never wins (#333)."""
    def rank(nb):
        card = cards.get(nb[1]["id"], {})
        kinds = {w["kind"] for w in card.get("warnings", [])}
        return ("spec" in kinds, card.get("recommendation") != "buy", nb[1]["total_landed_price"])
    ok = [(n, b) for n, b in enumerate(bids, 1)
          if b.get("supplier_id") in eligible_suppliers and orderable(b)
          and cards.get(b["id"], {}).get("recommendation") != "veto"]
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


def settle(req: RequestPayment, transaction: dict | None, now: datetime | None = None):
    """Create CommitPayment only from stored approval plus a successful MerchantSim charge result."""
    if transaction is None:
        return RejectPayment(reason="no open mandate")
    try:
        return payment.commit(req, transaction, now=now)
    except PermissionError as e:
        return RejectPayment(reason=str(e))
