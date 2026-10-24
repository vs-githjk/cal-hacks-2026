"""Tiger Data seller demand trends (T15): what is selling, and how a seller loses. Data only; Lane B renders it.

Reads the T13 tables. `demand_by_sku` buckets the `bid_curve_10s` continuous aggregate by hour; `loss_coach` buckets
`loss_reports` by day and counts the rounds the seller bid in against the rounds it lost (so the line can say
"lost 7 of 9 rounds"). Every query is parameterized; the seller id and window never enter the SQL text.

Result shape: {"status": "ok" | "not_configured" | "error", "rows": [...]} (loss_coach adds seller_id, rounds_bid,
rounds_lost). With TIGER_DATA_SERVICE_URL unset the status is "not_configured", rows are [] and no connection is
attempted. A failed query is status "error" with rows [] (the reason is in the log, never in the result, and never
carries the connection string). Nothing here invents a point.

Demand counts rounds that drew at least one sealed bid (a round nobody bid on has no bid_ticks row), so it is
"where sellers are competing", not total buyer need. bid_ticks stores no origin, so every point is labelled SIM.
"""
from __future__ import annotations

from . import store

MAX_HOURS = 24 * 30
MAX_DAYS = 365

_DEMAND = (
    "SELECT time_bucket('1 hour', bucket) AS hour, sku, count(DISTINCT round_id) AS rounds, "
    "sum(bids)::bigint AS bids, min(best_bid) AS best_bid "
    "FROM bid_curve_10s WHERE bucket >= now() - make_interval(hours => %s) "
    "GROUP BY sku, hour ORDER BY hour, sku")
_LOSSES = (
    "SELECT time_bucket('1 day', ts) AS day, count(*) AS losses, "
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY lost_by_cents) AS median_lost_by_cents "
    "FROM loss_reports WHERE seller_id = %s AND ts >= now() - make_interval(days => %s) "
    "GROUP BY day ORDER BY day")
_ROUNDS = (
    "SELECT (SELECT count(DISTINCT round_id) FROM bid_ticks "
    "WHERE seller_id = %s AND event = 'bid' AND ts >= now() - make_interval(days => %s)) AS rounds_bid, "
    "(SELECT count(DISTINCT round_id) FROM loss_reports "
    "WHERE seller_id = %s AND round_id IS NOT NULL AND ts >= now() - make_interval(days => %s)) AS rounds_lost")


def _int_in_range(v, name: str, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= hi:
        raise ValueError(f"{name} must be a whole number from 1 to {hi}")
    return v


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _cents(v):
    return None if v is None else int(round(v))


def demand_by_sku(hours: int = 24, *, connect=None) -> dict:
    """Rounds and sealed bids per SKU per hour over the last `hours` (1 to 720), from the bid_curve_10s aggregate."""
    hours = _int_in_range(hours, "hours", MAX_HOURS)
    try:
        raw = store._run(connect, lambda conn: _fetch(conn, [(_DEMAND, (hours,))])[0])
    except store.NotConfigured:
        return {"status": "not_configured", "rows": []}
    except store.TigerError:
        return {"status": "error", "rows": []}
    rows = [{"bucket": _iso(b), "sku": sku, "rounds": int(rounds), "bids": int(bids), "best_bid_cents": _cents(best)}
            for b, sku, rounds, bids, best in raw]
    return {"status": "ok", "rows": rows}


def loss_coach(seller_id: str, *, days: int = 30, connect=None) -> dict:
    """One seller's losses per day (count and median cents lost by) plus rounds bid in and rounds lost over `days`."""
    if not isinstance(seller_id, str) or not seller_id.strip():
        raise ValueError("seller_id must be a non-empty string")
    days = _int_in_range(days, "days", MAX_DAYS)
    empty = {"seller_id": seller_id, "rows": [], "rounds_bid": 0, "rounds_lost": 0}
    queries = [(_LOSSES, (seller_id, days)), (_ROUNDS, (seller_id, days, seller_id, days))]
    try:
        by_day, counts = store._run(connect, lambda conn: _fetch(conn, queries))
    except store.NotConfigured:
        return {"status": "not_configured", **empty}
    except store.TigerError:
        return {"status": "error", **empty}
    rounds_bid, rounds_lost = counts[0] if counts else (0, 0)
    rows = [{"bucket": _iso(d), "losses": int(n), "median_lost_by_cents": _cents(med)} for d, n, med in by_day]
    return {"status": "ok", "seller_id": seller_id, "rows": rows,
            "rounds_bid": int(rounds_bid or 0), "rounds_lost": int(rounds_lost or 0)}


def _fetch(conn, queries):
    out = []
    with conn.cursor() as cur:
        for sql, params in queries:
            cur.execute(sql, params)
            out.append(cur.fetchall())
    return out


def points(rows: list[dict]) -> list[dict]:
    """JSON points for the web TrendSpark: {t, v, origin, ...}. v is rounds for a demand row, losses for a loss row.
    Pure: the input is not changed and nothing is invented (no rows, no points). Origin is always SIM because the
    underlying tables carry none."""
    out = []
    for r in rows:
        if "rounds" in r:
            out.append({"t": r["bucket"], "v": r["rounds"], "sku": r["sku"], "bids": r["bids"],
                        "best_bid_cents": r["best_bid_cents"], "origin": "SIM"})
        else:
            out.append({"t": r["bucket"], "v": r["losses"], "median_lost_by_cents": r["median_lost_by_cents"],
                        "origin": "SIM"})
    return out
