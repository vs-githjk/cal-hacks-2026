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
    else:
        parts.append("No bid survived the checks.")
    parts.append(next_step)
    return " ".join(parts)


NEXT_BUY = ("Next: I get a fresh quote and then call your phone for the approval code. "
            "Nothing is paid unless you approve on that call.")
NEXT_NONE = "Next: nothing was ordered; I keep hunting until your deadline."


def from_round(rnd: dict, cards: dict) -> str | None:
    """round_summary from the Buyer's ROUND state. Never raises (a summary must not be able to fail a round)."""
    try:
        import common
        winner = rnd.get("market_winner")
        return round_summary(asked=rnd.get("asked") or common.SELLERS, received=rnd.get("received_bids", {}),
                             screened=rnd.get("screened_bids", {}), review_bids=rnd.get("review_bids", []), cards=cards,
                             winner=winner, cap=(rnd.get("need") or {}).get("spend_limit"),
                             next_step=NEXT_BUY if winner else NEXT_NONE)
    except Exception:
        return None
