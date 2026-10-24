"""Tiger Data store (T13): price history, sealed-bid ticks, loss reports, and two continuous aggregates.

Env: TIGER_DATA_SERVICE_URL (a postgres:// connection string). With it unset every function raises NotConfigured
before any connection is attempted. psycopg2 is imported only when a connection is opened, so this module imports
without it. The connection string, its password and its host never appear in an exception, a log line or status().
A row's origin (LIVE, MIRROR, SIM) is the origin at write time: a Bright Data row written as LIVE is MIRROR (dated)
to any later reader, so readers must not show a stored row as LIVE.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ENV = "TIGER_DATA_SERVICE_URL"
HERE = Path(__file__).resolve().parent
log = logging.getLogger("data.tiger")

ORIGINS = ("LIVE", "MIRROR", "SIM")
BID_EVENTS = ("bid", "withdraw", "win", "blocked")

# Used only when the server refuses percentile_cont inside a continuous aggregate: typical_cents becomes the mean.
MARKET_1H_FALLBACK = """CREATE MATERIALIZED VIEW IF NOT EXISTS market_1h WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
  SELECT sku, time_bucket('1 hour', ts) AS bucket, avg(price_cents) AS typical_cents,
         min(price_cents) AS min_cents, count(*) AS n
  FROM price_obs WHERE in_stock GROUP BY sku, bucket WITH NO DATA"""

_INSERT_PRICE_OBS = ("INSERT INTO price_obs (ts, sku, store, provider, url, price_cents, in_stock, origin) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (ts, sku, store, provider, url) DO NOTHING")
_INSERT_BID_TICK = "INSERT INTO bid_ticks (ts, round_id, sku, seller_id, price_cents, event) VALUES (%s, %s, %s, %s, %s, %s)"
_INSERT_LOSS = "INSERT INTO loss_reports (ts, round_id, seller_id, sku, lost_by_cents, reason) VALUES (%s, %s, %s, %s, %s, %s)"
_BEST_BID_VS_MARKET = (
    "SELECT c.bucket, c.sku, c.best_bid, c.bids, m.typical_cents, m.n "
    "FROM bid_curve_10s c "
    "LEFT JOIN LATERAL (SELECT typical_cents, n FROM market_1h h WHERE h.sku = c.sku ORDER BY h.bucket DESC LIMIT 1) m ON true "
    "WHERE c.round_id = %s ORDER BY c.bucket")

_state: dict = {"last_call": None, "last_result": "not_configured", "market_1h": None}


class NotConfigured(RuntimeError):
    """TIGER_DATA_SERVICE_URL is not set; nothing was attempted."""


class TigerError(RuntimeError):
    """A connection or query failed. The message never carries the connection string."""


def _url() -> str:
    return os.environ.get(ENV, "").strip()


def status() -> dict:
    configured = bool(_url())
    if not configured:
        result = "not_configured"
    else:
        result = "not_called" if _state["last_result"] == "not_configured" else _state["last_result"]
    return {"sponsor": "tiger", "configured": configured, "last_call": _state["last_call"], "last_result": result}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact(text: str, url: str) -> str:
    parts = urlsplit(url)
    for secret in (url, parts.password, parts.hostname, parts.username):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _connect():
    """Open one connection (the default connect). Errors say what failed, never where."""
    try:
        import psycopg2
    except ImportError:
        raise TigerError("psycopg2 is not installed") from None
    try:
        return psycopg2.connect(_url(), connect_timeout=10)
    except Exception as e:
        log.warning("tiger connect failed: %s", type(e).__name__)
        raise TigerError(f"connection failed ({type(e).__name__})") from None


def _run(connect, work, *, autocommit: bool = False):
    url = _url()
    if not url:
        _state["last_result"] = "not_configured"
        raise NotConfigured(f"{ENV} is not set")
    _state["last_call"] = _now_iso()
    conn = None
    try:
        conn = (connect or _connect)()
        conn.autocommit = autocommit
        result = work(conn)
    except TigerError:
        _state["last_result"] = "error"
        raise
    except Exception as e:
        _state["last_result"] = "error"
        first = (str(e).splitlines() or [""])[0]
        log.warning("tiger query failed: %s", type(e).__name__)
        raise TigerError(f"{type(e).__name__}: {_redact(first, url)}"[:300]) from None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    _state["last_result"] = "ok"
    return result


def split_statements(text: str) -> list[tuple[str, bool]]:
    """schema.sql as [(statement, optional)]. Full-line comments are dropped; a line `-- optional` marks the next statement."""
    out, buf, optional, next_optional = [], [], False, False
    for line in text.splitlines():
        s = line.strip()
        if s == "-- optional":
            next_optional = True
            continue
        if not s or s.startswith("--"):
            continue
        if not buf:
            optional, next_optional = next_optional, False
        buf.append(line.rstrip())
        if s.endswith(";"):
            out.append(("\n".join(buf).rstrip().rstrip(";"), optional))
            buf = []
    if buf:
        raise ValueError("schema.sql ends inside a statement")
    return out


def _is_market_view(sql: str) -> bool:
    return sql.lstrip().upper().startswith("CREATE MATERIALIZED VIEW") and " market_1h " in sql


def apply_schema(*, connect=None) -> dict:
    """Create everything in schema.sql (idempotent). Returns {"market_1h": "median"|"avg_fallback", "optional_failed": [...]}."""
    stmts = split_statements((HERE / "schema.sql").read_text())

    def work(conn):
        market, failed = "median", []
        with conn.cursor() as cur:
            for sql, optional in stmts:
                try:
                    cur.execute(sql)
                except Exception:
                    if optional:
                        m = re.match(r"\s*SELECT\s+(\w+)", sql)
                        failed.append(m.group(1) if m else "optional")
                    elif _is_market_view(sql) and "percentile_cont" in sql:
                        cur.execute(MARKET_1H_FALLBACK)
                        market = "avg_fallback"
                    else:
                        raise
        return {"market_1h": market, "optional_failed": failed, "statements": len(stmts)}

    out = _run(connect, work, autocommit=True)
    _state["market_1h"] = out["market_1h"]
    return out


def _check_text(row: dict, key: str, optional: bool = False) -> None:
    v = row.get(key)
    if v is None and optional:
        return
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{key} must be a non-empty string")


def _check_cents(row: dict, key: str, optional: bool = False) -> None:
    v = row.get(key)
    if v is None and optional:
        return
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{key} must be whole cents (int)")


def _insert(connect, sql: str, param_sets: list[tuple]) -> dict:
    submitted = len(param_sets)
    if not submitted:
        if not _url():
            _state["last_result"] = "not_configured"
            raise NotConfigured(f"{ENV} is not set")
        return {"submitted": 0, "inserted": 0}

    def work(conn):
        inserted = 0
        with conn.cursor() as cur:
            for params in param_sets:
                cur.execute(sql, params)
                inserted += max(cur.rowcount or 0, 0)
        conn.commit()
        return {"submitted": submitted, "inserted": inserted}

    return _run(connect, work)


def write_price_obs(rows: list[dict], *, connect=None) -> dict:
    """Insert price_obs rows (see load.to_price_obs). A row already stored is skipped. Returns {"submitted", "inserted"}."""
    sets = []
    for r in rows:
        for k in ("ts", "sku", "store", "provider"):
            _check_text(r, k)
        _check_cents(r, "price_cents")
        if r["price_cents"] <= 0:
            raise ValueError("price_cents must be positive")
        if not isinstance(r.get("in_stock"), bool):
            raise ValueError("in_stock must be a bool")
        if r.get("origin") not in ORIGINS:
            raise ValueError("origin must be LIVE, MIRROR or SIM")
        sets.append((r["ts"], r["sku"], r["store"], r["provider"], r.get("url") or "", r["price_cents"], r["in_stock"], r["origin"]))
    return _insert(connect, _INSERT_PRICE_OBS, sets)


def write_bid_ticks(rows: list[dict], *, connect=None) -> dict:
    sets = []
    for r in rows:
        for k in ("ts", "round_id", "sku", "seller_id"):
            _check_text(r, k)
        _check_cents(r, "price_cents", optional=True)
        if r.get("event") not in BID_EVENTS:
            raise ValueError(f"event must be one of {BID_EVENTS}")
        sets.append((r["ts"], r["round_id"], r["sku"], r["seller_id"], r.get("price_cents"), r["event"]))
    return _insert(connect, _INSERT_BID_TICK, sets)


def write_loss_reports(rows: list[dict], *, connect=None) -> dict:
    sets = []
    for r in rows:
        for k in ("ts", "seller_id"):
            _check_text(r, k)
        _check_cents(r, "lost_by_cents", optional=True)
        sets.append((r["ts"], r.get("round_id"), r["seller_id"], r.get("sku"), r.get("lost_by_cents"), r.get("reason")))
    return _insert(connect, _INSERT_LOSS, sets)


def best_bid_vs_market(round_id: str, *, connect=None) -> list[dict]:
    """Best sealed bid per 10 s bucket for one round next to the latest hourly market figure for the SKU (one query)."""
    if not isinstance(round_id, str) or not round_id.strip():
        raise ValueError("round_id must be a non-empty string")

    def work(conn):
        with conn.cursor() as cur:
            cur.execute(_BEST_BID_VS_MARKET, (round_id,))
            return cur.fetchall()

    out = []
    for bucket, sku, best, bids, typical, n in _run(connect, work):
        out.append({"bucket": bucket.isoformat() if hasattr(bucket, "isoformat") else bucket, "sku": sku,
                    "best_bid_cents": best, "bids": bids,
                    "market_typical_cents": None if typical is None else int(round(typical)), "market_n": n})
    return out
