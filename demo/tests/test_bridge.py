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
    assert kinds[:4] == ["post_goal", "set_allowance", "post_need", "open_round"]
    assert kinds.index("place_bid") < kinds.index("attach_verdict") < kinds.index("attach_advocate_card") < kinds.index("close_round")
    tail = kinds[kinds.index("close_round") + 1:]
    assert tail == ["attach_verdict", "create_mandate", "record_approval", "record_payment", "record_payment"]


def test_each_reducer_is_called_by_the_role_it_demands(steps):
    allowed = {"post_goal": "buyer", "post_need": "buyer", "set_allowance": "referee", "open_round": "referee", "close_round": "referee",
               "attach_verdict": "referee", "attach_claim_check": "referee", "attach_advocate_card": "referee", "create_mandate": "referee",
               "record_approval": "referee", "record_payment": "referee"}
    for s in steps:
        if s.reducer in ("set_floor", "place_bid"):
            assert s.actor.startswith("seller:")
        else:
            assert s.actor == allowed[s.reducer], s.reducer
    # a seller only ever bids as itself
    for s in steps:
        if s.reducer == "set_floor" or s.reducer == "place_bid":
            assert s.args.get("id", "").replace("bid-need-vidyut-5070ti-", "") in ("", s.actor.split(":")[1])


def test_vidyuts_demo_allowance_is_set_by_the_referee_right_after_the_goal(run, steps):
    a = run["beats"]["1"]["allowance"]
    step = next(s for s in steps if s.reducer == "set_allowance")
    assert step.actor == "referee" and steps.index(step) == 1 and steps[0].reducer == "post_goal"
    assert step.args == {"buyer_id": "vidyut", "per_purchase_limit": a["per_purchase_limit"], "period_limit": a["period_limit"], "period": a["period"]}
    assert (a["per_purchase_limit"], a["period_limit"]) == (250.0, 500.0)
    # the deal is still above it, so it still needs the call
    assert next(s for s in steps if s.reducer == "create_mandate").args["amount"] > step.args["per_purchase_limit"]
    assert [s.reducer for s in steps].count("set_allowance") == 1


def test_goal_and_need_are_vidyuts_and_withhold_nothing_new(steps):
    goal = steps[0].args
    assert goal["buyer_id"] == "vidyut" and goal["cap"] == 1300 and goal["origin"] == "SIM"
    assert goal["items"][0]["condition"] == "new or open-box"
    assert any(i["skipped_owned_part_id"] == "owned-psu" for i in goal["items"])
    need = steps[2].args
    assert need["spend_limit"] == 1300 and need["items"][0]["sku_spec"] == "rtx 5070 ti" and len(need["items"]) == 1
    assert need["items"][0]["condition"] == "new" and need["items"][0]["allowed_conditions"] == ["new", "open-box"]
    assert "Vidyut" in steps[0].say


def test_bids_carry_origin_picked_line_and_floor(run, steps):
    bids = {s.args["id"]: s for s in steps if s.reducer == "place_bid"}
    assert len(bids) == len(run["beats"]["2"]["bids"])
    best = bids["bid-need-vidyut-5070ti-best-buy"].args
    assert best["origin"] == "MIRROR" and best["lines"][0]["unit_price"] == 1249.99
    assert best["lines"][0]["offered_condition"] == "new" and best["source"].startswith("https://www.bestbuy.com")
    sim = bids["bid-need-vidyut-5070ti-shady-sam"].args
    assert sim["origin"] == "SIM"
    gg = bids["bid-need-vidyut-5070ti-gadget-grove"].args     # two alternative lines: BOTH are placed, the market picks one
    assert [(l["offered_condition"], l["unit_price"]) for l in gg["lines"]] == [("new", 1315.27), ("open-box", 1247.02)]
    assert gg["stated_total"] == 1247.02 and gg["source"].startswith("https://example.com/sim/gadget-grove")
    floors = {s.actor: s.args["floor"] for s in steps if s.reducer == "set_floor"}
    assert floors["seller:lowball"] > 1090.0          # the referee floor rejection is the market's, not ours
    assert floors["seller:gadget-grove"] == 1190.0    # one floor per SKU: the lowest of its two condition lines
    lowball = bids["bid-need-vidyut-5070ti-lowball"].args
    assert lowball["lines"][0]["unit_price"] < floors["seller:lowball"]


def test_shield_and_claim_results_come_from_the_real_run(run, steps):
    verdicts = [s.args for s in steps if s.reducer == "attach_verdict"]
    assert not any(v["bid_id"].endswith("lowball") for v in verdicts[:-1])    # a floor-rejected bid is never screened
    assert verdicts[-1]["verdict"] == "block" and verdicts[-1]["bid_id"].endswith("shady-sam")
    assert "shield.payee.swap" in verdicts[-1]["rule_ids"]
    claims = [s.args for s in steps if s.reducer == "attach_claim_check"]
    assert any(c["check"] == "false" and c["bid_id"].endswith("shady-sam") for c in claims)
    assert all(c["check"] in ("verified", "unverified", "false") for c in claims)


def test_advocate_cards_are_the_real_cards_and_every_veto_cites_its_source(run, steps):
    cards = [s.args for s in steps if s.reducer == "attach_advocate_card"]
    assert len(cards) == len(run["beats"]["2"]["cards"])
    by = {c["bid_id"].replace("bid-need-vidyut-5070ti-", ""): c for c in cards}
    assert by["shady-sam"]["recommendation"] == "veto" and by["shady-sam"]["rule_id"] == "advocate.condition"
    assert by["shady-sam"]["source_url"].endswith("shady-sam-gpu-5070ti-lies.html")
    assert by["bargain-bin"]["recommendation"] == "veto" and by["bargain-bin"]["rule_id"] == "fit.gpu_length"
    assert by["best-buy"]["recommendation"] == "caution"
    assert all(c["source_url"] and c["text"] for c in cards if c["recommendation"] == "veto")
    kinds = [s.reducer for s in steps]
    last_card = max(i for i, s in enumerate(steps) if s.reducer == "attach_advocate_card")
    assert last_card < kinds.index("close_round")                    # a card must land before the close to count


def test_round_two_cards_use_round_two_bid_ids(run):
    s2 = bridge.plan(run, delay=2.0, rounds=2)
    cards = [s.args["bid_id"] for s in s2 if s.reducer == "attach_advocate_card"]
    assert len(cards) == 2 * len(run["beats"]["2"]["cards"]) and sum(c.endswith("-r2") for c in cards) == len(cards) // 2


def test_payment_mode_follows_the_charge(run, steps):
    pays = [s for s in steps if s.reducer == "record_payment"]
    assert run["beats"]["4"]["charge"]["mode"] == "SIM stub"
    assert [p.args["mode"] for p in pays] == ["sim", "sim"] and pays[0].tag == bridge.SIM
    live = {**run, "beats": {**run["beats"], "4": {**run["beats"]["4"], "charge": {**run["beats"]["4"]["charge"], "mode": "Stripe test mode"}}}}
    lp = [s for s in bridge.plan(live) if s.reducer == "record_payment"]
    assert [p.args["mode"] for p in lp] == ["stripe_test", "stripe_test"] and lp[0].tag == "LIVE"


def test_money_steps_use_the_demos_real_mandate(run, steps):
    m = run["beats"]["4"]["mandate"]
    mand = next(s for s in steps if s.reducer == "create_mandate").args
    assert mand["hash"] == m["hash"] and mand["amount"] == 1249.99 and mand["payee"] == m["payee"]
    assert mand["buyer_id"] == "vidyut" and mand["requested_by"] == ""
    appr = next(s for s in steps if s.reducer == "record_approval").args
    assert appr == {"mandate_hash": m["hash"], "method": "voice_code", "approved_by": "vidyut"}
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
    assert [r for _, r, _ in log] == ["post_goal", "set_allowance", "post_need"]


def test_divergence_is_reported_when_the_market_ranks_another_bid_first(run):
    rows = [[1, "round-1", "b1", "bargain-bin", "Bargain Bin Hardware (SIM)", 1, 1199.0], [2, "round-1", "b2", "best-buy", "Best Buy", 2, 1249.99],
            [3, "round-1", "b3", "shady-sam", "Shady Sam's Deals (SIM)", 0, 757.44, ["Advocate veto (advocate.condition: x) [source: u]"]]]
    out = bridge.compare_to_db(rows, run)
    assert "#1 Bargain Bin Hardware (SIM) $1,199.00" in out[0] and any("DIVERGENCE" in line for line in out)
    assert any(line.startswith("market OUT: Shady Sam") and "Advocate veto" in line for line in out)
    rows[0][5], rows[1][5] = 2, 1
    assert "agree" in bridge.compare_to_db(rows, run)[-1]


def test_not_bridged_list_names_every_gap_and_no_secret():
    text = " ".join(bridge.NOT_BRIDGED)
    for word in ("loss reports", "set_goal_state", "floors per condition"):
        assert word in text
    for fixed in ("buyer allowance", "set_allowance", "advocate veto", "allowed_conditions", "alternative lines", "goal cap", "payment label", "footer"):
        assert fixed not in text, f"{fixed} is bridged now"
    assert "token" not in text.lower()


# ---------------------------------------------------------------- T7: --live-call (a fake Cartesia client, no network)

from pay.mandate import can_charge  # noqa: E402
from pay.replay import NonceStore  # noqa: E402
from pay.voice_cartesia import CartesiaClient, CartesiaError  # noqa: E402

TO = "+14155550123"


class FakeCartesia:
    """Stands in for pay.voice_cartesia.CartesiaClient: one number, scripted answers, never a socket."""
    approval_call_to = TO

    def __init__(self, says):
        self.says, self.calls, self.shown = says, [], {}

    def create_call(self, to_number, variables):
        assert to_number == TO
        self.calls.append((to_number, dict(variables)))
        return "call_1"

    def get_call(self, call_id):
        said = self.says(self.shown.get("code")) if callable(self.says) else self.says
        entries = [{"role": "assistant", "text": "Hello Vidyut, one purchase for you.", "start_timestamp": 0.0}]
        if said:
            entries.append({"role": "user", "text": said, "start_timestamp": 6.0})
        return {"status": "completed", "end_reason": "client_hangup", "transcript": entries}


def live_parts(run, says):
    mandate = bridge.fresh_pending_mandate(run["beats"]["4"]["mandate"])
    client = FakeCartesia(says)
    shown = []

    def show(code):
        client.shown["code"] = code
        shown.append(code)

    approver = bridge.make_live_approver(mandate, {"rule_id": "advocate.ok", "summary": "No problems found in the checks",
                                                   "source_url": "https://example.com/x"},
                                         client, buyer_name="Vidyut", on_code=show, secret="s" * 32,
                                         sleep=lambda x: None, poll=0)
    return mandate, client, shown, approver


def run_with(run, approver, mandate):
    log = []
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, mandate=mandate, live_call=True), clients(log), delay=0, say=lambda s: None, sleep=lambda x: None,
                              clock=lambda: 0.0, approver=approver)
    return log, outcomes


def test_live_plan_uses_the_fresh_pending_mandate_and_marks_the_approval_gate(run):
    old = run["beats"]["4"]["mandate"]
    fresh = bridge.fresh_pending_mandate(old)
    assert fresh["status"] == "pending" and fresh["hash"] != old["hash"]
    assert (fresh["deal_id"], fresh["amount"], fresh["payee"], fresh["buyer_id"]) == (old["deal_id"], old["amount"], old["payee"], old["buyer_id"])
    s = bridge.plan(run, delay=0, rounds=1, mandate=fresh, live_call=True)
    assert next(x for x in s if x.reducer == "create_mandate").args["hash"] == fresh["hash"]
    assert [x.args["mandate_hash"] for x in s if x.reducer in ("record_approval", "record_payment")] == [fresh["hash"]] * 3
    assert [x.gate for x in s if x.gate] == ["approval_call"]
    assert "third try" not in next(x for x in s if x.reducer == "record_approval").say     # the sim story is not told over a real call


def test_without_live_call_the_plan_is_unchanged(run, steps):
    assert [(s.actor, s.reducer, s.args) for s in bridge.plan(run, delay=2.0, rounds=1)] == [(s.actor, s.reducer, s.args) for s in steps]


def test_live_call_approved_places_one_call_and_records_approval_then_payment(run):
    mandate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    log, outcomes = run_with(run, approver, mandate)
    assert len(client.calls) == 1 and client.calls[0][0] == TO                       # exactly one call, to the configured number
    assert len(shown) == 1 and all(shown[0] not in str(v) for v in client.calls[0][1].values())   # the code is on screen only
    tail = [r for _, r, _ in log][[r for _, r, _ in log].index("create_mandate"):]
    assert tail == ["create_mandate", "record_approval", "record_payment", "record_payment"]
    assert outcomes[0]["approved"] is True and outcomes[0]["call_id"] == "call_1"
    assert mandate["status"] == "approved"


def test_the_code_judged_is_the_code_shown(run):
    from demo.approval_flow import _wrong_pair
    mandate, client, shown, approver = live_parts(run, lambda code: f"{_wrong_pair(code)} approve")   # two code words that are not the code
    log, outcomes = run_with(run, approver, mandate)
    assert shown and outcomes[0]["approved"] is False
    assert not any(r in ("record_approval", "record_payment") for _, r, _ in log)


def test_denied_call_records_the_denial_and_no_payment_step(run):
    mandate, client, shown, approver = live_parts(run, "hello there")                        # no code word, no approve
    log, outcomes = run_with(run, approver, mandate)
    kinds = [r for _, r, _ in log]
    assert "create_mandate" in kinds and "record_approval" not in kinds and "record_payment" not in kinds
    assert outcomes[0]["approved"] is False and outcomes[0]["reason"] and outcomes[0]["step"] == "approval_call"
    assert mandate["status"] != "approved"
    assert not can_charge(mandate, deal_id=mandate["deal_id"], amount=mandate["amount"], payee=mandate["payee"],
                          store=NonceStore())


def test_silence_on_the_call_denies(run):
    mandate, client, shown, approver = live_parts(run, "")
    log, outcomes = run_with(run, approver, mandate)
    assert outcomes[0]["approved"] is False and "record_payment" not in [r for _, r, _ in log]


def test_not_configured_denies_without_placing_a_call(run):
    mandate = bridge.fresh_pending_mandate(run["beats"]["4"]["mandate"])
    approver = bridge.make_live_approver(mandate, None, None, unconfigured="missing CARTESIA_API_KEY", buyer_name="Vidyut",
                                         on_code=lambda c: pytest.fail("no code is issued when nothing can be called"))
    log, outcomes = run_with(run, approver, mandate)
    assert outcomes == [{"step": "approval_call", "approved": False, "reason": "not_configured: missing CARTESIA_API_KEY", "call_id": None}]
    kinds = [r for _, r, _ in log]
    assert "create_mandate" in kinds and "record_approval" not in kinds and "record_payment" not in kinds


def test_a_failed_dial_denies(run):
    class Down(FakeCartesia):
        def create_call(self, to_number, variables):
            raise CartesiaError("call could not start")
    mandate = bridge.fresh_pending_mandate(run["beats"]["4"]["mandate"])
    approver = bridge.make_live_approver(mandate, None, Down(""), buyer_name="Vidyut", on_code=lambda c: None, secret="s" * 32,
                                         sleep=lambda x: None, poll=0)
    log, outcomes = run_with(run, approver, mandate)
    assert outcomes[0]["approved"] is False and outcomes[0]["reason"] == "call_failed"
    assert "record_payment" not in [r for _, r, _ in log]


def test_an_expired_mandate_is_denied_even_if_the_buyer_said_the_code(run):
    mandate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    mandate["expires_at"] = "2020-01-01T00:00:00Z"
    log, outcomes = run_with(run, approver, mandate)
    assert outcomes[0]["approved"] is False and client.calls == []
    assert "record_payment" not in [r for _, r, _ in log]


def test_live_call_flags_and_refusals(capsys):
    with pytest.raises(SystemExit):
        bridge.main(["--live-call", "--stripe", "--dry-run"])        # a Stripe charge must never run before the call approves
    assert bridge.main(["--dry-run", "--live-call", "--env-file", "/nonexistent/none.env"]) == 0
    out = capsys.readouterr().out
    assert "live call" in out.lower() and "CARTESIA" in out


def test_the_screen_code_gap_is_listed():
    assert "approval code" in " ".join(bridge.NOT_BRIDGED)


# ---------------------------------------------------------------- --two-buyers (T11): a second buyer after the same single units

@pytest.fixture(scope="module")
def two(run):
    return bridge.plan(run, delay=2.0, rounds=1, two_buyers=True)


def test_two_buyers_off_leaves_the_plan_untouched(run, steps):
    assert [(s.actor, s.reducer, s.args) for s in bridge.plan(run, delay=2.0, rounds=1, two_buyers=False)] == [(s.actor, s.reducer, s.args) for s in steps]
    assert not any(s.actor == bridge.SECOND_ACTOR for s in steps)


def test_the_second_buyer_comes_after_vidyuts_payment_and_acts_only_as_buyer_2(two, steps):
    n = len(steps)
    assert [(s.actor, s.reducer, s.args) for s in two[:n]] == [(s.actor, s.reducer, s.args) for s in steps]   # Vidyut's story is unchanged
    extra = two[n:]
    mine = [s for s in extra if s.actor == bridge.SECOND_ACTOR]
    assert [s.reducer for s in mine] == ["post_goal", "post_need"]
    assert {s.args["buyer_id"] for s in mine} == {"buyer-2"}
    assert mine[1].args["goal_id"] == mine[0].args["id"] and mine[0].args["id"] != next(s for s in steps if s.reducer == "post_goal").args["id"]
    assert extra[-1].reducer == "close_round" and extra[-1].actor == "referee"


def test_the_second_round_is_its_own_round_for_its_own_need_with_one_unit_per_seller(run, two):
    first = [s for s in two if s.reducer == "open_round"]
    assert len(first) == 2 and first[1].args["need_id"].endswith("buyer-2") and first[1].args["round_id"] != first[0].args["round_id"]
    need_qty = next(s for s in two if s.reducer == "post_need" and s.actor == bridge.SECOND_ACTOR).args["items"][0]["quantity"]
    bids = [s for s in two if s.reducer == "place_bid" and s.args["round_id"] == first[1].args["round_id"]]
    assert {s.actor.split(":")[1] for s in bids} == {b["seller_id"] for b in run["beats"]["2"]["bids"]}   # the same sellers
    for s in bids:
        assert all(l["quantity"] == need_qty for l in s.args["lines"])         # one unit in stock each, so a held unit cannot be re-awarded
    ids = [s.args["id"] for s in two if s.reducer == "place_bid"]
    assert len(ids) == len(set(ids))


def test_with_round_two_the_second_buyer_gets_round_three(run):
    s = bridge.plan(run, delay=0, rounds=2, two_buyers=True)
    assert [x.args["round_id"] for x in s if x.reducer == "open_round"] == ["round-1", "round-2", "round-3"]


def test_second_buyer_report_names_the_sold_out_seller_and_the_new_winner():
    rows = [
        [1, "round-2", "b-a", "seller-a", "Best Buy", 0, 1299.99, ["sold out to an earlier round"]],
        [2, "round-2", "b-b", "seller-b", "Gadget Grove", 1, 1319.0, []],
        [3, "round-1", "b-c", "seller-a", "Best Buy", 1, 1299.99, []],
    ]
    out = bridge.second_buyer_report(rows, "round-2")
    assert out == ["buyer-2's round: Best Buy is out: sold out to an earlier round", "buyer-2's round winner: Gadget Grove $1,319.00"]
    assert bridge.second_buyer_report([], "round-2") == ["buyer-2's round: no bid was ranked"]


def test_a_denied_live_call_releases_the_held_unit(run):
    mandate, client, shown, approver = live_parts(run, "hello there")
    log, outcomes = run_with(run, approver, mandate)
    denies = [(who, args) for who, r, args in log if r == "deny_approval"]
    assert outcomes[0]["approved"] is False
    assert [(who, a["mandate_hash"]) for who, a in denies] == [("referee", mandate["hash"])]


def test_an_approved_call_never_denies(run):
    mandate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    log, _ = run_with(run, approver, mandate)
    assert "deny_approval" not in [r for _, r, _ in log]


def test_a_market_without_deny_approval_does_not_crash_the_denied_run(run):
    mandate, client, shown, approver = live_parts(run, "")
    log = []
    cl = clients(log, fail={"deny_approval": ["no such reducer"]})
    notes = []
    bridge.execute(bridge.plan(run, delay=0, rounds=1, mandate=mandate, live_call=True), cl, delay=0, say=lambda s: None, sleep=lambda x: None,
                   clock=lambda: 0.0, approver=approver, note=notes.append)
    assert any("deny_approval not recorded" in n for n in notes)


def test_two_buyers_dry_run_prints_the_second_buyer(capsys):
    assert bridge.main(["--dry-run", "--two-buyers"]) == 0
    out = capsys.readouterr().out
    assert "buyer2" in out and "second buyer" in out
