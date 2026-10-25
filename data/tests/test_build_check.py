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
SCHEMA = json.loads((ACTOR / ".actor" / "input_schema.json").read_text())["properties"]
FORM = {k: v["prefill"] for k, v in SCHEMA.items() if "prefill" in v}  # what the Store form and the daily test run with
DEMO = {"cpu": {"name": "AMD Ryzen 7 9700X", "vendor": "AMD", "socket": "AM5", "tdp_w": 65},
        "motherboard": {"name": "Asus PRIME B650-PLUS WIFI", "socket": "AM5", "form_factor": "ATX", "memory_slots": 4},
        "memory": {"name": "32GB (2x16GB) DDR5-6000", "type": "DDR5", "form": "DIMM", "modules": 2},
        "gpu": {"name": "MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC"},
        "psu": {"name": "Corsair RM750e", "wattage": 750, "form_factor": "ATX", "pcie_16pin": 1, "pcie_8pin": 3},
        "case": {"name": "Fractal Design North", "max_gpu_length_mm": 355, "motherboard_form_factors": ["ATX", "Micro ATX", "Mini ITX"],
                 "psu_form_factors": ["ATX"]},
        "cooler": {"name": "Thermalright Peerless Assassin 120 SE"}}


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
    a = run(monkeypatch, FORM)
    assert len(a.rows) == 11 and all(r["build_id"] == "build-1" and r["build_verdict"] == "fail" for r in a.rows)
    assert a.status[-1][0].startswith("FAIL: cooler height") and a.status[-1][1] is True and a.kv["OUTPUT"]["builds"][0]["verdict"] == "fail"


def test_batch_builds_and_an_unreadable_build_never_pass(monkeypatch):
    a = run(monkeypatch, {"builds": [{"id": "ok", "parts": {"cpu": {"name": "c", "socket": "AM5"}, "motherboard": {"name": "b", "socket": "AM5"}}},
                                     {"id": "bad", "parts": {"cpu": "not a dict"}}]})
    assert a.status[-1][0] == "2 build(s): 0 pass, 1 partial, 0 fail, 1 uncertain"
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
    assert b.status[-1][0] == "1 build(s): 0 pass, 1 partial, 0 fail, 0 uncertain; 2 build(s) not run: your charge limit was reached"
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
    assert [b["build_id"] for b in actor.kv["OUTPUT"]["builds"]] == ["1", "2"] and actor.status[-1][0].startswith("2 build(s): 0 pass, 1 partial, 1 fail")
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
    assert r["verdict"] == "partial" and not r["complete"] and r["rules_run"] == 1
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


# #262: the main input is a form
def test_the_form_default_is_the_demo_build_and_catches_the_cooler(monkeypatch):
    mod = load_main(monkeypatch, None)
    builds = mod.builds_from(FORM)
    assert len(builds) == 1 and check_build(builds[0]["parts"])["summary"] == check_build(DEMO)["summary"]
    assert check_build(builds[0]["parts"])["summary"].startswith("FAIL: cooler height 155 mm exceeds case clearance 145 mm")


def test_the_json_build_overrides_the_form_part_by_part(monkeypatch):
    mod = load_main(monkeypatch, None)
    parts = mod.builds_from({**FORM, "parts": {"cooler": {"height_mm": 140}}})[0]["parts"]
    assert parts["cooler"] == {"name": "Thermalright Peerless Assassin 120 SE", "height_mm": 140}
    assert check_build(parts)["verdict"] == "pass"


def test_a_spec_without_a_name_still_makes_the_part_and_an_empty_form_makes_no_build(monkeypatch):
    mod = load_main(monkeypatch, None)
    assert mod.builds_from({"psuWattage": 650})[0]["parts"] == {"psu": {"name": "", "wattage": 650}}
    assert mod.builds_from({}) == [] and mod.builds_from({"cpu": "  "}) == []


def test_every_form_field_is_mapped_to_a_part():
    text = (ACTOR / "src" / "main.py").read_text()
    for key in SCHEMA:
        assert key in ("parts", "builds") or f'"{key}"' in text, key


# review fixes (#278)
@pytest.mark.parametrize("part,field", [("cooler", "height_mm"), ("psu", "wattage"), ("gpu", "length_mm")])
@pytest.mark.parametrize("bad", [float("nan"), "nan", float("inf"), "-inf", "1e999"])
def test_nan_and_infinite_sizes_never_pass(part, field, bad):
    parts = {k: dict(v) for k, v in DEMO.items()}
    parts["cooler"]["height_mm"] = 140  # so the demo's real cooler fail does not hide the probe
    parts[part][field] = bad
    r = check_build(parts)
    # never a pass; where maker data exists it replaces the bad value (the 155 mm cooler then fails for real)
    assert r["verdict"] in ("uncertain", "fail") and any(f"{part}.{field}" in p for p in r["problems"])


def test_a_partial_builds_rows_say_partial_with_the_missing_parts(monkeypatch):
    a = run(monkeypatch, {"builds": [{"id": "1", "parts": GOOD}]})
    assert all(r["build_verdict"] == "partial" and r["complete"] is False for r in a.rows)
    assert a.rows[0]["missing_parts"] == ["memory", "gpu", "psu", "case", "cooler"]
    full = run(monkeypatch, FORM)
    assert all(r["complete"] is True and r["missing_parts"] == [] for r in full.rows)


def test_a_plain_string_drive_is_named_as_unreadable():
    r = check_build({**DEMO, "storage": ["Samsung 990 Pro"]})
    assert r["verdict"] != "pass" and any("drive in storage could not be read" in p for p in r["problems"])


def test_a_row_citing_only_a_chipset_estimate_is_labelled_an_estimate():
    r = check_build({"gpu": {"name": "Zotac Gaming GeForce RTX 4070 Super"}, "psu": {"name": "p", "wattage": 650}})
    assert by_rule(r)["fit.psu_wattage"]["origin"] == "estimate (NVIDIA or AMD chipset reference figures)"
    mixed = by_rule(check_build({"gpu": {"name": "MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC"}, "psu": {"name": "p", "wattage": 750}}))
    assert mixed["fit.psu_wattage"]["origin"] == "MIRROR (dated maker data, Oct 24 2026) and chipset estimates"


def test_a_resume_without_its_output_record_does_not_call_earlier_builds_not_run(monkeypatch):
    actor = FakeActor({"builds": [{"id": "1", "parts": GOOD}, {"id": "2", "parts": GOOD}]})
    actor.kv["STATE_next_build"] = {"index": 1, "paid": False}
    asyncio.run(load_main(monkeypatch, actor).main())
    line = actor.status[-1][0]
    assert "not run" not in line and "1 earlier build(s) were checked before a restart" in line


# review fixes (#286)
AIO = {"name": "360 AIO", "type": "aio", "radiator_mm": 360, "height_mm": 150, "sockets": ["AM5"]}


def test_an_aio_cooler_with_no_fitting_radiator_mount_fails():
    r = check_build({"cooler": AIO, "case": {"name": "k", "radiator_mounts_mm": [120]}})
    assert by_rule(r)["fit.cooler_height"]["verdict"] == "fail" and "360 mm radiator has no mount" in by_rule(r)["fit.cooler_height"]["reason"]
    assert r["verdict"] == "fail" and r["parts"]["cooler"]["attrs"]["type"] == "aio"  # the type is never uppercased


def test_an_aio_with_a_fitting_mount_passes_and_with_no_mounts_given_is_uncertain():
    ok = check_build({"cooler": AIO, "case": {"name": "k", "radiator_mounts_mm": [240, 360]}})
    assert by_rule(ok)["fit.cooler_height"]["verdict"] == "pass"
    unknown = check_build({"cooler": AIO, "case": {"name": "k"}})
    assert by_rule(unknown)["fit.cooler_height"]["verdict"] == "uncertain" and unknown["verdict"] == "uncertain"


def test_a_case_type_keeps_its_case_and_finds_the_board_table():
    r = check_build({"motherboard": {"name": "b", "form_factor": "ATX"}, "case": {"name": "k", "type": "ATX Mid Tower"}})
    assert by_rule(r)["fit.form_factor"]["verdict"] == "pass" and r["parts"]["case"]["attrs"]["type"] == "ATX Mid Tower"


@pytest.mark.parametrize("part,field,drive", [("psu", "pcie_16pin", None), ("psu", "pcie_8pin", None),
                                              ("motherboard", "m2_slots", {"interface": "M.2 PCIe 4.0 X4"}),
                                              ("motherboard", "sata_ports", {"interface": "SATA 6.0 Gb/s"})])
@pytest.mark.parametrize("bad", [-1, -3, "-2", 1.5])
def test_negative_and_fractional_counts_never_pass(part, field, drive, bad):
    parts = {"psu": {"name": "p", "wattage": 750, "pcie_16pin": 0, "pcie_8pin": 0}, "gpu": {"name": "MSI GeForce RTX 5070 Ti 16G GAMING TRIO OC"},
             "motherboard": {"name": "b"}}
    parts[part][field] = bad
    if drive:
        parts["storage"] = [drive]
    r = check_build(parts)
    assert r["verdict"] != "pass" and any(f"{part}.{field}" in p for p in r["problems"])
    assert all(c["verdict"] != "pass" for c in r["checks"] if c["rule_id"] in ("fit.gpu_connectors", "fit.storage"))


def test_the_lows_lowercase_sizes_comma_sockets_and_tiny_tdp():
    r = check_build({"cpu": {"name": "c", "socket": "AM5"}, "cooler": {"name": "k", "sockets": "AM5, AM4", "height_mm": 120},
                     "motherboard": {"name": "b", "socket": "am5", "form_factor": "atx"}, "case": {"name": "k", "motherboard_form_factors": "atx, micro atx"}})
    assert by_rule(r)["fit.cooler_socket"]["verdict"] == "pass" and by_rule(r)["fit.form_factor"]["verdict"] == "pass"
    assert by_rule(r)["fit.cpu_socket"]["verdict"] == "pass"
    tiny = check_build({"cpu": {"name": "c", "vendor": "AMD", "tdp_w": 1}, "psu": {"name": "p", "wattage": 650}})
    assert "cpu.tdp_w" in " ".join(tiny["problems"]) and "tdp_w" not in tiny["parts"]["cpu"]["attrs"]


def test_a_memory_type_and_form_are_still_read_in_any_case():
    r = check_build({"motherboard": {"name": "Asus PRIME B650-PLUS WIFI"}, "memory": {"name": "m", "type": "ddr5", "form": "dimm"}})
    assert by_rule(r)["fit.ram_type"]["verdict"] == "pass" and by_rule(r)["fit.ram_form"]["verdict"] == "pass"


def test_the_bundled_actor_code_runs_on_its_own(tmp_path):  # Store build 0.1.7 shipped without part_specs and failed on import
    import shutil
    import subprocess
    root = tmp_path / "fit_checker" / "actor"
    shutil.copytree(ACTOR.parent, tmp_path / "fit_checker", ignore=shutil.ignore_patterns("data", "__pycache__", "tests"))
    subprocess.run(["sh", str(root / "bundle.sh")], check=True, cwd=root)
    code = (f"import sys; sys.path.insert(0, {str(root)!r}); "
            "from src.data.fit_checker.build_check import check_build; "
            "r = check_build({'cpu': {'name': 'AMD Ryzen 7 7800X3D'}, 'motherboard': {'name': 'Asus PRIME B650-PLUS WIFI'}}); "
            "print(len(r['checks']) > 0)")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=tmp_path)
    assert out.stdout.strip() == "True", out.stderr


def test_apify_push_uploads_the_git_ignored_bundle():  # .gitignore lists src/data/, so apify push needs .actorignore to keep it
    assert "src/data/" in (ACTOR / ".gitignore").read_text().split()
    lines = [ln.strip() for ln in (ACTOR / ".actorignore").read_text().splitlines()]
    assert "!src/data/**/*.py" in lines and "!src/data/**/*.json" in lines and "src/data/" not in lines
