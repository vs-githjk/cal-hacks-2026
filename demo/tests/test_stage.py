"""The stage runner: health check, reset, beats 1 to 5 in order with cues and delays. Fakes only: no market, no network, no sleeping."""
from __future__ import annotations

import re

import pytest

from demo import bridge, stage
from demo.common import Narrator
from demo.run_demo import run_all


@pytest.fixture(scope="module")
def run():
    return run_all(say=Narrator(False))


RUN: dict = {}


@pytest.fixture(autouse=True)
def offline(run, monkeypatch):
    RUN["run"] = run
    """main() reuses one run (the story is deterministic enough for these tests) and never reads the Cartesia env."""
    monkeypatch.setattr(stage, "run_all", lambda **kw: run)
    from pay import voice_cartesia as vc
    for name in vc.ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


UP = [{"service": "market-stdb", "label": "UP"}, {"service": "web", "label": "UP"}, {"service": "shield", "label": "SKIPPED"}]


class Fake:
    """A client that records every reducer call and prints it, so the cue / call order shows in the console text."""

    def __init__(self, log, name, fail=None, rows=None):
        self.log, self.name, self.fail, self.rows = log, name, fail or {}, rows

    def call(self, reducer, **args):
        self.log.append((self.name, reducer, args))
        print(f"CALL {self.name} {reducer}")
        if reducer in self.fail:
            raise RuntimeError(self.fail[reducer])

    def sql(self, query):
        if self.rows is None:
            raise RuntimeError("no round_result in this fake")
        return self.rows


class Time:
    """A clock that only moves when the code sleeps."""

    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s

    def clock(self):
        return self.t


def go(argv, *, rows=UP, fail=None, inputs=None, log=None, result_rows="market", on_ask=None):
    """result_rows: the market's round_result rows (default: the market agrees with the demo's winner; None: unreadable)."""
    log = [] if log is None else log
    if result_rows == "market":
        result_rows = market_rows(RUN["run"], RUN["run"]["beats"]["2"]["winner"]["seller_id"])
    clk = Time()
    asked = []

    def make_clients(args, steps, out):
        names = ["buyer", "referee"] + sorted({s.actor for s in steps if s.actor.startswith("seller:")})
        return {n: Fake(log, n, fail, result_rows) for n in names}

    def ask(prompt):
        asked.append(prompt)
        if on_ask is not None:
            on_ask(prompt)
        if inputs is None:
            return ""
        if not inputs:
            raise EOFError
        return inputs.pop(0)

    code = stage.main(argv, status_rows=lambda run_dir: rows, make_clients=make_clients, input_fn=ask, sleep=clk.sleep, clock=clk.clock)
    return code, log, clk, asked


def reducers(log):
    return [r for _, r, _ in log if r != "set_floor"]


# ---------------------------------------------------------------- the beat split

def test_every_step_lands_in_exactly_one_beat_in_order(run):
    steps = bridge.plan(run, delay=0, rounds=2)
    beats = stage.assign_beats(steps)
    assert sorted(beats) == [1, 2, 3, 4, 5]
    assert [s for n in sorted(beats) for s in beats[n]] == steps
    assert [s.reducer for s in beats[1]] == ["post_goal", "set_allowance", "post_need"]
    assert beats[2][0].reducer == "open_round" and beats[2][-1].reducer == "close_round"
    assert [s.reducer for s in beats[3]] == ["attach_verdict"]
    assert [s.reducer for s in beats[4]] == ["create_mandate", "record_approval", "record_payment", "record_payment"]
    assert beats[5][0].reducer == "open_round" and beats[5][-1].reducer == "close_round"


def test_one_round_plan_has_no_beat_five(run):
    beats = stage.assign_beats(bridge.plan(run, delay=0, rounds=1))
    assert sorted(beats) == [1, 2, 3, 4]


# ---------------------------------------------------------------- the auto run

def test_auto_runs_check_reset_then_beats_in_order_with_a_cue_before_each(capsys):
    code, log, clk, asked = go(["--auto", "--step-delay", "0"])
    assert code == 0 and asked == []
    out = capsys.readouterr().out
    assert log[0][:2] == ("referee", "reset_demo")
    assert reducers(log)[1:4] == ["post_goal", "set_allowance", "post_need"]
    assert reducers(log).count("open_round") == 2 and reducers(log)[-1] == "close_round"
    cues = [m.start() for m in re.finditer(r"SAY THIS", out)]
    assert len(cues) == 5
    # each cue prints before that beat's first call
    first_call = {1: out.index("CALL buyer post_goal"), 2: out.index("CALL referee open_round"),
                  3: out.index("CALL referee attach_verdict", out.index("CALL referee close_round")),
                  4: out.index("CALL referee create_mandate"), 5: out.index("CALL referee open_round", out.index("create_mandate"))}
    for n, at in zip(range(1, 6), cues):
        assert at < first_call[n]
    assert [m.group(1) for m in re.finditer(r"BEAT (\d) of 5", out)] == ["1", "2", "3", "4", "5"]


def test_auto_waits_the_configured_delay_between_cue_and_beat():
    code, log, clk, _ = go(["--auto", "--step-delay", "0", "--delays", "11,22,33,44,55"])
    assert code == 0
    holds = [s for s in clk.sleeps if s in (11, 22, 33, 44, 55)]
    assert holds == [11, 22, 33, 44, 55]


def test_default_delays_cover_every_beat_and_are_used_when_not_set(monkeypatch):
    assert sorted(stage.DEFAULT_DELAYS) == [1, 2, 3, 4, 5]
    marked = {1: 71, 2: 72, 3: 73, 4: 74, 5: 75}      # values no round window or step sleep can equal
    monkeypatch.setattr(stage, "DEFAULT_DELAYS", marked)
    code, log, clk, _ = go(["--auto", "--step-delay", "0"])
    assert [s for s in clk.sleeps if s in marked.values()] == [71, 72, 73, 74, 75]


def test_bad_delays_are_refused():
    for bad in ("1,2,3", "a,b,c,d,e", "1,2,3,4,-5"):
        with pytest.raises(SystemExit):
            go(["--auto", "--delays", bad])


def test_step_delay_reaches_the_bridge_plan():
    code, log, clk, _ = go(["--auto", "--step-delay", "3", "--delays", "0,0,0,0,0"])
    assert code == 0 and any(abs(s - 3) < 1e-9 for s in clk.sleeps)


# ---------------------------------------------------------------- enter to advance

def test_manual_mode_waits_for_enter_once_per_beat(monkeypatch):
    monkeypatch.setattr(stage, "DEFAULT_DELAYS", {1: 71, 2: 72, 3: 73, 4: 74, 5: 75})
    code, log, clk, asked = go(["--step-delay", "0"])
    assert code == 0 and len(asked) == 5
    assert not any(s in (71, 72, 73, 74, 75) for s in clk.sleeps)     # no reading delay when a person presses Enter
    assert "post_goal" in reducers(log)


def test_manual_mode_stops_cleanly_when_input_ends():
    code, log, clk, asked = go(["--step-delay", "0"], inputs=[""])           # one Enter, then end of input
    assert code == 1
    assert "post_goal" in reducers(log) and "open_round" not in reducers(log)       # beat 1 played, beat 2 never started


def test_q_at_the_prompt_stops_before_that_beat():
    code, log, clk, asked = go(["--step-delay", "0"], inputs=["", "q"])
    assert code == 1 and "post_goal" in reducers(log) and "open_round" not in reducers(log)


# ---------------------------------------------------------------- health check

@pytest.mark.parametrize("label", ["DOWN", "FAILED"])
def test_refuses_to_start_when_a_service_is_down(label, capsys):
    rows = [{"service": "market-stdb", "label": "UP"}, {"service": "web", "label": label}]
    code, log, clk, _ = go(["--auto"], rows=rows)
    assert code == 1 and log == []
    out = capsys.readouterr().out
    assert "NOT STARTING" in out and "web" in out and "--force" in out


def test_the_refusal_names_every_down_service_and_the_force_flag(capsys):
    rows = [{"service": "web", "label": "DOWN"}, {"service": "agents", "label": "FAILED"}, {"service": "shield", "label": "UP"}]
    code, log, *_ = go(["--auto"], rows=rows)
    out = capsys.readouterr().out
    down_line = next(l for l in out.splitlines() if "NOT STARTING" in l)
    assert code == 1 and "web" in down_line and "agents" in down_line and "shield" not in down_line and "--force" in out


def test_force_starts_anyway_and_says_so(capsys):
    rows = [{"service": "web", "label": "DOWN"}]
    code, log, *_ = go(["--auto", "--step-delay", "0", "--force"], rows=rows)
    assert code == 0 and "post_goal" in reducers(log)
    assert "FORCED" in capsys.readouterr().out


def test_nothing_started_is_refused():
    code, log, *_ = go(["--auto"], rows=[])
    assert code == 1 and log == []


def test_skipped_services_do_not_block():
    code, *_ = go(["--auto", "--step-delay", "0"], rows=[{"service": "shield", "label": "SKIPPED"}, {"service": "web", "label": "UP"}])
    assert code == 0


def test_down_services_helper():
    assert stage.down_services([{"service": "a", "label": "UP"}, {"service": "b", "label": "DOWN"}, {"service": "c", "label": "FAILED"},
                                {"service": "d", "label": "SKIPPED"}]) == ["b", "c"]


# ---------------------------------------------------------------- the live call

class Approver:
    def __init__(self, approved, reason=None):
        self.approved, self.reason, self.seen = approved, reason, []

    def __call__(self, step):
        self.seen.append(step.reducer)
        return {"step": "approval_call", "approved": self.approved, "reason": self.reason, "call_id": "call-1"}


def patch_live(monkeypatch, approver):
    seen = {}

    def fake(args, run, mandate, out):
        seen["mandate"] = mandate
        return approver, "live call: fake"

    monkeypatch.setattr(bridge, "live_approver_for", fake)
    return seen


def test_live_call_passes_through_to_the_bridge_and_records_on_approval(monkeypatch):
    approver = Approver(True)
    seen = patch_live(monkeypatch, approver)
    code, log, *_ = go(["--auto", "--step-delay", "0", "--live-call"])
    assert code == 0 and approver.seen == ["record_approval"]
    assert "record_approval" in reducers(log) and "record_payment" in reducers(log)
    created = next(a for _, r, a in log if r == "create_mandate")
    assert created["hash"] == seen["mandate"].mandate["hash"]   # the mandate the call judges is the one the market got
    assert reducers(log).count("open_round") == 2                  # beat 5 still plays


def test_live_call_denied_records_nothing_and_stops(monkeypatch, capsys):
    patch_live(monkeypatch, Approver(False, "wrong_code"))
    code, log, *_ = go(["--auto", "--step-delay", "0", "--live-call"])
    out = capsys.readouterr().out
    assert code == 1
    assert "record_approval" not in reducers(log) and "record_payment" not in reducers(log)
    assert reducers(log).count("open_round") == 1               # beat 5 never starts
    assert "DENIED" in out and "nothing" in out.lower()


def test_live_call_not_configured_is_a_denial_not_a_charge(capsys):
    code, log, *_ = go(["--auto", "--step-delay", "0", "--live-call", "--env-file", "/nonexistent/none.env"])
    assert code == 1
    assert "record_approval" not in reducers(log) and "record_payment" not in reducers(log)
    assert "create_mandate" in reducers(log)


def test_without_live_call_the_simulated_approval_is_recorded(monkeypatch):
    monkeypatch.setattr(bridge, "live_approver_for", lambda *a, **k: pytest.fail("no live call was asked for"))
    code, log, *_ = go(["--auto", "--step-delay", "0"])
    assert code == 0 and "record_approval" in reducers(log) and "record_payment" in reducers(log)


def test_live_call_cannot_be_combined_with_stripe():
    with pytest.raises(SystemExit):
        stage.main(["--live-call", "--stripe"])


def test_live_cue_differs_and_names_the_code_and_the_denial_rule():
    live, sim = stage.cue_for(4, live_call=True), stage.cue_for(4, live_call=False)
    assert live != sim and "code" in live.lower() and "approve" in live.lower() and "nothing is paid" in live.lower()
    assert "simulated" in sim.lower()
    for n in (1, 2, 3, 5):
        assert stage.cue_for(n, live_call=True) == stage.cue_for(n, live_call=False)


# ---------------------------------------------------------------- market refusal, dry run, copy

def test_a_market_refusal_stops_the_run_with_its_own_message(capsys):
    code, log, *_ = go(["--auto", "--step-delay", "0"], fail={"post_need": "need already exists"})
    out = capsys.readouterr().out
    assert code == 1 and "STOPPED" in out and "need already exists" in out
    assert "open_round" not in reducers(log)


def test_dry_run_prints_cues_and_calls_but_touches_nothing(capsys):
    def boom(*a, **k):
        raise AssertionError("dry run must not build clients")

    code = stage.main(["--dry-run"], status_rows=lambda d: pytest.fail("no health check in a dry run"), make_clients=boom,
                      input_fn=lambda p: pytest.fail("no prompt"), sleep=lambda s: pytest.fail("no sleep"))
    out = capsys.readouterr().out
    assert code == 0 and out.count("SAY THIS") == 5 and "post_goal" in out and "record_payment" in out


def test_cues_are_plain_one_line_and_follow_the_copy_rules():
    for n in range(1, 6):
        for live in (False, True):
            cue = stage.cue_for(n, live_call=live)
            assert "\n" not in cue and len(cue) < 260
            assert "\u2014" not in cue and "\u2013" not in cue and "secure" not in cue.lower()
            assert not re.search(r"\b(he|she|his|her|him)\b", cue, re.I)
            assert "Visa settles" not in cue
    assert "Vidyut" in stage.cue_for(1, live_call=False)
    assert "Gadget Grove (Vedant)" in stage.cue_for(5, live_call=False)


def test_the_stage_source_has_no_dashes_or_attribution():
    from pathlib import Path
    text = Path(stage.__file__).read_text(encoding="utf-8")
    assert "\u2014" not in text and "\u2013" not in text and "Co-Authored" not in text


# ---------------------------------------------------------------- the mandate is made when beat 4 starts

class SkewedClock:
    """pay.voice_cartesia and pay.mandate read the wall clock through their own `datetime`; this moves both together."""

    def __init__(self, monkeypatch):
        import datetime as dt
        from pay import mandate as pm, voice_cartesia as vc
        skew = self
        skew.minutes = 0

        class DT(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return dt.datetime.now(tz) + dt.timedelta(minutes=skew.minutes)

        monkeypatch.setattr(vc, "datetime", DT)
        monkeypatch.setattr(pm, "datetime", DT)


def test_live_call_mandate_is_made_at_beat_four_so_a_long_wait_does_not_expire_it(monkeypatch, capsys):
    from pay import voice_cartesia as vc
    clock = SkewedClock(monkeypatch)

    class Client:
        approval_call_to = "+15550000000"

    dialled = []

    def blocked_dial(client, variables):
        dialled.append(variables)
        raise vc.CartesiaError("test: dial blocked")      # reaching this line means the gate let the call through

    monkeypatch.setattr(vc.CartesiaClient, "from_env", classmethod(lambda cls, env: Client()))
    monkeypatch.setattr(vc, "place_call", blocked_dial)
    judged = []
    real = bridge.make_live_approver

    def spy(gate, *a, **k):
        judged.append(gate)
        return real(gate, *a, **k)

    monkeypatch.setattr(bridge, "make_live_approver", spy)

    def wait_at_beat_one(prompt):
        if "beat 1" in prompt:
            clock.minutes = 11        # judges walk up, the recorder is being set up: longer than any mandate lives

    code, log, *_ = go(["--live-call", "--step-delay", "0"], on_ask=wait_at_beat_one)
    out = capsys.readouterr().out
    assert len(dialled) == 1, "the gate refused before dialling"
    assert "(expired)" not in out and "call_failed" in out and code == 1       # the blocked dial is the only denial
    created = next(a for _, r, a in log if r == "create_mandate")
    assert judged[-1].mandate["hash"] == created["hash"]                     # the gate judged the mandate the market got
    assert "record_approval" not in reducers(log) and "record_payment" not in reducers(log)


def test_live_call_startup_does_not_make_the_call_mandate(monkeypatch):
    made = []
    real = bridge.DealGate.prepare
    monkeypatch.setattr(bridge.DealGate, "prepare", lambda self, ref: made.append(1) or real(self, ref))
    patch_live(monkeypatch, Approver(True))
    asked_when = []
    go(["--live-call", "--step-delay", "0"], on_ask=lambda prompt: asked_when.append(len(made)))
    assert asked_when and set(asked_when[:3]) == {0}      # nothing made while the operator is still at the beat 1 to 3 prompts
    assert len(made) == 1                                 # exactly one, at beat 4


# ---------------------------------------------------------------- round 1 read-back

def market_rows(run, first_seller_id):
    """round_result rows (id, round_id, bid_id, seller_id, persona, rank, landed, reasons) with `first_seller_id` ranked 1."""
    b2 = run["beats"]["2"]
    win = b2["winner"]["seller_id"]
    second = "gadget-grove" if first_seller_id == win else win
    bids = {b["seller_id"]: b for b in b2["bids"]}
    landed = {e["seller_id"]: e["landed"] for e in b2["ranking"]["ranked"]}
    return [("rr-1", "round-1", bids[first_seller_id]["id"], first_seller_id, bids[first_seller_id]["persona"], 1, landed[first_seller_id], []),
            ("rr-2", "round-1", bids[second]["id"], second, bids[second]["persona"], 2, landed[second], [])]


result_rows = market_rows


def test_beat_two_reads_the_market_ranking_back_and_says_when_it_agrees(run, capsys):
    win = run["beats"]["2"]["winner"]["seller_id"]
    code, *_ = go(["--auto", "--step-delay", "0"], result_rows=result_rows(run, win))
    out = capsys.readouterr().out
    assert code == 0 and "market ranking (round 1)" in out and "market and demo agree" in out and "DIVERGENCE" not in out


def test_a_different_market_number_one_prints_divergence_before_the_beat_four_cue(run, capsys):
    code, log, clk, asked = go(["--auto", "--step-delay", "0"], result_rows=result_rows(run, "gadget-grove"))
    out = capsys.readouterr().out
    assert code == 0
    gg = next(x for x in run["beats"]["2"]["sellers"] if x["id"] == "gadget-grove")
    assert next(a for _, r, a in log if r == "create_mandate")["payee"] == gg["id"]    # #194, #240: beat 4 pays the market's #1 by seller id
    assert out.index("DIVERGENCE") < out.index("BEAT 4 of 5")
    assert out.index("BEAT 2 of 5") < out.index("DIVERGENCE") < out.index("BEAT 3 of 5")
    assert any("not the demo's winner" in p for p in asked)         # --auto pauses once so the operator cannot miss it


def test_agreement_does_not_add_a_pause(run):
    win = run["beats"]["2"]["winner"]["seller_id"]
    _, _, _, asked = go(["--auto", "--step-delay", "0"], result_rows=result_rows(run, win))
    assert asked == []


def test_an_unreadable_market_ranking_stops_beat_four_with_nothing_paid(capsys):
    code, log, *_ = go(["--auto", "--step-delay", "0"], result_rows=None)     # the fake has no round_result
    out = capsys.readouterr().out
    assert "could not read round_result back (RuntimeError)" in out           # after beat 2: one note
    assert code == 1 and "no mandate was made" in out and "Nothing was charged" in out
    assert not any(r in ("create_mandate", "record_approval", "record_payment") for _, r, _ in log)


# ---------------------------------------------------------------- #183: one run under 120 s with a short sealed window

def test_a_full_auto_run_with_a_20_s_bid_window_takes_under_120_s():
    """The clock moves only when the code sleeps, so this is the run's own pacing: cues, steps and both sealed windows."""
    code, log, clk, _ = go(["--auto", "--bid-window", "20"])
    assert code == 0 and reducers(log).count("open_round") == 2
    assert clk.t - 1000.0 < 120, clk.t - 1000.0
    windows = [a["window_s"] for _, r, a in log if r == "open_round"]
    assert windows == [20, 20]


def test_without_the_flag_the_windows_cover_the_paced_steps_as_before():
    code, log, clk, _ = go(["--auto"])
    windows = [a["window_s"] for _, r, a in log if r == "open_round"]
    assert code == 0 and windows[0] > 20 and clk.t - 1000.0 > 120


def test_every_bid_and_check_lands_before_the_short_deadline():
    """Compressing the window compresses the step pace inside the round, so no bid arrives after the close."""
    run = RUN["run"]
    steps = bridge.plan(run, delay=2.0, rounds=2, bid_window=20)
    for rno in ("round-1", "round-2"):
        i = next(k for k, s in enumerate(steps) if s.reducer == "open_round" and s.args["round_id"] == rno)
        j = next(k for k, s in enumerate(steps) if s.reducer == "close_round" and s.args["round_id"] == rno)
        inside = sum(2.0 * s.pace for s in steps[i:j] if s.pause)
        assert steps[i].args["window_s"] == 20 and inside <= 20 - 6 + 1e-9, (rno, inside)


@pytest.mark.parametrize("bad", ["5", "0", "-3", "abc", "12", "14"])
def test_a_bid_window_below_the_minimum_is_refused(bad):
    with pytest.raises(SystemExit):
        stage.main(["--dry-run", "--bid-window", bad])
    with pytest.raises(SystemExit):
        bridge.main(["--dry-run", "--bid-window", bad])
