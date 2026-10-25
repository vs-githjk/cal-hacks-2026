"""The four seller minds behind one small facade, so seller_agent.py and the chat read the same state.

seller_1 Byte Bros Outlet  learner     agents/sellers/learner.py      learns its margin across rounds
seller_3 FlashDeal Frankie trickster   agents/sellers/trickster.py    rotates tricks, learns which got caught
seller_5 ReNew Refurb      refurb      agents/sellers/refurb.py       labelled lines, plain-words tradeoff
seller_6 Central Comp      mirror      agents/sellers/mirror_live.py  real dated listing, re-checked, never orderable
Prices and strategy stay code. A model may only phrase a chat reply (seller_chat.py); it never sets a price.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from agents.sellers import learner, mind_store, refurb, trickster

KINDS = {"seller_1": "learner", "seller_3": "trickster", "seller_5": "refurb", "seller_6": "mirror"}
STATEFUL = {"seller_1": learner, "seller_3": trickster}


def is_stateful(name: str) -> bool:
    return name in STATEFUL


def load(db: sqlite3.Connection, name: str) -> dict:
    module = STATEFUL[name]
    return module.check(mind_store.load(db, name, module.fresh))


def save(db: sqlite3.Connection, name: str, state: dict) -> None:
    mind_store.save(db, name, state)


def observe_loss(name: str, state: dict, report: dict, market_id: str) -> None:
    """A new (not yet counted) loss report for this seller's Market identity."""
    if name == "seller_1":
        learner.observe_loss(state, report, market_id)
    elif name == "seller_3":
        trickster.observe_report(state, report, market_id)


def observe_order(name: str, state: dict, need_id: str) -> None:
    """A trusted order reached this agent for `need_id`: it won the round."""
    if name == "seller_1":
        learner.observe_win(state, need_id)
    elif name == "seller_3":
        trickster.observe_order(state, need_id)


def read_state(name: str, db_path: str | Path | None = None) -> dict | None:
    """The saved mind state for a read-only reader (chat), a fresh state when none is saved, None when the seller has no
    state or the file cannot be read. It never writes."""
    if name not in STATEFUL:
        return None
    try:
        db = mind_store.open_store(db_path)
    except Exception:  # noqa: BLE001  (an unreadable state file means chat answers from a fresh mind)
        return STATEFUL[name].fresh()
    try:
        return load(db, name)
    except Exception:  # noqa: BLE001
        return STATEFUL[name].fresh()
    finally:
        db.close()


def apply_to_bid(name: str, need: dict, bid: dict, seller: dict, state: dict | None) -> tuple[dict, str | None]:
    """(the bid with this seller's mind applied, the one floor line it says or None for the default line).
    `state` is changed in place for the learner and the trickster; the caller saves it. Real listings (MIRROR bids) are
    never changed: no mind lies about, or rewrites, another store's page."""
    if name == "seller_1" and state is not None:
        learner.observe_bid(state, need["id"], bid)
        text = learner.note(state, seller["discount"])
        return {**bid, "strategy_note": text, "decision_trace": f"{bid['decision_trace']} Strategy: {text}"}, None
    if bid.get("origin") != "SIM":
        return bid, None
    if name == "seller_3" and state is not None:
        trick = trickster.choose(state, need["id"])
        out, _pages = trickster.apply(trick, bid)
        return out, f"FlashDeal Frankie: ${out['total_landed_price']:,.2f}. {trickster.lie_line(trick)}"
    if name == "seller_5":
        out = refurb.decorate(bid)
        return out, refurb.persona(out)
    return bid, None
