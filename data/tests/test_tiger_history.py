"""#260 round history to Tiger Data: ticks and loss reports with their origin, the schema's origin columns, and the load output.
Fakes only: no network, no database."""
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.tests.test_tiger import Connector, FakeConn
from data.tiger import history, load, store

URL = "postgres://tsdbadmin:S3cretPw@abc123.tsdb.cloud.timescale.com:35432/tsdb?sslmode=require"
NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
SCHEMA = Path(store.__file__).with_name("schema.sql")


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(store.ENV, URL)
    store._state.update(last_call=None, last_result="not_configured", market_1h=None)


# round_result rows as the market returns them: id, round_id, bid_id, seller_id, persona, rank, landed, reasons, lines, origin
ROWS = [(1, "round-1", "b1", "champ", "P", 1, 757.44, [], [], "SIM"),
        (2, "round-1", "b2", "second", "P", 2, 1049.98, [], [], "MIRROR"),
        (3, "round-1", "b3", "cheaper", "P", 0, 700.0, ["referee: below floor"], [], "SIM"),
        (4, "round-1", "b4", "dq", "P", 0, 1349.98, ["price: over"], [], "MIRROR"),
        (5, "round-2", "b5", "other-round", "P", 1, 1.0, [], [], "SIM")]


def test_ticks_carry_the_rows_origin_and_mark_the_champion_with_a_win_tick():
    ticks = history.round_ticks(ROWS[:4], "rtx 5070 ti", now=NOW)
    by = {t["seller_id"]: t for t in ticks}
    assert [by[s]["event"] for s in ("champ", "second", "cheaper", "dq")] == ["win", "bid", "blocked", "blocked"]
    assert [by[s]["origin"] for s in ("champ", "second", "cheaper", "dq")] == ["SIM", "MIRROR", "SIM", "MIRROR"]
    assert by["champ"]["price_cents"] == 75744 and by["champ"]["ts"] == "2026-10-24T18:00:00Z" and by["champ"]["sku"] == "rtx 5070 ti"


def test_a_row_without_a_readable_origin_is_sim_never_live_by_default():
    short = (1, "round-1", "b", "s", "P", 1, 5.0, [])
    odd = (1, "round-1", "b", "s", "P", 1, 5.0, [], [], "weird")
    assert history.round_ticks([short], "x", now=NOW)[0]["origin"] == "SIM" and history.round_ticks([odd], "x", now=NOW)[0]["origin"] == "SIM"
    live = (1, "round-1", "b", "s", "P", 1, 5.0, [], [], "LIVE")
    assert history.round_ticks([live], "x", now=NOW)[0]["origin"] == "LIVE"      # the store's readers show a stored LIVE as MIRROR


def test_sponsors_live_round_ticks_is_the_same_function():
    from demo import sponsors_live
    assert sponsors_live.round_ticks(ROWS[:2], "x", now=NOW) == history.round_ticks(ROWS[:2], "x", now=NOW)


def report(seller, **kw):
    return {"id": f"lr-round-1-{seller}", "round_id": "round-1", "seller_id": seller, "won": False, "gap_band": "within5", "reason": "price",
            "source_url": "https://example.com/x", "origin": "SIM", **kw}


def test_loss_rows_are_each_losers_gap_to_the_champion_in_whole_cents():
    rows = history.loss_rows([report("second"), report("dq", reason="condition", origin="MIRROR"), report("cheaper")], ROWS[:4], "rtx 5070 ti", now=NOW)
    by = {r["seller_id"]: r for r in rows}
    assert by["second"]["lost_by_cents"] == 29254 and by["dq"]["lost_by_cents"] == 59254     # landed minus the champion's, in cents
    assert by["cheaper"]["lost_by_cents"] == 0                                             # never a negative gap
    assert by["second"]["reason"] == "price" and by["dq"]["reason"] == "condition"
    assert (by["second"]["origin"], by["dq"]["origin"]) == ("SIM", "MIRROR")
    assert all(r["round_id"] == "round-1" and r["sku"] == "rtx 5070 ti" and r["ts"] == "2026-10-24T18:00:00Z" for r in rows)


def test_a_loss_with_no_row_or_no_champion_has_no_gap_rather_than_a_guess():
    assert history.loss_rows([report("ghost")], ROWS[:2], "x", now=NOW)[0]["lost_by_cents"] is None
    no_champ = [r for r in ROWS[:4] if r[5] != 1]
    assert history.loss_rows([report("second")], no_champ, "x", now=NOW)[0]["lost_by_cents"] is None


def test_unreadable_reports_are_left_out_not_written():
    bad = [report("a", won=True), report("b", reason="he is slow"), report("c b"), "nope", report("d", round_id="")]
    assert history.loss_rows(bad, ROWS[:2], "x", now=NOW) == []
    assert history.loss_rows([report("a", origin="weird")], ROWS[:2], "x", now=NOW)[0]["origin"] == "SIM"


# store: origin is written and validated
def test_bid_ticks_and_loss_reports_write_their_origin(configured):
    c = Connector()
    tick = {"ts": "2026-10-24T05:00:00Z", "round_id": "r1", "sku": "x", "seller_id": "s", "price_cents": 100, "event": "bid", "origin": "MIRROR"}
    store.write_bid_ticks([tick], connect=c)
    sql, params = c.conn.executed[0]
    assert "origin" in sql and sql.count("%s") == len(params) == 7 and params[-1] == "MIRROR"
    store.write_bid_ticks([{k: v for k, v in tick.items() if k != "origin"}], connect=c)
    assert c.conn.executed[1][1][-1] == "SIM"                                               # no origin given: SIM
    store.write_loss_reports([{"ts": "t", "round_id": "r1", "seller_id": "s", "sku": "x", "lost_by_cents": 5, "reason": "price", "origin": "MIRROR"}], connect=c)
    sql, params = c.conn.executed[2]
    assert "INSERT INTO loss_reports" in sql and "origin" in sql and sql.count("%s") == len(params) == 7 and params[-1] == "MIRROR"
    for bad in ("steal", "", None, 3):
        with pytest.raises(ValueError):
            store.write_bid_ticks([dict(tick, origin=bad)], connect=c)
        with pytest.raises(ValueError):
            store.write_loss_reports([{"ts": "t", "seller_id": "s", "origin": bad}], connect=c)


# schema: both tables carry origin, new and existing databases
def test_the_schema_gives_bid_ticks_and_loss_reports_an_origin_column_for_new_and_old_databases():
    text = SCHEMA.read_text()
    for t in ("bid_ticks", "loss_reports"):
        m = re.search(rf"CREATE TABLE IF NOT EXISTS {t} \((.*?)\) WITH", text, re.S)
        assert re.search(r"\borigin TEXT\b", m.group(1)), t
        assert f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS origin TEXT;" in text, t
    stmts = [s for s, optional in store.split_statements(text)]
    alters = [s for s in stmts if s.startswith("ALTER TABLE")]
    assert len(alters) == 2 and all("IF NOT EXISTS" in s and "NOT NULL" not in s and "DEFAULT" not in s for s in alters)


# load output: the optional columnstore policy is named, with its reason, never a bare failure
def test_apply_schema_returns_the_reason_an_optional_statement_failed_without_the_url(configured):
    msg = "feature not supported on this plan: columnstore " + URL
    c = Connector(FakeConn(fail=lambda sql: "add_columnstore_policy" in sql, fail_message=msg))
    out = store.apply_schema(connect=c)
    assert out["optional_failed"] == ["add_columnstore_policy"]
    reason = out["optional_reasons"]["add_columnstore_policy"]
    assert "plan" in reason and "S3cretPw" not in reason and "abc123" not in reason and URL not in reason


@pytest.mark.parametrize("why,expected", [
    ("feature not supported on this plan", "optional, skipped (plan does not support columnstore)"),
    ("columnstore is not available in the Free tier", "optional, skipped (plan does not support columnstore)"),
    ("function add_columnstore_policy(unknown, interval) does not exist", "optional, skipped (the server has no columnstore policy: function add_columnstore_policy(unknown, interval) does not exist)"),
])
def test_the_load_output_says_why_the_columnstore_policy_was_skipped(why, expected):
    assert load.optional_lines({"optional_failed": ["add_columnstore_policy"], "optional_reasons": {"add_columnstore_policy": why}}) == [
        f"add_columnstore_policy: {expected}"]


def test_the_load_output_names_any_other_optional_failure_and_says_none_when_all_applied():
    assert load.optional_lines({"optional_failed": [], "optional_reasons": {}}) == []
    out = load.optional_lines({"optional_failed": ["other"], "optional_reasons": {"other": "boom"}})
    assert out == ["other: optional, skipped (boom)"]


def test_load_main_prints_the_optional_line(configured, monkeypatch, capsys):
    monkeypatch.setattr(store, "apply_schema", lambda: {"market_1h": "median", "optional_failed": ["add_columnstore_policy"],
                                                        "optional_reasons": {"add_columnstore_policy": "not supported on this plan"}, "statements": 12})
    monkeypatch.setattr(store, "write_price_obs", lambda rows: {"submitted": len(rows), "inserted": len(rows)})
    assert load.main([]) == 0
    out = capsys.readouterr().out
    assert "add_columnstore_policy: optional, skipped (plan does not support columnstore)" in out and "S3cretPw" not in out
