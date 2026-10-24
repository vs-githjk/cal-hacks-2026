import pytest

from agents.buyer.planner import plan, resolve

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


def offer(seller, dollars, **spec):
    return {"seller": seller, "price_cents": dollars * 100, "spec": spec}


AM5 = {"socket": "AM5", "memory_type": "DDR5", "memory_form": "DIMM", "memory_slots": 4, "form_factor": "ATX", "m2_slots": 2}


def offers(boards=None):
    return {
        "gpu": [offer("Best Buy", 1199, name="RTX 5070 Ti long", chipset="RTX 5070 Ti", length_mm=336),
                offer("Central Computers", 1249, name="RTX 5070 Ti", chipset="RTX 5070 Ti", length_mm=304)],
        "cpu": [offer("Best Buy", 279, name="Ryzen 7 7700X", socket="AM5", tdp_w=105, vendor="AMD")],
        "motherboard": boards or [offer("B&H", 169, name="B650 board", **AM5)],
        "memory": [offer("Amazon", 99, name="32 GB DDR5", memory_type="DDR5", memory_form="DIMM", modules=2)],
        "storage": [offer("Best Buy", 119, name="2 TB NVMe", interface="NVMe")],
        "cooler": [offer("Amazon", 45, name="Tall cooler", height_mm=165, sockets=["AM5"]),
                   offer("Central Computers", 53, name="Low cooler", height_mm=155, sockets=["AM5"])],
    }


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
