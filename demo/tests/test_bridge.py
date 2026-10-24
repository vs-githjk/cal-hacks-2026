"""The screen bridge: demo run -> reducer calls. A fake client records calls, no network, no sleeping."""
from __future__ import annotations

import pytest

from demo import bridge
from demo.common import Narrator
from demo.run_demo import run_all


@pytest.fixture(scope="module")
def run():
    return run_all(say=Narrator(False))


@pytest.fixture(scope="module")
def steps(run):
    return bridge.plan(run, delay=2.0, rounds=1)


class Fake:
    def __init__(self, log, name, fail=None):
        self.log, self.name, self.fail = log, name, fail or {}

    def call(self, reducer, **args):
        self.log.append((self.name, reducer, args))
        if reducer in self.fail:
            raise RuntimeError(self.fail[reducer].pop(0) if self.fail[reducer] else "ok")


def clients(log, fail=None):
    names = ["buyer", "referee"] + sorted({s.actor for s in bridge.plan(run_all(say=Narrator(False))) if s.actor.startswith("seller:")})
    return {n: Fake(log, n, fail) for n in names}


def test_order_follows_the_stage_story(steps):
    kinds = [s.reducer for s in steps if s.reducer != "set_floor"]
    assert kinds[:3] == ["post_goal", "post_need", "open_round"]
    assert kinds.index("place_bid") < kinds.index("attach_verdict") < kinds.index("close_round")
    tail = kinds[kinds.index("close_round") + 1:]
    assert tail == ["attach_verdict", "create_mandate", "record_approval", "record_payment", "record_payment"]


def test_each_reducer_is_called_by_the_role_it_demands(steps):
    allowed = {"post_goal": "buyer", "post_need": "buyer", "open_round": "referee", "close_round": "referee",
               "attach_verdict": "referee", "attach_claim_check": "referee", "create_mandate": "referee",
               "record_approval": "referee", "record_payment": "referee"}
    for s in steps:
        if s.reducer in ("set_floor", "place_bid"):
            assert s.actor.startswith("seller:")
        else:
            assert s.actor == allowed[s.reducer], s.reducer
    # a seller only ever bids as itself
    for s in steps:
        if s.reducer == "set_floor" or s.reducer == "place_bid":
            assert s.args.get("id", "").replace("bid-need-tony-stark-5070ti-", "") in ("", s.actor.split(":")[1])


def test_goal_and_need_are_tony_starks_and_withhold_nothing_new(steps):
    goal = steps[0].args
    assert goal["buyer_id"] == "joe" and goal["cap"] == 1300 and goal["origin"] == "SIM"
    assert goal["items"][0]["condition"] == "new or open-box"
    assert any(i["skipped_owned_part_id"] == "owned-psu" for i in goal["items"])
    need = steps[1].args
    assert need["spend_limit"] == 1300 and need["items"][0]["sku_spec"] == "rtx 5070 ti" and len(need["items"]) == 1
    assert "Tony Stark" in steps[0].say


def test_bids_carry_origin_picked_line_and_floor(run, steps):
    bids = {s.args["id"]: s for s in steps if s.reducer == "place_bid"}
    assert len(bids) == len(run["beats"]["2"]["bids"])
    best = bids["bid-need-tony-stark-5070ti-best-buy"].args
    assert best["origin"] == "MIRROR" and best["lines"][0]["unit_price"] == 1249.99
    assert best["lines"][0]["offered_condition"] == "new" and best["source"].startswith("https://www.bestbuy.com")
    sim = bids["bid-need-tony-stark-5070ti-shady-sam"].args
    assert sim["origin"] == "SIM"
    gg = bids["bid-need-tony-stark-5070ti-gadget-grove"].args     # two alternative lines in the demo, the picked one is placed
    assert len(gg["lines"]) == 1 and gg["lines"][0]["offered_condition"] == "open-box" and gg["lines"][0]["unit_price"] == 1247.02
    floors = {s.actor: s.args["floor"] for s in steps if s.reducer == "set_floor"}
    assert floors["seller:lowball"] > 1090.0          # the referee floor rejection is the market's, not ours
    lowball = bids["bid-need-tony-stark-5070ti-lowball"].args
    assert lowball["lines"][0]["unit_price"] < floors["seller:lowball"]


def test_shield_and_claim_results_come_from_the_real_run(run, steps):
    verdicts = [s.args for s in steps if s.reducer == "attach_verdict"]
    assert not any(v["bid_id"].endswith("lowball") for v in verdicts[:-1])    # a floor-rejected bid is never screened
    assert verdicts[-1]["verdict"] == "block" and verdicts[-1]["bid_id"].endswith("shady-sam")
    assert "shield.payee.swap" in verdicts[-1]["rule_ids"]
    claims = [s.args for s in steps if s.reducer == "attach_claim_check"]
    assert any(c["check"] == "false" and c["bid_id"].endswith("shady-sam") for c in claims)
    assert all(c["check"] in ("verified", "unverified", "false") for c in claims)


def test_money_steps_use_the_demos_real_mandate(run, steps):
    m = run["beats"]["4"]["mandate"]
    mand = next(s for s in steps if s.reducer == "create_mandate").args
    assert mand["hash"] == m["hash"] and mand["amount"] == 1249.99 and mand["payee"] == m["payee"]
    assert mand["buyer_id"] == "joe" and mand["requested_by"] == ""
    appr = next(s for s in steps if s.reducer == "record_approval").args
    assert appr == {"mandate_hash": m["hash"], "method": "voice_code", "approved_by": "joe"}
    pays = [s.args for s in steps if s.reducer == "record_payment"]
    assert len(pays) == 2 and pays[0] == pays[1] and pays[0]["payment_ref"] == run["beats"]["4"]["charge"]["id"]


def test_round_window_covers_the_paced_steps(steps):
    op = next(s for s in steps if s.reducer == "open_round")
    paused = sum(s.pace for s in steps[2:] if s.pause and s.reducer not in ("create_mandate", "record_approval", "record_payment"))
    assert op.window_s >= 2 * (paused - 3) and op.window_s >= bridge.MIN_WINDOW_S


def test_round_two_has_distinct_bid_ids_and_a_lower_learner_price(run):
    s2 = bridge.plan(run, delay=2.0, rounds=2)
    ids = [s.args["id"] for s in s2 if s.reducer == "place_bid"]
    assert len(ids) == len(set(ids)) and any(i.endswith("-r2") for i in ids)
    p1 = next(s.args for s in s2 if s.reducer == "place_bid" and s.args["id"].endswith("gadget-grove"))["lines"][0]["unit_price"]
    p2 = next(s.args for s in s2 if s.reducer == "place_bid" and s.args["id"].endswith("gadget-grove-r2"))["lines"][0]["unit_price"]
    assert p2 < p1


def test_execute_calls_in_order_paces_and_waits_for_the_deadline(steps):
    log, sleeps, now = [], [], [100.0]
    def sleep(x):
        sleeps.append(x)
        now[0] += x
    bridge.execute(steps, clients(log), delay=2.0, say=lambda s: None, sleep=sleep, clock=lambda: now[0])
    assert [(a, r) for a, r, _ in log] == [(s.actor, s.reducer) for s in steps]
    paced = [x for x in sleeps if x == 2.0]
    assert len(paced) == sum(1 for s in steps if s.pause)
    assert now[0] - 100.0 >= next(s.window_s for s in steps if s.window_s) - 1   # it reached the deadline before closing


def test_close_retries_while_the_round_is_still_open_and_accepts_already_closed(steps):
    log = []
    fail = {"close_round": ["round is still open until its deadline", "round already closed"]}
    sleeps = []
    bridge.execute(steps, clients(log, fail), delay=0, say=lambda s: None, sleep=sleeps.append, clock=lambda: 0.0)
    assert [r for _, r, _ in log].count("close_round") == 2 and 1.0 in sleeps
    assert log[-1][1] == "record_payment"


def test_a_refused_reducer_stops_the_run(steps):
    log = []
    with pytest.raises(RuntimeError, match="not allowed"):
        bridge.execute(steps, clients(log, {"post_need": ["not allowed: post_need"]}), delay=0, say=lambda s: None, sleep=lambda x: None)
    assert [r for _, r, _ in log] == ["post_goal", "post_need"]


def test_divergence_is_reported_when_the_market_ranks_a_vetoed_bid_first(run):
    rows = [[1, "round-1", "b1", "bargain-bin", "Bargain Bin Hardware (SIM)", 1, 1199.0], [2, "round-1", "b2", "best-buy", "Best Buy", 2, 1249.99],
            [3, "round-1", "b3", "shady-sam", "Shady Sam's Deals (SIM)", 0, 757.44]]
    out = bridge.compare_to_db(rows, run)
    assert "#1 Bargain Bin Hardware (SIM) $1,199.00" in out[0] and "DIVERGENCE" in out[1]
    rows[0][5], rows[1][5] = 2, 1
    assert "agree" in bridge.compare_to_db(rows, run)[1]


def test_not_bridged_list_names_every_gap_and_no_secret():
    text = " ".join(bridge.NOT_BRIDGED)
    for word in ("advocate veto", "allowed_conditions", "loss reports", "set_goal_state", "set_allowance", "footer"):
        assert word in text
    assert "token" not in text.lower()
