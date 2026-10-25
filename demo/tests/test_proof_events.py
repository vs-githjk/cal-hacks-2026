"""Sponsor proof lines on the Fetch tile: LIVE only for a value this run really fetched (a Bright Data price read, a Tiger Data write of the
round's prices, a fresh CRS sandbox band); everything else stays SIM, or is not posted at all. Fakes only: no key, no network, no database."""
from __future__ import annotations

import pytest

from demo import bridge, build, sponsors_live as S
from demo.build_sim import FakeMarket, make_clients
from demo.run_demo import run_all
from demo.common import Narrator
from demo.tests.test_bridge import FakeCartesia, clients
from demo.tests.test_build import sim_catalog

ADDR = {"buyer": "agent1q" + "a" * 30, "advocate": "agent1q" + "b" * 30, "shield": "agent1q" + "c" * 30}
LIVE_PRICE = {"state": "ok", "price": 1299.99, "fetched_at": "2026-10-24T19:00:00Z", "origin": "LIVE"}
CRS_LIVE = {"business": True, "cached": False, "check": {"seller_id": "best-buy", "product": "tu_identity", "verified": True,
                                                         "reason_codes": ["CRS_IDENTITY_VERIFIED"], "origin": "SANDBOX",
                                                         "checked_at": "2026-10-24T19:00:00Z"}}


@pytest.fixture(autouse=True)
def no_sponsor_env(monkeypatch):
    for name in S.SPONSOR_ENV:
        monkeypatch.delenv(name, raising=False)


def origins(steps):
    return [s.args["origin"] for s in steps]


# ---------------------------------------------------------------- _event

def test_an_agent_event_is_sim_unless_asked_otherwise():
    assert bridge._event("buyer", ADDR, "x").args["origin"] == "SIM"
    s = bridge._event("buyer", ADDR, "x", "LIVE")
    assert s.args["origin"] == "LIVE" and "LIVE" in s.say and "SIM" not in s.say
    assert "SIM line" in bridge._event("buyer", ADDR, "x").say


def test_no_address_means_no_event():
    assert bridge._event("buyer", {}, "x", "LIVE") is None


# ---------------------------------------------------------------- which results are real

def test_a_live_price_read_is_a_live_event_with_the_price():
    steps = bridge.live_proof_steps(ADDR, price=LIVE_PRICE, quoted=1299.99)
    assert origins(steps) == ["LIVE"] and "Bright Data" in steps[0].args["text"] and "1,299.99" in steps[0].args["text"]


@pytest.mark.parametrize("res", [{"state": "not_configured", "price": None, "fetched_at": None, "origin": "MIRROR"},
                                 {"state": "slow", "price": None, "fetched_at": None, "origin": "MIRROR"},
                                 {"state": "empty", "price": None, "fetched_at": None, "origin": "MIRROR"},
                                 {"state": "ok", "price": 1.0, "fetched_at": None, "origin": "MIRROR"}, None])
def test_a_price_that_was_not_read_live_posts_nothing(res):
    assert bridge.live_proof_steps(ADDR, price=res, quoted=1299.99) == []


def test_a_tiger_write_that_stored_rows_is_live_and_one_that_did_not_is_not():
    ok = bridge.live_proof_steps(ADDR, tiger={"state": "written", "n": 4}, round_id="round-1")
    assert origins(ok) == ["LIVE"] and "Tiger Data" in ok[0].args["text"] and "4" in ok[0].args["text"]
    for res in ({"state": "not_configured", "n": 0}, {"state": "empty", "n": 0}, {"state": "error", "n": 0}, {"state": "unconfirmed", "n": 0},
                {"state": "written", "n": 0}, None):
        assert bridge.live_proof_steps(ADDR, tiger=res, round_id="round-1") == []


def test_a_fresh_crs_sandbox_band_is_live_and_names_the_band_never_a_cached_or_sim_one():
    steps = bridge.live_proof_steps(ADDR, crs=CRS_LIVE, seller="Best Buy")
    assert origins(steps) == ["LIVE"] and "CRS" in steps[0].args["text"] and "Best Buy" in steps[0].args["text"]
    cached = {**CRS_LIVE, "cached": True}
    sim = {"business": False, "check": None, "cached": False, "sim_reason": "no business CRS profile"}
    replay = {**CRS_LIVE, "check": {**CRS_LIVE["check"], "origin": "CACHED"}}
    broken = {**CRS_LIVE, "check": {**CRS_LIVE["check"], "verified": False, "reason_codes": ["CRS_INVALID"]}}
    unavailable = {**CRS_LIVE, "check": {**CRS_LIVE["check"], "verified": False, "reason_codes": ["CRS_UNAVAILABLE"]}}
    for crs in (cached, sim, replay, broken, unavailable, None):
        assert bridge.live_proof_steps(ADDR, crs=crs, seller="Best Buy") == []


def test_every_proof_step_is_a_referee_record_agent_event_on_the_buyers_tile():
    steps = bridge.live_proof_steps(ADDR, price=LIVE_PRICE, quoted=1.0, tiger={"state": "written", "n": 1}, round_id="r", crs=CRS_LIVE, seller="x")
    assert len(steps) == 3 and all(s.actor == "referee" and s.reducer == "record_agent_event" for s in steps)
    assert {s.args["address"] for s in steps} == {ADDR["buyer"]}


# ---------------------------------------------------------------- the beat 4 gate posts them

@pytest.fixture(scope="module")
def run():
    return run_all(say=Narrator(False))


def beat4(run, *, price_check=None, tiger=None, crs=None):
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    gate.addresses = ADDR
    gate.price_check, gate.tiger_writer = price_check, tiger
    if crs is not None:
        gate.crs_check = lambda payee: crs
    client = FakeCartesia(lambda code: f"{code} approve")
    approver = bridge.make_live_approver(gate, client, buyer_name="Vidyut", on_code=lambda code, why: client.shown.update(code=code),
                                         secret="s" * 32, sleep=lambda x: None, poll=0)
    log, notes = [], []
    bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), clients(log), delay=0, say=lambda s: None, sleep=lambda x: None,
                   clock=lambda: 0.0, approver=approver, deal_gate=gate, note=notes.append)
    return [a for _, r, a in log if r == "record_agent_event" and a.get("origin") == "LIVE"]


def test_beat_4_posts_live_lines_for_a_real_price_read_and_a_real_tiger_write(run):
    live = beat4(run, price_check=lambda listing: {"state": "ok", "price": listing["price"], "fetched_at": "2026-10-24T19:00:00Z", "origin": "LIVE"},
                 tiger=lambda rows: {"state": "written", "n": len(rows)})
    text = " ".join(a["text"] for a in live)
    assert "Bright Data" in text and "Tiger Data" in text and all(a["address"] == ADDR["buyer"] for a in live)


def test_beat_4_posts_no_live_line_when_nothing_was_fetched(run):
    assert beat4(run, price_check=lambda listing: {"state": "empty", "price": None, "fetched_at": None, "origin": "MIRROR"},
                 tiger=lambda rows: {"state": "not_configured", "n": 0}) == []


# ---------------------------------------------------------------- the build runner posts them

def build_with(price_check, addresses=ADDR, tmp_path=None):
    m = FakeMarket()
    r = build.BuildRun(build.demo_plan(), make_clients(m), catalog=sim_catalog, allowance={"per_purchase_limit": 5000.0, "period_limit": 9000.0,
                                                                                       "period": "week"},
                       real_gpu_round=False, price_check=price_check, agent_addresses=addresses, out_dir=tmp_path, sleep=lambda x: None,
                       clock=lambda: 0.0, delay=0)
    r.run()
    return [a for _, name, a in m.log if name == "record_agent_event"]


def test_a_build_that_read_a_live_price_posts_it_as_a_live_event_and_a_sim_run_posts_none(tmp_path, monkeypatch):
    # every MIRROR champion the run re-checks; SIM sellers have no listing to read, so a sim catalog posts nothing
    assert build_with(lambda listing: dict(LIVE_PRICE), tmp_path=tmp_path) == []
    assert build_with(lambda listing: dict(LIVE_PRICE), addresses={}, tmp_path=tmp_path) == []


def test_a_build_posts_a_live_line_for_a_champion_whose_price_it_read(tmp_path):
    m = FakeMarket()
    r = build.BuildRun(build.demo_plan(), make_clients(m), catalog=sim_catalog, real_gpu_round=False, agent_addresses=ADDR, out_dir=tmp_path,
                       sleep=lambda x: None, clock=lambda: 0.0, delay=0)
    r.live["gpu"] = {"state": "ok", "price": 1299.99, "fetchedAt": "2026-10-24T19:00:00Z", "origin": "LIVE", "quoted": 1299.99, "at": "t",
                     "text": "RTX 5070 Ti: price checked live via Bright Data: $1,299.99 (LIVE; quoted $1,299.99)"}
    r.live["cpu"] = {"state": "slow", "price": None, "fetchedAt": None, "origin": "MIRROR", "quoted": 285.0, "at": "t", "text": "x"}
    r.post_proof_events()
    posted = [a for _, name, a in m.log if name == "record_agent_event"]
    assert [a["origin"] for a in posted] == ["LIVE"] and "Bright Data" in posted[0]["text"]
    r.post_proof_events()   # once per value
    assert len([1 for _, name, a in m.log if name == "record_agent_event"]) == 1


def test_a_build_posts_the_crs_band_only_when_it_came_from_the_sandbox_now(tmp_path):
    for res, expected in ((CRS_LIVE, ["LIVE"]), ({**CRS_LIVE, "cached": True}, []), ({"business": False, "check": None, "cached": False}, [])):
        m = FakeMarket()
        r = build.BuildRun(build.demo_plan(), make_clients(m), catalog=sim_catalog, real_gpu_round=False, agent_addresses=ADDR, out_dir=tmp_path,
                           sleep=lambda x: None, clock=lambda: 0.0, delay=0)
        r._post_crs_proof("best-buy", res)
        assert [a["origin"] for _, name, a in m.log if name == "record_agent_event"] == expected
