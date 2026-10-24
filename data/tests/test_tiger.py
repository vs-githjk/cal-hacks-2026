"""Tiger Data store and loader (T13). No network: every connection is a fake."""
import logging
import re
from pathlib import Path

import pytest

from data.tiger import load, store

URL = "postgres://tsdbadmin:S3cretPw@abc123.tsdb.cloud.timescale.com:35432/tsdb?sslmode=require"
SCHEMA = Path(store.__file__).with_name("schema.sql")


class FakeCursor:
    """Records every statement. `fail` is a predicate on the SQL text that raises; `rows` is what fetchall returns."""

    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        if self.conn.fail and self.conn.fail(sql):
            raise self.conn.error(self.conn.fail_message)
        self.rowcount = 1
        if sql.lstrip().upper().startswith("INSERT INTO PRICE_OBS"):
            key = tuple(params[:5]) if params else None
            if key in self.conn.seen:
                self.rowcount = 0
            else:
                self.conn.seen.add(key)

    def fetchall(self):
        return self.conn.rows


class FakeConn:
    def __init__(self, fail=None, error=RuntimeError, fail_message="boom", rows=None):
        self.executed: list[tuple[str, object]] = []
        self.seen: set = set()
        self.fail, self.error, self.fail_message = fail, error, fail_message
        self.rows = rows or []
        self.autocommit = False
        self.closed = False
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class Connector:
    """A connect() stand-in that counts calls and hands out one FakeConn."""

    def __init__(self, conn=None):
        self.conn = conn or FakeConn()
        self.calls = 0

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


def ask(price=1299.99, **extra):
    r = {"provider": "apify", "store": "bestbuy", "sku": "rtx 5070 ti", "price": price, "in_stock": True,
         "condition": "new", "kind": "ask", "observed_at": "2026-10-24T05:08:39.627Z",
         "url": "https://www.bestbuy.com/x/sku/6614742", "snapshot_id": "bestbuy-20261024T0508Z", "origin": "MIRROR"}
    r.update(extra)
    return r


# (a) no env var: not configured, no connection attempt
def test_a_status_without_env_is_not_configured_and_never_connects(monkeypatch):
    import psycopg2

    def boom(*a, **k):
        raise AssertionError("connect attempted with no TIGER_DATA_SERVICE_URL")

    monkeypatch.setattr(psycopg2, "connect", boom)
    s = store.status()
    assert s == {"sponsor": "tiger", "configured": False, "last_call": None, "last_result": "not_configured"}
    c = Connector()
    for call in (lambda: store.write_price_obs([load.to_price_obs([ask()])[0]], connect=c),
                 lambda: store.write_bid_ticks([], connect=c),
                 lambda: store.best_bid_vs_market("r1", connect=c),
                 lambda: store.apply_schema(connect=c)):
        with pytest.raises(store.NotConfigured):
            call()
    assert c.calls == 0


def test_a_blank_env_counts_as_not_configured(monkeypatch):
    monkeypatch.setenv(store.ENV, "   ")
    assert store.status()["configured"] is False


def test_a_status_with_env_is_configured_and_never_prints_the_url(configured):
    s = store.status()
    assert s["configured"] is True and s["last_result"] == "not_called"
    assert URL not in repr(s) and "S3cretPw" not in repr(s)


# (b) schema file
def statements():
    return store.split_statements(SCHEMA.read_text())


def test_b_schema_creates_three_hypertables_and_two_continuous_aggregates():
    text = SCHEMA.read_text()
    for t in ("price_obs", "bid_ticks", "loss_reports"):
        m = re.search(rf"CREATE TABLE IF NOT EXISTS {t} \(.*?\) WITH \((.*?)\);", text, re.S)
        assert m and "tsdb.hypertable" in m.group(1), t
    for v in ("bid_curve_10s", "market_1h"):
        assert re.search(rf"CREATE MATERIALIZED VIEW IF NOT EXISTS {v} WITH \(timescaledb.continuous", text), v


def test_b_every_statement_is_idempotent_and_nothing_destroys():
    stmts = statements()
    assert len(stmts) >= 9
    for s, _optional in stmts:
        assert "IF NOT EXISTS" in s.upper() or "if_not_exists => true" in s, s
    upper = SCHEMA.read_text().upper()
    for word in ("DROP", "TRUNCATE", "DELETE"):
        assert not re.search(rf"\b{word}\b", upper), word
    assert store.MARKET_1H_FALLBACK.upper().count("IF NOT EXISTS") == 1
    for word in ("DROP", "TRUNCATE", "DELETE"):
        assert word not in store.MARKET_1H_FALLBACK.upper()


def test_b_columnstore_policy_is_the_only_optional_statement():
    opt = [s for s, optional in statements() if optional]
    assert len(opt) == 1 and "add_columnstore_policy" in opt[0]


def test_b_apply_schema_runs_each_statement_on_an_autocommit_connection(configured):
    c = Connector()
    out = store.apply_schema(connect=c)
    assert c.calls == 1 and c.conn.autocommit is True and c.conn.closed is True
    assert len(c.conn.executed) == len(statements())
    assert out["market_1h"] == "median" and out["optional_failed"] == []
    assert store.status()["last_result"] == "ok"


def test_b_optional_statement_failure_does_not_stop_the_schema(configured):
    c = Connector(FakeConn(fail=lambda sql: "add_columnstore_policy" in sql, fail_message="function does not exist"))
    out = store.apply_schema(connect=c)
    assert len(c.conn.executed) == len(statements())
    assert out["optional_failed"] == ["add_columnstore_policy"]


# (c) loader
def test_c_rows_become_price_obs_in_cents_with_origin_kept():
    bd = ask(1299.99, provider="brightdata", origin="LIVE", store="bestbuy", observed_at="2026-10-24T11:30:00+00:00")
    rows = load.to_price_obs([ask(1249.99), ask(1299.99, in_stock=False, store="bh"), bd])
    assert [r["price_cents"] for r in rows] == [124999, 129999, 129999]
    assert [r["origin"] for r in rows] == ["MIRROR", "MIRROR", "LIVE"]
    assert rows[2]["provider"] == "brightdata" and rows[1]["in_stock"] is False
    assert set(rows[0]) == {"ts", "sku", "store", "provider", "price_cents", "in_stock", "origin", "url"}
    assert rows[0]["ts"] == "2026-10-24T05:08:39.627Z"


def test_c_price_to_cents_never_floats_off_by_one():
    for price, cents in ((19.99, 1999), (1299.99, 129999), (0.29, 29), (1234.565, 123457)):
        assert load.to_price_obs([ask(price)])[0]["price_cents"] == cents


def test_c_unknown_origin_is_sim_and_unusable_rows_are_skipped_with_a_reason():
    rows, skipped = load.convert([ask(origin="somewhere"), ask(None), ask(0), ask(-5), ask(float("nan")),
                                  ask(1.0, kind="sold", store="ebay_sold"), ask(1.0, store="ebay_live"),
                                  ask(1.0, condition="used"), ask(1.0, observed_at="not a date"), ask(1.0, sku="")])
    assert [r["origin"] for r in rows] == ["SIM"]
    assert skipped == {"no price": 4, "not a retail ask": 2, "not new": 1, "bad time": 1, "no sku": 1}


def test_c_insert_is_on_conflict_do_nothing_and_a_rerun_adds_nothing(configured):
    rows = load.to_price_obs([ask(1249.99), ask(1299.99, url="https://www.bestbuy.com/y")])
    c = Connector()
    first = store.write_price_obs(rows, connect=c)
    second = store.write_price_obs(rows, connect=c)
    assert first["inserted"] == 2 and first["submitted"] == 2
    assert second["inserted"] == 0 and second["submitted"] == 2
    sql = c.conn.executed[0][0]
    assert "ON CONFLICT (ts, sku, store, provider, url) DO NOTHING" in sql
    assert "%s" in sql and "1249" not in sql
    assert re.search(r"CREATE UNIQUE INDEX IF NOT EXISTS price_obs_uniq ON price_obs \(ts, sku, store, provider, url\)", SCHEMA.read_text())
    assert c.conn.commits == 2 and c.conn.closed is True


def test_c_same_store_same_time_two_listings_are_two_rows(configured):
    c = Connector()
    rows = load.to_price_obs([ask(1249.99, url="https://a"), ask(1299.99, url="https://b")])
    assert store.write_price_obs(rows, connect=c)["inserted"] == 2


def test_c_snapshot_rows_dry_run_prints_counts_without_env_or_connection(capsys, monkeypatch):
    import psycopg2

    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("connect")))
    assert load.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "price_obs rows" in out and "no connection made" in out
    assert URL not in out


def test_c_live_run_without_env_says_not_configured_and_exits_2(capsys):
    assert load.main([]) == 2
    assert "not configured" in capsys.readouterr().out.lower()


def test_c_live_run_writes_once_and_prints_counts_not_the_url(configured, capsys, monkeypatch):
    c = Connector()
    monkeypatch.setattr(store, "_connect", c)
    monkeypatch.setattr(load, "snapshot_rows", lambda: [ask(1249.99), ask(1299.99, url="https://b")])
    assert load.main([]) == 0
    out = capsys.readouterr().out
    assert "inserted 2 of 2" in out and URL not in out and "S3cretPw" not in out
    assert c.calls == 2  # schema, then rows


# (d) one parameterized query
def test_d_best_bid_vs_market_is_one_parameterized_query(configured):
    c = Connector(FakeConn(rows=[("2026-10-24T05:00:10+00:00", "rtx 5070 ti", 135000, 3, 124999, 6)]))
    evil = "r1'; DROP TABLE bid_ticks; --"
    out = store.best_bid_vs_market(evil, connect=c)
    assert len(c.conn.executed) == 1
    sql, params = c.conn.executed[0]
    assert params == (evil,) and evil not in sql and "DROP" not in sql.upper()
    assert sql.count("%s") == 1 and "bid_curve_10s" in sql and "market_1h" in sql
    assert out == [{"bucket": "2026-10-24T05:00:10+00:00", "sku": "rtx 5070 ti", "best_bid_cents": 135000, "bids": 3,
                    "market_typical_cents": 124999, "market_n": 6}]


def test_d_empty_round_id_is_refused_before_any_connection(configured):
    c = Connector()
    for bad in ("", None, 5):
        with pytest.raises(ValueError):
            store.best_bid_vs_market(bad, connect=c)
    assert c.calls == 0


def test_d_bid_ticks_use_placeholders_and_refuse_bad_events(configured):
    c = Connector()
    good = {"ts": "2026-10-24T05:00:00Z", "round_id": "r1", "sku": "rtx 5070 ti", "seller_id": "seller_1", "price_cents": 129999, "event": "bid"}
    assert store.write_bid_ticks([good], connect=c)["inserted"] == 1
    sql, params = c.conn.executed[0]
    assert "INSERT INTO bid_ticks" in sql and "%s" in sql and "129999" not in sql and params[1] == "r1"
    for bad in (dict(good, event="steal"), dict(good, price_cents=1.5), dict(good, round_id="")):
        with pytest.raises(ValueError):
            store.write_bid_ticks([bad], connect=c)


# (e) the connection string never leaks
def test_e_connect_failure_hides_the_url_everywhere(configured, monkeypatch, caplog):
    import psycopg2

    def boom(dsn, **k):
        raise psycopg2.OperationalError(f'connection to server failed, dsn={dsn} host abc123.tsdb.cloud.timescale.com password S3cretPw')

    monkeypatch.setattr(psycopg2, "connect", boom)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(store.TigerError) as ei:
            store.write_price_obs(load.to_price_obs([ask()]))
    e = ei.value
    text = " ".join([str(e), repr(e), repr(e.args)])
    assert "S3cretPw" not in text and "abc123" not in text and URL not in text
    assert e.__cause__ is None and e.__suppress_context__ is True
    assert "S3cretPw" not in caplog.text and "abc123" not in caplog.text
    s = store.status()
    assert s["last_result"] == "error" and "S3cretPw" not in repr(s) and "abc123" not in repr(s)


def test_e_query_error_is_redacted_too(configured, caplog):
    c = Connector(FakeConn(fail=lambda sql: True, fail_message=f"bad thing at {URL} for S3cretPw"))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(store.TigerError) as ei:
            store.best_bid_vs_market("r1", connect=c)
    assert URL not in str(ei.value) and "S3cretPw" not in str(ei.value) and "S3cretPw" not in caplog.text
    assert ei.value.__cause__ is None and ei.value.__suppress_context__ is True
    assert c.conn.closed is True


def test_e_psycopg2_missing_is_a_typed_error_not_an_import_crash(configured, monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("psycopg2"):
            raise ImportError("no psycopg2")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(store.TigerError, match="psycopg2"):
        store.write_price_obs(load.to_price_obs([ask()]))


def test_e_modules_import_without_psycopg2():
    import subprocess
    import sys

    code = ("import sys; sys.modules['psycopg2'] = None; "
            "import data.tiger.store, data.tiger.load; print('ok')")
    root = Path(store.__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


# (f) percentile_cont fallback
def test_f_percentile_failure_falls_back_to_avg_and_min(configured):
    c = Connector(FakeConn(fail=lambda sql: "percentile_cont" in sql, fail_message="function percentile_cont is not supported in continuous aggregates"))
    out = store.apply_schema(connect=c)
    assert out["market_1h"] == "avg_fallback"
    ran = [sql for sql, _ in c.conn.executed]
    fb = [s for s in ran if "market_1h" in s and "percentile_cont" not in s and s.lstrip().upper().startswith("CREATE MATERIALIZED VIEW")]
    assert len(fb) == 1 and "avg(price_cents)" in fb[0] and "min(price_cents)" in fb[0]
    assert "AS typical_cents" in fb[0]
    assert len(ran) == len(statements()) + 1  # the failed statement, the fallback, and the rest
    assert store.status()["last_result"] == "ok"


def test_f_fallback_failure_is_an_error_not_a_silent_pass(configured):
    c = Connector(FakeConn(fail=lambda sql: "CREATE MATERIALIZED VIEW IF NOT EXISTS market_1h" in sql, fail_message="nope"))
    with pytest.raises(store.TigerError):
        store.apply_schema(connect=c)
    assert store.status()["last_result"] == "error"


def test_f_other_statement_failures_do_not_trigger_the_fallback(configured):
    c = Connector(FakeConn(fail=lambda sql: sql.lstrip().startswith("CREATE TABLE IF NOT EXISTS bid_ticks"), fail_message="denied"))
    with pytest.raises(store.TigerError):
        store.apply_schema(connect=c)
    assert not any("avg(price_cents)" in sql for sql, _ in c.conn.executed)
