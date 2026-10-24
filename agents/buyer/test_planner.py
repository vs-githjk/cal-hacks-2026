import pytest

from agents.buyer.planner import plan, resolve, split
from agents.buyer.build_plan_demo import AM5, CLASH_BOARDS, OWNED, offer, offers, run

def test_six_part_plan_with_a_budget_each():
    p = plan(200_000, OWNED)
    assert [x["part"] for x in p["parts"]] == ["gpu", "cpu", "motherboard", "memory", "storage", "cooler"]
    assert sum(x["budget_cents"] for x in p["parts"]) == 200_000
    budgets = {x["part"]: x["budget_cents"] for x in p["parts"]}
    assert 120_000 < budgets["gpu"] < 130_000 and 25_000 < budgets["cpu"] < 30_000
    for rule in ("fit.cpu_socket", "fit.ram_type", "fit.gpu_length", "fit.psu_wattage", "fit.cooler_height"):
        assert rule in p["rules"]
    line = p["steps"][0]["line"]
    assert line.startswith("Plan: GPU ~$") and "Your power supply and case stay." in line
    assert "\u2014" not in line and "\u2013" not in line


def test_owned_part_gets_no_round():
    assert "gpu" not in [x["part"] for x in plan(100_000, {"gpu": {"name": "owned"}})["parts"]]


@pytest.mark.parametrize("cap", [0, -1, 1.5, True, "2000"])
def test_bad_cap_refused(cap):
    with pytest.raises(ValueError):
        plan(cap)


def test_six_rounds_lock_a_build_with_fit_knockouts():
    r = resolve(plan(200_000, OWNED), offers())
    assert r["status"] == "locked" and len(r["picks"]) == 6
    assert r["picks"]["gpu"]["seller"] == "Central Computers" and r["picks"]["cooler"]["spec"]["name"] == "Low cooler"
    assert {k["rule_id"] for k in r["knockouts"]} == {"fit.gpu_length", "fit.cooler_height"}
    assert r["total_cents"] == 196_800 and r["steps"][-1]["line"] == "Build locked: 6 parts, 4 sellers, $1,968."


def test_socket_clash_triggers_a_board_swap():
    boards = [offer("B&H", 149, name="B760 board", **{**AM5, "socket": "LGA1700"}), offer("B&H", 169, name="B650 board", **AM5)]
    r = resolve(plan(200_000, OWNED), offers(boards))
    kinds = [s["kind"] for s in r["steps"] if s.get("part") == "motherboard"]
    assert kinds == ["clash", "swap"]
    clash = next(s for s in r["steps"] if s["kind"] == "clash")
    assert clash["rule_id"] == "fit.cpu_socket" and clash["with"] == ["cpu"] and "LGA1700" in clash["line"]
    assert r["picks"]["motherboard"]["spec"]["name"] == "B650 board" and r["status"] == "locked"


def test_no_board_fits_blocks_and_pays_nothing():
    boards = [offer("B&H", 149, name="B760 board", **{**AM5, "socket": "LGA1700"})]
    r = resolve(plan(200_000, OWNED), offers(boards))
    assert r["status"] == "blocked" and "motherboard" not in r["picks"]
    assert r["steps"][-1]["line"].endswith("Nothing was paid.")


def test_over_budget_board_triggers_reallocation():
    p = plan(200_000, OWNED)
    r = run()
    assert [s["kind"] for s in r["steps"] if s.get("part") == "motherboard"] == ["clash", "swap", "reallocate"]
    assert r["status"] == "locked" and r["total_cents"] == 198_800 <= p["cap_cents"]
    # the board's overage (and the GPU and CPU savings) moved to the parts still open
    left = split(200_000 - (1249 + 279 + 189) * 100, ["memory", "storage", "cooler"])
    assert r["budgets"]["memory"] == left["memory"]


def test_over_budget_with_no_room_under_the_cap_is_knocked_out():
    r = resolve(plan(200_000, OWNED), {**offers(), "gpu": [offer("Best Buy", 1650, name="RTX 5080", chipset="RTX 5080", length_mm=300)]})
    assert r["status"] == "blocked" and r["knockouts"][0]["rule_id"] == "budget.over"
    assert "cap leaves no room" in r["knockouts"][0]["reason"]


def test_demo_lines_have_no_dashes_and_tell_the_story():
    lines = [s["line"] for s in run()["steps"]]
    assert not any("\u2014" in x or "\u2013" in x for x in lines)
    assert lines[0].startswith("Plan:") and lines[-1] == "Build locked: 6 parts, 4 sellers, $1,988."
