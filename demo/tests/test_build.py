"""#345 phase 1: a full build in the market. A fake market stands in for SpacetimeDB (it applies the rules the real one applies at
the points this run touches: floors out of scope, advocate vetoes and cautions at the close, rank 1 only for a mandate, the allowance
rule on create_mandate, no payment without an approval). A fake Cartesia stands in for the call and a fake fetch for Bright Data:
no network, no live call, no database."""
from __future__ import annotations

import json
import threading
import time

import pytest

from demo import build
from demo.common import MIRROR, SIM
from demo.build_sim import FakeMarket, make_clients  # noqa: F401
from demo.sellers import Line, Seller
from demo.tests.test_bridge import FakeCartesia


def kinds(m):
    return [r for _, r, _ in m.log]


def calls(m, reducer):
    return [a for _, r, a in m.log if r == reducer]


def seller(sid, name, price, origin=SIM, url=None, length=303, snap=""):
    url = url or f"https://example.com/sim/{sid}"
    line = Line("new", price, round(price * 0.9, 2), url, origin, page_condition="new", attrs={"category": "gpu", "length_mm": length},
                basis="test", snapshot_date=snap)
    return Seller(sid, name, origin, [line], 0.0, 30, payee=f"{sid}@pay.example.test", shipping_captured=True, claims=[])


def sim_catalog(spec, index):
    return build.default_catalog(spec, index, mirror=False, trap=False)


def run_build(m=None, *, allowance=None, cartesia="default", says=None, tmp_path=None, catalog=sim_catalog, plan=None, real_gpu=False, **kw):
    m = m or FakeMarket()
    notes, shown = [], {}
    if cartesia == "default":
        cartesia = FakeCartesia(says if says is not None else (lambda code: f"{code} approve"))
    if cartesia is not None and not hasattr(cartesia, "shown"):
        cartesia.shown = {}

    def on_code(code):
        cartesia.shown["code"] = code
    r = build.BuildRun(plan or build.demo_plan(), make_clients(m), catalog=catalog, allowance=allowance, cartesia=cartesia, real_gpu_round=real_gpu,
                       secret="s" * 32, out_dir=tmp_path, note=notes.append, sleep=lambda x: None, clock=lambda: 0.0, delay=0,
                       on_code=on_code, call_timing={"sleep": lambda x: None, "poll": 0}, **kw)
    out = r.run()
    return r, out, m, cartesia, notes


# ---------------------------------------------------------------- the plan

PLANNER_PLAN = {"cap_cents": 200000, "owned": {"psu": {"name": "Corsair RM750e", "watts": 750}, "case": {"name": "NR200P", "gpu_max_mm": 305}},
                "parts": [{"part": "gpu", "budget_cents": 126585}, {"part": "cpu", "budget_cents": 28354}, {"part": "motherboard", "budget_cents": 17215},
                          {"part": "memory", "budget_cents": 10126}, {"part": "storage", "budget_cents": 12151}, {"part": "cooler", "budget_cents": 5569}]}


def test_the_planners_plan_becomes_a_build_plan_with_the_boards_part_ids_and_dollars():
    p = build.plan_from_planner(PLANNER_PLAN)
    assert [x.part for x in p.parts] == ["gpu", "cpu", "board", "ram", "ssd", "cooler"]
    assert p.cap == 2000.0 and p.parts[0].budget == 1265.85 and [o.part for o in p.owned] == ["psu", "case"]
    assert p.owned[0].label == "Corsair RM750e" and p.owned[0].budget == 0.0


@pytest.mark.parametrize("edit", [lambda d: d["parts"].append({"part": "toaster", "budget_cents": 100}),
                                  lambda d: d["parts"].append({"part": "gpu", "budget_cents": 100}),
                                  lambda d: d["parts"][0].update(budget_cents=0), lambda d: d["parts"][0].update(budget_cents=1.5),
                                  lambda d: d["parts"][0].update(budget_cents=999999), lambda d: d["parts"].clear(),
                                  lambda d: d["owned"].update(toaster={"name": "x"})])
def test_a_plan_we_cannot_read_raises_before_anything_is_bid(edit):
    d = json.loads(json.dumps(PLANNER_PLAN))
    edit(d)
    with pytest.raises(ValueError):
        build.plan_from_planner(d)


# ---------------------------------------------------------------- the market, driven like the bridge

def test_one_goal_of_type_build_with_an_item_per_part_and_owned_parts_skipped(tmp_path):
    r, out, m, *_ = run_build(tmp_path=tmp_path)
    goal = calls(m, "post_goal")
    contract = json.loads((build.ROOT / "contracts" / "Goal.schema.json").read_text())["properties"]["type"]["enum"]
    assert len(goal) == 1 and goal[0]["type"] in contract and goal[0]["type"] == "build_by_date" and goal[0]["id"] == "goal-build-1" and goal[0]["buyer_id"] == "vidyut"
    skipped = {i["sku_spec"]: i["skipped_owned_part_id"] for i in goal[0]["items"] if i["skipped_owned_part_id"]}
    assert skipped == {"750 w psu": "owned-psu", "case (305 mm gpu room)": "owned-case"} and len(goal[0]["items"]) == 8


def test_one_need_and_one_round_per_part_to_buy_and_none_for_an_owned_part(tmp_path):
    r, out, m, *_ = run_build(tmp_path=tmp_path)
    needs, opens, closes = calls(m, "post_need"), calls(m, "open_round"), calls(m, "close_round")
    assert [n["id"] for n in needs] == [f"need-goal-build-1-{p}" for p in ("gpu", "cpu", "board", "ram", "ssd", "cooler")]
    assert all(n["goal_id"] == "goal-build-1" and len(n["items"]) == 1 for n in needs)
    assert [n["spend_limit"] for n in needs] == [1300.0, 285.0, 170.0, 100.0, 120.0, 55.0]
    assert [o["need_id"] for o in opens] == [n["id"] for n in needs] and len(closes) == 6
    assert not any("psu" in n["id"] or "case" in n["id"] for n in needs)


def test_a_round_opens_and_closes_before_the_next_part_opens_and_the_cap_is_never_sent_to_a_seller(tmp_path):
    r, out, m, *_ = run_build(tmp_path=tmp_path)
    seq = [(r, a.get("round_id")) for _, r, a in m.log if r in ("open_round", "close_round")]
    assert [x[0] for x in seq] == ["open_round", "close_round"] * 6
    for who, reducer, args in m.log:
        if who.startswith("seller:"):
            assert "spend_limit" not in json.dumps(args) and "1260" not in json.dumps(args.get("lines", ""))


def test_each_reducer_is_called_by_the_role_it_demands(tmp_path):
    r, out, m, *_ = run_build(tmp_path=tmp_path)
    allowed = {"post_goal": "buyer", "post_need": "buyer", "set_allowance": "referee", "open_round": "referee", "close_round": "referee",
               "attach_verdict": "referee", "attach_advocate_card": "referee", "create_mandate": "referee", "record_approval": "referee",
               "record_payment": "referee", "issue_build_approval_code": "referee", "clear_build_approval_code": "referee"}
    for who, reducer, _ in m.log:
        if reducer in ("set_floor", "place_bid"):
            assert who.startswith("seller:")
        else:
            assert who == allowed[reducer], reducer


def test_the_markets_rank_one_is_each_parts_champion_and_the_cheapest_card_that_is_too_long_is_vetoed_out(tmp_path):
    r, out, m, *_ = run_build(tmp_path=tmp_path)
    v = out["view"]
    gpu = next(p for p in v["parts"] if p["part"] == "gpu")
    assert gpu["status"] == "locked" and gpu["champion"]["sellerId"] != "bargain-bin" and gpu["champion"]["origin"] == "SIM"
    veto = next(r for r in m.rows if r[3] == "bargain-bin" and r[1].endswith("-gpu"))
    assert veto[5] == 0 and "fit.gpu_length" in veto[7][0]
    assert all(p["status"] == "locked" for p in v["parts"] if p["status"] != "owned")


def test_the_demo_build_has_three_winning_sellers_and_labels_everything_sim(tmp_path):
    r, out, m, *_ = run_build(tmp_path=tmp_path)
    v = out["view"]
    assert v["approval"]["sellers"] == 3 and v["origin"] == "SIM" and all(e["origin"] == "SIM" for e in v["events"])
    assert round(v["spent"], 2) == v["approval"]["total"] and v["spent"] <= v["budget"]


def test_a_view_file_is_written_at_every_step_and_the_last_one_is_the_final_view(tmp_path):
    r, out, m, *_ = run_build(tmp_path=tmp_path)
    final = json.loads((tmp_path / build.VIEW_FILE).read_text())
    lines = [json.loads(l) for l in (tmp_path / build.STEPS_FILE).read_text().splitlines()]
    assert len(lines) > 60 and lines[-1] == final == out["view"]
    statuses = [next(p for p in l["parts"] if p["part"] == "gpu")["status"] for l in lines]
    assert statuses[0] == "planned" and "bidding" in statuses and statuses[-1] == "locked" and statuses.index("bidding") < statuses.index("locked")
    assert [l["approval"]["state"] for l in lines][0] == "waiting" and lines[-1]["approval"]["state"] == "paid"


# ---------------------------------------------------------------- one call, one mandate per part, a receipt per part

def test_above_the_allowance_one_call_reads_the_whole_build_then_a_mandate_per_part_then_a_receipt_per_part(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, allowance={"per_purchase_limit": 250.0, "period_limit": 500.0, "period": "month"})
    assert out["status"] == "paid" and len(client.calls) == 1
    total = out["view"]["approval"]["total"]
    spoken = client.calls[0][1]["deal_script"]
    assert "6 parts from 3 sellers" in spoken and "dollars" in spoken
    assert kinds(m).index("create_mandate") > max(i for i, k in enumerate(kinds(m)) if k == "close_round")
    mands = calls(m, "create_mandate")
    assert len(mands) == 6 and round(sum(a["amount"] for a in mands), 2) == total
    won = {row[2]: row for row in m.rows if row[5] == 1}
    for a in mands:                                  # each one is a rank 1 bid's deal, paid to its seller at its landed price
        row = won[a["deal_id"][5:]]
        assert a["payee"] == row[3] and a["amount"] == row[6] and a["expiry_minutes"] == 10 and a["buyer_id"] == "vidyut"
    appr = calls(m, "record_approval")
    assert len(appr) == 6 and {a["method"] for a in appr} == {"voice_code"} and len({a["voice_approval_id"] for a in appr}) == 1
    assert all(a["voice_approval_id"] for a in appr)
    pays = calls(m, "record_payment")
    assert len(pays) == 6 and {p["mode"] for p in pays} == {"sim"} and {p["mandate_hash"] for p in pays} == {a["hash"] for a in mands}
    v = out["view"]
    assert v["approval"]["state"] == "paid" and len(v["approval"]["mandates"]) == 6 and v["approval"]["method"] == "voice_code"
    receipts = [e for e in v["events"] if e["kind"] == "receipt"]
    assert len(receipts) == 6 and all(e["text"].startswith("SIM payment confirmed for deal deal-") and e["origin"] == "SIM" for e in receipts)
    kinds_in_order = [e["kind"] for e in v["events"]]
    assert kinds_in_order.index("call") < kinds_in_order.index("approved") < kinds_in_order.index("receipt")


class WatchingCartesia(FakeCartesia):
    """Records what the market held at the moment the call was placed."""
    def __init__(self, market, says):
        super().__init__(says)
        self.market, self.at_call = market, None

    def create_call(self, to_number, variables):
        self.at_call = {"mandates": len(self.market.mandates), "payments": len(self.market.payments), "approvals": len(self.market.approvals)}
        return super().create_call(to_number, variables)


def test_no_part_is_approved_by_the_markets_allowance_rule_when_the_build_needed_the_call(tmp_path):
    # every part is under the per-purchase limit but the build is not: the market would auto-approve a mandate at once, so no
    # mandate may exist before the call approves (the call covers the whole build)
    m = FakeMarket()
    watch = WatchingCartesia(m, lambda code: f"{code} approve")
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, cartesia=watch, allowance={"per_purchase_limit": 400.0, "period_limit": 5000.0, "period": "month"})
    assert out["status"] == "paid" and len(watch.calls) == 1
    assert watch.at_call == {"mandates": 0, "payments": 0, "approvals": 0}
    assert len(m.mandates) == 6 and len(m.payments) == 6


def test_inside_the_allowance_it_pays_with_no_call_and_says_allowance(tmp_path):
    m = FakeMarket()
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance={"per_purchase_limit": 5000.0, "period_limit": 9000.0, "period": "month"})
    assert out["status"] == "paid" and client.calls == []
    assert len(calls(m, "create_mandate")) == 6 and calls(m, "record_approval") == [] and len(calls(m, "record_payment")) == 6
    assert out["view"]["approval"]["method"] == "allowance" and out["view"]["approval"]["state"] == "paid"
    assert "call" not in [e["kind"] for e in out["view"]["events"]]
    assert {a["method"] for a in m.approvals.values()} == {"allowance"}


def test_a_period_limit_too_small_for_the_whole_build_still_needs_the_call(tmp_path):
    r, out, m, client, notes = run_build(FakeMarket(spent=8000.0), tmp_path=tmp_path,
                                         allowance={"per_purchase_limit": 5000.0, "period_limit": 9000.0, "period": "month"})
    assert len(client.calls) == 1 and out["status"] == "paid" and out["view"]["approval"]["method"] == "voice_code"


def test_a_missing_allowance_is_zero_so_the_build_calls(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, allowance=None)
    assert len(client.calls) == 1


def test_a_denied_call_makes_no_mandate_and_pays_nothing(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, says=lambda code: "no, do not buy that")
    assert out["status"] == "denied" and len(client.calls) == 1
    assert not set(kinds(m)) & {"create_mandate", "record_approval", "record_payment"}
    v = out["view"]
    assert v["approval"]["state"] == "denied" and "nothing was paid" in v["approval"]["reason"].lower() and v["approval"]["mandates"] == []
    assert "denied" in [e["kind"] for e in v["events"]]


def test_a_silent_call_denies(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, says="")
    assert out["status"] == "denied" and not set(kinds(m)) & {"create_mandate", "record_payment"}


def test_a_wrong_code_denies(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, says="alpha bravo approve")
    assert out["status"] == "denied" and not set(kinds(m)) & {"create_mandate", "record_payment"}


def test_no_cartesia_means_no_call_no_mandate_and_nothing_paid(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, cartesia=None)
    assert out["status"] == "denied" and out["reason"] == "not_configured" and not set(kinds(m)) & {"create_mandate", "record_payment"}


def test_there_is_no_scripted_approval_a_build_that_needs_the_call_never_approves_without_one(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, cartesia=None, allowance={"per_purchase_limit": 10.0, "period_limit": 10.0, "period": "week"})
    assert calls(m, "record_approval") == [] and m.approvals == {} and m.payments == {}


def test_a_refused_payment_stops_the_run_and_the_view_does_not_say_paid(tmp_path):
    m = FakeMarket()
    m.fail["record_payment"] = "no approval row for this mandate hash; payment refused"
    with pytest.raises(RuntimeError):
        run_build(m, tmp_path=tmp_path)
    v = json.loads((tmp_path / build.VIEW_FILE).read_text())
    assert v["approval"]["state"] == "denied" and not any(e["kind"] == "receipt" for e in v["events"])


def test_the_gpu_runs_the_bridges_own_round_so_the_liar_is_vetoed_by_the_real_advocate_and_never_wins(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=build.default_catalog, real_gpu=True, allowance=ALLOW)
    sam = next(row for row in m.rows if row[3] == "shady-sam")
    assert sam[5] == 0 and "advocate.condition" in sam[7][0]
    gpu = next(p for p in out["view"]["parts"] if p["part"] == "gpu")
    assert out["status"] == "paid" and gpu["status"] == "locked" and gpu["champion"]["sellerId"] not in ("shady-sam", "bargain-bin", "lowball")
    placed = {s for who, reducer, _ in m.log if reducer == "place_bid" for s in [who]}
    assert "seller:shady-sam" in placed and "seller:bargain-bin" in placed and "seller:lowball" in placed   # the planted cast bids
    cards = [a for a in calls(m, "attach_advocate_card")]
    assert {"fit.gpu_length", "advocate.condition"} <= {c["rule_id"] for c in cards}
    assert gpu["champion"]["origin"] in ("SIM", "MIRROR") and gpu["budget"] == 1300.0


def allowance_calls(m):
    return [(a["per_purchase_limit"], a["period_limit"], a["period"]) for _, r, a in m.log if r == "set_allowance"]


def test_after_the_call_every_part_is_approved_by_the_calls_voice_code_even_a_part_under_the_per_buy_limit(tmp_path):
    # the market approves a mandate at or under the per-purchase limit by itself (method allowance, no voice id), and a following
    # record_approval is swallowed: the build zeroes the per-buy limit while it makes the mandates, then restores it
    r, out, m, client, notes = run_build(tmp_path=tmp_path, allowance=dict(ALLOW))
    assert out["status"] == "paid" and len(m.approvals) == 6
    assert {v["method"] for v in m.approvals.values()} == {"voice_code"}
    ids = {v["voice_approval_id"] for v in m.approvals.values()}
    assert len(ids) == 1 and "" not in ids
    assert allowance_calls(m) == [(250.0, 500.0, "month"), (0.0, 500.0, "month"), (250.0, 500.0, "month")]
    assert m.allow["per"] == 250.0 and m.allow["spent"] == 0.0, "the allowance is back and nothing counted against it"
    order = kinds(m)
    zero = [i for i, (_, r_, a) in enumerate(m.log) if r_ == "set_allowance" and a["per_purchase_limit"] == 0.0][0]
    assert zero < order.index("create_mandate") and order.index("record_approval") < len(order) - order[::-1].index("set_allowance")


def test_the_allowance_is_restored_when_a_mandate_is_refused_midway(tmp_path):
    m = FakeMarket()
    m.fail["record_approval"] = "mandate expired; the deal must be re-quoted"
    with pytest.raises(RuntimeError):
        run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert allowance_calls(m)[-1] == (250.0, 500.0, "month") and m.allow["per"] == 250.0 and m.payments == {}


def test_a_failed_restore_leaves_the_allowance_at_zero_and_says_so(tmp_path):
    m = FakeMarket()
    real = m.set_allowance

    def flaky(a):
        if a["per_purchase_limit"] > 0 and len(allowance_calls(m)) > 2:
            raise RuntimeError("market down")
        real(a)
    m.set_allowance = flaky
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert m.allow["per"] == 0.0 and any("allowance" in n and "$0" in n for n in notes)


def test_the_build_is_denied_with_no_payment_when_a_mandate_has_no_voice_code_row(tmp_path):
    m = FakeMarket()
    m.swallow_approval = True
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert out["status"] == "denied" and out["reason"] == "approval_missing" and m.payments == {}
    assert "record_payment" not in kinds(m) and out["view"]["approval"]["state"] == "denied"
    assert "voice" in out["view"]["approval"]["reason"].lower() and "Nothing was paid" in out["view"]["approval"]["reason"]
    assert len(calls(m, "deny_approval")) == 6, "the held units go back on sale"


def test_an_approval_row_carrying_another_calls_id_is_not_the_calls_approval(tmp_path):
    m = FakeMarket()
    real = m.record_approval

    def wrong_id(a):
        real({**a, "voice_approval_id": "va-someone-else"})
    m.record_approval = wrong_id
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert out["status"] == "denied" and out["reason"] == "approval_missing" and m.payments == {}


def test_without_the_private_tables_the_public_floor_events_still_prove_the_method(tmp_path):
    m = FakeMarket()
    m.deals_readable = False
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert out["status"] == "paid"
    m2 = FakeMarket()
    m2.deals_readable, m2.swallow_approval = False, True
    r, out, m2, client, notes = run_build(m2, tmp_path=tmp_path / "b", allowance=dict(ALLOW))
    assert out["status"] == "denied" and m2.payments == {}


def test_a_build_that_cannot_be_read_back_at_all_pays_nothing(tmp_path):
    m = FakeMarket()
    m.deals_readable = m.events_readable = False
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert out["status"] == "denied" and m.payments == {} and "record_payment" not in kinds(m)


def test_no_stripe_test_charge_is_made_before_every_approval_is_confirmed(tmp_path):
    m = FakeMarket()
    m.swallow_approval = True
    stripe = []
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW), use_stripe=True,
                                         env={"STRIPE_SECRET_KEY": "sk_test_x"}, stripe_test=lambda mand, key: stripe.append(mand) or {})
    assert out["status"] == "denied" and stripe == []


def test_the_markets_own_spent_this_period_decides_not_a_hard_coded_zero(tmp_path):
    # the build was given room for the whole total, but the market already counts $8,500 spent this period
    m = FakeMarket(spent=8500.0)
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance={"per_purchase_limit": 5000.0, "period_limit": 9000.0, "period": "month"})
    assert len(client.calls) == 1 and out["status"] == "paid" and out["view"]["approval"]["method"] == "voice_code"
    assert {v["method"] for v in m.approvals.values()} == {"voice_code"} and m.allow["spent"] == 8500.0


class TighteningCartesia(FakeCartesia):
    """The buyer lowers their own per-purchase limit while the call is in progress."""
    def __init__(self, market, says, to):
        super().__init__(says)
        self.market, self.to = market, to

    def get_call(self, call_id):
        self.market.allow = {**self.market.allow, "per": self.to}
        return super().get_call(call_id)


def test_a_limit_the_buyer_tightens_during_the_call_is_restored_as_tightened(tmp_path):
    m = FakeMarket()
    cart = TighteningCartesia(m, lambda code: f"{code} approve", 60.0)
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, cartesia=cart, allowance=dict(ALLOW))
    assert out["status"] == "paid" and len(cart.calls) == 1
    assert allowance_calls(m)[-2:] == [(0.0, 500.0, "month"), (60.0, 500.0, "month")] and m.allow["per"] == 60.0
    assert {v["method"] for v in m.approvals.values()} == {"voice_code"}


def test_an_allowance_that_cannot_be_read_after_the_call_makes_no_mandate(tmp_path):
    m = FakeMarket()

    class Blinding(FakeCartesia):
        def get_call(self, call_id):
            m.allowance_readable = False
            return super().get_call(call_id)
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, cartesia=Blinding(lambda code: f"{code} approve"), allowance=dict(ALLOW))
    assert out["status"] == "denied" and out["reason"] == "allowance_unreadable" and "create_mandate" not in kinds(m) and m.payments == {}
    assert allowance_calls(m) == [(250.0, 500.0, "month")]


def test_an_allowance_that_cannot_be_read_stops_before_any_call_or_mandate_even_when_the_plan_gave_one(tmp_path):
    m = FakeMarket()
    m.allowance_readable = False
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert out["status"] == "denied" and out["reason"] == "allowance_unreadable"
    assert client.calls == [] and "create_mandate" not in kinds(m) and m.payments == {}
    assert allowance_calls(m) == [(250.0, 500.0, "month")], "the allowance was never touched"


def test_a_per_buy_limit_the_buyer_tightened_is_restored_as_it_was_not_as_the_plan_had_it(tmp_path):
    m = FakeMarket()
    real = m.set_allowance

    def once(a):
        real(a)
        if len(allowance_calls(m)) == 1:
            m.allow = {**m.allow, "per": 60.0}      # the buyer tightens their own limit after the build set it
    m.set_allowance = once
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert out["status"] == "paid" and allowance_calls(m)[-2:] == [(0.0, 500.0, "month"), (60.0, 500.0, "month")] and m.allow["per"] == 60.0


def test_inside_the_allowance_a_part_the_market_would_not_auto_approve_denies_before_any_payment(tmp_path):
    m = FakeMarket()
    real = m.create_mandate

    def stingy(a):   # the market's own rule disagrees with the build's reading of the allowance
        m.allow = {**m.allow, "per": 1.0}
        real(a)
    m.create_mandate = stingy
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance={"per_purchase_limit": 5000.0, "period_limit": 9000.0, "period": "month"})
    assert out["status"] == "denied" and m.payments == {} and "record_payment" not in kinds(m) and client.calls == []


def test_a_round_the_market_has_not_closed_gives_no_champion(tmp_path):
    m = FakeMarket()
    m.never_close = True
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    assert out["status"] == "denied" and "create_mandate" not in kinds(m) and client.calls == []
    assert {p["status"] for p in out["view"]["parts"] if p["status"] != "owned"} == {"bidding"}


def test_a_knockout_stage_leader_is_never_a_champion():
    row = {"roundId": "r", "bidId": "b", "sellerId": "s", "persona": "S", "rank": 1, "landed": 10.0, "reasons": [], "origin": "SIM"}
    for status, ok in (("", True), ("champion", True), ("advancing", False), ("knocked_out", False)):
        champ, why = build.champion_of([{**row, "status": status}])
        assert (champ is not None) is ok, status
    assert build.champion_of([row])[0] is not None   # an older market with no status column


def test_a_stage_leader_that_has_not_won_fails_the_part(tmp_path):
    m = FakeMarket()
    m.knockout = {"round-goal-build-1-gpu"}
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance=dict(ALLOW))
    gpu = next(p for p in out["view"]["parts"] if p["part"] == "gpu")
    assert gpu["status"] == "failed" and out["status"] == "denied" and "create_mandate" not in kinds(m)


def test_a_rerun_starts_the_steps_file_over(tmp_path):
    run_build(tmp_path=tmp_path)
    first = (tmp_path / build.STEPS_FILE).read_text().splitlines()
    run_build(tmp_path=tmp_path)
    again = (tmp_path / build.STEPS_FILE).read_text().splitlines()
    assert len(again) == len(first) and json.loads(again[0])["parts"][2]["status"] == "planned"


# ---------------------------------------------------------------- fail safe

def only(spec_part, sellers):
    def catalog(spec, index):
        return sellers if spec.part == spec_part else sim_catalog(spec, index)
    return catalog


def test_a_part_whose_every_bid_is_vetoed_fails_the_build_does_not_call_and_nothing_is_paid(tmp_path):
    cat = only("cpu", [seller("bargain-bin", "Bargain Bin Hardware (SIM)", 270.0, length=336)])

    class Spec(build.PartSpec):
        pass
    # a CPU has no length rule, so make the only bid a GPU-length trap by asking the advocate through a custom card builder
    import demo.build as b
    orig = b.advocate_card
    b.advocate_card = lambda spec, bid, clearance=305: ({"bid_id": bid["id"], "recommendation": "veto", "call_reason": {
        "rule_id": "fit.cpu_socket", "summary": "LGA1700 CPU, AM5 board", "source_url": "https://example.com/spec"}}
        if spec.part == "cpu" else orig(spec, bid, clearance))
    try:
        r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=cat)
    finally:
        b.advocate_card = orig
    cpu = next(p for p in out["view"]["parts"] if p["part"] == "cpu")
    assert cpu["status"] == "failed" and "no eligible bid" in cpu["reason"] and "champion" not in cpu
    assert out["status"] == "denied" and client.calls == [] and not set(kinds(m)) & {"create_mandate", "record_approval", "record_payment"}
    assert out["view"]["approval"]["state"] == "denied" and "Nothing was paid" in out["view"]["approval"]["reason"]


def test_a_part_with_no_bid_inside_its_budget_fails_the_build(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=only("ram", [seller("fair-price-pc", "Fair Price PC (SIM)", 999.0)]))
    ram = next(p for p in out["view"]["parts"] if p["part"] == "ram")
    assert ram["status"] == "failed" and client.calls == [] and "create_mandate" not in kinds(m) and out["status"] == "denied"


def test_a_rank_one_that_is_held_back_is_never_mandated(tmp_path):
    import demo.build as b
    orig = b.advocate_card
    b.advocate_card = lambda spec, bid, clearance=305: ({"bid_id": bid["id"], "recommendation": "caution", "call_reason": {
        "rule_id": "fit.gpu_length", "summary": "fit not confirmed", "source_url": "https://example.com/spec"}}
        if spec.part == "gpu" else orig(spec, bid, clearance))
    try:
        r, out, m, client, notes = run_build(tmp_path=tmp_path)
    finally:
        b.advocate_card = orig
    gpu = next(p for p in out["view"]["parts"] if p["part"] == "gpu")
    assert gpu["status"] == "failed" and "held back" in gpu["reason"] and "champion" not in gpu
    assert client.calls == [] and "create_mandate" not in kinds(m) and out["status"] == "denied"


def test_a_seller_that_never_joined_the_market_is_never_mandated_even_as_rank_one(tmp_path):
    cc = [seller("central_computers_sf", "Central Computers (SF)", 1100.0, origin=MIRROR, url="https://www.centralcomputer.com/x")]
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=only("gpu", cc))
    gpu = next(p for p in out["view"]["parts"] if p["part"] == "gpu")
    assert gpu["status"] == "failed" and "not a partner" in gpu["reason"]
    assert client.calls == [] and "create_mandate" not in kinds(m) and m.payments == {}


def test_a_champion_this_run_never_bid_is_never_mandated(tmp_path):
    m = FakeMarket()
    r = build.BuildRun(build.demo_plan(), make_clients(m), catalog=sim_catalog, cartesia=FakeCartesia("x"), out_dir=tmp_path, delay=0,
                       sleep=lambda x: None, clock=lambda: 0.0, real_gpu_round=False)
    r.run_rounds()
    r.ledger.pop(r.champions()[0]["gpu"]["bidId"])      # the market's rank 1 is not one of ours
    champs, bad = r.champions()
    assert "gpu" in bad and "not placed by this build" in bad["gpu"] and "gpu" not in champs


# ---------------------------------------------------------------- Bright Data per part

def mirror_catalog(snap="2026-10-24T21:12:13+00:00"):
    def catalog(spec, index):
        base = sim_catalog(spec, index)
        if spec.part in ("gpu", "cpu"):
            return [seller("best-buy", "Best Buy", round(spec.budget * 0.8, 2), origin=MIRROR, url=f"https://www.bestbuy.com/p/{spec.part}", snap=snap)] + base
        return base
    return catalog


ALLOW = {"per_purchase_limit": 250.0, "period_limit": 500.0, "period": "month"}


def ok_check(listing):
    return {"state": "ok", "price": listing["price"], "fetched_at": "2026-10-24T23:50:00Z", "origin": "LIVE", "quoted": listing["price"]}


def test_every_mirror_champion_is_rechecked_live_in_parallel_before_the_call(tmp_path):
    barrier, seen = threading.Barrier(2, timeout=5), []

    def check(listing):
        seen.append(listing["url"])
        barrier.wait()          # both reads must be in flight at once, or this raises BrokenBarrierError
        return ok_check(listing)
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=mirror_catalog(), allowance=ALLOW, price_check=check)
    assert sorted(seen) == ["https://www.bestbuy.com/p/cpu", "https://www.bestbuy.com/p/gpu"] and out["status"] == "paid"
    v = out["view"]
    gpu = next(p for p in v["parts"] if p["part"] == "gpu")
    assert gpu["champion"]["origin"] == "MIRROR" and gpu["champion"]["liveCheck"]["state"] == "ok" and gpu["champion"]["liveCheck"]["origin"] == "LIVE"
    assert gpu["champion"]["sourceUrl"] == "https://www.bestbuy.com/p/gpu"
    assert "checked live just now" in client.calls[0][1]["deal_script"]
    assert any("checked live" in e["text"] and e["origin"] == "LIVE" for e in v["events"])


def test_sim_champions_are_not_sent_to_bright_data(tmp_path):
    seen = []
    r, out, m, client, notes = run_build(tmp_path=tmp_path, allowance=ALLOW, price_check=lambda l: seen.append(l) or ok_check(l))
    assert seen == [] and out["status"] == "paid" and all("liveCheck" not in p.get("champion", {}) for p in out["view"]["parts"])


def test_a_failed_live_read_keeps_the_dated_price_says_so_and_the_build_goes_on(tmp_path):
    def boom(listing):
        raise OSError("blocked")
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=mirror_catalog(), allowance=ALLOW, price_check=boom)
    assert out["status"] == "paid"
    gpu = next(p for p in out["view"]["parts"] if p["part"] == "gpu")
    assert gpu["champion"]["liveCheck"]["state"] == "empty" and gpu["champion"]["liveCheck"]["origin"] == "MIRROR"
    text = next(e["text"] for e in out["view"]["events"] if e["parts"] == ["gpu"] and "live price not read" in e["text"])
    assert "MIRROR price stays" in text and "dated listing of 2026-10-24" in text
    assert "dated listing snapshot" in client.calls[0][1]["deal_script"] and "checked live" not in client.calls[0][1]["deal_script"]


def test_a_slow_live_read_is_cut_off_at_the_timeout_and_the_dated_price_stays(tmp_path):
    def slow(listing):
        time.sleep(1.5)
        return ok_check(listing)
    t0 = time.monotonic()
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=mirror_catalog(), allowance=ALLOW, price_check=slow, recheck_timeout=0.2)
    assert time.monotonic() - t0 < 1.4 and out["status"] == "paid"
    gpu = next(p for p in out["view"]["parts"] if p["part"] == "gpu")
    assert gpu["champion"]["liveCheck"]["state"] == "slow" and any("too slow" in e["text"] for e in out["view"]["events"])


def test_a_live_price_above_the_quote_places_no_call_and_pays_nothing(tmp_path):
    def rose(listing):
        return {"state": "price_changed", "price": listing["price"] + 50, "fetched_at": "2026-10-24T23:50:00Z", "origin": "LIVE"}
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=mirror_catalog(), allowance=ALLOW, price_check=rose)
    assert out["status"] == "denied" and out["reason"] == "price_recheck" and client.calls == []
    assert not set(kinds(m)) & {"create_mandate", "record_payment"} and "live price rose" in out["view"]["approval"]["reason"]


def test_a_part_that_is_out_of_stock_live_places_no_call(tmp_path):
    def gone(listing):
        return {"state": "out_of_stock", "price": listing["price"], "fetched_at": "2026-10-24T23:50:00Z", "origin": "LIVE"}
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=mirror_catalog(), allowance=ALLOW, price_check=gone)
    assert out["status"] == "denied" and client.calls == [] and "create_mandate" not in kinds(m)


def test_a_live_price_below_the_quote_does_not_stop_the_build(tmp_path):
    def cheaper(listing):
        return {"state": "price_changed", "price": listing["price"] - 5, "fetched_at": "2026-10-24T23:50:00Z", "origin": "LIVE"}
    r, out, m, client, notes = run_build(tmp_path=tmp_path, catalog=mirror_catalog(), allowance=ALLOW, price_check=cheaper)
    assert out["status"] == "paid"


# ---------------------------------------------------------------- CRS, the payee gate

def test_a_business_payee_without_a_verified_crs_check_holds_the_whole_build(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, allowance=ALLOW, crs_check=lambda sid: {"business": True, "check": None})
    assert out["status"] == "denied" and out["reason"] == "crs_gate" and client.calls == [] and "create_mandate" not in kinds(m)


def test_a_crs_check_that_raises_holds_the_payee_gate(tmp_path):
    def boom(sid):
        raise TimeoutError("slow")
    r, out, m, client, notes = run_build(tmp_path=tmp_path, allowance=ALLOW, crs_check=boom)
    assert out["status"] == "denied" and client.calls == [] and "create_mandate" not in kinds(m)


def test_sim_sellers_pass_the_payee_gate_without_a_check(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, allowance=ALLOW, crs_check=lambda sid: {"business": False, "check": None})
    assert out["status"] == "paid"


# ---------------------------------------------------------------- the sellers

def test_the_default_catalog_labels_every_line_and_never_bids_a_store_that_did_not_join():
    spec = build.demo_plan().parts[0]
    sellers = build.default_catalog(spec, 0)
    assert all(l.origin in (SIM, MIRROR) for s in sellers for l in s.lines) and all(s.origin in (SIM, MIRROR) for s in sellers)
    assert not any("central" in s.id for s in sellers)
    assert any(s.origin == MIRROR for s in sellers), "data/ holds real dated GPU listings, so the GPU round has MIRROR sellers"
    for p in build.demo_plan().parts[1:]:
        assert {s.origin for s in build.default_catalog(p, 1)} == {SIM}, "data/ has no listing for this part, so it is SIM"


def test_the_cheapest_sim_seller_rotates_so_the_build_has_more_than_one_winner():
    wins = set()
    for i, p in enumerate(build.demo_plan().parts):
        honest = [s for s in build.default_catalog(p, i, mirror=False) if not (p.part == "gpu" and s.id == "bargain-bin")]
        wins.add(min(honest, key=lambda s: s.lines[0].list_price).id)
    assert len(wins) == 3
    assert all(l.list_price <= p.budget for i, p in enumerate(build.demo_plan().parts) for s in build.default_catalog(p, i, mirror=False) for l in s.lines)


# ---------------------------------------------------------------- the CLI

def test_dry_run_prints_the_steps_touches_nothing_and_exits_zero(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert build.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "post_goal" in out and out.count("post_need") == 7 and out.count("open_knockout_round") == 7 and "create_mandate" not in out   # six parts and the board's re-plan
    # #363: the market has sealed knockout rounds, so auto picks open_knockout_round for each of the same seven rounds, never the plain open_round
    assert out.count("open_round") == 0 and out.count("close_stage") >= 7


# ---------------------------------------------------------------- #398: the dry run names each payee's CRS status

def crs_lines(out):
    return [l for l in out.splitlines() if "CRS" in l and ("profile" in l or "unknown" in l) and "CRS per payee" not in l]


def crs_offline(monkeypatch, tmp_path, profile=None):
    """Point CRS at a temp profile file and cache, with credentials set and every network path raising."""
    from demo import bridge
    mod = bridge.crs_module()
    def boom(*a, **k):
        raise AssertionError("a dry run must never reach the CRS sandbox")
    for name in ("_login", "_get_token", "_request", "_open_request"):
        monkeypatch.setattr(mod, name, boom)
    monkeypatch.setenv("CRS_USERNAME", "test-user")
    monkeypatch.setenv("CRS_PASSWORD", "test-password")
    monkeypatch.setenv("CRS_SIGNAL_CACHE_PATH", str(tmp_path / "cache.json"))
    if profile is None:
        monkeypatch.delenv("CRS_TEST_IDENTITIES_PATH", raising=False)
    else:
        path = tmp_path / "private.json"
        path.write_text(profile if isinstance(profile, str) else json.dumps(profile))
        monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(path))


def test_dry_run_with_no_profile_file_says_no_crs_profile_for_every_payee(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    crs_offline(monkeypatch, tmp_path)
    assert build.main(["--dry-run"]) == 0
    lines = crs_lines(capsys.readouterr().out)
    for sid in ("gadget-grove", "fair-price-pc", "bargain-bin"):
        mine = [l for l in lines if f"({sid})" in l]
        assert len(mine) == 1 and "no CRS profile" in mine[0] and "[SIM]" in mine[0]
    assert all("no CRS profile" in l for l in lines) and len(lines) >= 3


def test_dry_run_names_a_business_payee_as_not_checked_and_an_individual_as_sim(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    crs_offline(monkeypatch, tmp_path, {"sellers": {
        "fair-price-pc": {"seller_type": "business", "consent": True, "persona_ref": "P01", "request": {"field": "synthetic"}},
        "gadget-grove": {"seller_type": "individual", "consent": True}}})
    assert build.main(["--dry-run"]) == 0
    lines = crs_lines(capsys.readouterr().out)
    fair = [l for l in lines if "(fair-price-pc)" in l]
    assert len(fair) == 1 and "business CRS profile (P01)" in fair[0] and "not checked" in fair[0]
    grove = [l for l in lines if "(gadget-grove)" in l]
    assert len(grove) == 1 and "no CRS profile: its CRS profile is an individual seller" in grove[0]


def test_dry_run_shows_a_recorded_band_with_its_time_never_as_live(capsys, tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.chdir(tmp_path)
    crs_offline(monkeypatch, tmp_path, {"sellers": {
        "bargain-bin": {"seller_type": "business", "consent": True, "persona_ref": "P12", "request": {"field": "synthetic"}}}})
    at = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    (tmp_path / "cache.json").write_text(json.dumps({"bargain-bin": {"persona_ref": "P12", "reason": "x", "signal": {
        "supplier_id": "bargain-bin", "stability": "not_verified", "checked_at": at, "source": "sandbox"}}}))
    assert build.main(["--dry-run"]) == 0
    line = next(l for l in crs_lines(capsys.readouterr().out) if "(bargain-bin)" in l)
    assert "CRS band not_verified" in line and f"recorded {at}" in line and "[LIVE]" not in line
    assert "the payee gate would hold" in line


def test_dry_run_with_an_unreadable_profile_file_says_unknown_never_no_profile(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    crs_offline(monkeypatch, tmp_path, "not json")
    assert build.main(["--dry-run"]) == 0
    lines = crs_lines(capsys.readouterr().out)
    assert lines and all("CRS unknown" in l and "no CRS profile" not in l for l in lines)
