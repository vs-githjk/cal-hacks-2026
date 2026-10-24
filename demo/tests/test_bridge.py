"""The screen bridge: demo run -> reducer calls. A fake client records calls, no network, no sleeping."""
from __future__ import annotations

import pytest

from demo import bridge
from demo.common import Narrator


@pytest.fixture(scope="module")
def run():
    from demo.run_demo import run_all
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
    closes = [i for i, kind in enumerate(kinds) if kind == "close_round"]
    assert kinds.index("place_bid") < closes[0] < kinds.index("attach_verdict") < kinds.index("attach_advocate_card") < closes[1]
    assert kinds[closes[1] + 1:] == ["create_mandate"]


def test_each_reducer_is_called_by_the_role_it_demands(steps):
    allowed = {"post_goal": "buyer", "post_need": "buyer", "open_round": "referee", "close_round": "referee",
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


def test_goal_and_need_are_vidyuts_and_withhold_nothing_new(steps):
    goal = steps[0].args
    assert goal["buyer_id"] == "vidyut" and goal["cap"] == 1300 and goal["origin"] == "SIM"
    assert goal["items"][0]["condition"] == "new or open-box"
    assert any(i["skipped_owned_part_id"] == "owned-psu" for i in goal["items"])
    need = steps[1].args
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
    assert len(verdicts) == len(run["beats"]["2"]["shield"])
    assert {(v["bid_id"], v["verdict"]) for v in verdicts} == {
        (bridge.bid_id(next(b for b in run["beats"]["2"]["bids"] if b["id"] == v["bid_id"]), 1), v["verdict"])
        for v in run["beats"]["2"]["shield"]}
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
    closes = [i for i, kind in enumerate(kinds) if kind == "close_round"]
    assert closes[0] < last_card < closes[1]                          # cards bind during the review window


def test_round_two_cards_use_round_two_bid_ids(run):
    s2 = bridge.plan(run, delay=2.0, rounds=2)
    cards = [s.args["bid_id"] for s in s2 if s.reducer == "attach_advocate_card"]
    assert len(cards) == 2 * len(run["beats"]["2"]["cards"]) and sum(c.endswith("-r2") for c in cards) == len(cards) // 2


def test_local_approval_and_payment_are_never_written_to_market(steps):
    assert not any(s.reducer in ("record_approval", "record_payment") for s in steps)


def test_money_steps_use_the_demos_real_mandate(run, steps):
    m = run["beats"]["4"]["mandate"]
    mand = next(s for s in steps if s.reducer == "create_mandate").args
    assert mand["hash"] == m["hash"] and mand["amount"] == 1249.99 and mand["payee"] == m["payee"]
    assert mand["buyer_id"] == "vidyut" and mand["requested_by"] == ""
    assert mand["goal_id"] == run["beats"]["1"]["goal"]["id"]
    assert mand["need_id"] == run["beats"]["1"]["need"]["id"]
    assert mand["expiry_minutes"] == 10


def test_round_window_covers_the_paced_steps(steps):
    op = next(s for s in steps if s.reducer == "open_round")
    paused = sum(s.pace for s in steps[2:] if s.pause and s.reducer not in ("close_round", "create_mandate"))
    assert op.window_s >= 2 * (paused - 3) and op.window_s >= bridge.MIN_WINDOW_S


def test_round_two_has_distinct_bid_ids_and_a_lower_learner_price(run):
    s2 = bridge.plan(run, delay=2.0, rounds=2)
    ids = [s.args["id"] for s in s2 if s.reducer == "place_bid"]
    assert len(ids) == len(set(ids)) and any(i.endswith("-r2") for i in ids)
    p1 = next(s.args for s in s2 if s.reducer == "place_bid" and s.args["id"].endswith("gadget-grove"))["lines"][0]["unit_price"]
    p2 = next(s.args for s in s2 if s.reducer == "place_bid" and s.args["id"].endswith("gadget-grove-r2"))["lines"][0]["unit_price"]
    assert p2 < p1


def test_execute_calls_in_order_paces_and_waits_for_the_deadline():
    log, sleeps, now = [], [], [100.0]
    def sleep(x):
        sleeps.append(x)
        now[0] += x
    steps = [bridge.Step("buyer", "post_goal", pause=True), bridge.Step("referee", "open_round", window_s=13, pause=True),
             bridge.Step("referee", "close_round", close=True)]
    bridge.execute(steps, {"buyer": Fake(log, "buyer"), "referee": Fake(log, "referee")}, delay=2.0,
                   say=lambda s: None, sleep=sleep, clock=lambda: now[0])
    assert [(a, r) for a, r, _ in log] == [(s.actor, s.reducer) for s in steps]
    paced = [x for x in sleeps if x == 2.0]
    assert len(paced) == sum(1 for s in steps if s.pause)
    assert now[0] - 100.0 >= next(s.window_s for s in steps if s.window_s) - 1   # it reached the deadline before closing


def test_close_retries_while_the_round_is_still_open_and_accepts_already_closed():
    log = []
    fail = {"close_round": ["round is still open until its deadline", "round already closed"]}
    sleeps = []
    bridge.execute([bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True)],
                   {"referee": Fake(log, "referee", fail)}, delay=0, say=lambda s: None,
                   sleep=sleeps.append, clock=lambda: 0.0)
    assert [r for _, r, _ in log].count("close_round") == 2 and 1.0 in sleeps
    assert log[-1][1] == "close_round"


def test_a_refused_reducer_stops_the_run():
    log = []
    with pytest.raises(RuntimeError, match="not allowed"):
        bridge.execute([bridge.Step("buyer", "post_goal"), bridge.Step("buyer", "post_need")],
                       {"buyer": Fake(log, "buyer", {"post_need": ["not allowed: post_need"]})},
                       delay=0, say=lambda s: None, sleep=lambda x: None)
    assert [r for _, r, _ in log] == ["post_goal", "post_need"]


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
    for word in ("loss reports", "record_loss_report", "create_mandate", "HOLD_FOR_CALL", "ambiguous evidence URLs are skipped",
                 "set_allowance", "floors per condition"):
        assert word in text
    for fixed in ("no table or reducer", "goal stays ACTIVE", "advocate veto", "allowed_conditions", "alternative lines", "goal cap", "payment label", "footer"):
        assert fixed not in text, f"{fixed} is bridged now"
    assert "token" not in text.lower()


def _gate_run():
    line = {"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1.0, "offered_condition": "new",
            "listing_url": "https://example.test/gpu", "listing_id": "fixture-1", "listing_hash": "a" * 64, "origin": "SIM",
            "attrs": {}, "basis": "fixture", "shipping": 0.0}
    bid = {"id": "bid-1", "seller_id": "seller-a", "origin": "SIM", "source": "fixture",
           "total_landed_price": 10.0, "lines": [line]}
    return {"beats": {
        "1": {"goal": {"id": "goal-1"}, "need": {"id": "need-1", "items": [{"sku_spec": "gpu", "quantity": 1}]}},
        "2": {"winner": {"bid_id": "bid-1", "seller_id": "seller-a", "line": 0, "landed": 10.0},
              "winner_bid": bid},
        "4": {"mandate": {"amount": 10.0}},
    }}


class GateBridge:
    def __init__(self, log, winner):
        self.log, self.winner = log, winner

    def review_candidates(self, round_id):
        self.log.append(("review_candidates", round_id))
        return [{"round_id": round_id, "need_id": "need-1", "bid_id": "bid-1", "binding_hash": "b" * 64,
                 "line_metadata": [{"lineIndex": 0, "listingId": "fixture-1", "listingHash": "a" * 64}],
                 "lines": [{"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1.0, "line_index": 0,
                            "listing_id": "fixture-1", "listing_hash": "a" * 64}]}]

    def attach_advocate_card(self, **args):
        self.log.append(("attach_advocate_card", args))

    def attach_claim_check(self, **args):
        self.log.append(("attach_claim_check", args))

    def authoritative_winner(self, round_id, need_items):
        self.log.append(("authoritative_winner", round_id, need_items))
        return self.winner


def test_stripe_is_rejected_before_local_demo_runs(monkeypatch, capsys):
    import sys
    from types import ModuleType

    called = []
    run_demo = ModuleType("demo.run_demo")
    run_demo.run_all = lambda **kwargs: called.append("run_all")
    monkeypatch.setitem(sys.modules, "demo.run_demo", run_demo)

    assert bridge.main(["--stripe"]) == 2
    assert called == []
    assert "verified checkout evidence" in capsys.readouterr().out
    with pytest.raises(SystemExit) as help_exit:
        bridge.main(["--help"])
    assert help_exit.value.code == 0
    help_text = capsys.readouterr().out
    assert "disabled pending verified checkout evidence" in help_text
    assert "winner verification precedes every charge" not in help_text


def test_round_mapping_publishes_exact_metadata_and_defers_bound_reviews():
    import hashlib
    import json

    line = {"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1, "offered_condition": "new", "shipping": 0.0,
            "listing_url": "https://example.test/gpu", "listing_id": "fixture-1", "origin": "SIM",
            "attrs": {"model": "gpu"}, "basis": "SIM fixture"}
    bid = {"id": "bid-1", "seller_id": "seller-a", "persona": "Seller A", "origin": "SIM", "lines": [line],
           "total_landed_price": 10.0, "perks": [], "claims": []}
    steps = bridge.round_steps(round_no=1, need_id="need-1", bids=[bid],
                               ranking={"ranked": [{"seller_id": "seller-a", "line": 0}], "disqualified": []},
                               sellers={"seller-a": {"lines": [{"floor": 1}]}},
                               shield=[{"bid_id": "bid-1", "verdict": "allow", "rule_ids": []}],
                               claims={"bid-1": [{"text": "new", "check": "verified", "evidence_url": line["listing_url"],
                                                  "origin": "SIM"}]},
                               cards=[{"bid_id": "bid-1", "recommendation": "buy",
                                       "call_reason": {"rule_id": "ok", "summary": "ok", "source_url": line["listing_url"]}}],
                               delay=0, pace=1)
    bid_step = next(step for step in steps if step.reducer == "place_bid")
    expected_hash = hashlib.sha256(json.dumps(line, sort_keys=True, separators=(",", ":"),
                                               ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert bid_step.args["line_metadata"][0]["listingHash"] == expected_hash
    assert bid_step.args["line_metadata"][0]["listingId"] == "fixture-1"
    closes = [i for i, step in enumerate(steps) if step.reducer == "close_round"]
    cards = [i for i, step in enumerate(steps) if step.reducer == "attach_advocate_card"]
    assert closes[0] < cards[0] < closes[1]
    assert not any(step.pause for step in steps if step.reducer in ("attach_verdict", "attach_claim_check", "attach_advocate_card"))


def test_mirror_listing_hash_comes_from_the_captured_snapshot_record():
    import hashlib
    import json
    from pathlib import Path

    snapshot = next((Path(bridge.ROOT) / "data" / "mirror" / "snapshots").glob("bestbuy*.json"))
    card = json.loads(snapshot.read_text(encoding="utf-8"))[0]
    line = {"listing_id": card["id"], "listing_url": card["source"], "origin": "MIRROR",
            "snapshot_id": card["snapshot_id"], "attrs": card["attrs"], "shipping": 0.0}
    digest = hashlib.sha256(json.dumps(card, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    metadata = bridge._line_metadata({"lines": [line], "total_landed_price": 1.0})
    assert metadata[0]["listingHash"] == digest


def test_missing_mirror_snapshot_hash_fails_closed():
    line = {"listing_id": "missing-listing", "listing_url": "https://example.test/missing", "origin": "MIRROR",
            "snapshot_id": "missing-snapshot", "attrs": {}, "shipping": 0.0}
    with pytest.raises(RuntimeError, match="listing hash is unavailable"):
        bridge._line_metadata({"lines": [line], "total_landed_price": 1.0})


def test_missing_line_shipping_fails_closed():
    line = {"listing_id": "fixture-1", "listing_url": "https://example.test/gpu", "origin": "SIM",
            "attrs": {}, "unit_price": 10.0, "quantity": 1}
    with pytest.raises(RuntimeError, match="shipping metadata is unavailable"):
        bridge._line_metadata({"lines": [line], "total_landed_price": 12.0})


def test_seller_shipping_is_read_from_the_real_seller_fixture():
    from demo.sellers import all_sellers

    seller = next(s for s in all_sellers()[0] if s.id == "gadget-grove")
    assert bridge._seller_shipping("gadget-grove") == seller.shipping


def test_place_bid_maps_demo_id_to_market_bridge_bid_id():
    from agents.market_bridge import MarketBridge
    import inspect

    assert "bid_id" in inspect.signature(MarketBridge.publish_bid).parameters
    log = []

    class SellerBridge:
        def publish_bid(self, *, bid_id, round_id, seller_id, **kwargs):
            log.append((bid_id, round_id, seller_id, kwargs))

    step = bridge.Step("seller:seller-a", "place_bid", {"id": "bid-1", "round_id": "round-1",
                      "seller_id": "seller-a", "persona": "Seller A", "lines": [], "line_metadata": []})
    bridge.execute([step], {step.actor: Fake(log, step.actor)}, bridges={step.actor: SellerBridge()},
                   delay=0, say=lambda _: None)
    assert log[0][:3] == ("bid-1", "round-1", "seller-a")


def test_review_line_metadata_uses_original_index_for_alternative_line():
    log, now = [], [0.0]

    class AlternativeBridge(GateBridge):
        def review_candidates(self, round_id):
            return [{"round_id": round_id, "need_id": "need-1", "bid_id": "bid-1", "binding_hash": "b" * 64,
                     "line_metadata": [{"lineIndex": 1, "listingId": "fixture-2", "listingHash": "c" * 64}],
                     "lines": [{"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1.0, "line_index": 1,
                                "listing_id": "fixture-2", "listing_hash": "c" * 64}]}]

    steps = [bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True, review=True),
             bridge.Step("referee", "attach_advocate_card", {"bid_id": "bid-1", "recommendation": "buy",
                         "rule_id": "ok", "text": "ok", "source_url": "url", "origin": "SIM"})]
    bridge.execute(steps, {"referee": Fake(log, "referee")}, bridges={"referee": AlternativeBridge(log, None)},
                   run=_gate_run(), delay=0, say=lambda _: None, sleep=lambda x: None, clock=lambda: now[0])
    assert any(entry[0] == "attach_advocate_card" for entry in log)


def test_claim_check_binds_only_to_claims_original_listing_line():
    line0 = {"sku_spec": "gpu", "unit_price": 12.0, "quantity": 1, "offered_condition": "new",
             "listing_url": "https://example.test/new", "listing_id": "listing-new", "listing_hash": "a" * 64,
             "origin": "SIM", "shipping": 0.0, "attrs": {}}
    line1 = {"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1, "offered_condition": "open-box",
             "listing_url": "https://example.test/open", "listing_id": "listing-open", "listing_hash": "b" * 64,
             "origin": "SIM", "shipping": 0.0, "attrs": {}}
    bid = {"id": "bid-1", "seller_id": "seller-a", "persona": "Gadget Grove", "origin": "SIM",
           "lines": [line0, line1], "total_landed_price": 10.0, "perks": [], "claims": []}
    claims = [{"text": "New, retail box", "check": "false", "evidence_url": line0["listing_url"], "origin": "SIM"},
              {"text": "Open-box, retail box", "check": "false", "evidence_url": line1["listing_url"], "origin": "SIM"}]
    steps = bridge.round_steps(round_no=1, need_id="need-1", bids=[bid],
                               ranking={"ranked": [{"seller_id": "seller-a", "line": 1}], "disqualified": []},
                               sellers={"seller-a": {"lines": [{"floor": 1}]}}, shield=[],
                               claims={"bid-1": claims}, cards=[], delay=0, pace=1)
    check_args = [step.args for step in steps if step.reducer == "attach_claim_check"]
    assert [(item["claim"], item["line_index"], item["listing_id"], item["listing_hash"])
            for item in check_args] == [("Open-box, retail box", 1, "listing-open", "b" * 64)]
    log, now = [], [0.0]
    candidate_bridge = GateBridge(log, None)
    candidate_bridge.review_candidates = lambda round_id: [{"round_id": round_id, "need_id": "need-1", "bid_id": "bid-1",
        "binding_hash": "b" * 64, "line_metadata": [
            {"lineIndex": 0, "listingId": "listing-new", "listingHash": "a" * 64},
            {"lineIndex": 1, "listingId": "listing-open", "listingHash": "b" * 64}],
        "lines": [{"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1.0, "line_index": 1,
                   "listing_id": "listing-open", "listing_hash": "b" * 64}]}]
    review_steps = [bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True, review=True),
                    bridge.Step("referee", "attach_claim_check", check_args[0]),
                    bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True)]
    bridge.execute(review_steps, {"referee": Fake(log, "referee")}, bridges={"referee": candidate_bridge},
                   run=_gate_run(), delay=0, say=lambda _: None, sleep=lambda _: None, clock=lambda: now[0])
    attached = next(entry[1] for entry in log if entry[0] == "attach_claim_check")
    assert (attached["line_index"], attached["listing_id"], attached["listing_hash"]) == (1, "listing-open", "b" * 64)

    ambiguous_bid = {**bid, "lines": [line0, {**line1, "listing_url": line0["listing_url"]}]}
    ambiguous = bridge.round_steps(round_no=1, need_id="need-1", bids=[ambiguous_bid],
                                   ranking={"ranked": [{"seller_id": "seller-a", "line": 1}], "disqualified": []},
                                   sellers={"seller-a": {"lines": [{"floor": 1}]}}, shield=[],
                                   claims={"bid-1": claims}, cards=[], delay=0, pace=1)
    assert not any(step.reducer == "attach_claim_check" for step in ambiguous)


def test_published_gadget_grove_claims_each_have_the_selected_line_check_without_divergence(run):
    b2 = run["beats"]["2"]
    bid = next(bid for bid in b2["bids"] if bid["seller_id"] == "gadget-grove")
    selected_index = bridge._entries(b2["ranking"])["gadget-grove"]["line"]
    steps = bridge.plan(run, delay=0)
    publish = next(step for step in steps if step.reducer == "place_bid" and step.args["id"] == bid["id"])
    checks = [step.args for step in steps if step.reducer == "attach_claim_check" and step.args["bid_id"] == bid["id"]]

    assert publish.args["claims"] == [check["claim"] for check in checks]
    assert publish.args["claims"]
    assert all((check["line_index"], check["listing_id"], check["listing_hash"])
               == (selected_index, bid["lines"][selected_index].get("listing_id")
                   or bid["lines"][selected_index]["listing_url"],
                   bridge._line_metadata(bid, seller_shipping=bridge._seller_shipping("gadget-grove"))[selected_index]["listingHash"])
               for check in checks)

    winner = b2["winner"]
    rows = [[1, "round-1", winner["bid_id"], winner["seller_id"], "local selected winner", 1, winner["landed"]]]
    assert not any("DIVERGENCE" in line for line in bridge.compare_to_db(rows, run))


def test_plan_binds_mandate_to_goal_and_need_and_has_no_synthetic_approval_or_payment():
    goal = {"id": "goal-1", "type": "build", "cap": 10.0, "deadline": "2026-10-25",
            "items": [{"part": "gpu", "sku_spec": "gpu", "condition": "new", "allowed_conditions": ["new"],
                       "variant": "model", "quantity": 1}]}
    need = {"id": "need-1", "delivery_window": "soon", "spend_limit": 10.0, "consent": True,
            "auction_window_s": 8, "items": [{"sku_spec": "gpu", "condition": "new", "allowed_conditions": ["new"],
                                                "variant": "model", "quantity": 1, "unit": "item"}]}
    line = {"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1, "offered_condition": "new",
            "listing_url": "https://example.test/gpu", "listing_id": "fixture-1", "listing_hash": "a" * 64,
            "origin": "SIM", "attrs": {}, "basis": "fixture", "shipping": 0.0}
    bid = {"id": "bid-1", "seller_id": "seller-a", "persona": "Seller A", "origin": "SIM", "source": "fixture",
           "lines": [line], "total_landed_price": 10.0, "perks": [], "claims": []}
    run = {"beats": {
        "1": {"goal": goal, "goal_text": "goal", "need": need},
        "2": {"sellers": [{"id": "seller-a", "name": "Seller A", "lines": [{"floor": 1}]}], "bids": [bid],
              "ranking": {"ranked": [{"seller_id": "seller-a", "bid_id": "bid-1", "line": 0}],
                          "disqualified": []}, "shield": [], "claims": {},
              "cards": [{"bid_id": "bid-1", "recommendation": "buy",
                         "call_reason": {"rule_id": "ok", "summary": "ok", "source_url": line["listing_url"]}}],
              "winner": {"bid_id": "bid-1", "seller_id": "seller-a", "line": 0, "landed": 10.0},
              "winner_bid": bid},
        "4": {"mandate": {"id": "m1", "hash": "h1", "deal_id": "d1", "amount": 10.0, "payee": "seller-a",
                          "nonce": "n1", "origin": "SIM"}},
    }}
    steps = bridge.plan(run, delay=0)
    mandate = next(step.args for step in steps if step.reducer == "create_mandate")
    assert (mandate["goal_id"], mandate["need_id"]) == ("goal-1", "need-1")
    assert not any(step.reducer in ("record_approval", "record_payment") for step in steps)


def test_mandate_waits_for_review_bound_checks_final_close_and_exact_market_winner():
    log, now = [], [0.0]
    client = Fake(log, "referee")
    winner = {"round_id": "round-1", "bid_id": "bid-1", "seller_id": "seller-a", "landed": 10.0,
              "landed_cents": 1000, "lines": [{"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1.0,
                "original_line_index": 0, "listing_id": "fixture-1", "listing_hash": "a" * 64, "shipping": 0.0}],
              "origin": "SIM", "source": "https://example.test/gpu", "binding_hash": "b" * 64}
    db = {"referee": GateBridge(log, winner), "buyer": GateBridge(log, winner)}
    steps = [bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True, review=True),
             bridge.Step("referee", "attach_advocate_card", {"bid_id": "bid-1", "recommendation": "buy",
                         "rule_id": "ok", "text": "ok", "source_url": "https://example.test/gpu", "origin": "SIM"}),
             bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True),
             bridge.Step("referee", "create_mandate", {"hash": "h", "goal_id": "goal-1", "need_id": "need-1",
                         "_round_id": "round-1"})]
    bridge.execute(steps, {"referee": client}, bridges=db, run=_gate_run(), delay=0, say=lambda step: None,
                   sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), clock=lambda: now[0])

    actions = [entry[1] if entry[0] == "referee" else entry[0] for entry in log]
    closes = [i for i, action in enumerate(actions) if action == "close_round"]
    assert closes[0] < actions.index("review_candidates") < actions.index("attach_advocate_card") < closes[1]
    assert actions.index("attach_advocate_card") < closes[1] < actions.index("authoritative_winner")
    assert "create_mandate" in actions
    assert all(reducer not in actions for reducer in ("record_approval", "record_payment"))


def test_claim_check_uses_review_binding_and_original_selected_line():
    log = []
    referee_bridge = GateBridge(log, None)
    steps = [bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True, review=True),
             bridge.Step("referee", "attach_claim_check", {"bid_id": "bid-1", "claim": "new",
                         "check": "unverified", "evidence_url": "https://example.test/gpu", "origin": "SIM",
                         "line_index": 0, "listing_id": "fixture-1", "listing_hash": "a" * 64}),
             bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True)]
    now = [0.0]
    bridge.execute(steps, {"referee": Fake(log, "referee")}, bridges={"referee": referee_bridge},
                   run=_gate_run(), delay=0, say=lambda step: None,
                   sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), clock=lambda: now[0])
    evidence = next(entry[1] for entry in log if entry[0] == "attach_claim_check")
    assert evidence["binding_hash"] == "b" * 64
    assert (evidence["line_index"], evidence["listing_id"], evidence["listing_hash"]) == (0, "fixture-1", "a" * 64)


@pytest.mark.parametrize("change", [None, {"bid_id": "other"}, {"landed_cents": 1001},
                                     {"binding_hash": "c" * 64}, {"lines": [{"sku_spec": "gpu", "unit_price": 10.0,
                                      "quantity": 1.0, "original_line_index": 0, "listing_id": "fixture-1",
                                      "listing_hash": "c" * 64, "shipping": 0.0}]}])
def test_missing_or_mismatched_market_winner_stops_before_mandate_or_money(change):
    log = []
    winner = {"round_id": "round-1", "bid_id": "bid-1", "seller_id": "seller-a", "landed": 10.0,
              "landed_cents": 1000, "lines": [{"sku_spec": "gpu", "unit_price": 10.0, "quantity": 1.0,
                "original_line_index": 0, "listing_id": "fixture-1", "listing_hash": "a" * 64, "shipping": 0.0}],
              "origin": "SIM", "source": "https://example.test/gpu", "binding_hash": "b" * 64}
    if change is None:
        winner = None
    else:
        winner.update(change)
    steps = [bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True, review=True),
             bridge.Step("referee", "close_round", {"round_id": "round-1"}, close=True),
             bridge.Step("referee", "create_mandate", {"hash": "h", "need_id": "need-1", "_round_id": "round-1"}),
             bridge.Step("referee", "record_approval", {"mandate_hash": "h"}),
             bridge.Step("referee", "record_payment", {"mandate_hash": "h"})]
    with pytest.raises(RuntimeError, match="winner"):
        bridge.execute(steps, {"referee": Fake(log, "referee")}, bridges={"buyer": GateBridge(log, winner),
                       "referee": GateBridge(log, winner)}, run=_gate_run(), delay=0, say=lambda step: None,
                       sleep=lambda _: None, clock=lambda: 0.0)
    reducers = [entry[1] for entry in log if len(entry) == 3 and entry[0] == "referee"]
    assert "create_mandate" not in reducers
    assert "record_approval" not in reducers and "record_payment" not in reducers
