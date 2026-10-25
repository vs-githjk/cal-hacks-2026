"""#260: a closed round's history goes to Tiger Data from the bridge: a bid tick per bid (a win tick for the champion) before the
call, and a loss report per loser after the payment, each with its origin. Best effort: a Tiger failure never stops a round or
a payment. Fakes only: no key, no network, no database."""
from __future__ import annotations

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


def go(run, *, ticks=None, losses=None, approve=True):
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    gate.tiger_writer, gate.tiger_loss_writer = ticks, losses
    client = FakeCartesia((lambda code: f"{code} approve") if approve else (lambda code: f"{code} no"))
    approver = bridge.make_live_approver(gate, client, buyer_name="Vidyut", on_code=lambda code, why: client.shown.update(code=code),
                                         secret="s" * 32, sleep=lambda x: None, poll=0)
    log, notes = [], []
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), clients(log), delay=0, say=lambda s: None,
                              sleep=lambda x: None, clock=lambda: 0.0, approver=approver, deal_gate=gate, note=notes.append)
    return log, outcomes, notes


def test_every_loser_of_the_round_is_written_to_tiger_with_its_gap_and_origin(run):
    written = []
    log, outcomes, notes = go(run, ticks=lambda rows: {"state": "written", "n": len(rows)},
                              losses=lambda rows: written.append(rows) or {"state": "written", "n": len(rows)})
    assert outcomes[0]["approved"] is True and len(written) == 1                        # one write for the whole round
    reports = [a for _, r, a in log if r == "record_loss_report"]
    assert len(written[0]) == len(reports) > 0
    assert {r["seller_id"] for r in written[0]} == {a["seller_id"] for a in reports}
    assert all(r["round_id"] == "round-1" and r["origin"] == "SIM" and r["sku"] == run["beats"]["1"]["goal"]["items"][0]["sku_spec"] for r in written[0])
    by = {r["seller_id"]: r for r in written[0]}
    gap = {s: by[s]["lost_by_cents"] for s in by}
    assert gap["gadget-grove"] is not None and gap["gadget-grove"] >= 0                  # a row the fake market returned
    assert gap["amazon-direct"] is None                                                  # the fake market has no row for it: no guess
    assert any("wrote" in n and "loss reports" in n for n in notes)


def test_the_loss_write_comes_after_the_payment_so_it_is_never_on_the_money_path(run):
    order = []
    log, outcomes, notes = go(run, losses=lambda rows: order.append("losses") or {"state": "written", "n": 1})
    kinds = [r for _, r, _ in log]
    assert order == ["losses"] and kinds.index("record_payment") < len(kinds) - 1       # payment done before the write was asked


def test_a_failing_tiger_loss_write_is_a_line_and_the_deal_stands(run):
    def boom(rows):
        raise RuntimeError("connection refused")
    log, outcomes, notes = go(run, ticks=boom, losses=boom)
    kinds = [r for _, r, _ in log]
    assert outcomes[0]["approved"] is True and "record_payment" in kinds and kinds.count("record_loss_report") > 0
    assert any("loss reports not written" in n for n in notes) and any("Tiger Data: not written" in n for n in notes)


def test_a_slow_or_unconfigured_tiger_is_said_and_never_blocks(run):
    log, outcomes, notes = go(run, losses=S.write_loss_reports)       # no TIGER_DATA_SERVICE_URL in this test
    assert outcomes[0]["approved"] is True
    assert any("not configured" in n and "loss reports" in n for n in notes)


def test_without_a_writer_nothing_is_written_and_no_line_is_added(run):
    log, outcomes, notes = go(run)
    assert outcomes[0]["approved"] is True and not any("Tiger Data" in n for n in notes)


def test_a_denied_call_records_no_loss_reports_so_none_reach_tiger(run):
    written = []
    log, outcomes, notes = go(run, losses=lambda rows: written.append(rows) or {"state": "written", "n": 1}, approve=False)
    assert outcomes[0]["approved"] is False and written == []


def test_the_round_ticks_carry_the_origin_of_each_market_row(run):
    written = []
    rows = market_rows(run)
    go(run, ticks=lambda t: written.append(t) or {"state": "written", "n": len(t)})
    assert written and all(t["origin"] in ("LIVE", "MIRROR", "SIM") for t in written[0]) and len(written[0]) == len(rows)


def test_a_hung_bounded_call_times_out_on_a_daemon_thread_that_cannot_hold_process_exit():
    import concurrent.futures as cf
    import threading
    release = threading.Event()
    before = {t for t in threading.enumerate()}
    with pytest.raises(cf.TimeoutError):
        S._bounded(lambda: release.wait(30), 0.1)
    hung = [t for t in threading.enumerate() if t not in before]
    try:
        assert hung and all(t.daemon for t in hung)
    finally:
        release.set()


def test_a_bounded_call_returns_its_value_and_reraises_its_error():
    assert S._bounded(lambda: 41 + 1, 1.0) == 42
    with pytest.raises(KeyError):
        S._bounded(lambda: {}["x"], 1.0)


def test_main_wires_both_writers_when_tiger_is_in_the_environment(monkeypatch):
    seen = {}
    monkeypatch.setenv("TIGER_DATA_SERVICE_URL", "postgres://u:p@h/db")
    real = bridge.DealGate

    class Spy(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            seen["gate"] = self
    monkeypatch.setattr(bridge, "DealGate", Spy)
    try:
        bridge.main(["--dry-run"])
    except SystemExit:
        pass
    gate = seen.get("gate")
    assert gate is not None and gate.tiger_writer is S.write_round_ticks and gate.tiger_loss_writer is S.write_loss_reports
