"""#260 week and month windows in data.tiger.trends: price_trend and seller_record. No network: every connection is a fake."""
from datetime import datetime, timezone

import pytest

from data.tests.test_tiger_trends import URL, Conn, Connector
from data.tiger import store, trends

D1 = datetime(2026, 10, 22, tzinfo=timezone.utc)
D2 = datetime(2026, 10, 23, tzinfo=timezone.utc)
D3 = datetime(2026, 10, 24, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.delenv(store.ENV, raising=False)
    store._state.update(last_call=None, last_result="not_configured", market_1h=None)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(store.ENV, URL)


def price_conn(days, held=3, origins=("MIRROR", "SIM")):
    agg = [(min(d[1] for d in days), 70000, sum(d[3] for d in days), list(origins))] if days else [(None, None, 0, [])]
    return Conn({"GROUP BY day": days, "array_agg": agg, "ceil(": [(held,)]})


def record_conn(counts=(9, 2, 7), held=12, gap=(8.2, 5), origins=("SIM",)):
    return Conn({"SELECT (SELECT": [counts], "ceil(": [(held,)], "JOIN bid_ticks": [gap], "array_agg": [(list(origins),)]})


def test_windows_are_a_week_and_a_month():
    assert trends.WINDOWS == (7, 30)


def test_price_trend_is_parameterized_and_reports_min_median_now_and_direction(configured):
    hostile = "rtx 5070 ti'; DROP TABLE price_obs;--"
    c = Connector(price_conn([(D1, 68900, 70000, 3), (D2, 69900, 71000, 2), (D3, 67500, 72500, 4)]))
    out = trends.price_trend(hostile, 7, connect=c)
    assert len(c.conn.executed) == 3
    for sql, params in c.conn.executed:
        assert hostile not in sql and "DROP" not in sql.upper() and sql.count("%s") == len(params) and params[0] == hostile
        assert "FROM price_obs" in sql
    assert out["status"] == "ok" and out["window_days"] == 7 and out["days_of_data"] == 3
    assert (out["min_cents"], out["median_cents"], out["now_cents"], out["n"]) == (67500, 70000, 72500, 9)
    assert out["direction"] == "up" and out["origins"] == ["MIRROR", "SIM"]
    assert [r["median_cents"] for r in out["rows"]] == [70000, 71000, 72500]


@pytest.mark.parametrize("first,last,want", [(70000, 69000, "flat"), (70000, 71400, "flat"), (70000, 71500, "up"), (70000, 68000, "down")])
def test_price_direction_uses_a_two_percent_flat_band(configured, first, last, want):
    c = Connector(price_conn([(D1, 1, first, 1), (D3, 1, last, 1)]))
    assert trends.price_trend("rtx 5070 ti", 7, connect=c)["direction"] == want


def test_price_trend_never_pads_a_short_history(configured):
    # Tiger has held this SKU for 1 day only: one point, no direction, days_of_data 1 against a 30 day window
    c = Connector(price_conn([(D3, 69900, 70500, 2)], held=1))
    out = trends.price_trend("rtx 5070 ti", 30, connect=c)
    assert out["days_of_data"] == 1 and out["window_days"] == 30 and out["direction"] == "not_enough_days"
    assert len(out["rows"]) == 1 and out["now_cents"] == 70500


def test_price_trend_days_of_data_is_capped_at_the_window(configured):
    c = Connector(price_conn([(D1, 1, 70000, 1), (D3, 1, 70000, 1)], held=90))
    assert trends.price_trend("rtx 5070 ti", 7, connect=c)["days_of_data"] == 7


def test_price_trend_stored_live_reads_as_mirror_and_unknown_as_sim(configured):
    c = Connector(price_conn([(D1, 1, 70000, 1), (D3, 1, 70000, 1)], origins=("LIVE", "weird")))
    assert trends.price_trend("rtx 5070 ti", 7, connect=c)["origins"] == ["MIRROR", "SIM"]


def test_price_trend_with_no_rows_is_ok_and_empty(configured):
    out = trends.price_trend("rtx 5070 ti", 7, connect=Connector(price_conn([])))
    assert out["status"] == "ok" and out["n"] == 0 and out["rows"] == [] and out["direction"] == "no_data" and out["days_of_data"] == 0


def test_price_trend_no_env_is_not_configured_and_never_connects():
    c = Connector()
    out = trends.price_trend("rtx 5070 ti", 7, connect=c)
    assert out["status"] == "not_configured" and out["rows"] == [] and out["min_cents"] is None and c.calls == 0


def test_price_trend_failure_leaks_nothing(configured):
    out = trends.price_trend("rtx 5070 ti", 7, connect=Connector(Conn(fail="boom " + URL)))
    assert out["status"] == "error" and URL not in str(out) and "S3cretPw" not in str(out)


@pytest.mark.parametrize("bad_sku,bad_days", [("", 7), (None, 7), ("x", 0), ("x", 366), ("x", True), ("x", 7.5)])
def test_price_trend_rejects_bad_input_before_connecting(configured, bad_sku, bad_days):
    c = Connector()
    with pytest.raises(ValueError):
        trends.price_trend(bad_sku, bad_days, connect=c)
    assert c.calls == 0


def test_seller_record_counts_entered_won_lost_and_the_median_gap_band(configured):
    hostile = "seller_3'; DROP TABLE bid_ticks;--"
    c = Connector(record_conn())
    out = trends.seller_record(hostile, 7, connect=c)
    assert len(c.conn.executed) == 4
    for sql, params in c.conn.executed:
        assert hostile not in sql and "DROP" not in sql.upper() and sql.count("%s") == len(params) and params[0] == hostile
    assert out == {"status": "ok", "seller_id": hostile, "window_days": 7, "days_of_data": 7, "rounds_entered": 9, "rounds_won": 2,
                   "rounds_lost": 7, "win_rate": 0.222, "median_gap_band": "within10", "gap_samples": 5, "origins": ["SIM"]}


def test_seller_record_origins_are_those_of_the_rows_read_and_a_stored_live_reads_as_mirror(configured):
    out = trends.seller_record("seller_3", 7, connect=Connector(record_conn(origins=("LIVE", "MIRROR", "weird", None))))
    assert out["origins"] == ["MIRROR", "SIM"]
    none = trends.seller_record("seller_9", 7, connect=Connector(record_conn(counts=(0, 0, 0), held=None, gap=(None, 0), origins=())))
    assert none["origins"] == [] and none["rounds_entered"] == 0


@pytest.mark.parametrize("pct,band", [(0.0, "within5"), (5.0, "within5"), (5.01, "within10"), (10.0, "within10"), (20.0, "within20"), (20.5, "over20")])
def test_gap_band_matches_the_learning_rule(pct, band):
    assert trends.gap_band(pct) == band


def test_gap_bands_equal_the_demo_learning_rule():
    from demo import learning
    assert tuple(trends.GAP_BANDS) == tuple(learning.BANDS)


def test_seller_record_short_history_reports_the_days_tiger_holds(configured):
    out = trends.seller_record("seller_3", 30, connect=Connector(record_conn(counts=(2, 0, 2), held=3, gap=(None, 0))))
    assert out["days_of_data"] == 3 and out["window_days"] == 30 and out["median_gap_band"] is None and out["gap_samples"] == 0


def test_seller_record_with_no_history_has_no_rate_and_no_band(configured):
    out = trends.seller_record("seller_9", 7, connect=Connector(record_conn(counts=(0, 0, 0), held=None, gap=(None, 0))))
    assert out["status"] == "ok" and out["days_of_data"] == 0 and out["win_rate"] is None and out["rounds_entered"] == 0


def test_seller_record_failure_and_no_env(configured, monkeypatch):
    out = trends.seller_record("seller_3", 7, connect=Connector(Conn(fail="boom " + URL)))
    assert out["status"] == "error" and URL not in str(out)
    monkeypatch.delenv(store.ENV)
    c = Connector()
    assert trends.seller_record("seller_3", 7, connect=c)["status"] == "not_configured" and c.calls == 0


@pytest.mark.parametrize("bad_id,bad_days", [("", 7), (None, 7), ("s", 0), ("s", 366), ("s", False)])
def test_seller_record_rejects_bad_input_before_connecting(configured, bad_id, bad_days):
    c = Connector()
    with pytest.raises(ValueError):
        trends.seller_record(bad_id, bad_days, connect=c)
    assert c.calls == 0
