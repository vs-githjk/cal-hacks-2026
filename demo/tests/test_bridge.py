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
    def __init__(self, log, name, fail=None, rows=None):
        self.log, self.name, self.fail, self.rows = log, name, fail or {}, rows

    def call(self, reducer, **args):
        self.log.append((self.name, reducer, args))
        if reducer in self.fail:
            raise RuntimeError(self.fail[reducer].pop(0) if self.fail[reducer] else "ok")

    def sql(self, query):
        assert query == "SELECT * FROM round_result"
        if self.rows is None:
            raise RuntimeError("no round_result in this fake")
        return self.rows() if callable(self.rows) else self.rows


def market_rows(run, first="best-buy", second="gadget-grove"):
    """round_result rows as the market returns them (id, round_id, bid_id, seller_id, persona, rank, landed, reasons)."""
    b2 = run["beats"]["2"]
    bids = {b["seller_id"]: b for b in b2["bids"]}
    landed = {e["seller_id"]: e["landed"] for e in b2["ranking"]["ranked"]}
    return [(1, "round-1", bids[first]["id"], first, bids[first]["persona"], 1, landed[first], []),
            (2, "round-1", bids[second]["id"], second, bids[second]["persona"], 2, landed[second], [])]


def clients(log, fail=None, rows="market"):
    r = run_all(say=Narrator(False))
    names = ["buyer", "referee"] + sorted({s.actor for s in bridge.plan(r) if s.actor.startswith("seller:")})
    rows = market_rows(r) if rows == "market" else rows
    return {n: Fake(log, n, fail, rows) for n in names}


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
    assert best["origin"] == "MIRROR" and best["lines"][0]["unit_price"] == 1299.99
    assert best["lines"][0]["offered_condition"] == "new" and best["source"].startswith("https://www.bestbuy.com")
    sim = bids["bid-need-vidyut-5070ti-shady-sam"].args
    assert sim["origin"] == "SIM"
    gg = bids["bid-need-vidyut-5070ti-gadget-grove"].args     # two alternative lines: BOTH are placed, the market picks one
    assert [(l["offered_condition"], l["unit_price"]) for l in gg["lines"]] == [("new", 1315.27), ("open-box", 1286.02)]
    assert gg["stated_total"] == 1286.02 and gg["source"].startswith("https://example.com/sim/gadget-grove")
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
    assert by["best-buy"]["recommendation"] == "buy"                # ASUS Prime, 304 mm in a 305 mm case
    assert all(c["source_url"] and c["text"] for c in cards if c["recommendation"] == "veto")
    kinds = [s.reducer for s in steps]
    last_card = max(i for i, s in enumerate(steps) if s.reducer == "attach_advocate_card")
    assert last_card < kinds.index("close_round")                    # a card must land before the close to count


def test_round_two_cards_use_round_two_bid_ids(run):
    s2 = bridge.plan(run, delay=2.0, rounds=2)
    cards = [s.args["bid_id"] for s in s2 if s.reducer == "attach_advocate_card"]
    assert len(cards) == 2 * len(run["beats"]["2"]["cards"]) and sum(c.endswith("-r2") for c in cards) == len(cards) // 2


def test_a_scripted_approval_never_records_a_live_payment(run, steps):
    """#193: without a real call the plan's payment is the SIM stub, even if the run's beat 4 made a Stripe test charge."""
    pays = [s for s in steps if s.reducer == "record_payment"]
    assert run["beats"]["4"]["charge"]["mode"] == "SIM stub"
    assert [p.args["mode"] for p in pays] == ["sim", "sim"] and pays[0].tag == bridge.SIM
    live = {**run, "beats": {**run["beats"], "4": {**run["beats"]["4"], "charge": {**run["beats"]["4"]["charge"], "mode": "Stripe test mode",
                                                                                        "id": "pi_test_scripted"}}}}
    lp = [s for s in bridge.plan(live) if s.reducer == "record_payment"]
    assert [p.args["mode"] for p in lp] == ["sim", "sim"] and lp[0].tag == bridge.SIM
    assert all(p.args["payment_ref"].startswith("ch_sim_") for p in lp) and "pi_test_scripted" not in lp[0].say


def test_a_scripted_approval_is_labelled_sim_script_not_voice(steps):
    appr = next(s for s in steps if s.reducer == "record_approval")
    assert appr.args["method"] == "sim_script" and appr.tag == bridge.SIM
    assert "no phone call" in appr.say


def test_money_steps_use_the_demos_real_mandate(run, steps):
    m = run["beats"]["4"]["mandate"]
    mand = next(s for s in steps if s.reducer == "create_mandate").args
    assert mand["hash"] == m["hash"] and mand["amount"] == 1299.99 and mand["payee"] == m["payee"]
    assert mand["buyer_id"] == "vidyut" and mand["requested_by"] == ""
    appr = next(s for s in steps if s.reducer == "record_approval").args
    assert appr == {"mandate_hash": m["hash"], "method": "sim_script", "approved_by": "vidyut"}
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
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False      # a market without approve_typed (#191): the code may go to /buyer
    client = FakeCartesia(says)
    shown = []

    def show(code, why_not):
        client.shown["code"] = code
        shown.append((code, why_not))

    approver = bridge.make_live_approver(gate, client, buyer_name="Vidyut", on_code=show, secret="s" * 32, sleep=lambda x: None, poll=0)
    return gate, client, shown, approver


def run_with(run, approver, gate, rows="market", fail=None):
    log = []
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), clients(log, fail, rows), delay=0, say=lambda s: None,
                              sleep=lambda x: None, clock=lambda: 0.0, approver=approver, deal_gate=gate)
    return log, outcomes


def test_live_plan_marks_the_mandate_and_approval_gates(run):
    s = bridge.plan(run, delay=0, rounds=1, live_call=True)
    assert [(x.reducer, x.gate) for x in s if x.gate] == [("create_mandate", "build_mandate"), ("record_approval", "approval_call")]
    assert "third try" not in next(x for x in s if x.reducer == "record_approval").say     # the sim story is not told over a real call
    assert next(x for x in s if x.reducer == "create_mandate").args["expiry_minutes"] == bridge.MANDATE_MINUTES == 10


def test_the_gate_builds_a_fresh_pending_mandate_from_the_markets_rank_one(run):
    old = run["beats"]["4"]["mandate"]
    gate = bridge.DealGate(run)
    m = gate.prepare(Fake([], "referee", rows=market_rows(run)))
    assert m["status"] == "pending" and m["hash"] != old["hash"]
    assert (m["deal_id"], m["amount"], m["payee"], m["buyer_id"]) == (old["deal_id"], old["amount"], old["payee"], old["buyer_id"])
    steps = [gate.bind(x) for x in bridge.plan(run, delay=0, rounds=1, live_call=True)]
    assert next(x for x in steps if x.reducer == "create_mandate").args["hash"] == m["hash"]
    assert [x.args["mandate_hash"] for x in steps if x.reducer in ("record_approval", "record_payment")] == [m["hash"]] * 3
    assert all(x.args["amount"] == m["amount"] and x.args["payment_ref"] == "ch_sim_" + m["hash"][:12] for x in steps if x.reducer == "record_payment")


def test_h5_the_bridge_pays_the_markets_number_one_not_the_demos_winner(run):
    """#194 H5: the market ranks Gadget Grove first; the mandate, the approval and the payment all name Gadget Grove."""
    rows = market_rows(run, first="gadget-grove", second="best-buy")
    gg = next(x for x in run["beats"]["2"]["sellers"] if x["id"] == "gadget-grove")
    for live in (False, True):
        gate = bridge.DealGate(run)
        log = []
        approver = None
        if live:
            _, client, _, _ = live_parts(run, lambda code: f"{code} approve")
            approver = bridge.make_live_approver(gate, client, buyer_name="Vidyut",
                                                 on_code=lambda code, why: client.shown.update(code=code), secret="s" * 32,
                                                 sleep=lambda x: None, poll=0)
        outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=live), clients(log, rows=rows), delay=0,
                                  say=lambda s: None, sleep=lambda x: None, clock=lambda: 0.0, approver=approver, deal_gate=gate)
        made = next(a for _, r, a in log if r == "create_mandate")
        assert made["payee"] == gg["payee"] and made["deal_id"] == f"deal-{rows[0][2]}" and made["amount"] == rows[0][6]
        assert all(a["mandate_hash"] == made["hash"] for _, r, a in log if r in ("record_approval", "record_payment"))
        assert "record_payment" in [r for _, r, _ in log] and all(o["approved"] for o in outcomes)


@pytest.mark.parametrize("rows", [[], None, "unknown", "two-firsts"])
def test_no_readable_market_rank_one_makes_no_mandate_and_pays_nothing(run, rows):
    if rows == "unknown":
        rows = [(1, "round-1", "bid-x", "someone-else", "Nobody", 1, 999.0, [])]
    elif rows == "two-firsts":
        rows = market_rows(run)
        rows = [rows[0], (*rows[1][:5], 1, *rows[1][6:])]
    log = []
    gate = bridge.DealGate(run)
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1), clients(log, rows=rows), delay=0, say=lambda s: None,
                              sleep=lambda x: None, clock=lambda: 0.0, deal_gate=gate)
    kinds = [r for _, r, _ in log]
    assert outcomes[-1]["step"] == "build_mandate" and outcomes[-1]["approved"] is False
    assert not any(k in kinds for k in ("create_mandate", "record_approval", "record_payment"))


def test_can_charge_after_the_call_compares_with_the_market_not_the_mandate(run):
    """#194 H5: after the call the market is read again; a rank 1 that no longer matches the mandate denies."""
    rows = [market_rows(run)]
    gate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    real = client.get_call

    def get_call(call_id):            # while the call runs, the market's rank 1 moves to another seller
        rows[0] = market_rows(run, first="gadget-grove", second="best-buy")
        return real(call_id)
    client.get_call = get_call
    log, outcomes = run_with(run, approver, gate, rows=lambda: rows[0])
    assert outcomes[0]["approved"] is False and outcomes[0]["reason"].startswith("can_charge")
    assert "record_payment" not in [r for _, r, _ in log]


def test_the_code_goes_to_buyer_through_issue_approval_code_and_is_not_printed(run):
    gate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    log, outcomes = run_with(run, approver, gate)
    issued = [(who, a) for who, r, a in log if r == "issue_approval_code"]
    assert outcomes[0]["approved"] is True
    assert issued == [("referee", {"mandate_hash": gate.mandate["hash"], "code": shown[0][0]})] and shown[0][1] is None
    kinds = [r for _, r, _ in log]
    assert kinds.index("create_mandate") < kinds.index("issue_approval_code") < kinds.index("record_approval")


def test_the_code_stays_off_buyer_while_the_market_has_typed_approval(run, tmp_path):
    """#211 review: issue_approval_code arms the market's approve_typed, so the code never goes to /buyer while it exists."""
    gate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    gate.typed_approval_present = lambda: True
    log, outcomes = run_with(run, approver, gate)
    assert "issue_approval_code" not in [r for _, r, _ in log]
    assert "approve_typed" in shown[0][1] and outcomes[0]["approved"] is True       # the call still judges the same code
    with_typed, without, missing = tmp_path / "a.ts", tmp_path / "b.ts", tmp_path / "none.ts"
    with_typed.write_text("export const approve_typed = spacetimedb.reducer(")
    without.write_text("export const issue_approval_code = spacetimedb.reducer(")
    assert bridge.market_has_typed_approval(with_typed) and not bridge.market_has_typed_approval(without)
    assert bridge.market_has_typed_approval(missing)                                  # unreadable: fail closed
    assert bridge.DealGate(run).typed_approval_present is bridge.market_has_typed_approval


def test_a_refused_issue_approval_code_falls_back_to_the_console_and_says_why(run):
    gate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    run_with(run, approver, gate, fail={"issue_approval_code": ["no such reducer"]})
    assert shown[0][1] and "issue_approval_code refused" in shown[0][1]


def test_live_approver_for_prints_the_code_only_when_buyer_could_not_show_it(run, capsys, monkeypatch):
    import argparse
    seen = {}

    def spy(g, client, **kw):
        seen.update(kw)
        return lambda step: None
    monkeypatch.setattr(bridge, "make_live_approver", spy)
    bridge.live_approver_for(argparse.Namespace(env_file="/nonexistent/none.env"), run, bridge.DealGate(run), Narrator(True))
    seen["on_code"]("alpha bravo", None)
    seen["on_code"]("charlie delta", "issue_approval_code refused (x)")
    text = capsys.readouterr().out
    assert "alpha bravo" not in text and "on /buyer now" in text
    assert "SCREEN CODE: charlie delta" in text


def test_without_live_call_the_plan_is_unchanged(run, steps):
    assert [(s.actor, s.reducer, s.args) for s in bridge.plan(run, delay=2.0, rounds=1)] == [(s.actor, s.reducer, s.args) for s in steps]


def test_live_call_approved_places_one_call_and_records_approval_then_payment(run):
    gate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    log, outcomes = run_with(run, approver, gate)
    assert len(client.calls) == 1 and client.calls[0][0] == TO                       # exactly one call, to the configured number
    assert len(shown) == 1 and all(shown[0][0] not in str(v) for v in client.calls[0][1].values())   # the code is on screen only
    tail = [r for _, r, _ in log][[r for _, r, _ in log].index("create_mandate"):]
    assert tail == ["create_mandate", "issue_approval_code", "record_approval", "record_payment", "record_payment"]
    assert outcomes[0]["approved"] is True and outcomes[0]["call_id"] == "call_1"
    assert gate.mandate["status"] == "approved"


def test_the_code_judged_is_the_code_shown(run):
    from demo.approval_flow import _wrong_pair
    gate, client, shown, approver = live_parts(run, lambda code: f"{_wrong_pair(code)} approve")   # two code words that are not the code
    log, outcomes = run_with(run, approver, gate)
    assert shown and outcomes[0]["approved"] is False
    assert not any(r in ("record_approval", "record_payment") for _, r, _ in log)


def test_denied_call_records_the_denial_and_no_payment_step(run):
    gate, client, shown, approver = live_parts(run, "hello there")                        # no code word, no approve
    log, outcomes = run_with(run, approver, gate)
    kinds = [r for _, r, _ in log]
    assert "create_mandate" in kinds and "record_approval" not in kinds and "record_payment" not in kinds
    assert outcomes[0]["approved"] is False and outcomes[0]["reason"] and outcomes[0]["step"] == "approval_call"
    mandate = gate.mandate
    assert mandate["status"] != "approved"
    assert not can_charge(mandate, deal_id=mandate["deal_id"], amount=mandate["amount"], payee=mandate["payee"],
                          store=NonceStore())


def test_silence_on_the_call_denies(run):
    gate, client, shown, approver = live_parts(run, "")
    log, outcomes = run_with(run, approver, gate)
    assert outcomes[0]["approved"] is False and "record_payment" not in [r for _, r, _ in log]


def test_not_configured_denies_without_placing_a_call(run):
    gate = bridge.DealGate(run)
    approver = bridge.make_live_approver(gate, None, unconfigured="missing CARTESIA_API_KEY", buyer_name="Vidyut",
                                         on_code=lambda c, w: pytest.fail("no code is issued when nothing can be called"))
    log, outcomes = run_with(run, approver, gate)
    assert outcomes == [{"step": "approval_call", "approved": False, "reason": "not_configured: missing CARTESIA_API_KEY", "call_id": None}]
    kinds = [r for _, r, _ in log]
    assert "create_mandate" in kinds and "record_approval" not in kinds and "record_payment" not in kinds


def test_a_failed_dial_denies(run):
    class Down(FakeCartesia):
        def create_call(self, to_number, variables):
            raise CartesiaError("call could not start")
    gate = bridge.DealGate(run)
    approver = bridge.make_live_approver(gate, Down(""), buyer_name="Vidyut", on_code=lambda c, w: None, secret="s" * 32,
                                         sleep=lambda x: None, poll=0)
    log, outcomes = run_with(run, approver, gate)
    assert outcomes[0]["approved"] is False and outcomes[0]["reason"] == "call_failed"
    assert "record_payment" not in [r for _, r, _ in log]


def test_an_expired_mandate_is_denied_even_if_the_buyer_said_the_code(run):
    gate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    real = gate.prepare

    def expired(referee):
        m = real(referee)
        m["expires_at"] = "2020-01-01T00:00:00Z"
        return m
    gate.prepare = expired
    log, outcomes = run_with(run, approver, gate)
    assert outcomes[0]["approved"] is False and client.calls == []
    assert "record_payment" not in [r for _, r, _ in log]


def test_live_call_flags_and_refusals(capsys):
    assert bridge.main(["--dry-run", "--live-call", "--env-file", "/nonexistent/none.env"]) == 0
    out = capsys.readouterr().out
    assert "live call" in out.lower() and "CARTESIA" in out


def test_stripe_without_a_live_call_is_refused(monkeypatch):
    """#193: a Stripe test charge needs a real call; the scripted approval can never lead to one."""
    from demo import approval_flow
    monkeypatch.setattr(approval_flow, "stripe_charge_test", lambda *a, **k: pytest.fail("no Stripe call without a live call"))
    with pytest.raises(SystemExit):
        bridge.main(["--stripe", "--dry-run"])
    with pytest.raises(SystemExit):
        bridge.main(["--stripe"])


def test_live_call_with_stripe_makes_no_charge_before_the_round(monkeypatch, capsys):
    """#193: the run that builds the plan never charges; the Stripe call waits behind the approval gate."""
    from demo import approval_flow
    monkeypatch.setattr(approval_flow, "stripe_charge_test", lambda *a, **k: pytest.fail("charged before the call"))
    monkeypatch.setenv(approval_flow.STRIPE_ENV, "sk_test_FAKEKEY1234567890")
    assert bridge.main(["--dry-run", "--live-call", "--stripe", "--env-file", "/nonexistent/none.env"]) == 0
    out = capsys.readouterr().out
    assert "after the call approves" in out and "sk_test_FAKEKEY1234567890" not in out


def stripe_parts(run, says, key="sk_test_FAKEKEY1234567890"):
    gate, client, shown, approver = live_parts(run, says)
    charged = []

    def fake_stripe(m, k):
        charged.append((m["hash"], k))
        return {"mode": "Stripe test mode", "id": "pi_test_1", "object": "payment_intent", "amount_cents": int(round(m["amount"] * 100)),
                "currency": "usd", "payment_method": "pm_card_visa (Stripe test card)", "status": "succeeded",
                "idempotency_key": "mandate:" + m["hash"]}
    notes = []
    charger = bridge.make_charger(gate, {"STRIPE_SECRET_KEY": key}, use_stripe=True, stripe_test=fake_stripe)
    return gate, approver, charger, charged, notes


def run_with_charger(run, approver, gate, charger, order=None):
    log = []
    cl = clients(log)
    if order is not None:
        real = charger

        def charger(step):
            order.append(("charge", [r for _, r, _ in log]))
            return real(step)
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), cl, delay=0, say=lambda s: None,
                              sleep=lambda x: None, clock=lambda: 0.0, approver=approver, charger=charger, deal_gate=gate)
    return log, outcomes


def test_live_call_with_stripe_charges_once_only_after_the_market_records_the_approval(run):
    gate, approver, charger, charged, _ = stripe_parts(run, lambda code: f"{code} approve")
    order = []
    log, outcomes = run_with_charger(run, approver, gate, charger, order)
    mandate = gate.mandate
    assert outcomes[0]["approved"] is True and charged == [(mandate["hash"], "sk_test_FAKEKEY1234567890")]
    before = order[0][1]
    assert "record_approval" in before and "record_payment" not in before        # approval row first, then the charge
    pays = [a for _, r, a in log if r == "record_payment"]
    assert len(pays) == 2 and all(p["mode"] == "stripe_test" and p["payment_ref"] == "pi_test_1" and p["mandate_hash"] == mandate["hash"]
                                  for p in pays)
    appr = next(a for _, r, a in log if r == "record_approval")
    assert appr["method"] == "voice_code"                                          # a real call is the only voice approval


def test_a_denied_or_silent_live_call_never_charges(run):
    for says in ("hello there", ""):
        gate, approver, charger, charged, _ = stripe_parts(run, says)
        log, outcomes = run_with_charger(run, approver, gate, charger)
        assert outcomes[0]["approved"] is False and charged == []
        assert "record_payment" not in [r for _, r, _ in log]


def test_the_charger_never_runs_without_an_approver(run):
    """Fail closed: a charger handed to execute without a live-call gate is ignored, and the SIM stub is what gets recorded."""
    gate, _, charger, charged, _ = stripe_parts(run, "")
    log = []
    bridge.execute(bridge.plan(run, delay=0, rounds=1), clients(log), delay=0, say=lambda s: None, sleep=lambda x: None,
                   clock=lambda: 0.0, approver=None, charger=charger)
    assert charged == [] and all(a["mode"] == "sim" for _, r, a in log if r == "record_payment")


def test_charger_without_a_test_key_records_the_sim_stub_and_says_why(run):
    gate = bridge.DealGate(run)
    gate.prepare(Fake([], "referee", rows=market_rows(run)))
    charger = bridge.make_charger(gate, {"STRIPE_SECRET_KEY": "sk_live_notatestkey"}, use_stripe=True,
                                  stripe_test=lambda *a: pytest.fail("never with a live key"))
    paid = charger(None)
    assert paid["args"]["mode"] == "sim" and paid["tag"] == bridge.SIM and paid["args"]["payment_ref"].startswith("ch_sim_")
    assert "is not an sk_test_ key" in paid["note"] and "sk_live_notatestkey" not in str(paid)


def test_the_screen_code_gap_is_closed():
    assert "approval code" not in " ".join(bridge.NOT_BRIDGED)          # #194: issue_approval_code puts it on /buyer


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
    gate, client, shown, approver = live_parts(run, "hello there")
    log, outcomes = run_with(run, approver, gate)
    denies = [(who, args) for who, r, args in log if r == "deny_approval"]
    assert outcomes[0]["approved"] is False
    assert [(who, a["mandate_hash"]) for who, a in denies] == [("referee", gate.mandate["hash"])]


def test_an_approved_call_never_denies(run):
    gate, client, shown, approver = live_parts(run, lambda code: f"{code} approve")
    log, _ = run_with(run, approver, gate)
    assert "deny_approval" not in [r for _, r, _ in log]


def test_a_market_without_deny_approval_does_not_crash_the_denied_run(run):
    gate, client, shown, approver = live_parts(run, "")
    log = []
    cl = clients(log, fail={"deny_approval": ["no such reducer"]})
    notes = []
    bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), cl, delay=0, say=lambda s: None, sleep=lambda x: None,
                   clock=lambda: 0.0, approver=approver, note=notes.append, deal_gate=gate)
    assert any("deny_approval not recorded" in n for n in notes)


def test_two_buyers_dry_run_prints_the_second_buyer(capsys):
    assert bridge.main(["--dry-run", "--two-buyers"]) == 0
    out = capsys.readouterr().out
    assert "buyer2" in out and "second buyer" in out
