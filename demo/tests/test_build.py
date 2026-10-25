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
from demo.bridge import Step
from demo.common import MIRROR, SIM
from demo.sellers import Line, Seller
from demo.tests.test_bridge import FakeCartesia


class FakeMarket:
    def __init__(self, per_buy=0.0):
        self.log, self.bids, self.cards, self.verdicts, self.needs, self.rounds = [], {}, {}, {}, {}, {}
        self.rows, self.mandates, self.approvals, self.payments = [], {}, {}, {}
        self.per_buy, self.fail, self.floors = per_buy, {}, {}

    def client(self, name):
        return _Client(self, name)

    # reducers (only those with a rule worth faking)
    def set_floor(self, a):
        self.floors[(a["seller_id"], a["sku_spec"])] = a["floor"]

    def place_bid(self, a):
        line = min(a["lines"], key=lambda l: l["unit_price"])
        below = line["unit_price"] < self.floors.get((a["seller_id"], line["sku_spec"]), 0)
        self.bids[a["id"]] = {**a, "landed": line["unit_price"], "below_floor": below}

    def post_need(self, a):
        self.needs[a["id"]] = a

    def attach_advocate_card(self, a):
        self.cards[a["bid_id"]] = a

    def attach_verdict(self, a):
        self.verdicts[a["bid_id"]] = a["verdict"]

    def open_round(self, a):
        self.rounds[a["round_id"]] = a

    def close_round(self, a):
        rid = a["round_id"]
        need = self.needs[self.rounds[rid]["need_id"]]
        mine = [b for b in self.bids.values() if b["round_id"] == rid]
        ok, out = [], []
        for b in mine:
            card, verdict = self.cards.get(b["id"]), self.verdicts.get(b["id"], "allow")
            if b["below_floor"]:
                out.append((b, ["referee: below the seller's own floor"]))
            elif verdict != "allow":
                out.append((b, [f"shield {verdict}"]))
            elif card and card["recommendation"] == "veto":
                out.append((b, [f"advocate veto ({card['rule_id']}): {card['text']}"]))
            elif b["landed"] > need["spend_limit"]:
                out.append((b, ["over the cap"]))
            else:
                ok.append(b)
        ok.sort(key=lambda b: (bool(self.cards.get(b["id"]) and self.cards[b["id"]]["recommendation"] == "caution"), b["landed"]))
        for i, b in enumerate(ok, 1):
            held = self.cards.get(b["id"], {}).get("recommendation") == "caution"
            self.rows.append((len(self.rows) + 1, rid, b["id"], b["seller_id"], b["persona"], i, b["landed"],
                              [f"held back: advocate caution ({self.cards[b['id']]['rule_id']}: {self.cards[b['id']]['text']})"] if held else [],
                              b["lines"], b["origin"], b["source"]))
        for b, why in out:
            self.rows.append((len(self.rows) + 1, rid, b["id"], b["seller_id"], b["persona"], 0, b["landed"], why, b["lines"], b["origin"], b["source"]))

    def create_mandate(self, a):
        bid_id = a["deal_id"][5:]
        won = next((r for r in self.rows if r[2] == bid_id and r[5] == 1), None)
        if won is None:
            raise RuntimeError("a mandate needs the rank 1 bid of a closed round")
        if a["payee"] != won[3] or abs(a["amount"] - won[6]) > 1e-9:
            raise RuntimeError("payee or amount differs from the winner")
        self.mandates[a["hash"]] = a
        if a["amount"] <= self.per_buy:
            self.approvals[a["hash"]] = {"method": "allowance", "voice_approval_id": ""}

    def record_approval(self, a):
        if a["mandate_hash"] not in self.mandates:
            raise RuntimeError("no mandate with that hash")
        if a["method"] == "voice_code" and not a["voice_approval_id"]:
            raise RuntimeError("a voice approval needs the VoiceApproval id from the call")
        self.approvals.setdefault(a["mandate_hash"], {"method": a["method"], "voice_approval_id": a["voice_approval_id"]})

    def record_payment(self, a):
        if a["mandate_hash"] not in self.approvals:
            raise RuntimeError("no approval row for this mandate hash; payment refused")
        self.payments[a["mandate_hash"]] = a


class _Client:
    def __init__(self, market, name):
        self.m, self.name = market, name

    def call(self, reducer, **args):
        self.m.log.append((self.name, reducer, args))
        if self.m.fail.get(reducer):
            raise RuntimeError(self.m.fail[reducer])
        seen = {**args, "seller_id": self.name.split(":", 1)[1]} if reducer in ("place_bid", "set_floor") else args   # the market knows the caller
        getattr(self.m, reducer, lambda a: None)(seen)

    def sql(self, query):
        assert query == "SELECT * FROM round_result"
        return list(self.m.rows)


def kinds(m):
    return [r for _, r, _ in m.log]


def calls(m, reducer):
    return [a for _, r, a in m.log if r == reducer]


class Clients(dict):
    """Every seller id gets its own client, as the bridge makes one per seller identity."""
    def __init__(self, m):
        super().__init__({n: m.client(n) for n in ("buyer", "referee")})
        self.m = m

    def __missing__(self, key):
        self[key] = self.m.client(key)
        return self[key]

    def __contains__(self, key):
        return True


def make_clients(m):
    return Clients(m)


def seller(sid, name, price, origin=SIM, url=None, length=303, snap=""):
    url = url or f"https://example.com/sim/{sid}"
    line = Line("new", price, round(price * 0.9, 2), url, origin, page_condition="new", attrs={"category": "gpu", "length_mm": length},
                basis="test", snapshot_date=snap)
    return Seller(sid, name, origin, [line], 0.0, 30, payee=f"{sid}@pay.example.test", shipping_captured=True, claims=[])


def sim_catalog(spec, index):
    return build.default_catalog(spec, index, mirror=False)


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
    assert len(goal) == 1 and goal[0]["type"] == "build" and goal[0]["id"] == "goal-build-1" and goal[0]["buyer_id"] == "vidyut"
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
               "record_payment": "referee"}
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
    m = FakeMarket(per_buy=400.0)
    watch = WatchingCartesia(m, lambda code: f"{code} approve")
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, cartesia=watch, allowance={"per_purchase_limit": 400.0, "period_limit": 5000.0, "period": "month"})
    assert out["status"] == "paid" and len(watch.calls) == 1
    assert watch.at_call == {"mandates": 0, "payments": 0, "approvals": 0}
    assert len(m.mandates) == 6 and len(m.payments) == 6


def test_inside_the_allowance_it_pays_with_no_call_and_says_allowance(tmp_path):
    m = FakeMarket(per_buy=5000.0)
    r, out, m, client, notes = run_build(m, tmp_path=tmp_path, allowance={"per_purchase_limit": 5000.0, "period_limit": 9000.0, "period": "month"})
    assert out["status"] == "paid" and client.calls == []
    assert len(calls(m, "create_mandate")) == 6 and calls(m, "record_approval") == [] and len(calls(m, "record_payment")) == 6
    assert out["view"]["approval"]["method"] == "allowance" and out["view"]["approval"]["state"] == "paid"
    assert "call" not in [e["kind"] for e in out["view"]["events"]]
    assert {a["method"] for a in m.approvals.values()} == {"allowance"}


def test_a_period_limit_too_small_for_the_whole_build_still_needs_the_call(tmp_path):
    r, out, m, client, notes = run_build(tmp_path=tmp_path, allowance={"per_purchase_limit": 5000.0, "period_limit": 9000.0, "period": "month",
                                                                      "spent_this_period": 8000.0})
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
    r._execute(build.goal_steps(r.plan, None))
    for i, spec in enumerate(r.plan.parts):
        r._run_part(i, spec)
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
    assert "post_goal" in out and out.count("post_need") == 6 and out.count("open_round") == 6 and "create_mandate" not in out
