"""#345 phase 2: real fit checks in the BuildView, a re-plan on a clash (a second need and round), the planner adapter against #358's documented
output, knockout stages when the market has them, paced and staggered rounds, and the optional publisher for the hosted board.
Everything runs on demo.build_sim's in-memory market, a fake Cartesia and a virtual clock: no network, no call, no database."""
from __future__ import annotations

import json
import sys
import types

import pytest

from demo import build
from demo.build_sim import FakeMarket, make_clients
from demo.tests.test_bridge import FakeCartesia
from demo.tests.test_build import ALLOW, calls, kinds, run_build, sim_catalog

RULES = {"socket", "ddr", "case_room", "power", "cooler_height"}


def trap_catalog(spec, index):
    """The demo's own catalog: SIM sellers, and the cheapest board is an LGA1700 board (the clash the fit check finds)."""
    return build.default_catalog(spec, index, mirror=False)


# What #358's planner.plan(200_000, OWNED) returns (agents/buyer/planner.py in PR #358, read from its diff and run once outside the repo).
PLAN_358 = {
    "cap_cents": 200000,
    "owned": {"psu": {"name": "750 W PSU", "wattage": 750, "form_factor": "ATX", "pcie_16pin": 1},
              "case": {"name": "Owned case", "max_gpu_length_mm": 305, "max_cooler_height_mm": 160,
                       "motherboard_form_factors": ["ATX", "Micro ATX"], "psu_form_factors": ["ATX"]}},
    "parts": [{"part": "gpu", "budget_cents": 126585}, {"part": "cpu", "budget_cents": 28354}, {"part": "motherboard", "budget_cents": 17215},
              {"part": "memory", "budget_cents": 10126}, {"part": "storage", "budget_cents": 12151}, {"part": "cooler", "budget_cents": 5569}],
    "rules": ["fit.cpu_socket", "fit.ram_type", "fit.ram_form", "fit.ram_slots", "fit.psu_wattage", "fit.gpu_connectors", "fit.gpu_length",
              "fit.cooler_socket", "fit.cooler_height", "fit.form_factor", "fit.psu_form_factor", "fit.storage"],
    "steps": [{"kind": "plan", "line": "Plan: GPU ~$1,266, CPU ~$284, board ~$172, RAM ~$101, SSD ~$122, cooler ~$56. Your power supply and case stay."}],
}


class Clock:
    """A virtual clock: sleep moves it, so a run's timeline can be read back exactly."""
    def __init__(self):
        self.t = 0.0

    def sleep(self, s):
        self.t += max(0.0, s)

    def __call__(self):
        return self.t


def drive(tmp_path=None, *, m=None, plan=None, catalog=trap_catalog, allowance=None, stagger=None, delay=2.0, real_gpu=False, **kw):
    """A BuildRun on the in-memory market with a virtual clock. Returns (run, out, market, stamps) where stamps is [(virtual s, reducer, round id)]."""
    m = m or FakeMarket()
    clock, stamps = Clock(), []
    cartesia = FakeCartesia(lambda code: f"{code} approve")
    cartesia.shown = {}
    r = build.BuildRun(plan or build.demo_plan(), make_clients(m), catalog=catalog, allowance=allowance, cartesia=cartesia, real_gpu_round=real_gpu,
                       secret="s" * 32, out_dir=tmp_path, sleep=clock.sleep, clock=clock, delay=delay, stagger=stagger,
                       on_code=lambda code: cartesia.shown.__setitem__("code", code), call_timing={"sleep": lambda x: None, "poll": 0},
                       say=lambda s: stamps.append((clock.t, s.reducer, s.args.get("round_id"))), **kw)
    return r, r.run(), m, stamps


# ---------------------------------------------------------------- checks

OWNED = build.demo_plan().owned
AM5_CPU = {"name": "8-core CPU", "attrs": {"socket": "AM5", "tdp_w": 105, "vendor": "AMD"}}
BOARD = {"socket": "AM5", "memory_type": "DDR5", "memory_form": "DIMM", "memory_slots": 4, "form_factor": "ATX", "m2_slots": 2}


def test_the_fit_checkers_rules_become_the_boards_check_lines_with_the_rule_id_as_source():
    lines = build.fit_checks(OWNED, {"cpu": AM5_CPU, "board": {"name": "B760", "attrs": {**BOARD, "socket": "LGA1700"}}})
    sock = next(l for l in lines if l["rule"] == "socket")
    assert sock == {"a": "cpu", "b": "board", "rule": "socket", "state": "clash", "detail": "CPU socket AM5 does not match board socket LGA1700",
                    "source": "fit.cpu_socket"}
    ok = build.fit_checks(OWNED, {"cpu": AM5_CPU, "board": {"name": "B650", "attrs": BOARD}})
    assert next(l for l in ok if l["rule"] == "socket")["state"] == "ok"
    assert {l["rule"] for l in ok + lines} <= RULES and {l["state"] for l in ok + lines} <= set(build.CHECK_STATES)


def test_owned_parts_count_in_the_checks_and_a_rule_it_cannot_judge_is_unknown_never_ok():
    gpu = {"name": "RTX 5070 Ti", "attrs": {"chipset": "RTX 5070 Ti", "length_mm": 336}}
    lines = build.fit_checks(OWNED, {"gpu": gpu})
    room = next(l for l in lines if l["rule"] == "case_room")
    assert room["state"] == "clash" and (room["a"], room["b"]) == ("gpu", "case") and "336" in room["detail"]
    assert build.fit_checks(OWNED, {}) == []
    odd = build.fit_checks(OWNED, {"cpu": {"name": "x", "attrs": {}}, "board": {"name": "y", "attrs": {}}})
    assert [l["state"] for l in odd if l["rule"] == "socket"] == ["unknown"]


def test_the_view_carries_the_real_checks_from_the_locked_champions_and_the_owned_parts(tmp_path):
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog)
    checks = out["view"]["checks"]
    assert {c["rule"] for c in checks} == RULES and all(c["source"].startswith("fit.") for c in checks)
    assert all(c["state"] in ("ok", "unknown") for c in checks) and any(c["state"] == "ok" for c in checks)
    assert {(c["a"], c["b"]) for c in checks if c["rule"] == "case_room"} >= {("gpu", "case")}


# ---------------------------------------------------------------- the re-plan

def test_a_socket_clash_marks_the_part_replanned_and_opens_a_second_need_and_round(tmp_path):
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW))
    v = out["view"]
    board = next(p for p in v["parts"] if p["part"] == "board")
    assert out["status"] == "paid" and board["status"] == "replanned"
    assert board["needId"] == "need-goal-build-1-board-2" and board["roundId"] == "round-goal-build-1-board-2"
    ids = [n["id"] for n in calls(m, "post_need")]
    assert ids.count("need-goal-build-1-board") == 1 and "need-goal-build-1-board-2" in ids and len(ids) == 7
    assert [o["need_id"] for o in calls(m, "open_round")].count("need-goal-build-1-board-2") == 1
    assert all(p["status"] == "locked" for p in v["parts"] if p["part"] not in ("board", "psu", "case"))
    assert board["champion"]["bidId"].startswith("bid-need-goal-build-1-board-2-")
    assert "clash" not in {c["state"] for c in v["checks"]} and next(c for c in v["checks"] if c["rule"] == "socket")["state"] == "ok"
    paid = [d for d in calls(m, "create_mandate")]
    assert len(paid) == 6 and any(d["deal_id"].startswith("deal-bid-need-goal-build-1-board-2-") for d in paid)
    assert not any(d["deal_id"].startswith("deal-bid-need-goal-build-1-board-bargain") for d in paid)


def test_the_event_log_shows_red_then_the_swap_then_green_for_the_board(tmp_path):
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW))
    ev = [e for e in out["view"]["events"] if "board" in e["parts"]]
    kinds_ = [e["kind"] for e in ev]
    red, swap = kinds_.index("clash"), kinds_.index("replan")
    green = next(i for i, e in enumerate(ev) if e["kind"] == "locked" and "green" in e["text"])
    assert red < swap < green
    assert "LGA1700" in ev[red]["text"] and "AM5" in ev[red]["text"] and ev[red]["text"].startswith("Clash:")
    assert "need-goal-build-1-board-2" in ev[swap]["text"] and ev[green]["parts"] == ["board", "cpu"]
    assert not any("—" in e["text"] or "–" in e["text"] for e in out["view"]["events"])
    assert board_origin_ok(out["view"])


def board_origin_ok(v):
    return all(e["origin"] in ("SIM", "MIRROR", "LIVE") for e in v["events"])


def test_the_clash_is_visible_in_the_steps_replay_before_the_swap(tmp_path):
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW))
    lines = [json.loads(l) for l in (tmp_path / build.STEPS_FILE).read_text().splitlines()]
    seen = [any(c["state"] == "clash" for c in l["checks"]) for l in lines]
    assert any(seen) and not seen[-1] and seen.index(True) < len(seen) - 1
    first = next(l for l in lines if any(c["state"] == "clash" for c in l["checks"]))
    assert next(p for p in first["parts"] if p["part"] == "board")["status"] == "locked"   # red: the pick is in, the check says no


def test_a_second_clash_denies_the_build_and_pays_nothing(tmp_path):
    again = lambda spec, index, clash: build.default_catalog(spec, index, mirror=False)   # the same LGA1700 trap, again
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW), replan_catalog=again)
    assert out["status"] == "denied" and out["reason"] == "fit_clash" and "create_mandate" not in kinds(m) and m.payments == {}
    assert len([n for n in calls(m, "post_need") if "board" in n["id"]]) == 2, "one re-plan, never a third round"
    assert "socket" in out["view"]["approval"]["reason"] and "Nothing was paid" in out["view"]["approval"]["reason"]


def test_no_replan_when_nothing_clashes(tmp_path):
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog, allowance=dict(ALLOW))
    assert len(calls(m, "post_need")) == 6 and not [e for e in out["view"]["events"] if e["kind"] in ("clash", "replan")]


# ---------------------------------------------------------------- the planner adapter (#358)

def test_the_358_plan_shape_is_read_with_the_owned_specs_and_the_planners_own_line():
    p = build.plan_from_planner(PLAN_358)
    assert [x.part for x in p.parts] == ["gpu", "cpu", "board", "ram", "ssd", "cooler"] and p.cap == 2000.0
    assert [o.part for o in p.owned] == ["psu", "case"] and p.owned[1].attrs["max_gpu_length_mm"] == 305 and p.owned[0].attrs["wattage"] == 750
    assert "name" not in p.owned[0].attrs and p.plan_line.startswith("Plan: GPU ~$1,266")


def test_the_planners_line_is_the_plan_event_and_its_owned_specs_feed_the_fit_checks(tmp_path):
    plan = build.plan_from_planner(PLAN_358, goal_id="goal-build-1")
    r, out, m, stamps = drive(tmp_path, plan=plan, catalog=sim_catalog)
    first = next(e for e in out["view"]["events"] if e["kind"] == "plan")
    assert first["text"] == PLAN_358["steps"][0]["line"]
    assert any(c["rule"] == "case_room" and c["state"] == "ok" for c in out["view"]["checks"])


def test_without_the_planner_module_the_default_plan_is_used(monkeypatch):
    monkeypatch.setitem(sys.modules, "agents.buyer.planner", None)   # an import of it raises ImportError, as on a main without #358
    plan, source = build.planned_build()
    assert source == "default" and [p.part for p in plan.parts] == ["gpu", "cpu", "board", "ram", "ssd", "cooler"]


def test_with_the_planner_module_its_plan_drives_the_build(monkeypatch):
    seen = {}

    def fake_plan(cap_cents, owned=None):
        seen["cap"], seen["owned"] = cap_cents, sorted(owned or {})
        return json.loads(json.dumps(PLAN_358))
    monkeypatch.setitem(sys.modules, "agents.buyer.planner", types.SimpleNamespace(plan=fake_plan))
    plan, source = build.planned_build()
    assert source == "planner" and seen["owned"] == ["case", "psu"] and seen["cap"] == build.PLANNER_CAP_CENTS
    assert plan.plan_line.startswith("Plan: GPU") and plan.owned[0].attrs["wattage"] == 750


def test_a_planner_that_breaks_falls_back_to_the_default_plan_and_says_why(monkeypatch):
    def broken(cap_cents, owned=None):
        raise ValueError("cap_cents must be a positive whole number of cents")
    monkeypatch.setitem(sys.modules, "agents.buyer.planner", types.SimpleNamespace(plan=broken))
    notes = []
    plan, source = build.planned_build(note=notes.append)
    assert source == "default" and any("planner" in n and "default plan" in n for n in notes)


def test_the_default_plan_gpu_budget_leaves_room_for_the_demos_real_gpu_listings():
    assert build.demo_plan().parts[0].budget >= 1300.0   # the demo GPU round's bids sit just under $1,300
    assert build.PLANNER_CAP_CENTS == 210_000, "a $2,100 cap gives the planner's 1250/1975 GPU share about $1,329"


# ---------------------------------------------------------------- knockout rounds (#363)

def test_without_knockout_support_every_round_is_one_stage(tmp_path):
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog)
    assert calls(m, "open_knockout_round") == [] and calls(m, "close_stage") == [] and len(calls(m, "open_round")) == 6


def test_knockout_rounds_use_the_markets_stage_reducers_with_at_most_three_stages(tmp_path):
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog, allowance=dict(ALLOW), knockout=True)
    assert calls(m, "open_round") == [] and calls(m, "close_round") == []
    opens = calls(m, "open_knockout_round")
    assert len(opens) == 6 and all(o["max_stages"] == 3 and o["stage_window_s"] >= 6 for o in opens)
    assert out["status"] == "paid" and all(p["status"] == "locked" for p in out["view"]["parts"] if p["status"] != "owned")
    assert max(row[13] for row in m.rows) <= 3
    assert len(calls(m, "close_stage")) > 6, "a stage 2 ran"


def test_a_survivor_improves_only_below_its_own_last_offer_and_never_below_its_floor(tmp_path):
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog, allowance=dict(ALLOW), knockout=True)
    firsts = {(b["round_id"], b["seller_id"]): b for b in m.bids.values() if b["stage"] == 1}
    later = [b for b in m.bids.values() if b["stage"] > 1]
    assert later
    for b in later:
        first = firsts[(b["round_id"], b["seller_id"])]
        assert b["landed"] < first["landed"] and not b["below_floor"] and b["id"].endswith(f"-s{b['stage']}")
    for who, reducer, args in m.log:   # a stage 2 offer is the seller's own call
        if reducer == "place_bid" and "-s" in args["id"][-3:]:
            assert who == f"seller:{m.bids[args['id']]['seller_id']}"


def test_only_the_markets_champion_row_is_mandated_in_a_knockout_build(tmp_path):
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog, allowance=dict(ALLOW), knockout=True)
    champs = {row[2] for row in m.rows if row[14] == "champion"}
    mandated = {d["deal_id"][5:] for d in calls(m, "create_mandate")}
    assert mandated == champs and len(mandated) == 6
    assert not any(row[2] in mandated and row[14] != "champion" for row in m.rows)


def test_a_knockout_replan_runs_its_own_knockout_round(tmp_path):
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW), knockout=True)
    board = next(p for p in out["view"]["parts"] if p["part"] == "board")
    assert board["status"] == "replanned" and board["roundId"].endswith("board-2")
    assert [o["round_id"] for o in calls(m, "open_knockout_round")].count("round-goal-build-1-board-2") == 1


# ---------------------------------------------------------------- pacing

def test_staggered_rounds_all_open_within_ten_seconds_and_close_in_order(tmp_path):
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW), stagger=2.0)
    opens = [(t, rid) for t, red, rid in stamps if red == "open_round"]
    closes = [(t, rid) for t, red, rid in stamps if red == "close_round"]
    first6 = opens[:6]
    assert [rid for _, rid in first6] == [f"round-goal-build-1-{p}" for p in ("gpu", "cpu", "board", "ram", "ssd", "cooler")]
    assert max(t for t, _ in first6) - min(t for t, _ in first6) <= 10.0
    assert first6[-1][0] < closes[0][0], "every part's round is open before the first one closes"
    round1 = [c for c in closes if not c[1].endswith("-2")]
    assert [rid for _, rid in round1] == [rid for _, rid in first6] and [t for t, _ in round1] == sorted(t for t, _ in round1)
    assert out["status"] == "paid" and next(p for p in out["view"]["parts"] if p["part"] == "board")["status"] == "replanned"


def test_a_staggered_six_part_build_with_one_replan_fits_a_90_second_beat(tmp_path):
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW), stagger=2.0)
    last = max(t for t, red, rid in stamps if red in ("close_round", "close_stage"))
    assert last <= 90.0 and r.schedule_s <= 90.0, (last, r.schedule_s)


def test_the_demo_as_main_runs_it_with_the_real_gpu_cast_still_fits_the_beat_and_with_knockout_stages_too(tmp_path):
    for knockout in (False, True):
        r, out, m, stamps = drive(tmp_path / str(knockout), catalog=build.default_catalog, allowance=dict(ALLOW), stagger=build.STAGGER_S, real_gpu=True,
                                  knockout=knockout)
        last = max(t for t, red, rid in stamps if red in ("close_round", "close_stage"))
        assert out["status"] == "paid" and last <= 90.0 and r.schedule_s <= 90.0, (knockout, last)
        assert next(p for p in out["view"]["parts"] if p["part"] == "gpu")["champion"]["origin"] == "MIRROR"


def test_a_sequential_build_runs_one_round_at_a_time(tmp_path):
    r, out, m, stamps = drive(tmp_path, catalog=sim_catalog, allowance=dict(ALLOW))
    seq = [red for _, red, _ in stamps if red in ("open_round", "close_round")]
    assert seq == ["open_round", "close_round"] * 6


def test_staggering_never_changes_what_the_market_decides(tmp_path):
    a = drive(tmp_path / "a", allowance=dict(ALLOW), stagger=2.0)[1]["view"]
    b = drive(tmp_path / "b", allowance=dict(ALLOW), stagger=None)[1]["view"]
    pick = lambda v: {p["part"]: (p["status"], p.get("champion", {}).get("sellerId")) for p in v["parts"]}
    assert pick(a) == pick(b) and a["approval"]["total"] == b["approval"]["total"]


# ---------------------------------------------------------------- publishing for the hosted board

def test_every_view_reaches_the_publisher_and_the_last_is_the_final_view(tmp_path):
    sent = []
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW), publisher=lambda gid, text: sent.append((gid, text)), publish_interval=0.0)
    assert len(sent) > 20 and {g for g, _ in sent} == {"goal-build-1"}
    assert json.loads(sent[-1][1]) == out["view"] and all(isinstance(json.loads(t), dict) for _, t in sent)


def test_publishing_is_throttled_but_the_final_view_always_goes(tmp_path):
    sent, every = [], []
    r, out, m, stamps = drive(tmp_path / "a", allowance=dict(ALLOW), publisher=lambda gid, text: sent.append(text), publish_interval=1000.0)
    drive(tmp_path / "b", allowance=dict(ALLOW), publisher=lambda gid, text: every.append(text), publish_interval=0.0)
    assert 1 <= len(sent) < len(every) and json.loads(sent[-1]) == out["view"]   # the per-step views are thinned, the milestones and the end are not


def test_the_referee_publishes_through_the_markets_reducer(tmp_path):
    m = FakeMarket()
    clients = make_clients(m)
    notes = []
    pub = build.ViewPublisher(clients["referee"], note=notes.append)
    r, out, m, stamps = drive(tmp_path, m=m, allowance=dict(ALLOW), publisher=pub, publish_interval=0.0)
    assert m.published and m.published[-1][0] == "goal-build-1" and json.loads(m.published[-1][1]) == out["view"]
    assert all(who == "referee" for who, red, _ in m.log if red == "publish_build_view")


def test_a_publisher_that_fails_never_stops_the_build_and_says_so_once(tmp_path):
    m = FakeMarket()
    m.fail["publish_build_view"] = "unknown reducer"
    notes = []
    pub = build.ViewPublisher(make_clients(m)["referee"], note=notes.append)
    r, out, m, stamps = drive(tmp_path, m=m, allowance=dict(ALLOW), publisher=pub, publish_interval=0.0)
    assert out["status"] == "paid" and len([n for n in notes if "publish_build_view" in n]) == 1
    assert len(calls(m, "publish_build_view")) == build.ViewPublisher.MAX_FAILURES, "it stops asking after three failures"


def test_the_publisher_is_off_when_the_market_has_no_such_reducer(tmp_path):
    index = tmp_path / "index.ts"
    index.write_text("export const place_bid = spacetimedb.reducer({}, () => {});\n")
    assert not build.market_has_reducer("publish_build_view", module=index) and build.make_publisher({}, module=index) is None
    index.write_text("export const publish_build_view = spacetimedb.reducer({ goalId: t.string(), json: t.string() }, () => {});\n")
    assert build.market_has_reducer("publish_build_view", module=index)
    pub = build.make_publisher(make_clients(FakeMarket()), module=index)
    assert isinstance(pub, build.ViewPublisher)
    assert not build.market_has_reducer("publish_build_view", module=tmp_path / "missing.ts")


def test_the_view_file_and_steps_file_are_still_written_when_a_publisher_is_set(tmp_path):
    r, out, m, stamps = drive(tmp_path, allowance=dict(ALLOW), publisher=lambda gid, text: None)
    assert json.loads((tmp_path / build.VIEW_FILE).read_text()) == out["view"]
    assert len((tmp_path / build.STEPS_FILE).read_text().splitlines()) > 60


# ---------------------------------------------------------------- the dry run

def test_dry_run_shows_the_whole_build_the_replan_and_real_checks(capsys, tmp_path):
    rc = build.main(["--dry-run", "--planner", "default", "--out-dir", str(tmp_path)])
    text = capsys.readouterr().out
    assert rc == 0 and "Re-plan" in text and "Clash:" in text and "fit re-check green" in text
    assert "ONE call for the whole build" in text and "no call was placed" in text.lower()
    v = json.loads((tmp_path / build.VIEW_FILE).read_text())
    assert [p["status"] for p in v["parts"] if p["part"] == "board"] == ["replanned"]
    assert sum(1 for p in v["parts"] if p["status"] in ("locked", "replanned")) == 6 and v["approval"]["state"] == "waiting"
    assert v["checks"] and all(c["source"].startswith("fit.") and c["state"] != "clash" for c in v["checks"])
    assert not any("—" in l or "–" in l for l in text.splitlines())


def test_dry_run_touches_no_files_unless_asked(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(build, "OUT_DIR", tmp_path / "default-out")
    assert build.main(["--dry-run", "--planner", "default"]) == 0
    assert not (tmp_path / "default-out").exists()
