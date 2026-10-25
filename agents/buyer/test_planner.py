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
    assert r["picks"]["gpu"]["seller"] == "Silicon Sally's Surplus" and r["picks"]["cooler"]["spec"]["name"] == "Low cooler"
    assert {k["rule_id"] for k in r["knockouts"]} == {"fit.gpu_length", "fit.cooler_height"}
    assert r["total_cents"] == 196_800 and r["steps"][-1]["line"] == "Build locked: 6 parts, 3 sellers, $1,968."


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
    assert lines[0].startswith("Plan:") and lines[-1] == "Build locked: 6 parts, 3 sellers, $1,988."


def test_resolve_returns_checks_and_a_swap_carries_its_own():
    r = run()
    assert r["status"] == "locked" and r["checks"] and all(c["verdict"] != "fail" for c in r["checks"])
    swap = next(s for s in r["steps"] if s["kind"] == "swap")
    assert swap["checks"] and not [c for c in swap["checks"] if c["verdict"] == "fail" and "B650 board" in c["parts"]]
    assert {c["rule_id"] for c in swap["checks"]} >= {"fit.cpu_socket"}
    assert "checks" not in next(s for s in r["steps"] if s["kind"] == "pick")


def test_blocked_build_still_returns_checks():
    boards = [offer("B&H", 149, name="B760 board", **{**AM5, "socket": "LGA1700"})]
    assert "checks" in resolve(plan(200_000, OWNED), offers(boards))


def test_uncertain_check_needs_a_check_and_does_not_lock():
    unknown_type = {k: v for k, v in AM5.items() if k != "memory_type"}
    r = resolve(plan(200_000, OWNED), offers([offer("B&H", 169, name="B650 board", **unknown_type)]))
    assert r["status"] == "needs_check" and len(r["picks"]) == 6
    assert any(c["verdict"] == "uncertain" for c in r["checks"])
    kinds = [s["kind"] for s in r["steps"]]
    assert "locked" not in kinds and kinds[-1] == "needs_check"
    assert "swap" not in kinds and "B650 board" in r["picks"]["motherboard"]["spec"]["name"]
    line = r["steps"][-1]["line"]
    assert "board" in line and "\u2014" not in line and "\u2013" not in line


def _one_gpu(*gpus):
    return resolve(plan(200_000, OWNED), {**offers(), "gpu": list(gpus)})


GPU = dict(name="RTX 5070 Ti", chipset="RTX 5070 Ti", length_mm=304)


def test_origin_is_carried_and_defaults_to_sim():
    r = run()
    assert all(x["origin"] == "SIM" for x in r["picks"].values())
    assert {k["origin"] for k in r["knockouts"]} == {"SIM"}
    live = _one_gpu({**offer("Byte Bros Outlet", 1200, **GPU), "origin": "LIVE"})
    assert live["picks"]["gpu"]["origin"] == "LIVE"
    for bad in (None, "live", 5):
        o = {**offer("Byte Bros Outlet", 1200, **GPU), "origin": bad}
        assert _one_gpu(o)["picks"]["gpu"]["origin"] == "SIM"
    o = offer("Byte Bros Outlet", 1200, **GPU)
    del o["origin"]
    assert _one_gpu(o)["picks"]["gpu"]["origin"] == "SIM"


def test_not_orderable_offer_never_wins_even_when_mirror_and_cheapest():
    cheap = {**offer("Mirror store", 900, **GPU), "origin": "MIRROR", "orderable": False}
    r = _one_gpu(cheap, offer("Byte Bros Outlet", 1200, **GPU))
    assert r["picks"]["gpu"]["seller"] == "Byte Bros Outlet"
    assert r["knockouts"][0]["rule_id"] == "offer.not_orderable" and r["knockouts"][0]["origin"] == "MIRROR"
    assert r["knockouts"][0]["reason"] == "cannot be ordered"


def test_fitting_mirror_offer_can_win_and_keeps_its_origin():
    cheap = {**offer("Mirror store", 900, **GPU), "origin": "MIRROR"}
    r = _one_gpu(cheap, offer("Byte Bros Outlet", 1200, **GPU))
    assert r["status"] == "locked" and r["picks"]["gpu"]["seller"] == "Mirror store"
    assert r["picks"]["gpu"]["origin"] == "MIRROR"
    assert not [k for k in r["knockouts"] if k["rule_id"] == "offer.mirror"]


def test_floor_ignores_a_later_cheapest_offer_that_is_not_orderable():
    base = offers()
    bad_cpu = {**offer("FlashDeal Frankie", 1, name="cheap cpu"), "orderable": False}
    later = {**base, "cpu": base["cpu"] + [bad_cpu]}
    naive = sum(min(o["price_cents"] for o in later[k]) for k in ("cpu", "motherboard", "memory", "storage", "cooler"))
    price = 200_000 - naive  # fits only if the unorderable offer counted toward the floor
    p = plan(200_000, OWNED)
    assert price > next(x["budget_cents"] for x in p["parts"] if x["part"] == "gpu")
    r = resolve(p, {**later, "gpu": [{**offer("Big GPU", price, **GPU), "price_cents": price}]})
    assert r["knockouts"][0]["rule_id"] == "budget.over" and r["status"] == "blocked"


@pytest.mark.parametrize("price", [0, -5, 12.5, "100", None, True])
def test_no_real_price_never_wins(price):
    bad = {**offer("FlashDeal Frankie", 1, **GPU), "price_cents": price}
    r = _one_gpu(bad, offer("Byte Bros Outlet", 1200, **GPU))
    assert r["picks"]["gpu"]["seller"] == "Byte Bros Outlet"
    assert r["knockouts"][0]["rule_id"] == "offer.bad_price" and r["knockouts"][0]["reason"] == "has no real price"


@pytest.mark.parametrize("spec", [None, {}])
def test_offer_without_spec_is_knocked_out(spec):
    bare = {"seller": "FlashDeal Frankie", "price_cents": 100_000, "spec": spec}
    r = _one_gpu(bare, offer("Byte Bros Outlet", 1200, **GPU))
    assert r["picks"]["gpu"]["seller"] == "Byte Bros Outlet"
    assert r["knockouts"][0]["rule_id"] == "offer.no_spec"
    assert r["knockouts"][0]["reason"] == "has no part details to check"


def test_all_parts_owned_is_blocked_not_locked():
    from agents.buyer.planner import PARTS
    r = resolve(plan(200_000, {**{k: {"name": k} for k in PARTS}}), {})
    assert r["status"] == "blocked" and r["picks"] == {} and r["total_cents"] == 0
    assert r["steps"][-1]["line"] == "Nothing to buy: every part is already yours."
    assert "locked" not in [s["kind"] for s in r["steps"]]

