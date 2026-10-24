"""PC build compatibility Actor: named parts, maker data only for exact parts we hold, caller specs win, unknown is uncertain."""
import asyncio
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


def run(monkeypatch, inp):
    actor = FakeActor(inp)
    asyncio.run(load_main(monkeypatch, actor).main())
    return actor


def test_a_run_writes_one_row_per_rule_and_a_summary(monkeypatch):
    a = run(monkeypatch, {"parts": DEMO})
    assert len(a.rows) == 11 and all(r["build_id"] == "build-1" and r["build_verdict"] == "fail" for r in a.rows)
    assert a.status[-1][0].startswith("FAIL: cooler height") and a.status[-1][1] is True and a.kv["OUTPUT"]["builds"][0]["verdict"] == "fail"


def test_batch_builds_and_an_unreadable_build_never_pass(monkeypatch):
    a = run(monkeypatch, {"builds": [{"id": "ok", "parts": {"cpu": {"name": "c", "socket": "AM5"}, "motherboard": {"name": "b", "socket": "AM5"}}},
                                     {"id": "bad", "parts": {"cpu": "not a dict"}}]})
    assert a.status[-1][0] == "2 builds: 1 pass, 0 fail, 1 uncertain"
    assert [r["rule_id"] for r in a.rows if r["build_id"] == "bad"] == ["fit.no_checks"]


def test_no_build_ends_with_a_clear_message(monkeypatch):
    a = run(monkeypatch, {})
    assert a.rows == [] and "No build given" in a.status[-1][0]
