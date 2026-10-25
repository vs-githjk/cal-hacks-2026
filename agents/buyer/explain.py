"""One short, sourced summary of a finished round, in plain words and with no ids.

Deterministic text built only from facts the Buyer already holds: which bids arrived, which the Smell Test stopped
(by its rule id), which the Advocate vetoed (by warning kind, with the source host of the evidence), who won on
landed price, and what happens next. No LLM writes it, so it cannot add a fact: an explanation must not be able to
invent a reason. It decides nothing; the ranking, the vetoes and the approval are made elsewhere.

Seller names come from each bid's own `persona` field and are shown as plain text, cut to one short line.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# Advocate warning kinds that cause a veto (agents/advocate/checks.py VETO_KINDS) -> why, in plain words
VETO_WHY = {
    "condition": "the condition it claimed did not match its own listing page",
    "fit": "it would not fit your build",
    "fit_unconfirmed": "its fit with your build could not be confirmed",
    "recall": "the part matches a safety recall",
    "same_seller": "it came from a seller that was already in this round",
    "mirror_not_orderable": "that store never joined the market, so it cannot be bought from",
}
# Smell Test rule id prefix -> why, in plain words
SMELL_WHY = (
    ("shield.price", "it claimed a was-price that the price history never showed"),
    ("shield.secret", "it asked for something private"),
    ("shield.intent", "its text tried to instruct me instead of describe a product"),
    ("shield.", "its text broke a Smell Test rule"),
)


def _name(bid: dict) -> str:
    return re.sub(r"[^\w .&'-]", "", str(bid.get("persona") or "a seller"))[:40].strip() or "a seller"


def _host(url) -> str:
    try:
        return urlparse(str(url)).netloc.removeprefix("www.") or "source unavailable"
    except Exception:
        return "source unavailable"


def _money(x) -> str:
    return f"${x:,.2f}"


def _smell(screen: dict) -> str:
    ids = [i for i in (screen.get("rule_ids") or []) if isinstance(i, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", i)]
    rid = ids[0] if ids else "unknown rule"
    why = next((w for p, w in SMELL_WHY if rid.startswith(p)), "a Smell Test rule flagged it")
    return f"{why} (Smell Test rule {rid})"


def _veto(card: dict) -> str:
    warnings = [w for w in card.get("warnings") or [] if isinstance(w, dict)]
    hit = next((w for w in warnings if w.get("kind") in VETO_WHY), None)
    if hit is None:
        return "the advocate found a problem (no source on file)"
    return f"{VETO_WHY[hit['kind']]} (source: {_host(hit.get('source_url'))})"


def round_summary(*, asked, received: dict, screened: dict, review_bids: list, cards: dict, winner: dict | None,
                  cap: float | None, next_step: str) -> str:
    """The Buyer's reading of the round. `received` = every bid that arrived {id: bid}; `screened` = Smell Test verdicts
    {bid_id: {"verdict", "rule_ids"}}; `review_bids` = the bids the Advocate reviewed; `cards` = {bid_id: card}."""
    bids = list(received.values())
    n, m = len(bids), len(list(asked))
    parts = [f"Round summary: {n} of {m} sellers bid" + (f" ({', '.join(_name(b) for b in bids)})." if bids else ".")]
    for b in bids:
        s = screened.get(b.get("id"), {})
        if s.get("verdict") not in (None, "allow"):
            parts.append(f"The Smell Test stopped {_name(b)}: {_smell(s)}.")
    for b in review_bids:
        card = cards.get(b.get("id"), {})
        if card.get("recommendation") == "veto":
            parts.append(f"The advocate vetoed {_name(b)}: {_veto(card)}.")
        elif card.get("recommendation") == "caution":
            parts.append(f"The advocate flagged {_name(b)} with a caution.")
    if winner:
        under = f", {_money(cap - winner['total_landed_price'])} under your cap" if cap and cap >= winner["total_landed_price"] else ""
        parts.append(f"{_name(winner)} won on landed price at {_money(winner['total_landed_price'])} "
                     f"(item plus shipping){under}.")
    elif not bids:
        parts.append("No seller offers arrived, so there was nothing to rank.")
    else:
        parts.append("No bid survived the checks.")
    if next_step:
        parts.append(next_step)
    return " ".join(parts)


NO_WINNER_WHY = "No reviewed Market bid passed the authoritative ranking. Nothing ordered."
NO_OFFERS_WHY = "No seller offers arrived this round. Nothing ordered."


def no_winner_why(received: dict) -> str:
    """The owner-facing reason for a round with no winner: say plainly when no offers arrived at all."""
    return NO_WINNER_WHY if received else NO_OFFERS_WHY


def arrival_line(asked, received: dict) -> str:
    """One log line: how many bids arrived and from whom, and which asked sellers stayed silent. Ids only (no prices)."""
    asked = [str(a) for a in asked]
    came = sorted({str(b.get("supplier_id")) for b in received.values() if isinstance(b, dict)})
    silent = [a for a in asked if a not in came]
    line = f"Round ended with {len(received)} of {len(asked)} bids received"
    line += f" (from {', '.join(came)})" if came else " (from nobody)"
    return line + (f"; no reply from {', '.join(silent)}" if silent else "")


NEXT_BUY = ("Next: I get a fresh quote and then call your phone for the approval code. "
            "Nothing is paid unless you approve on that call.")


def _after_failure(attempts_so_far: int) -> str:
    """What a failed round really leads to (buyer_agent.fail_round): a fresh round, or a paused goal after MAX_ATTEMPTS."""
    import hunt
    n = attempts_so_far + 1  # this round counts as a failure too
    if hunt.after_failed_round(n) == "PAUSED":
        return (f"Nothing was ordered. That was failed round {n} of {hunt.MAX_ATTEMPTS}, so I paused this goal; "
                "send it again to restart.")
    return (f"Nothing was ordered. That was failed round {n} of {hunt.MAX_ATTEMPTS}; "
            f"I run a fresh round in {hunt.RETRY_S} seconds.")


def retry_line(attempts_so_far: int) -> str:
    return "Next: " + _after_failure(attempts_so_far)


def closing(best: int | None, verdict: str | None, ready: bool, attempts_so_far: int) -> str:
    """The true next step, chosen after conclude knows whether it will order: `best` is the index of an orderable bid
    or None, `verdict` is logic.decide's answer for it, `ready` is eligible_for_order."""
    if best is None:
        return ("Next: I will not order any of these bids (a store that never joined, a failed seller check or a veto "
                "rules each one out). " + _after_failure(attempts_so_far))
    if verdict == "over_limit":
        return "Next: the best eligible bid is over your cap. " + _after_failure(attempts_so_far)
    if not ready:
        return ("Next: I will not order this bid because it is unreviewed or vetoed. Nothing was ordered; "
                "reply CANCEL to start a new goal.")
    return NEXT_BUY


def from_round(rnd: dict, cards: dict) -> str | None:
    """round_summary from the Buyer's ROUND state, without the next step when there is a winner (conclude adds the
    true one with `closing`). Never raises (a summary must not be able to fail a round)."""
    try:
        import common
        winner = rnd.get("market_winner")
        return round_summary(asked=rnd.get("asked") or common.SELLERS, received=rnd.get("received_bids", {}),
                             screened=rnd.get("screened_bids", {}), review_bids=rnd.get("review_bids", []), cards=cards,
                             winner=winner, cap=(rnd.get("need") or {}).get("spend_limit"),
                             next_step="" if winner else retry_line(rnd.get("attempts", 0)))
    except Exception:
        return None
