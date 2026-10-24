import pytest

from agents.buyer.planner import plan

OWNED = {"psu": {"name": "750 W PSU", "wattage": 750, "form_factor": "ATX", "pcie_16pin": 1},
         "case": {"name": "Owned case", "max_gpu_length_mm": 305, "max_cooler_height_mm": 160,
                  "motherboard_form_factors": ["ATX", "Micro ATX"], "psu_form_factors": ["ATX"]}}


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
    assert "—" not in line and "–" not in line


def test_owned_part_gets_no_round():
    assert "gpu" not in [x["part"] for x in plan(100_000, {"gpu": {"name": "owned"}})["parts"]]


@pytest.mark.parametrize("cap", [0, -1, 1.5, True, "2000"])
def test_bad_cap_refused(cap):
    with pytest.raises(ValueError):
        plan(cap)
