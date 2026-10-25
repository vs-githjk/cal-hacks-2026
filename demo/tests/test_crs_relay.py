"""Lane D: relay the CRS sandbox signals (agents/crs.py cache) into the market's record_supplier_signal.

No market, no network, no CRS call: the market is a fake client and the cache is a temp file of sanitized signals.
Fail closed: a seller with no valid, fresh, mapped signal is never relayed, so the market never shows it as verified."""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from demo import bridge, build, crs_relay

NOW = datetime(2026, 10, 24, 20, 0, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]
WITH = {"approve_typed", "open_round", "record_supplier_signal"}   # reducer names a market with PR #320 lists
WITHOUT = {"approve_typed", "open_round"}                           # the market on main today


def sig(sid="seller_1", stability="verified_stable", at="2026-10-24T19:37:18.568687Z", source="sandbox"):
    return {"supplier_id": sid, "stability": stability, "checked_at": at, "source": source}


def entry(signal, persona="P01"):
    """One crs-signals.json entry: persona ref, the four-field signal and the fixed reason text. No identity data."""
    return {"persona_ref": persona, "signal": signal, "reason": "fixed text"}


def cache_of(*signals):
    return {s["supplier_id"]: entry(s) for s in signals}


class FakeMarket:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def call(self, reducer, **args):
        self.calls.append((reducer, args))
        err = self.fail.get(args.get("supplier_id"))
        if err:
            raise err


def run_relay(cache, market=None, reducers=WITH, now=NOW):
    market = market or FakeMarket()
    notes = []
    report = crs_relay.relay(market, cache, reducers=reducers, now=now, note=notes.append)
    return market, report, notes


# ---------------------------------------------------------------- the one mapping

def test_mapping_is_the_one_the_seller_agents_use():
    """The CRS supplier ids seller_1..3 are the market seller ids seller-a..c (seller_agent._MARKET_SELLER_SUBJECT)."""
    text = (ROOT / "agents" / "sellers" / "seller_agent.py").read_text(encoding="utf-8")
    agents_map = ast.literal_eval(re.search(r"^_MARKET_SELLER_SUBJECT = (\{.*\})$", text, re.M).group(1))
    assert crs_relay.MARKET_SELLER == agents_map == {"seller_1": "seller-a", "seller_2": "seller-b", "seller_3": "seller-c"}


def test_the_mapping_covers_every_business_profile_the_cache_can_hold():
    """No CRS seller of record is left out of the mapping; each market id appears once."""
    assert len(set(crs_relay.MARKET_SELLER.values())) == len(crs_relay.MARKET_SELLER)


# ---------------------------------------------------------------- plan: cache -> calls

def test_plan_maps_each_signal_to_its_market_seller_with_band_time_and_source():
    cache = cache_of(sig("seller_1"), sig("seller_2"), sig("seller_3", "not_verified"))
    calls, skipped = crs_relay.plan(cache, now=NOW)
    assert skipped == []
    assert calls == [
        {"supplier_id": "seller-a", "stability": "verified_stable", "checked_at": "2026-10-24T19:37:18Z", "source": "sandbox"},
        {"supplier_id": "seller-b", "stability": "verified_stable", "checked_at": "2026-10-24T19:37:18Z", "source": "sandbox"},
        {"supplier_id": "seller-c", "stability": "not_verified", "checked_at": "2026-10-24T19:37:18Z", "source": "sandbox"},
    ]


def test_caution_and_not_verified_are_relayed_as_themselves_never_upgraded():
    calls, _ = crs_relay.plan(cache_of(sig("seller_1", "caution"), sig("seller_2", "not_verified")), now=NOW)
    assert [c["stability"] for c in calls] == ["caution", "not_verified"]


def test_a_recorded_cache_entry_keeps_its_source():
    calls, _ = crs_relay.plan(cache_of(sig(source="recorded")), now=NOW)
    assert calls[0]["source"] == "recorded"


@pytest.mark.parametrize("bad, why", [
    (sig(stability="stable"), "band"),
    (sig(stability="VERIFIED_STABLE"), "band"),
    (sig(source="live"), "source"),
    (sig(source="simulated"), "source"),
    (sig(at="yesterday"), "time"),
    (sig(at=""), "time"),
    (sig(at="2026-10-23T19:00:00Z"), "stale"),                      # older than 24 hours
    (sig(at="2026-10-24T20:30:00Z"), "future"),                     # a clock cannot run ahead
    ({**sig(), "extra": "x"}, "fields"),                            # exactly the four fields, nothing else rides along
    ({k: v for k, v in sig().items() if k != "source"}, "fields"),
    (sig(sid="seller_2"), "id"),                                    # the signal says it is for another seller than its key
])
def test_an_invalid_signal_is_skipped_with_a_reason_and_never_relayed(bad, why):
    calls, skipped = crs_relay.plan({"seller_1": entry(bad)}, now=NOW)
    assert calls == []
    assert len(skipped) == 1 and skipped[0][0] == "seller_1" and why in skipped[0][1]


@pytest.mark.parametrize("cache", [{}, [], "x", None, {"seller_1": None}, {"seller_1": "verified"}, {"seller_1": {"signal": None}},
                                   {"seller_1": {"signal": "verified_stable"}}])
def test_a_missing_or_odd_cache_relays_nothing(cache):
    calls, _ = crs_relay.plan(cache, now=NOW)
    assert calls == []


def test_a_seller_with_no_market_id_is_skipped_by_name():
    calls, skipped = crs_relay.plan(cache_of(sig("seller_6"), sig("seller_1")), now=NOW)
    assert [c["supplier_id"] for c in calls] == ["seller-a"]
    assert skipped == [("seller_6", "no market seller id for it")]


def test_the_cache_is_never_trusted_for_a_verified_it_does_not_hold():
    """A seller absent from the cache gets no call at all (the market shows no signal, never verified)."""
    calls, _ = crs_relay.plan(cache_of(sig("seller_1")), now=NOW)
    assert {c["supplier_id"] for c in calls} == {"seller-a"}


# ---------------------------------------------------------------- relay: calls the reducer as the referee

def test_relay_calls_record_supplier_signal_once_per_signal_with_the_exact_arguments():
    market, report, notes = run_relay(cache_of(sig("seller_1"), sig("seller_3", "not_verified")))
    assert market.calls == [
        ("record_supplier_signal", {"supplier_id": "seller-a", "stability": "verified_stable", "checked_at": "2026-10-24T19:37:18Z", "source": "sandbox"}),
        ("record_supplier_signal", {"supplier_id": "seller-c", "stability": "not_verified", "checked_at": "2026-10-24T19:37:18Z", "source": "sandbox"}),
    ]
    assert report["sent"] == ["seller-a", "seller-c"] and report["status"] == "sent"
    assert any("seller-a" in n and "verified_stable" in n for n in notes)


def test_a_market_without_the_reducer_is_skipped_with_a_clear_note_and_no_call():
    market, report, notes = run_relay(cache_of(sig()), reducers=WITHOUT)
    assert market.calls == []
    assert report["status"] == "no_reducer"
    assert any("record_supplier_signal" in n and "PR 320" in n for n in notes)


def test_when_the_schema_is_unreadable_it_tries_and_a_404_means_the_reducer_is_missing():
    market = FakeMarket(fail={"seller-a": RuntimeError("record_supplier_signal failed (404): no such reducer")})
    market, report, notes = run_relay(cache_of(sig("seller_1"), sig("seller_2")), market=market, reducers=None)
    assert len(market.calls) == 1                      # stops at the first 404: the others would fail the same way
    assert report["status"] == "no_reducer" and report["sent"] == []
    assert any("PR 320" in n for n in notes)


def test_one_refused_seller_does_not_stop_the_others_and_is_reported():
    market = FakeMarket(fail={"seller-a": RuntimeError("record_supplier_signal failed (400): not allowed")})
    market, report, notes = run_relay(cache_of(sig("seller_1"), sig("seller_2")), market=market)
    assert [c[1]["supplier_id"] for c in market.calls] == ["seller-a", "seller-b"]
    assert report["sent"] == ["seller-b"] and report["failed"] == [("seller-a", "record_supplier_signal failed (400): not allowed")]
    assert report["status"] == "partial"


def test_dry_run_prints_the_calls_and_touches_no_market():
    market, report, notes = run_relay(cache_of(sig("seller_1")))
    market2 = FakeMarket()
    notes2 = []
    report2 = crs_relay.relay(market2, cache_of(sig("seller_1")), reducers=WITH, now=NOW, note=notes2.append, dry_run=True)
    assert market2.calls == [] and report2["status"] == "dry_run" and report2["sent"] == []
    assert any("would call record_supplier_signal" in n and "seller-a" in n for n in notes2)


def test_nothing_to_relay_says_so():
    market, report, notes = run_relay({})
    assert market.calls == [] and report["status"] == "nothing"
    assert any("no usable CRS signal" in n for n in notes)


def test_notes_never_carry_identity_data():
    cache = {"seller_1": {**entry(sig()), "request": {"firstName": "Jane", "ssn": "000-00-0000"}}}
    market, report, notes = run_relay(cache)
    assert "Jane" not in " ".join(notes) and "000-00" not in " ".join(notes)
    assert all(set(a) == {"supplier_id", "stability", "checked_at", "source"} for _, a in market.calls)


# ---------------------------------------------------------------- reading the cache and the schema

def test_read_cache_of_a_missing_or_broken_file_is_empty_not_an_error(tmp_path):
    assert crs_relay.read_cache(tmp_path / "none.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert crs_relay.read_cache(bad) == {}
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(cache_of(sig())), encoding="utf-8")
    assert "seller_1" in crs_relay.read_cache(ok)


def test_detect_reducers_reads_the_names_from_the_schema_and_is_none_when_unreadable():
    body = json.dumps({"reducers": [{"name": "open_round"}, {"name": "record_supplier_signal"}]}).encode()

    class Resp:
        def __init__(self, data): self.data = data
        def read(self): return self.data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    seen = []
    def opener(url, timeout=0):
        seen.append(url)
        return Resp(body)
    assert crs_relay.detect_reducers("http://127.0.0.1:3000", "tech-bazaar", opener=opener) == {"open_round", "record_supplier_signal"}
    assert seen == ["http://127.0.0.1:3000/v1/database/tech-bazaar/schema?version=9"]

    def broken(url, timeout=0): raise OSError("down")
    assert crs_relay.detect_reducers("http://127.0.0.1:3000", "tech-bazaar", opener=broken) is None
    assert crs_relay.detect_reducers("http://127.0.0.1:3000", "tech-bazaar", opener=lambda u, timeout=0: Resp(b"[1]")) is None


# ---------------------------------------------------------------- best effort: never stops a round

def test_best_effort_never_raises_whatever_goes_wrong(tmp_path):
    class Boom:
        def call(self, reducer, **args): raise ValueError("odd")
    notes = []
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps(cache_of(sig())), encoding="utf-8")
    out = crs_relay.relay_best_effort(Boom(), note=notes.append, cache_path=cache, reducers=WITH, now=NOW)
    assert out["status"] in {"partial", "failed"} and any("seller-a" in n for n in notes)
    out2 = crs_relay.relay_best_effort(None, note=notes.append, cache_path=cache, reducers=WITH, now=NOW)   # no client at all
    assert out2["status"] == "failed"
    out3 = crs_relay.relay_best_effort(FakeMarket(), note=lambda t: 1 / 0, cache_path=cache, reducers=WITH, now=NOW)  # the note itself explodes
    assert out3["status"] == "failed"


# ---------------------------------------------------------------- the command

def test_main_dry_run_reads_the_cache_and_needs_no_market(tmp_path, capsys, monkeypatch):
    cache = tmp_path / "c.json"
    data = cache_of(sig("seller_1", at=(datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")))
    cache.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(crs_relay, "referee_client", lambda *a, **k: pytest.fail("a dry run must not open a market client"))
    assert crs_relay.main(["--dry-run", "--cache", str(cache)]) == 0
    out = capsys.readouterr().out
    assert "would call record_supplier_signal" in out and "seller-a" in out and "verified_stable" in out


def test_main_dry_run_with_no_usable_signal_exits_nonzero(tmp_path, capsys):
    assert crs_relay.main(["--dry-run", "--cache", str(tmp_path / "missing.json")]) == 2
    assert "no usable CRS signal" in capsys.readouterr().out


# ---------------------------------------------------------------- wired into the bridge and the build

class Recorder:
    def __init__(self, log, name="x"): self.log, self.name = log, name
    def call(self, reducer, **args): self.log.append((self.name, reducer))
    def sql(self, q): return []


def _steps(*reducers):
    return [bridge.Step("referee", r, {}, tag="SIM", say=r) for r in reducers]


def test_bridge_execute_relays_right_before_each_round_opens_and_only_then():
    log = []
    steps = _steps("post_goal", "open_round", "close_round")
    bridge.execute(steps, {"referee": Recorder(log)}, delay=0, say=lambda s: None, sleep=lambda s: None,
                   before_round=lambda: log.append(("relay", "before")))
    assert log == [("x", "post_goal"), ("relay", "before"), ("x", "open_round"), ("x", "close_round")]


def test_a_failing_relay_hook_never_stops_the_round():
    log, notes = [], []
    def boom(): raise RuntimeError("market down")
    bridge.execute(_steps("open_round", "close_round"), {"referee": Recorder(log)}, delay=0, say=lambda s: None,
                   sleep=lambda s: None, note=notes.append, before_round=boom)
    assert log == [("x", "open_round"), ("x", "close_round")]
    assert any("CRS relay" in n for n in notes)


def test_execute_without_a_hook_is_unchanged():
    log = []
    bridge.execute(_steps("open_round"), {"referee": Recorder(log)}, delay=0, say=lambda s: None, sleep=lambda s: None)
    assert log == [("x", "open_round")]


def test_build_run_passes_its_relay_to_the_bridge_and_defaults_to_none(monkeypatch):
    seen = {}
    monkeypatch.setattr(bridge, "execute", lambda steps, clients, **kw: seen.update(kw))
    plan = build.demo_plan()
    build.BuildRun(plan, {}, out_dir=None)._execute([])
    assert seen["before_round"] is None
    called = []
    build.BuildRun(plan, {}, out_dir=None, relay_signals=lambda: called.append(1))._execute([])
    seen["before_round"]()
    assert called == [1]
