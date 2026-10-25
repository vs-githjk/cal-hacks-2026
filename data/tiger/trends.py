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
WINDOWS = (7, 30)   # the week and the month the Market Pulse orchestrator (#260) reports
FLAT_BAND = 0.02    # a price move under 2 percent between the first and last day of a window is "flat"

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


_PRICE_DAYS = (
    "SELECT time_bucket('1 day', ts) AS day, min(price_cents), percentile_cont(0.5) WITHIN GROUP (ORDER BY price_cents), "
    "count(*) FROM price_obs WHERE sku = %s AND in_stock AND ts >= now() - make_interval(days => %s) "
    "GROUP BY day ORDER BY day")
_PRICE_ALL = (
    "SELECT min(price_cents), percentile_cont(0.5) WITHIN GROUP (ORDER BY price_cents), count(*), array_agg(DISTINCT origin) "
    "FROM price_obs WHERE sku = %s AND in_stock AND ts >= now() - make_interval(days => %s)")
_PRICE_SPAN = "SELECT ceil(extract(epoch FROM now() - min(ts)) / 86400)::int FROM price_obs WHERE sku = %s"
_RECORD = (
    "SELECT (SELECT count(DISTINCT round_id) FROM bid_ticks WHERE seller_id = %s AND ts >= now() - make_interval(days => %s)), "
    "(SELECT count(DISTINCT round_id) FROM bid_ticks WHERE seller_id = %s AND event = 'win' "
    "AND ts >= now() - make_interval(days => %s)), "
    "(SELECT count(DISTINCT round_id) FROM loss_reports WHERE seller_id = %s AND round_id IS NOT NULL "
    "AND ts >= now() - make_interval(days => %s))")
# the origins of the rows the record is built from (a row stored before #260 has none and reads as SIM)
_RECORD_ORIGINS = (
    "SELECT array_agg(DISTINCT coalesce(origin, 'SIM')) FROM ("
    "SELECT origin FROM bid_ticks WHERE seller_id = %s AND ts >= now() - make_interval(days => %s) "
    "UNION ALL SELECT origin FROM loss_reports WHERE seller_id = %s AND ts >= now() - make_interval(days => %s)) o")
_RECORD_SPAN = "SELECT ceil(extract(epoch FROM now() - min(ts)) / 86400)::int FROM bid_ticks WHERE seller_id = %s"
# the gap of each loss as a percent of the round's winning price (the win tick of the same round and SKU)
_RECORD_GAP = (
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY l.lost_by_cents * 100.0 / w.price_cents), count(*) "
    "FROM loss_reports l JOIN bid_ticks w ON w.round_id = l.round_id AND w.sku = l.sku AND w.event = 'win' AND w.price_cents > 0 "
    "WHERE l.seller_id = %s AND l.lost_by_cents IS NOT NULL AND l.ts >= now() - make_interval(days => %s)")
# the SIM learning rule's bands (= demo/learning.py BANDS, pinned by a test)
GAP_BANDS = (("within5", 5.0), ("within10", 10.0), ("within20", 20.0))


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


def gap_band(pct: float) -> str:
    for name, top in GAP_BANDS:
        if pct <= top:
            return name
    return "over20"


def _origins(raw) -> list[str]:
    """Stored origins as a reader may show them: a stored LIVE row is MIRROR (dated), anything unknown is SIM."""
    seen = {"MIRROR" if o == "LIVE" else o if o in store.ORIGINS else "SIM" for o in (raw or [])}
    return sorted(seen)


def price_trend(sku: str, days: int, *, connect=None) -> dict:
    """The SKU's in-stock price over the last `days` (1 to 365): lowest ask, median ask, the latest day's median ("now")
    and whether it rose, fell or held against the window's first day. `days_of_data` is how many days Tiger has held
    this SKU (capped at the window): below `window_days` the caller must say "only N days of data". Nothing is padded."""
    if not isinstance(sku, str) or not sku.strip():
        raise ValueError("sku must be a non-empty string")
    days = _int_in_range(days, "days", MAX_DAYS)
    empty = {"sku": sku, "window_days": days, "days_of_data": 0, "n": 0, "min_cents": None, "median_cents": None,
             "now_cents": None, "direction": "no_data", "origins": [], "rows": []}
    queries = [(_PRICE_DAYS, (sku, days)), (_PRICE_ALL, (sku, days)), (_PRICE_SPAN, (sku,))]
    try:
        by_day, agg, span = store._run(connect, lambda conn: _fetch(conn, queries))
    except store.NotConfigured:
        return {"status": "not_configured", **empty}
    except store.TigerError:
        return {"status": "error", **empty}
    rows = [{"bucket": _iso(d), "min_cents": _cents(lo), "median_cents": _cents(med), "n": int(n)} for d, lo, med, n in by_day]
    lo, med, n, origins = agg[0] if agg else (None, None, 0, [])
    if not rows or not n:
        return {"status": "ok", **empty}
    held = int(span[0][0]) if span and span[0] and span[0][0] is not None else 0
    first, last = rows[0]["median_cents"], rows[-1]["median_cents"]
    if len(rows) < 2 or not first:
        direction = "not_enough_days"
    else:
        move = (last - first) / first
        direction = "up" if move > FLAT_BAND else "down" if move < -FLAT_BAND else "flat"
    return {"status": "ok", "sku": sku, "window_days": days, "days_of_data": max(1, min(days, held)), "n": int(n),
            "min_cents": _cents(lo), "median_cents": _cents(med), "now_cents": last, "direction": direction,
            "origins": _origins(origins), "rows": rows}


def seller_record(seller_id: str, days: int, *, connect=None) -> dict:
    """One seller's record over the last `days` (1 to 365): rounds entered, won, lost, and the median gap of its losses
    as a band (the loss's `lost_by` as a percent of the round's winning price). `days_of_data` as in price_trend.
    Entered counts every round with a tick for the seller (a win tick is the winner's only tick). Never invents a band:
    `median_gap_band` is None when no loss could be joined to its round's winning tick. `origins` are those of the rows
    read (a stored LIVE reads as MIRROR, a row with none as SIM); [] when there are none."""
    if not isinstance(seller_id, str) or not seller_id.strip():
        raise ValueError("seller_id must be a non-empty string")
    days = _int_in_range(days, "days", MAX_DAYS)
    empty = {"seller_id": seller_id, "window_days": days, "days_of_data": 0, "rounds_entered": 0, "rounds_won": 0,
             "rounds_lost": 0, "win_rate": None, "median_gap_band": None, "gap_samples": 0, "origins": []}
    queries = [(_RECORD, (seller_id, days, seller_id, days, seller_id, days)), (_RECORD_SPAN, (seller_id,)),
               (_RECORD_GAP, (seller_id, days)), (_RECORD_ORIGINS, (seller_id, days, seller_id, days))]
    try:
        counts, span, gap, origins = store._run(connect, lambda conn: _fetch(conn, queries))
    except store.NotConfigured:
        return {"status": "not_configured", **empty}
    except store.TigerError:
        return {"status": "error", **empty}
    entered, won, lost = (int(x or 0) for x in (counts[0] if counts else (0, 0, 0)))
    held = int(span[0][0]) if span and span[0] and span[0][0] is not None else 0
    med, samples = gap[0] if gap else (None, 0)
    band = gap_band(float(med)) if med is not None and samples else None
    return {"status": "ok", "seller_id": seller_id, "window_days": days, "days_of_data": max(1, min(days, held)) if held else 0,
            "rounds_entered": entered, "rounds_won": won, "rounds_lost": lost,
            "win_rate": round(won / entered, 3) if entered else None, "median_gap_band": band, "gap_samples": int(samples or 0),
            "origins": _origins(origins[0][0] if origins and origins[0] else [])}


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
