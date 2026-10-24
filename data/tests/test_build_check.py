"""PC build compatibility Actor: named parts, maker data only for exact parts we hold, caller specs win, unknown is uncertain."""
import asyncio

import pytest
import importlib.util
import json
import sys
import types
from pathlib import Path

from data.fit_checker.build_check import check_build

ACTOR = Path(__file__).resolve().parents[1] / "fit_checker" / "actor"
DEMO = json.loads((ACTOR / ".actor" / "input_schema.json").read_text())["properties"]["parts"]["prefill"]


def by_rule(result):
    return {c["rule_id"]: c for c in result["checks"]}


def test_the_default_build_catches_the_cooler_that_does_not_fit_from_maker_data_on_both_sides():
    r = check_build(DEMO)
    assert r["verdict"] == "fail" and r["summary"].startswith("FAIL: cooler height 155 mm exceeds case clearance 145 mm")
    h = by_rule(r)["fit.cooler_height"]
    assert any("thermalright.com" in s for s in h["sources"]) and any("fractal-design.com" in s for s in h["sources"])
    assert by_rule(r)["fit.gpu_length"]["verdict"] == "pass" and "msi.com" in by_rule(r)["fit.gpu_length"]["sources"][0]


def test_a_check_cites_only_maker_data_it_used():
    r = check_build(DEMO)
    assert by_rule(r)["fit.cpu_socket"]["sources"] == []  # both sockets came from the input, not the Asus page


def test_the_callers_own_spec_wins_over_maker_data():
    parts = {**DEMO, "cooler": {"name": "Thermalright Peerless Assassin 120 SE", "height_mm": 140}}
    r = check_build(parts)
    assert by_rule(r)["fit.cooler_height"]["verdict"] == "pass" and "height_mm" not in r["parts"]["cooler"]["maker_data"]


def test_an_unknown_part_is_uncertain_never_guessed():
    r = check_build({"cooler": {"name": "Some Cooler 9000"}, "case": {"name": "Fractal Design North"}})
    assert by_rule(r)["fit.cooler_height"]["verdict"] == "uncertain" and r["verdict"] == "uncertain"


def test_maker_lengths_apply_only_to_the_rtx_5070_ti_model_named():
    r = check_build({"gpu": {"name": "MSI GeForce RTX 5080 16G GAMING TRIO OC"}, "case": {"name": "x", "max_gpu_length_mm": 300}})
    assert "length_mm" not in r["parts"]["gpu"]["attrs"] and by_rule(r)["fit.gpu_length"]["verdict"] == "uncertain"


def test_wrong_ram_generation_fails_from_the_boards_maker_page():
    r = check_build({"motherboard": {"name": "Asus PRIME B650-PLUS WIFI"}, "memory": {"name": "kit", "type": "DDR4", "form": "DIMM"}})
    c = by_rule(r)["fit.ram_type"]
    assert c["verdict"] == "fail" and "asus.com" in c["sources"][0]


def load_main(monkeypatch, actor):
    apify = types.ModuleType("apify")
    apify.Actor = actor
    pkg = types.ModuleType("src.data.fit_checker.build_check")
    pkg.check_build = check_build
    for name, mod in (("apify", apify), ("src", types.ModuleType("src")), ("src.data", types.ModuleType("src.data")),
                      ("src.data.fit_checker", types.ModuleType("src.data.fit_checker")), ("src.data.fit_checker.build_check", pkg)):
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("build_actor_main_under_test", ACTOR / "src" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeActor:
    def __init__(self, inp):
        self.inp, self.rows, self.kv, self.status = inp, [], {}, []
        self.charges, self.fail_charge, self.limit = [], False, 99

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_input(self):
        return self.inp

    async def push_data(self, rows):
        self.rows += rows if isinstance(rows, list) else [rows]

    async def set_value(self, k, v):
        self.kv[k] = v

    async def set_status_message(self, msg, is_terminal=None):
        self.status.append((msg, is_terminal))

    async def get_value(self, k):
        return self.kv.get(k)

    async def charge(self, event_name, count):
        self.charges.append(event_name)
        if self.fail_charge:
            raise RuntimeError("not on pay-per-event")
        return types.SimpleNamespace(event_charge_limit_reached=len(self.charges) >= self.limit)

    class log:
        warning = staticmethod(print)


def run(monkeypatch, inp, **kw):
    actor = FakeActor(inp)
    for k, v in kw.items():
        setattr(actor, k, v)
    asyncio.run(load_main(monkeypatch, actor).main())
    return actor


def test_a_run_writes_one_row_per_rule_and_a_summary(monkeypatch):
    a = run(monkeypatch, {"parts": DEMO})
    assert len(a.rows) == 11 and all(r["build_id"] == "build-1" and r["build_verdict"] == "fail" for r in a.rows)
    assert a.status[-1][0].startswith("FAIL: cooler height") and a.status[-1][1] is True and a.kv["OUTPUT"]["builds"][0]["verdict"] == "fail"


def test_batch_builds_and_an_unreadable_build_never_pass(monkeypatch):
    a = run(monkeypatch, {"builds": [{"id": "ok", "parts": {"cpu": {"name": "c", "socket": "AM5"}, "motherboard": {"name": "b", "socket": "AM5"}}},
                                     {"id": "bad", "parts": {"cpu": "not a dict"}}]})
    assert a.status[-1][0] == "2 build(s): 1 pass, 0 fail, 1 uncertain"
    assert [r["rule_id"] for r in a.rows if r["build_id"] == "bad"] == ["fit.no_checks"]


def test_no_build_ends_with_a_clear_message(monkeypatch):
    a = run(monkeypatch, {})
    assert a.rows == [] and "No build given" in a.status[-1][0]


GOOD = {"cpu": {"name": "c", "socket": "AM5"}, "motherboard": {"name": "b", "socket": "AM5"}}


def test_one_charge_per_build_that_ran_a_rule_and_none_for_unreadable_or_empty(monkeypatch):
    a = run(monkeypatch, {"builds": [{"id": "1", "parts": GOOD}, {"id": "2", "parts": {"cpu": "bad"}},
                                     {"id": "3", "parts": {"cpu": {"name": "alone"}}}, {"id": "4", "parts": GOOD}]})
    assert a.charges == ["build-checked", "build-checked"] and a.kv["STATE_next_build"] == {"index": 4, "paid": False}


def test_a_restart_resumes_after_the_saved_build_and_never_charges_it_twice(monkeypatch):
    actor = FakeActor({"builds": [{"id": "1", "parts": GOOD}, {"id": "2", "parts": GOOD}]})
    actor.kv["STATE_next_build"] = 1
    asyncio.run(load_main(monkeypatch, actor).main())
    assert actor.charges == ["build-checked"] and {r["build_id"] for r in actor.rows} == {"2"}


def test_a_failed_charge_stops_the_run_and_delivers_nothing_unpaid(monkeypatch):  # #248 item 3
    a = run(monkeypatch, {"builds": [{"id": "1", "parts": GOOD}, {"id": "2", "parts": GOOD}]}, fail_charge=True)
    assert a.rows == [] and a.status[-1][0].endswith("2 build(s) not run: the charge failed")


def test_the_limit_stops_the_run_and_the_summary_names_the_builds_not_run(monkeypatch):  # #248 item 3
    b = run(monkeypatch, {"builds": [{"id": str(i), "parts": GOOD} for i in range(3)]}, limit=1)
    assert len(b.charges) == 1 and {r["build_id"] for r in b.rows} == {"0"}
    assert b.status[-1][0] == "1 build(s): 1 pass, 0 fail, 0 uncertain; 2 build(s) not run: your charge limit was reached"
    assert b.kv["OUTPUT"]["checked"] == 1 and b.kv["OUTPUT"]["total"] == 3


# review fixes (#248)
def test_a_spent_limit_before_a_build_delivers_nothing(monkeypatch):
    actor = FakeActor({"builds": [{"id": "1", "parts": GOOD}]})

    async def spent(event_name, count):
        return types.SimpleNamespace(event_charge_limit_reached=True, charged_count=0)
    actor.charge = spent
    asyncio.run(load_main(monkeypatch, actor).main())
    assert actor.rows == [] and actor.status[-1][0].endswith("1 build(s) not run: your charge limit was reached")


def test_a_paid_build_is_redelivered_on_restart_without_a_second_charge(monkeypatch):
    actor = FakeActor({"builds": [{"id": "1", "parts": GOOD}, {"id": "2", "parts": GOOD}]})
    actor.kv["STATE_next_build"] = {"index": 0, "paid": True}
    asyncio.run(load_main(monkeypatch, actor).main())
    assert actor.charges == ["build-checked"] and [r["build_id"] for r in actor.rows] == ["1", "2"]


def test_a_resume_keeps_builds_already_reported_and_a_corrupt_state_starts_over(monkeypatch):
    actor = FakeActor({"builds": [{"id": "1", "parts": GOOD}, {"id": "2", "parts": GOOD}]})
    actor.kv["STATE_next_build"] = 1
    actor.kv["OUTPUT"] = {"builds": [{"build_id": "1", "verdict": "fail", "summary": "FAIL: x", "checks": []}]}
    asyncio.run(load_main(monkeypatch, actor).main())
    assert [b["build_id"] for b in actor.kv["OUTPUT"]["builds"]] == ["1", "2"] and actor.status[-1][0].startswith("2 build(s): 1 pass, 1 fail")
    c = run(monkeypatch, {"builds": [{"id": "1", "parts": GOOD}]})
    c2 = FakeActor({"builds": [{"id": "1", "parts": GOOD}]})
    c2.kv["STATE_next_build"] = "abc"
    asyncio.run(load_main(monkeypatch, c2).main())
    assert len(c2.rows) == len(c.rows) == 1


def test_a_part_given_as_a_plain_name_is_still_checked():
    parts = {**DEMO, "cooler": "Thermalright Peerless Assassin 120 SE"}
    assert check_build(parts)["summary"].startswith("FAIL: cooler height 155 mm exceeds case clearance 145 mm")


@pytest.mark.parametrize("parts,word", [({**DEMO, "gpus": {"name": "x"}}, "gpus"), ({**DEMO, "cooler": 5}, "cooler"),
                                        ({**DEMO, "storage": "Samsung 990"}, "storage"), ("not a build", "build")])
def test_an_unreadable_part_or_unknown_key_makes_the_build_uncertain_and_names_it(parts, word):
    r = check_build({**parts, "cooler": {"name": "Noctua NH-U12S"}} if isinstance(parts, dict) and word != "cooler" else parts)
    assert r["verdict"] in ("uncertain", "fail") and r["verdict"] != "pass" and any(word in p for p in r["problems"])


def test_a_partial_build_never_says_a_plain_pass():
    r = check_build({"cpu": {"name": "c", "socket": "AM5"}, "motherboard": {"name": "b", "socket": "AM5"}})
    assert r["verdict"] == "pass" and not r["complete"] and r["rules_run"] == 1
    assert r["summary"].startswith("PASS for the 1 rule(s) that could run; not given: memory, gpu, psu, case, cooler")


def test_maker_rows_need_the_brand_in_the_title():
    r = check_build({"gpu": {"name": "Zotac Gaming GeForce RTX 5070 Ti Prime"}, "case": {"name": "x", "max_gpu_length_mm": 310}})
    assert "length_mm" not in r["parts"]["gpu"]["attrs"] and by_rule(r)["fit.gpu_length"]["verdict"] == "uncertain"


def test_the_nr200p_uses_the_lower_glass_panel_clearance():
    r = check_build({"cooler": {"name": "Thermalright Peerless Assassin 120 SE"}, "case": {"name": "Cooler Master MasterBox NR200P"}})
    assert by_rule(r)["fit.cooler_height"]["reason"] == "cooler height 155 mm exceeds case clearance 153 mm"


def test_sibling_figures_and_chipset_estimates_are_cited_as_such():
    r = check_build({"gpu": {"name": "ASUS TUF Gaming GeForce RTX 5070 Ti OC"}, "case": {"name": "x", "max_gpu_length_mm": 340},
                     "psu": {"name": "p", "wattage": 850}})
    assert "sibling model" in by_rule(r)["fit.gpu_length"]["sources"][0]
    assert any("estimate" in s for s in by_rule(r)["fit.psu_wattage"]["sources"])


def test_case_strings_and_zero_are_read_sensibly():
    r = check_build({"cpu": {"name": "c", "socket": "am5"}, "motherboard": {"name": "b", "socket": "AM5", "form_factor": "ATX"},
                     "gpu": {"name": "g", "length_mm": "300"}, "case": {"name": "k", "max_gpu_length_mm": 0, "motherboard_form_factors": "ATX"}})
    assert by_rule(r)["fit.cpu_socket"]["verdict"] == "pass" and by_rule(r)["fit.form_factor"]["verdict"] == "pass"
    assert by_rule(r)["fit.gpu_length"]["verdict"] == "uncertain" and any("max_gpu_length_mm" in p for p in r["problems"])
    assert r["parts"]["gpu"]["attrs"]["length_mm"] == 300


def test_rows_say_where_their_numbers_came_from():
    r = check_build(DEMO)
    assert by_rule(r)["fit.cooler_height"]["origin"].startswith("MIRROR") and by_rule(r)["fit.ram_slots"]["origin"] == "your input"
