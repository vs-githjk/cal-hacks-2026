"""The public Actor charges one claim-checked event per judged claim (issue #170). apify is stubbed; no network."""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "claim_check" / "actor" / "src" / "main.py"


def load_main(monkeypatch):
    apify = types.ModuleType("apify")
    apify.Actor = object()
    pkg = types.ModuleType("src.data.claim_check")
    pkg.check_claim = lambda c: {}
    for name, mod in (("apify", apify), ("src", types.ModuleType("src")), ("src.data", types.ModuleType("src.data")),
                      ("src.data.claim_check", pkg)):
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("actor_main_under_test", MAIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(mod, claims, check, charge, state=None):
    rows, calls, logs = [], [], []
    store = state if state is not None else {}

    async def get_state():
        return store.get("next")

    async def set_state(v):
        store["next"] = v

    async def push(row):
        rows.append(row)

    async def charge_spy(**kw):
        calls.append(kw)
        if charge:
            return charge(**kw)

    n = asyncio.run(mod.run_claims(claims, check, push, charge_spy, log=logs.append, get_state=get_state, set_state=set_state))
    return n, rows, calls, logs


JUDGED = {"result": "false", "evidence_hash": "ab" * 32, "reason": "differs"}
FETCH_FAILED = {"result": "unverified", "evidence_hash": "", "method": "could not verify: page fetch failed (TimeoutError)", "reason": "could not verify"}


def test_three_judged_claims_charge_three_events(monkeypatch):
    mod = load_main(monkeypatch)
    n, rows, calls, _ = run(mod, [{"text": "$1"}, {"text": "$2"}, {"text": "$3"}], lambda c: dict(JUDGED), None)
    assert n == 3 and len(rows) == 3 and calls == [{"event_name": "claim-checked", "count": 1}] * 3


def test_a_fetch_failure_or_an_unchecked_claim_charges_nothing(monkeypatch):
    mod = load_main(monkeypatch)
    n, rows, calls, _ = run(mod, [{"text": "$1"}], lambda c: dict(FETCH_FAILED), None)
    assert n == 0 and calls == [] and len(rows) == 1

    def boom(c):
        raise RuntimeError("bad claim")
    n, rows, calls, _ = run(mod, [{"text": "$1"}], boom, None)
    assert n == 0 and calls == [] and rows[0]["result"] == "unverified"


def test_a_charge_exception_is_logged_and_the_run_finishes(monkeypatch):
    mod = load_main(monkeypatch)

    def refuse(**kw):
        raise RuntimeError("Actor is not on pay-per-event pricing")
    n, rows, calls, logs = run(mod, [{"text": "$1"}, {"text": "$2"}], lambda c: dict(JUDGED), refuse)
    assert n == 0 and len(rows) == 2 and len(calls) == 2 and len(logs) == 2 and "charge skipped" in logs[0]


UNVERIFIED_FETCHED = {"result": "unverified", "evidence_hash": "cd" * 32, "method": "could not verify: no structured data", "reason": "could not verify"}


def test_unverified_is_free_even_when_a_page_came_back(monkeypatch):  # #174: a 200 page with no structured data
    mod = load_main(monkeypatch)
    n, rows, calls, _ = run(mod, [{"text": "$1"}, {"text": "30-day returns"}], lambda c: dict(UNVERIFIED_FETCHED), None)
    assert n == 0 and calls == [] and len(rows) == 2


def test_a_restarted_run_from_saved_state_charges_each_claim_once(monkeypatch):
    mod = load_main(monkeypatch)
    state, claims = {}, [{"text": "$1"}, {"text": "$2"}, {"text": "$3"}]
    seen = []

    def crash_on_third(c):
        seen.append(c["text"])
        if c["text"] == "$3" and len(seen) == 3:
            raise KeyboardInterrupt  # the run dies before claim 3 is pushed or charged
        return dict(JUDGED)
    try:
        run(mod, claims, crash_on_third, None, state=state)
    except KeyboardInterrupt:
        pass
    assert state["next"] == 2
    n, rows, calls, _ = run(mod, claims, lambda c: dict(JUDGED), None, state=state)  # restart: only claim 3 is left
    assert n == 1 and [r["text"] for r in rows] == ["$3"] and len(calls) == 1 and state["next"] == 3


def test_the_loop_stops_at_the_users_charge_limit(monkeypatch):
    mod = load_main(monkeypatch)

    class Res:
        charged_count, event_charge_limit_reached = 1, True
    n, rows, calls, logs = run(mod, [{"text": "$1"}, {"text": "$2"}], lambda c: dict(JUDGED), lambda **kw: Res())
    assert n == 1 and len(rows) == 1 and len(calls) == 1 and "limit" in logs[0]
