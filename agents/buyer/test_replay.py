import asyncio
import json
import urllib.request
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agents.buyer import state
from agents.buyer import replay
from agents.buyer.replay import run_replay


T0 = datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)
EVENT_KINDS = {"observation", "round_started", "bid_received", "advocate_veto", "goal_progress",
               "deal_found", "deadline", "retry", "quote_expired", "round_complete", "goal_expired"}


class SimClock:
    def __init__(self, now=T0):
        self.value = now

    def now(self):
        return self.value

    def advance_to(self, value):
        assert value >= self.value
        self.value = value


def scenario(*, until=T0 + timedelta(hours=1), **overrides):
    value = {"run_id": "run-1", "buyer_id": "buyer-1", "goal_id": "goal-1", "mode": "SIM",
             "transport": "SIM", "input_origin": "MIRROR", "until": until}
    value.update(overrides)
    return value


def rows(times=(T0 + timedelta(seconds=1),), *, origin="MIRROR"):
    return [{"provider": "apify", "store": "bestbuy", "sku": "gpu", "price": 100.0,
             "in_stock": True, "condition": "new", "kind": "ask", "observed_at": at.isoformat(),
             "url": "https://shop.example/listing/1", "snapshot_id": f"listing-{i}", "origin": origin}
            for i, at in enumerate(times)]


def summary(at, sc, kind="observation"):
    return {"kind": kind, "at": at, "run_id": sc["run_id"],
            "buyer_id": sc["buyer_id"], "goal_id": sc["goal_id"]}


def seed_state(path, sc=None):
    sc = sc or scenario()
    db = state.open_state(path)
    try:
        state.save_goal(db, {"id": sc["goal_id"], "buyer_id": sc["buyer_id"],
                             "type": "budget_cap", "items": [{"sku_spec": "gpu", "quantity": 1}],
                             "cap": 200, "deadline": (T0 + timedelta(days=3)).isoformat(),
                             "state": "ACTIVE", "reserved_amount": 0, "created_at": T0.isoformat()})
    finally:
        db.close()


def sim_dispatch(calls, *, wakeup_at=None, mutate_rows=False):
    wakeup_pending = False
    wakeup_fired = False
    async def dispatch(event, *, now, db, scenario):
        nonlocal wakeup_pending, wakeup_fired
        calls.append((event["kind"], now))
        if event["kind"] == "observation":
            if mutate_rows:
                event["row"]["price"] = -1
            goal = state.load_goal(db, scenario["goal_id"], scenario["buyer_id"])
            if goal and goal["state"] == "ACTIVE":
                state.save_goal(db, {**goal, "state": "HUNTING"})
        if event["kind"] == "observation" and wakeup_at is not None and not wakeup_fired:
            wakeup_pending = True
        elif event["kind"] == "wakeup":
            wakeup_pending, wakeup_fired = False, True
        next_wakeup = wakeup_at if wakeup_pending else None
        return {"next_wakeup_at": next_wakeup,
                "events": [summary(now, scenario)]}
    return dispatch


def test_driver_schedules_observations_and_wakeup_with_deterministic_tie_order(tmp_path):
    rows_in = rows((T0 + timedelta(seconds=1), T0 + timedelta(seconds=5)))
    calls = []
    due = T0 + timedelta(seconds=5)
    path = tmp_path / ".state" / "replay.sqlite3"
    sc = scenario(until=due)
    seed_state(path, sc)
    report = asyncio.run(run_replay(rows_in, sc, sim_dispatch(calls, wakeup_at=due), SimClock(), path))
    assert calls == [("observation", T0 + timedelta(seconds=1)), ("wakeup", due), ("observation", due)]
    assert report["dispatch_count"] == 3 and report["wakeup_count"] == 1
    assert [e["kind"] for e in report["events"]] == ["observation"] * 3


def test_rows_are_copied_preserved_and_report_metadata_is_derived(tmp_path):
    feed_path = Path(__file__).resolve().parents[2] / "data" / "baselines" / "feed.json"
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    original = json.loads(json.dumps(feed["rows"]))
    calls = []
    clock = SimClock(datetime.fromisoformat(feed["from"].replace("Z", "+00:00")) - timedelta(seconds=1))
    path = tmp_path / ".state" / "mirror.sqlite3"
    sc = scenario(until=datetime.fromisoformat(feed["to"].replace("Z", "+00:00")), input_origin=feed["origin"])
    seed_state(path, sc)
    report = asyncio.run(run_replay(feed["rows"], sc, sim_dispatch(calls, mutate_rows=True), clock, path))
    assert feed["rows"] == original
    assert report["row_count"] == len(original)
    assert report["source_counts"] == {provider: sum(r["provider"] == provider for r in original)
                                        for provider in {r["provider"] for r in original}}
    assert report["from"] == original[0]["observed_at"] and report["to"] == original[-1]["observed_at"]
    assert report["input_digest_basis"] == "canonical rows argument; not source file bytes"
    assert len(report["input_rows_sha256"]) == 64


def test_new_feed_fields_and_provider_labels_are_preserved(tmp_path):
    source = {**rows()[0], "provider": "ebay-sold", "title": "Observed listing title",
              "sold_date": "2026-10-24"}
    captured = []
    async def dispatch(event, *, now, db, scenario):
        captured.append(event["row"])
        return {"next_wakeup_at": None, "events": [summary(now, scenario)]}
    path = tmp_path / ".state" / "new-feed-fields.sqlite3"
    sc = scenario()
    seed_state(path, sc)
    report = asyncio.run(run_replay([source], sc, dispatch, SimClock(), path))
    assert captured[0] == source
    assert report["source_counts"] == {"ebay-sold": 1}


def test_isolated_protected_state_persists_and_reopens(tmp_path):
    path = tmp_path / ".state" / "private-run.sqlite3"
    sc = scenario()
    seed_state(path, sc)
    asyncio.run(run_replay(rows(), sc, sim_dispatch([]), SimClock(), path))
    db = state.open_state(path)
    try:
        goal = state.load_goal(db, "goal-1", "buyer-1")
    finally:
        db.close()
    assert goal["state"] == "HUNTING"
    assert path.resolve() != state.DEFAULT_DB_PATH.resolve()


def test_three_day_sim_clock_advances_without_sleep(tmp_path, monkeypatch):
    def no_sleep(*args, **kwargs):
        raise AssertionError("replay must not sleep")
    monkeypatch.setattr(time, "sleep", no_sleep)
    end = T0 + timedelta(days=3)
    times = tuple(T0 + timedelta(days=day) for day in range(4))
    calls = []
    start = time.perf_counter()
    path = tmp_path / ".state" / "three-day-sim.sqlite3"
    sc = scenario(until=end, input_origin="SIM")
    seed_state(path, sc)
    report = asyncio.run(run_replay(rows(times, origin="SIM"), sc,
                                    sim_dispatch(calls, wakeup_at=T0 + timedelta(days=2)), SimClock(T0), path))
    assert time.perf_counter() - start < 60
    assert report["input_origin"] == "SIM" and report["to"] == end.isoformat()
    assert calls[-1] == ("observation", end)


def test_driver_does_not_use_network_or_payment_capabilities(tmp_path, monkeypatch):
    from pay.merchant_sim import MerchantSim, StripeTestCharger
    def blocked(*args, **kwargs):
        raise AssertionError("pure replay driver must not dispatch network or payment actions")
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(MerchantSim, "handle", blocked)
    monkeypatch.setattr(StripeTestCharger, "charge", blocked)
    path = tmp_path / ".state" / "sentinels.sqlite3"
    sc = scenario()
    seed_state(path, sc)
    asyncio.run(run_replay(rows(), sc, sim_dispatch([]), SimClock(), path))


def test_scenario_rejects_external_capability_fields(tmp_path):
    path = tmp_path / ".state" / "capabilities.sqlite3"
    sc = scenario()
    seed_state(path, sc)
    with pytest.raises(ValueError):
        asyncio.run(run_replay(rows(), {**sc, "provider_client": object()}, sim_dispatch([]), SimClock(), path))


@pytest.mark.parametrize("changes", [
    {"mode": "LIVE"}, {"transport": "HTTP"}, {"run_id": ""}, {"buyer_id": "other"},
    {"goal_id": "other"}, {"until": datetime(2026, 10, 24, 6, 0)},
])
def test_invalid_sim_scenario_rejects_before_dispatch(tmp_path, changes):
    calls = []
    path = tmp_path / ".state" / "invalid.sqlite3"
    seed_state(path)
    with pytest.raises(ValueError):
        asyncio.run(run_replay(rows(), scenario(**changes), sim_dispatch(calls), SimClock(), path))
    assert calls == []


def test_default_live_database_path_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(run_replay(rows(), scenario(), sim_dispatch([]), SimClock(), state.DEFAULT_DB_PATH))


def test_state_path_must_be_dedicated_and_dispatch_must_be_async(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(run_replay(rows(), scenario(), sim_dispatch([]), SimClock(), tmp_path / "state.sqlite3"))
    def sync_dispatch(*args, **kwargs):
        return {"next_wakeup_at": None, "events": []}
    with pytest.raises(ValueError):
        asyncio.run(run_replay(rows(), scenario(), sync_dispatch, SimClock(),
                               tmp_path / ".state" / "sync.sqlite3"))


@pytest.mark.parametrize("bad_rows", [
    rows((T0 + timedelta(seconds=2), T0 + timedelta(seconds=1))),
    [{**rows()[0], "observed_at": "2026-10-24T05:00:01"}],
    [{**rows()[0], "origin": "SIM"}],
    [{**rows()[0], "price": float("nan")}],
])
def test_invalid_or_out_of_order_rows_reject(tmp_path, bad_rows):
    with pytest.raises(ValueError):
        asyncio.run(run_replay(bad_rows, scenario(), sim_dispatch([]), SimClock(),
                               tmp_path / ".state" / "invalid-rows.sqlite3"))


@pytest.mark.parametrize("wakeup", [
    T0 + timedelta(seconds=1),
    datetime(2026, 10, 24, 5, 0, 3),
    T0 - timedelta(seconds=1),
])
def test_nonadvancing_naive_or_backwards_wakeup_rejects(tmp_path, wakeup):
    calls = []
    path = tmp_path / ".state" / "bad-wakeup.sqlite3"
    seed_state(path)
    with pytest.raises(ValueError):
        asyncio.run(run_replay(rows(), scenario(), sim_dispatch(calls, wakeup_at=wakeup),
                               SimClock(), path))


@pytest.mark.parametrize("bad_ids", [
    {"run_id": "wrong"}, {"buyer_id": "wrong"}, {"goal_id": "wrong"},
])
def test_callback_event_with_wrong_ids_rejects_without_echoing(tmp_path, bad_ids):
    async def bad_dispatch(event, *, now, db, scenario):
        return {"next_wakeup_at": None,
                "events": [summary(now, {**scenario, **bad_ids})]}
    path = tmp_path / ".state" / "wrong-ids.sqlite3"
    sc = scenario()
    seed_state(path, sc)
    with pytest.raises(ValueError):
        asyncio.run(run_replay(rows(), sc, bad_dispatch, SimClock(), path))


def test_runaway_dispatch_count_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "MAX_DISPATCHES", 1)
    path = tmp_path / ".state" / "bounded.sqlite3"
    sc = scenario()
    seed_state(path, sc)
    calls = []
    with pytest.raises(ValueError, match="dispatch limit"):
        asyncio.run(run_replay(rows((T0 + timedelta(seconds=1), T0 + timedelta(seconds=2))), sc,
                               sim_dispatch(calls), SimClock(), path))
    assert len(calls) == 1


def test_callback_event_count_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "MAX_EVENTS", 1)
    async def too_many_events(event, *, now, db, scenario):
        return {"next_wakeup_at": None,
                "events": [summary(now, scenario), summary(now, scenario, "goal_progress")]}
    path = tmp_path / ".state" / "event-limit.sqlite3"
    sc = scenario()
    seed_state(path, sc)
    with pytest.raises(ValueError, match="bounded list"):
        asyncio.run(run_replay(rows(), sc, too_many_events, SimClock(), path))


def test_callback_report_rejects_arbitrary_text_fields(tmp_path):
    async def unsafe_dispatch(event, *, now, db, scenario):
        return {"next_wakeup_at": None,
                "events": [{**summary(now, scenario), "text": "credential=must-not-report"}]}
    path = tmp_path / ".state" / "unsafe-event.sqlite3"
    sc = scenario()
    seed_state(path, sc)
    with pytest.raises(ValueError):
        asyncio.run(run_replay(rows(), sc, unsafe_dispatch, SimClock(), path))
