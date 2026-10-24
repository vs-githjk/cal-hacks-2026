from data.fit_checker import check_fit
from data.fit_checker.depth import cooler_vs_case, ram_vs_board


def test_cooler_height_pass_fail_unknown():  # #159
    assert cooler_vs_case("Noctua NH-L12S", "Fractal Design North")["verdict"] == "pass"
    out = cooler_vs_case("Thermalright Peerless Assassin 120 SE", "Fractal Design North")
    assert out["verdict"] == "fail" and "155" in out["reason"] and "145" in out["reason"] and out["source"]
    assert cooler_vs_case("Noctua NH-D15", "Cooler Master MasterBox NR200P")["verdict"] == "fail"
    assert cooler_vs_case("Noctua NH-U12S", "Lian Li O11 Dynamic EVO")["verdict"] == "uncertain"   # case not held
    assert cooler_vs_case("Mystery Cooler 9000", "Fractal Design North")["verdict"] == "uncertain"


def test_ram_generation_pass_fail_unknown():
    assert ram_vs_board("MSI PRO Z890-A WIFI", "DDR5")["verdict"] == "pass"
    out = ram_vs_board("MSI PRO Z790-A WIFI", "DDR4")
    assert out["verdict"] == "fail" and "DDR4" in out["reason"] and out["source"]
    assert ram_vs_board("Asus PRIME Z270-A", "DDR4")["verdict"] == "pass"
    assert ram_vs_board("Asus PRIME Z270-A", None, None)["verdict"] == "uncertain"
    assert ram_vs_board("Some Board X1", "DDR5")["verdict"] == "uncertain"


def test_so_dimm_does_not_fit_a_desktop_board_and_unstated_forms_stay_as_before():
    assert ram_vs_board("MSI PRO Z890-A WIFI", "DDR5", "SO-DIMM")["verdict"] == "fail"
    board = {"id": "m", "category": "motherboard", "name": "b", "attrs": {"memory_type": "DDR5"}, "origin": "SIM", "source": "t"}
    mem = {"id": "r", "category": "memory", "name": "k", "attrs": {"type": "DDR5", "form": "SO-DIMM"}, "origin": "SIM", "source": "t"}
    out = check_fit([board, mem])
    assert next(c for c in out["checks"] if c["rule_id"] == "fit.ram_form")["verdict"] == "uncertain"
    mem["attrs"].pop("form")
    assert all(c["rule_id"] != "fit.ram_form" for c in check_fit([board, mem])["checks"])


def test_names_match_exactly_after_normalizing_case_and_spaces():  # review fix: no loose matching
    assert ram_vs_board("MSI PRO Z790-A WIFI", "DDR5")["verdict"] == "pass"
    assert ram_vs_board("  msi   pro z790-a  wifi ", "DDR5")["verdict"] == "pass"
    ddr4_variant = ram_vs_board("MSI PRO Z790-A WIFI DDR4", "DDR4")
    assert ddr4_variant["verdict"] == "uncertain" and ddr4_variant["source"] is None and "not in our maker data" in ddr4_variant["reason"]
    assert ram_vs_board("MSI PRO B760M-A DDR4", "DDR4")["verdict"] == "uncertain"  # the maker's "DDR4 II" board is a different name
    assert cooler_vs_case("Noctua NH-D15 chromax", "Fractal Design North")["verdict"] == "uncertain"
