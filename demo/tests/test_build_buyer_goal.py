"""#253: the build runner builds from the buyer's own goal (--buyer-id X, no --goal-id), or from a planner JSON (--plan FILE); the default run is
unchanged. Offline: the in-memory market stands in for SpacetimeDB (its my_goals view answers the buyer's own identity only, as the real one does)."""
from __future__ import annotations

import json

import pytest

from demo import build
from demo.build_sim import FakeMarket, SimMarket, make_clients
from demo.tests.test_build import ALLOW, PLANNER_PLAN, calls, kinds, sim_catalog

OWNED_ITEMS = [{"sku_spec": "psu 750w", "condition": "new", "variant": "retail", "quantity": 1, "skipped_owned_part_id": "owned-1"},
               {"sku_spec": "case", "condition": "new", "variant": "retail", "quantity": 1, "skipped_owned_part_id": "owned-2"}]


def item(sku, owned=""):
    return {"sku_spec": sku, "condition": "new", "variant": "retail", "quantity": 1, "skipped_owned_part_id": owned}


def post(m, goal_id="g-1", buyer="vidyut", cap=2100.0, items=None, typ="build_by_date", deadline="2026-10-31T23:59:00Z"):
    m.goal_reader = buyer
    make_clients(m)["buyer"].call("post_goal", id=goal_id, buyer_id=buyer, type=typ, cap=cap, deadline=deadline, po_number="", origin="SIM",
                                  items=items if items is not None else [item("rtx 5070 ti"), *OWNED_ITEMS])


# ---------------------------------------------------------------- reading the goal

def test_the_latest_active_build_goal_of_the_buyer_is_read_with_its_items():
    m = SimMarket()
    post(m, "old", cap=1000.0)
    post(m, "new", cap=2100.0)
    goal, items = build.read_buyer_goal(make_clients(m)["buyer"], "vidyut")
    assert goal == {"id": "new", "buyer_id": "vidyut", "type": "build_by_date", "cap": 2100.0, "deadline": "2026-10-31T23:59:00Z"}
    assert [i["sku_spec"] for i in items] == ["rtx 5070 ti", "psu 750w", "case"] and items[1]["skipped_owned_part_id"] == "owned-1"


def test_only_an_active_build_by_date_goal_counts():
    m = SimMarket()
    post(m, "p", typ="part_by_date")
    post(m, "closed")
    m.goal_state["closed"] = "DONE"
    with pytest.raises(build.GoalNotFound) as e:
        build.read_buyer_goal(make_clients(m)["buyer"], "vidyut")
    assert "no ACTIVE build_by_date goal" in str(e.value) and "vidyut" in str(e.value)


def test_no_goal_at_all_is_a_clear_error_that_names_the_identity_rule():
    with pytest.raises(build.GoalNotFound) as e:
        build.read_buyer_goal(make_clients(SimMarket())["buyer"], "someone-else")
    assert "someone-else" in str(e.value) and "own identity" in str(e.value) and "\n" not in str(e.value)


def test_the_referee_cannot_read_a_buyers_goal_so_the_runner_never_asks_it():
    m = SimMarket()
    post(m)
    with pytest.raises(build.GoalNotFound):
        build.read_buyer_goal(make_clients(m)["referee"], "vidyut")


def test_a_token_that_belongs_to_another_buyer_is_named_in_the_error():
    m = SimMarket()
    post(m, buyer="vidyut")
    with pytest.raises(build.GoalNotFound) as e:
        build.read_buyer_goal(make_clients(m)["buyer"], "someone-else")
    assert "belong to vidyut" in str(e.value) and "--buyer-token" in str(e.value)


def test_a_spacetime_timestamp_cell_becomes_an_iso_deadline():
    assert build._iso([1_793_000_000_000_000]) == "2026-10-26T07:33:20Z"
    assert build._iso({"__timestamp_micros_since_unix_epoch__": 0}) == "1970-01-01T00:00:00Z"
    with pytest.raises(build.GoalNotFound):
        build._iso(None)


# ---------------------------------------------------------------- the plan

GOAL = {"id": "g-1", "buyer_id": "vidyut", "cap": 2100.0, "deadline": "2026-10-31T23:59:00Z"}


def test_a_gpu_goal_with_owned_psu_and_case_is_a_one_part_plan_with_the_goals_cap_and_deadline():
    plan, warnings = build.plan_from_goal(GOAL, [item("RTX 5070 Ti"), *OWNED_ITEMS])
    assert [p.part for p in plan.parts] == ["gpu"] and [o.part for o in plan.owned] == ["psu", "case"] and warnings == []
    assert (plan.goal_id, plan.buyer_id, plan.cap, plan.deadline) == ("g-1", "vidyut", 2100.0, "2026-10-31T23:59:00Z")
    assert plan.parts[0].budget == 1300.0 and "SIM split" in plan.plan_line and "g-1" in plan.plan_line
    assert plan.owned[1].attrs["max_gpu_length_mm"] == 305   # the default buyer's owned parts are the demo's


def test_another_buyers_owned_parts_carry_no_invented_specs():
    plan, _ = build.plan_from_goal({**GOAL, "buyer_id": "someone-else"}, [item("rtx 5070 ti"), *OWNED_ITEMS])
    assert [o.attrs for o in plan.owned] == [{}, {}]


def test_a_full_build_goal_splits_the_cap_and_never_over_it():
    items = [item(s) for s in ("rtx 5070 ti", "8-core CPU", "ATX motherboard", "32 GB DDR5", "2 TB NVMe", "Tower cooler")] + OWNED_ITEMS
    plan, _ = build.plan_from_goal(GOAL, items)
    assert [p.part for p in plan.parts] == ["gpu", "cpu", "board", "ram", "ssd", "cooler"] and sum(p.budget for p in plan.parts) <= 2100.0
    small, _ = build.plan_from_goal({**GOAL, "cap": 1015.0}, items)
    assert sum(p.budget for p in small.parts) <= 1015.0 and small.parts[0].budget < 1300.0


def test_a_gpu_the_demo_has_no_listings_for_is_a_warning_not_a_silent_swap():
    plan, warnings = build.plan_from_goal(GOAL, [item("rtx 4070 super 12gb"), *OWNED_ITEMS])
    assert plan.parts[0].label == "RTX 5070 Ti" and len(warnings) == 1 and "rtx 4070 super 12gb" in warnings[0]


@pytest.mark.parametrize("items,why", [([item("banana")], "which part"),
                                       ([item("rtx 5070 ti"), item("rtx 5070 ti")], "twice"),
                                       ([{**item("rtx 5070 ti"), "quantity": 2}], "one of each"),
                                       ([item("psu 750w")], "cannot buy a psu"),
                                       (OWNED_ITEMS, "nothing to buy"),
                                       ([], "nothing to buy")])
def test_a_goal_the_runner_cannot_build_is_refused_with_the_reason(items, why):
    with pytest.raises(build.GoalNotFound) as e:
        build.plan_from_goal(GOAL, items)
    assert why in str(e.value)


def test_a_goal_without_a_cap_is_refused():
    with pytest.raises(build.GoalNotFound):
        build.plan_from_goal({**GOAL, "cap": 0.0}, [item("rtx 5070 ti")])


# ---------------------------------------------------------------- the run reuses the goal

def test_the_run_never_posts_a_second_goal_and_builds_the_plan_of_the_goal(tmp_path):
    m = FakeMarket()
    post(m)
    plan, _ = build.plan_from_goal(*build.read_buyer_goal(make_clients(m)["buyer"], "vidyut"))
    m.log.clear()   # the buyer's own post_goal above is not the run's
    r = build.BuildRun(plan, make_clients(m), catalog=sim_catalog, allowance=dict(ALLOW), real_gpu_round=False, reuse_goal=True, out_dir=tmp_path,
                       sleep=lambda x: None, clock=lambda: 0.0, delay=0, secret="s" * 32)
    out = r.run()
    assert calls(m, "post_goal") == [] and list(m.goals) == ["g-1"], "the buyer's own goal is the only goal"
    assert [p["part"] for p in out["view"]["parts"] if p["status"] != "owned"] == ["gpu"] and out["view"]["goalId"] == "g-1"
    assert out["view"]["budget"] == 2100.0 and "SIM split" in next(e["text"] for e in out["view"]["events"] if e["kind"] == "plan")
    assert "set_allowance" in kinds(m)


def test_without_reuse_the_run_still_posts_its_goal():
    m = FakeMarket()
    build.BuildRun(build.demo_plan(), make_clients(m), catalog=sim_catalog, real_gpu_round=False, out_dir=None, sleep=lambda x: None,
                   clock=lambda: 0.0, delay=0).run_rounds()
    assert len(calls(m, "post_goal")) == 1


def test_no_allowance_means_the_buyers_own_allowance_is_left_alone():
    m = FakeMarket()
    post(m, buyer="someone-else")
    plan, _ = build.plan_from_goal(*build.read_buyer_goal(make_clients(m)["buyer"], "someone-else"))
    m.log.clear()
    build.BuildRun(plan, make_clients(m), catalog=sim_catalog, allowance=None, real_gpu_round=False, reuse_goal=True, out_dir=None,
                   sleep=lambda x: None, clock=lambda: 0.0, delay=0).run_rounds()
    assert calls(m, "set_allowance") == [] and calls(m, "post_goal") == []


# ---------------------------------------------------------------- the command line

def test_the_default_run_is_unchanged_the_demo_plan_and_goal_build_1(capsys, tmp_path):
    assert build.main(["--dry-run", "--step-delay", "0", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    # #358 put the 6-part planner on main: with it importable the default run says "plan from the planner", without it "plan from the default"
    # (the demo plan). Either way the goal id, the six parts and the $2,100 cap are the demo's.
    assert ("plan from the planner" in out or "plan from the default" in out) and "goal-build-1" in out
    assert "6 parts to buy, 2 owned, cap $2,100.00" in out


def test_a_plan_file_is_built_through_plan_from_planner(capsys, tmp_path):
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(PLANNER_PLAN))
    assert build.main(["--dry-run", "--step-delay", "0", "--plan", str(f), "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "plan file plan.json" in out and "$2,000" in out


def test_a_bad_plan_file_is_one_error_line_and_exit_1(capsys, tmp_path):
    f = tmp_path / "plan.json"
    f.write_text(json.dumps({"cap_cents": 100, "parts": [{"part": "nonsense", "budget_cents": 50}]}))
    assert build.main(["--dry-run", "--plan", str(f)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and len(err.strip().splitlines()) == 1


def test_a_missing_plan_file_is_one_error_line(capsys, tmp_path):
    assert build.main(["--dry-run", "--plan", str(tmp_path / "nope.json")]) == 1
    assert capsys.readouterr().err.startswith("error:")


def test_buyer_id_without_a_goal_and_no_goal_in_the_market_is_a_one_line_error(capsys, monkeypatch):
    m = SimMarket()
    monkeypatch.setattr(build, "_buyer_client", lambda args: make_clients(m)["buyer"])
    assert build.main(["--buyer-id", "someone-else"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: no goal to build from for someone-else") and len(err.strip().splitlines()) == 1


def test_buyer_id_with_dry_run_says_to_use_a_plan_file(capsys):
    assert build.main(["--dry-run", "--buyer-id", "someone-else"]) == 1
    assert "--plan" in capsys.readouterr().err
