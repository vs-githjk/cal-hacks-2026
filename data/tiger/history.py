"""A closed round as Tiger Data history (#260): one bid tick per bid and one loss report per loser, each with its origin.

Pure converters, so any round runner (demo/bridge.py, the full-build runner) can call them and hand the rows to
`store.write_bid_ticks` and `store.write_loss_reports` through `demo.sponsors_live.write_round_ticks` and
`write_loss_reports` (bounded, best effort: a Tiger failure is a console line and a log line, never a stopped round or payment).

Input rows are the market's `round_result` rows: tuples (id, round_id, bid_id, seller_id, persona, rank, landed, reasons,
lines, origin) as `SELECT * FROM round_result` returns them (a shorter tuple has no origin, which reads as SIM), or dicts with
the same snake_case keys. Origins are LIVE, MIRROR or SIM; anything else is SIM, so history never says LIVE by accident.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from . import store

LOSS_REASONS = ("price", "fit", "condition", "delivery", "record", "advocate_veto")


def _origin(value: Any) -> str:
    return value if value in store.ORIGINS else "SIM"


def _field(row: Any, index: int, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[index]
    except (IndexError, TypeError, KeyError):
        return None


def _price(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None          # never a zero, negative or infinite price in the history
    return float(value)


def _ts(now: Optional[datetime]) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def round_ticks(rows: list, sku: str, *, now: Optional[datetime] = None) -> list[dict]:
    """One bid_ticks row per readable round_result row: rank 1 is the "win" tick, rank 0 (disqualified at the close) is
    "blocked", the rest are "bid"; prices in whole cents; origin from the row."""
    ts = _ts(now)
    out = []
    for r in rows:
        price = _price(_field(r, 6, "landed"))
        rank = _field(r, 5, "rank")
        if price is None or rank is None:
            continue
        event = "win" if str(rank) == "1" else "blocked" if str(rank) == "0" else "bid"
        out.append({"ts": ts, "round_id": str(_field(r, 1, "round_id")), "sku": sku, "seller_id": str(_field(r, 3, "seller_id")),
                    "price_cents": int(round(price * 100)), "event": event, "origin": _origin(_field(r, 9, "origin"))})
    return out


def loss_rows(reports: list, rows: list, sku: str, *, now: Optional[datetime] = None) -> list[dict]:
    """One loss_reports row per readable LossReport of the round. `lost_by_cents` is the loser's landed price minus the
    champion's (rank 1), in whole cents and never below 0; None when either row is missing. The origin is the report's.
    A report that is not a loss, has an unknown reason or has no ids is left out."""
    ts = _ts(now)
    landed = {str(_field(r, 3, "seller_id")): _price(_field(r, 6, "landed")) for r in rows}
    champ = next((landed[str(_field(r, 3, "seller_id"))] for r in rows if str(_field(r, 5, "rank")) == "1"), None)
    out = []
    for rep in reports:
        if not isinstance(rep, Mapping) or rep.get("won") is not False or rep.get("reason") not in LOSS_REASONS:
            continue
        sid, rid = rep.get("seller_id"), rep.get("round_id")
        if not isinstance(sid, str) or not sid.strip() or not isinstance(rid, str) or not rid.strip() or any(c.isspace() for c in sid):
            continue
        mine = landed.get(sid)
        lost_by = None if mine is None or champ is None else max(0, int(round((mine - champ) * 100)))
        out.append({"ts": ts, "round_id": rid, "seller_id": sid, "sku": sku, "lost_by_cents": lost_by, "reason": rep["reason"],
                    "origin": _origin(rep.get("origin"))})
    return out
