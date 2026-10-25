"""#373 review fixes: the real #363 market closes a stage on its own deadline, a knockout never crowns a caution, the deployed module is
probed, the in-memory market keeps the real rules it was missing, the hosted copy of the view carries no money or identity, and one line
per (a, b, rule) in `checks`."""
from __future__ import annotations

import json

import pytest

from demo import build
from demo.build_sim import SimMarket, make_clients
from demo.tests.test_build import ALLOW, calls, kinds
from demo.tests.test_build_phase2 import OWNED, drive, sim_catalog, trap_catalog


# ---------------------------------------------------------------- 1: the market's scheduler closes each stage first

def test_a_knockout_build_survives_the_markets_deadline_scheduler_closing_every_stage_before_the_referees_call(tmp_path):
    m = SimMarket(scheduler_first=True)
    r, out, m, stamps = drive(tmp_path, m=m, catalog=sim_catalog, allowance=dict(ALLOW), knockout=True)
    assert out["status"] == "paid" and all(p["status"] == "locked" for p in out["view"]["parts"] if p["status"] != "owned")
    assert len(calls(m, "close_stage")) > 6, "the referee still asked; the market had already closed the stage"


def test_a_knockout_replan_also_survives_the_scheduler(tmp_path):
    r, out, m, stamps = drive(tmp_path, m=SimMarket(scheduler_first=True), allowance=dict(ALLOW), knockout=True)
    assert out["status"] == "paid" and next(p for p in out["view"]["parts"] if p["part"] == "board")["status"] == "replanned"


def test_a_stage_that_never_closes_still_stops_the_run_with_the_markets_message(tmp_path):
    m = SimMarket()
    real = m.close_stage

    def refuse(a):
        raise RuntimeError("round is still open until its deadline")
    m.close_stage = refuse
    with pytest.raises(RuntimeError, match="still open"):
        drive(tmp_path, m=m, catalog=sim_catalog, allowance=dict(ALLOW), knockout=True)
    assert len(calls(m, "close_stage")) <= 1 + build.CLOSE_RETRIES


# ---------------------------------------------------------------- 2: a caution is never the champion

def _caution_cpu(monkeypatch):
    real = build.advocate_card

    def card(spec, bid, *a, **kw):
        c = real(spec, bid, *a, **kw)
        if spec.part == "cpu" and bid["seller_id"] == "bargain-bin":
            return {**c, "recommendation": "caution", "call_reason": {"rule_id": "advocate.fit_unknown", "summary": "length unknown", "source_url": ""}}
        return c
    monkeypatch.setattr(build, "advocate_card", card)


def test_a_cautioned_bid_is_sent_to_a_knockout_market_as_a_held_back_veto_and_knocked_out_with_that_reason(tmp_path, monkeypatch):
    _caution_cpu(monkeypatch)
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog, allowance=dict(ALLOW), knockout=True)
    sent = [a for a in calls(m, "attach_advocate_card") if a["rule_id"] == "advocate.fit_unknown"]
    assert sent and all(a["recommendation"] == "veto" and a["text"].startswith("held back (caution)") for a in sent)
    cpu = next(p for p in out["view"]["parts"] if p["part"] == "cpu")
    assert cpu["status"] == "locked" and cpu["champion"]["sellerId"] != "bargain-bin" and out["status"] == "paid"
    assert any("held back (caution)" in e["text"] for e in out["view"]["events"] if e["kind"] == "knockout")


def test_a_knockout_market_that_crowns_a_caution_cannot_make_it_the_champion(tmp_path, monkeypatch):
    _caution_cpu(monkeypatch)
    monkeypatch.setattr(build, "_cards_for_market", lambda cards, knockout: cards)   # the market is sent the plain caution and, like #363, crowns it
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog, allowance=dict(ALLOW), knockout=True)
    champ_rows = [row for row in m.rows if row[14] == "champion" and row[3] == "bargain-bin" and row[1].endswith("-cpu")]
    assert champ_rows, "the stand-in, like #363, ranks by price and crowned the cheapest bid"
    cpu = next(p for p in out["view"]["parts"] if p["part"] == "cpu")
    assert cpu["status"] == "failed" and "held back" in cpu["reason"] and "advocate.fit_unknown" in cpu["reason"]
    assert out["status"] == "denied" and "create_mandate" not in kinds(m) and m.payments == {}


def test_a_plain_round_still_holds_a_caution_back_and_the_next_bid_wins(tmp_path, monkeypatch):
    _caution_cpu(monkeypatch)
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog, allowance=dict(ALLOW))
    cpu = next(p for p in out["view"]["parts"] if p["part"] == "cpu")
    assert cpu["status"] == "locked" and cpu["champion"]["sellerId"] != "bargain-bin", "the market ranked the caution last"
    assert out["status"] == "paid"


# ---------------------------------------------------------------- 3: the deployed module is probed

class _Client:
    def __init__(self, err=None):
        self.err, self.calls = err, []

    def call(self, reducer, **args):
        self.calls.append((reducer, args))
        if self.err:
            raise RuntimeError(self.err)


def test_a_reducer_the_deployed_market_lacks_is_detected_from_its_404():
    assert not build.deployed_has_reducer(_Client("close_stage failed (404): No such procedure close_stage"), "close_stage", round_id="x")
    assert build.deployed_has_reducer(_Client("close_stage failed (530): no round x"), "close_stage", round_id="x")
    assert build.deployed_has_reducer(_Client(None), "close_stage", round_id="x")
    c = _Client("sql failed (400)")
    assert build.deployed_has_reducer(c, "close_stage", round_id="x") and c.calls == [("close_stage", {"round_id": "x"})]


def test_knockout_falls_back_to_plain_rounds_when_the_source_has_it_but_the_deployment_does_not(tmp_path):
    index = tmp_path / "index.ts"
    index.write_text("export const open_knockout_round = spacetimedb.reducer({}, () => {});\n")
    notes = []
    absent = {"referee": _Client("close_stage failed (404): No such procedure")}
    present = {"referee": _Client("close_stage failed (530): no round probe")}
    assert build.resolve_knockout("auto", absent, notes.append, module=index) is False and any("not republished" in n or "plain rounds" in n for n in notes)
    assert build.resolve_knockout("auto", present, notes.append, module=index) is True
    assert build.resolve_knockout("off", present, notes.append, module=index) is False
    assert build.resolve_knockout("on", absent, notes.append, module=index) is True
    index.write_text("export const place_bid = spacetimedb.reducer({}, () => {});\n")
    probe = {"referee": _Client("close_stage failed (530): no round probe")}
    assert build.resolve_knockout("auto", probe, notes.append, module=index) is False and probe["referee"].calls == [], "no probe when the source lacks it"


# ---------------------------------------------------------------- 4: the stand-in keeps the real market's rules

def _bid(m, seller, rid, bid_id, price, cond="new", stage=None):
    m.client(f"seller:{seller}").call("place_bid", id=bid_id, round_id=rid, persona=seller.title(), origin="SIM", source="",
                                      lines=[{"sku_spec": "x", "offered_condition": cond, "unit_price": price, "quantity": 1}])


def _open(m, rid="r", need="n", ko=False, cap=100.0):
    m.client("buyer").call("post_need", id=need, spend_limit=cap, items=[{"sku_spec": "x", "condition": "new", "allowed_conditions": []}])
    m.client("referee").call("open_knockout_round" if ko else "open_round", round_id=rid, need_id=need, **({"stage_window_s": 15, "max_stages": 3} if ko else {"window_s": 12}))


def test_the_stand_in_rejects_a_line_whose_condition_the_goal_does_not_allow():
    m = SimMarket()
    _open(m)
    _bid(m, "a", "r", "b1", 50.0, cond="unknown")
    _bid(m, "b", "r", "b2", 60.0)
    m.client("referee").call("close_round", round_id="r")
    out = {row[3]: row for row in m.rows}
    assert out["a"][5] == 0 and out["a"][7] == ["condition: offered unknown, goal asks for new"] and out["b"][5] == 1


def test_the_stand_in_refuses_an_allowance_above_the_ladders_top_step():
    m = SimMarket()
    with pytest.raises(RuntimeError, match="ladder"):
        m.client("referee").call("set_allowance", buyer_id="vidyut", per_purchase_limit=601.0, period_limit=1500.0, period="month")
    with pytest.raises(RuntimeError, match="ladder"):
        m.client("referee").call("set_allowance", buyer_id="vidyut", per_purchase_limit=600.0, period_limit=1501.0, period="month")
    m.client("referee").call("set_allowance", buyer_id="vidyut", per_purchase_limit=600.0, period_limit=1500.0, period="month")
    assert m.allow["per"] == 600.0


def test_a_stage_two_offer_below_the_floor_stands_and_is_knocked_out_at_the_close_not_refused():
    m = SimMarket()
    _open(m, ko=True)
    for s, p in (("a", 50.0), ("b", 60.0), ("c", 70.0)):
        m.client(f"seller:{s}").call("set_floor", sku_spec="x", floor=40.0 if s == "b" else 10.0)
        _bid(m, s, "r", f"{s}1", p)
    m.client("referee").call("close_stage", round_id="r")
    _bid(m, "a", "r", "a2", 45.0)
    _bid(m, "b", "r", "b2", 30.0)    # below b's own floor of 40
    m.client("referee").call("close_stage", round_id="r")
    stage2 = {row[3]: row for row in m.rows if row[13] == 2}
    assert stage2["b"][14] == "knocked_out" and "floor" in stage2["b"][7][0] and stage2["a"][14] == "champion"


def test_the_stand_in_knocks_out_the_last_place_by_price_and_never_holds_a_caution_back_in_a_knockout():
    m = SimMarket()
    _open(m, ko=True)
    for s, p in (("a", 50.0), ("b", 60.0), ("c", 70.0)):
        _bid(m, s, "r", f"{s}1", p)
    m.client("referee").call("attach_advocate_card", bid_id="a1", recommendation="caution", rule_id="advocate.fit_unknown", text="length unknown",
                             source_url="", origin="SIM")
    m.client("referee").call("close_stage", round_id="r")
    stage1 = {row[3]: row for row in m.rows if row[13] == 1}
    assert stage1["c"][14] == "knocked_out" and stage1["a"][5] == 1 and stage1["a"][7] == [], "the caution leads on price and nothing holds it back"


# ---------------------------------------------------------------- 5: the hosted copy carries no money or identity

def _full_view(tmp_path):
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW))
    return out["view"]


def test_the_public_view_drops_mandates_payees_amounts_and_the_buyer(tmp_path):
    v = _full_view(tmp_path)
    assert v["approval"]["mandates"] and v["buyerId"] and v["budget"] and v["spent"], "the local view keeps them"
    pub = build.public_view(v)
    text = json.dumps(pub)
    for key in ("mandates", "mandateHash", "payee", "buyerId", "budget", "spent", "total", "sellers"):
        assert key not in text.replace('"sellerId"', ""), key
    assert set(pub) == {"goalId", "origin", "parts", "checks", "events", "approval"} and set(pub["approval"]) == {"state"}
    assert pub["approval"]["state"] == v["approval"]["state"] and pub["goalId"] == v["goalId"]
    for p in pub["parts"]:
        assert set(p) <= {"part", "label", "status", "origin", "needId", "roundId", "champion", "reason"}
        if "champion" in p:
            assert set(p["champion"]) <= {"persona", "landed", "origin", "sourceUrl"}
    assert any(p.get("champion", {}).get("landed") for p in pub["parts"]), "a champion's landed price after the close is public"


def test_the_public_events_carry_no_spend_or_payment_lines_and_no_budget(tmp_path):
    v = _full_view(tmp_path)
    pub = build.public_view(v)
    assert {e["kind"] for e in pub["events"]} <= {"plan", "round_open", "knockout", "locked", "clash", "replan"}
    texts = " ".join(e["text"] for e in pub["events"])
    assert "Build ready" not in texts and "payment" not in texts.lower() and "budget" not in texts.lower() and "Calling" not in texts
    assert any(e["kind"] == "plan" for e in pub["events"]) and any(e["kind"] == "clash" for e in pub["events"])
    assert not [e for e in pub["events"] if e["kind"] == "plan" and "$" in e["text"]]
    # the local view keeps every line
    assert {"call", "approved", "receipt"} <= {e["kind"] for e in v["events"]}


def test_what_reaches_the_publisher_is_the_public_view_and_the_local_files_keep_the_full_one(tmp_path):
    sent = []
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW), publisher=lambda gid, text: sent.append(text), publish_interval=0.0)
    assert json.loads(sent[-1]) == build.public_view(out["view"])
    assert all("mandateHash" not in t and "buyerId" not in t for t in sent)
    assert json.loads((tmp_path / build.VIEW_FILE).read_text()) == out["view"] and "mandateHash" in (tmp_path / build.VIEW_FILE).read_text()


# ---------------------------------------------------------------- 6: the demo cap

def test_the_default_goal_is_two_thousand_one_hundred_dollars():
    assert build.demo_plan().cap == 2100.0 and build.PLANNER_CAP_CENTS == 210_000
    plan, source = build.planned_build(planner=None)
    assert plan.cap == 2100.0 and plan.parts[0].budget >= 1300.0


# ---------------------------------------------------------------- 7: one line per (a, b, rule)

def test_checks_have_one_line_per_pair_and_rule_and_the_worse_state_wins():
    cpu = {"name": "8-core CPU", "attrs": {"socket": "AM5", "tdp_w": 105, "vendor": "AMD"}}
    gpu = {"name": "RTX 5070 Ti", "attrs": {"chipset": "RTX 5070 Ti", "length_mm": 300}}
    lines = build.fit_checks(OWNED, {"cpu": cpu, "gpu": gpu})
    keys = [(l["a"], l["b"], l["rule"]) for l in lines]
    assert len(keys) == len(set(keys)) and ("gpu", "psu", "power") in keys
    small = [build.PartSpec("psu", "300 W PSU", 0.0, {"wattage": 300, "form_factor": "ATX", "pcie_16pin": 0}), OWNED[1]]
    bad = build.fit_checks(small, {"cpu": cpu, "gpu": gpu})
    power = [l for l in bad if l["rule"] == "power"]
    assert len(power) == 1 and power[0]["state"] == "clash" and power[0]["source"].startswith("fit.")
