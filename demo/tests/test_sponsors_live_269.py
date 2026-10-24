"""#269: on --live-call, Bright Data re-checks the winner's price right before the call and Tiger Data stores the
round's prices; sponsor_status reads the same env file as the bridge. Fakes only: no key, no network, no database."""
from __future__ import annotations

import time

import pytest

from demo import bridge, sponsors_live as S
from demo.common import Narrator
from demo.run_demo import run_all
from demo.tests.test_bridge import FakeCartesia, clients, market_rows


@pytest.fixture(scope="module")
def run():
    return run_all(say=Narrator(False))


@pytest.fixture(autouse=True)
def no_sponsor_env(monkeypatch):
    for name in S.SPONSOR_ENV:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------- env

def test_the_bridge_env_file_feeds_only_the_sponsor_names(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("BRIGHT_DATA_API_KEY=bd-test-not-real\nTIGER_DATA_SERVICE_URL=postgres://u:p@h/db\nOTHER=x\n")
    monkeypatch.setenv("TIGER_DATA_SERVICE_URL", "postgres://process-wins")
    names = S.load_sponsor_env(env)
    import os
    assert os.environ["BRIGHT_DATA_API_KEY"] == "bd-test-not-real" and os.environ["TIGER_DATA_SERVICE_URL"] == "postgres://process-wins"
    assert "OTHER" not in os.environ and names == ["BRIGHT_DATA_API_KEY"]
    assert "bd-test-not-real" not in capsys.readouterr().out


def test_sponsor_status_reads_the_same_env_file(tmp_path, capsys):
    from scripts import sponsor_status
    env = tmp_path / ".env"
    env.write_text("BRIGHT_DATA_API_KEY=bd-test-not-real\n")
    sponsor_status.main(["--env-file", str(env), "--crs-cache", str(tmp_path / "none.json")])
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("Bright Data"))
    assert "configured: yes" in line and "bd-test-not-real" not in out


# ---------------------------------------------------------------- Bright Data re-check

def test_a_live_price_read_says_live_and_when(run):
    res = S.price_recheck({"url": "https://www.bestbuy.com/x", "price": 1299.99},
                          fetch=lambda *, urls: [{"url": urls[0], "price": 1299.99, "in_stock": True}])
    assert res["state"] == "ok" and res["origin"] == "LIVE" and "via Bright Data" in S.price_note(res, 1299.99)


def test_a_slow_bright_data_keeps_the_mirror_price_and_says_so():
    def slow(*, urls):
        time.sleep(2)
        return []
    res = S.price_recheck({"url": "https://x.example/p", "price": 10.0}, fetch=slow, timeout=0.2)
    assert res["state"] == "slow" and res["origin"] == "MIRROR"
    assert "MIRROR price stays" in S.price_note(res, 10.0)


def test_no_key_means_not_configured_and_no_request():
    res = S.price_recheck({"url": "https://x.example/p", "price": 10.0})
    assert res["state"] == "not_configured" and "not configured" in S.price_note(res, 10.0)


def live(run, price_check=None, tiger=None):
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    if price_check is not None:
        gate.price_check = price_check
    if tiger is not None:
        gate.tiger_writer = tiger
    client = FakeCartesia(lambda code: f"{code} approve")
    approver = bridge.make_live_approver(gate, client, buyer_name="Vidyut",
                                         on_code=lambda code, why: client.shown.update(code=code), secret="s" * 32,
                                         sleep=lambda x: None, poll=0)
    log, notes = [], []
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), clients(log), delay=0,
                              say=lambda s: None, sleep=lambda x: None, clock=lambda: 0.0, approver=approver,
                              deal_gate=gate, note=notes.append)
    return log, outcomes, notes, client


def test_the_winner_is_rechecked_live_before_the_call_and_the_call_says_so(run):
    seen = []

    def check(listing):
        seen.append(listing)
        return {"state": "ok", "price": listing["price"], "fetched_at": "2026-10-24T19:00:00Z", "origin": "LIVE"}
    log, outcomes, notes, client = live(run, price_check=check)
    assert seen and seen[0]["url"].startswith("http") and outcomes[0]["approved"] is True
    assert client.calls and any("checked live" in str(v) for v in client.calls[0][1].values())
    assert any("via Bright Data" in n for n in notes)


def test_a_live_price_above_the_quote_stops_the_call_and_nothing_is_paid(run):
    def check(listing):
        return {"state": "price_changed", "price": listing["price"] + 50, "fetched_at": "2026-10-24T19:00:00Z", "origin": "LIVE"}
    log, outcomes, notes, client = live(run, price_check=check)
    kinds = [r for _, r, _ in log]
    assert outcomes[0]["approved"] is False and "price_recheck" in outcomes[0]["reason"] and client.calls == []
    assert "record_payment" not in kinds and "deny_approval" in kinds


def test_a_failed_recheck_keeps_the_quote_and_the_call_goes_on(run):
    log, outcomes, notes, client = live(run, price_check=lambda listing: {"state": "empty", "detail": "blocked", "origin": "MIRROR",
                                                                          "price": None, "fetched_at": None})
    assert outcomes[0]["approved"] is True and any("MIRROR price stays" in n for n in notes)
    assert any("dated listing snapshot" in str(v) for v in client.calls[0][1].values())


# ---------------------------------------------------------------- Tiger Data

def test_the_rounds_prices_go_to_tiger_with_the_winner_marked(run):
    written = []
    S_rows = market_rows(run)
    log, outcomes, notes, _ = live(run, tiger=lambda rows: written.append(rows) or {"state": "written", "n": len(rows)})
    assert written and len(written[0]) == len(S_rows)
    events = {r["seller_id"]: r["event"] for r in written[0]}
    assert events[S_rows[0][3]] == "win" and all(e == "bid" for s, e in events.items() if s != S_rows[0][3])
    assert all(isinstance(r["price_cents"], int) for r in written[0]) and any("Tiger Data" in n for n in notes)


def test_a_tiger_failure_is_said_and_never_stops_the_deal(run):
    def boom(rows):
        raise RuntimeError("connection refused")
    log, outcomes, notes, _ = live(run, tiger=boom)
    assert outcomes[0]["approved"] is True and "record_payment" in [r for _, r, _ in log]
    assert any("Tiger Data: not written" in n for n in notes)


def test_write_round_ticks_says_not_configured_without_a_url(run):
    res = S.write_round_ticks(S.round_ticks(market_rows(run), "rtx 5070 ti"))
    assert res["state"] == "not_configured"



def test_the_tiger_note_counts_what_the_store_inserted(monkeypatch):
    from data.tiger import store
    monkeypatch.setenv("TIGER_DATA_SERVICE_URL", "postgres://user:pw@host/db")
    monkeypatch.setattr(store, "write_bid_ticks", lambda ticks: {"inserted": 0})
    ticks = [{"ts": "t", "round_id": "round-1", "sku": "x", "seller_id": "s", "price_cents": 100, "event": "win"}]
    res = S.write_round_ticks(ticks)
    assert res["state"] == "empty" and "stored 0" in S.tiger_note(res, "round-1")
    assert S.write_round_ticks([])["state"] == "empty"


def test_a_slow_tiger_write_is_unconfirmed_not_not_written(monkeypatch):
    from data.tiger import store
    monkeypatch.setenv("TIGER_DATA_SERVICE_URL", "postgres://user:pw@host/db")
    monkeypatch.setattr(store, "write_bid_ticks", lambda ticks: time.sleep(1.0) or {"inserted": 1})
    res = S.write_round_ticks([{"ts": "t", "round_id": "r", "sku": "x", "seller_id": "s", "price_cents": 1, "event": "bid"}],
                              timeout=0.1)
    assert res["state"] == "unconfirmed" and "write not confirmed" in S.tiger_note(res, "r")


@pytest.mark.parametrize("landed", ["inf", "-5", "0", True, None, "abc"])
def test_bad_prices_never_reach_the_history(landed):
    assert S.round_ticks([(1, "round-1", "b", "s", "P", 2, landed, [])], "x") == []


def test_a_disqualified_bid_is_a_blocked_tick():
    ticks = S.round_ticks([(1, "round-1", "b", "s", "P", 0, 12.5, [])], "x")
    assert ticks[0]["event"] == "blocked"
