"""Tiger Data seller demand trends (T15). No network: every connection is a fake cursor."""
from datetime import datetime, timezone

import pytest

from data.tiger import store, trends

URL = "postgres://tsdbadmin:S3cretPw@abc123.tsdb.cloud.timescale.com:35432/tsdb?sslmode=require"
H1 = datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)
H2 = datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)


class Cur:
    def __init__(self, conn):
        self.conn = conn
        self.last = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        self.last = sql
        if self.conn.fail:
            raise RuntimeError(self.conn.fail)

    def fetchall(self):
        for needle, rows in self.conn.rows_by.items():
            if needle in self.last:
                return rows
        return []


class Conn:
    def __init__(self, rows_by=None, fail=None):
        self.executed, self.rows_by, self.fail = [], rows_by or {}, fail
        self.autocommit, self.closed = False, False

    def cursor(self):
        return Cur(self)

    def commit(self):
        pass

    def close(self):
        self.closed = True


class Connector:
    def __init__(self, conn=None):
        self.conn, self.calls = conn or Conn(), 0

    def __call__(self):
        self.calls += 1
        return self.conn


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.delenv(store.ENV, raising=False)
    store._state.update(last_call=None, last_result="not_configured", market_1h=None)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(store.ENV, URL)


# no env: not configured, never invented points, no connection attempt
def test_no_env_is_not_configured_with_no_rows_and_no_connection(monkeypatch):
    monkeypatch.setattr(store, "_connect", lambda: pytest.fail("connected without env"))
    c = Connector()
    d = trends.demand_by_sku(connect=c)
    l = trends.loss_coach("seller_3", connect=c)
    assert d == {"status": "not_configured", "rows": []}
    assert l == {"status": "not_configured", "seller_id": "seller_3", "rows": [], "rounds_bid": 0, "rounds_lost": 0}
    assert c.calls == 0
    assert trends.points(d["rows"]) == [] and trends.points(l["rows"]) == []


# demand: time_bucket on the continuous aggregate, one parameterized query
def test_demand_query_uses_time_bucket_on_the_aggregate_and_is_parameterized(configured):
    c = Connector(Conn({"bid_curve_10s": [(H1, "rtx 5070 ti", 3, 7, 129999), (H2, "rtx 5070 ti", 2, 4, None)]}))
    out = trends.demand_by_sku(hours=12, connect=c)
    (sql, params), = c.conn.executed
    assert "time_bucket('1 hour'" in sql and "FROM bid_curve_10s" in sql
    assert sql.count("%s") == 1 and params == (12,)
    assert "12" not in sql and "S3cretPw" not in sql
    assert out["status"] == "ok"
    assert out["rows"] == [
        {"bucket": H1.isoformat(), "sku": "rtx 5070 ti", "rounds": 3, "bids": 7, "best_bid_cents": 129999},
        {"bucket": H2.isoformat(), "sku": "rtx 5070 ti", "rounds": 2, "bids": 4, "best_bid_cents": None},
    ]
    assert c.conn.closed


def test_demand_default_window_is_24_hours(configured):
    c = Connector()
    trends.demand_by_sku(connect=c)
    assert c.conn.executed[0][1] == (24,)


@pytest.mark.parametrize("bad", [0, -1, 721, True, "24", 1.5, None])
def test_demand_rejects_a_bad_window_before_connecting(configured, bad):
    c = Connector()
    with pytest.raises(ValueError):
        trends.demand_by_sku(hours=bad, connect=c)
    assert c.calls == 0


def test_configured_but_empty_is_ok_with_no_invented_points(configured):
    out = trends.demand_by_sku(connect=Connector())
    assert out == {"status": "ok", "rows": []}
    assert trends.points(out["rows"]) == []


# loss coach: parameterized by seller, bucketed by day, with the rounds-entered denominator
def test_loss_coach_is_parameterized_and_reports_lost_of_entered(configured):
    hostile = "seller_1'; DROP TABLE loss_reports;--"
    c = Connector(Conn({"AS rounds_bid": [(9, 8)],
                        "FROM loss_reports": [(H1, 7, 2300), (H2, 1, None)]}))
    out = trends.loss_coach(hostile, connect=c)
    assert len(c.conn.executed) == 2
    counts_sql = c.conn.executed[0][0] if "AS rounds_bid" in c.conn.executed[0][0] else c.conn.executed[1][0]
    assert "FROM bid_ticks" in counts_sql and "event = 'bid'" in counts_sql
    for sql, params in c.conn.executed:
        assert hostile not in sql and "DROP" not in sql.upper()
        assert sql.count("%s") == len(params) and set(params[:1]) == {hostile}
        assert all(p == hostile or isinstance(p, int) for p in params)
    loss_sql = c.conn.executed[0][0]
    assert "time_bucket('1 day'" in loss_sql and "FROM loss_reports" in loss_sql and "seller_id = %s" in loss_sql
    assert out["status"] == "ok" and out["seller_id"] == hostile
    assert out["rows"] == [
        {"bucket": H1.isoformat(), "losses": 7, "median_lost_by_cents": 2300},
        {"bucket": H2.isoformat(), "losses": 1, "median_lost_by_cents": None},
    ]
    assert out["rounds_bid"] == 9 and out["rounds_lost"] == 8


@pytest.mark.parametrize("bad", ["", "  ", None, 5])
def test_loss_coach_rejects_a_bad_seller_before_connecting(configured, bad):
    c = Connector()
    with pytest.raises(ValueError):
        trends.loss_coach(bad, connect=c)
    assert c.calls == 0


# a failed query is a visible state, never rows, never the connection string
def test_failure_shows_error_status_and_leaks_nothing(configured):
    c = Connector(Conn(fail="could not reach abc123.tsdb.cloud.timescale.com with S3cretPw"))
    d = trends.demand_by_sku(connect=c)
    l = trends.loss_coach("seller_3", connect=c)
    for out in (d, l):
        assert out["status"] == "error" and out["rows"] == []
        text = repr(out)
        assert "S3cretPw" not in text and "abc123" not in text and "tsdbadmin" not in text


# points: pure mapper for Lane B, origin never claims LIVE
def test_points_maps_demand_and_loss_rows_and_never_says_live():
    demand = [{"bucket": H1.isoformat(), "sku": "rtx 5070 ti", "rounds": 3, "bids": 7, "best_bid_cents": 129999}]
    loss = [{"bucket": H2.isoformat(), "losses": 7, "median_lost_by_cents": 2300}]
    assert trends.points(demand) == [{"t": H1.isoformat(), "v": 3, "sku": "rtx 5070 ti", "bids": 7,
                                      "best_bid_cents": 129999, "origin": "SIM"}]
    assert trends.points(loss) == [{"t": H2.isoformat(), "v": 7, "median_lost_by_cents": 2300, "origin": "SIM"}]
    assert all(p["origin"] == "SIM" for p in trends.points(demand + loss))


def test_points_does_not_mutate_or_invent():
    rows = [{"bucket": H1.isoformat(), "sku": "x", "rounds": 1, "bids": 1, "best_bid_cents": 1}]
    snap = [dict(r) for r in rows]
    trends.points(rows)
    assert rows == snap
    assert trends.points([]) == []
