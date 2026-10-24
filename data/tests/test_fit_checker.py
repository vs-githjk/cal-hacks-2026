"""c2 fit checker tests. Real part combinations; specs from the makers' pages (see data/fit_checker/tables.py)."""
from data.fit_checker import check_fit
from data.fit_checker.normalize import from_dataset


def card(cat, name="", **attrs):
    return {"id": f"{cat}:{name}", "category": cat, "name": name, "attrs": attrs, "origin": "SIM", "source": "test"}


def rule(out, rule_id):
    return next(c for c in out["checks"] if c["rule_id"] == rule_id)


# dataset-shaped rows (docyx/pc-part-dataset field names)
R7_9800X3D = from_dataset("cpu", {"name": "AMD Ryzen 7 9800X3D", "microarchitecture": "Zen 5", "tdp": 120})
R7_5800X3D = from_dataset("cpu", {"name": "AMD Ryzen 7 5800X3D", "microarchitecture": "Zen 3", "tdp": 105})
R5_5600X = from_dataset("cpu", {"name": "AMD Ryzen 5 5600X", "microarchitecture": "Zen 3", "tdp": 65})
I5_14600K = from_dataset("cpu", {"name": "Intel Core i5-14600K", "microarchitecture": "Raptor Lake Refresh", "tdp": 125})
I9_14900K = from_dataset("cpu", {"name": "Intel Core i9-14900K", "microarchitecture": "Raptor Lake Refresh", "tdp": 125})
U7_265K = from_dataset("cpu", {"name": "Intel Core Ultra 7 265K", "microarchitecture": "Arrow Lake", "tdp": 125})
TR_7960X = from_dataset("cpu", {"name": "AMD Threadripper 7960X", "microarchitecture": "Zen 4", "tdp": 350})

B650 = from_dataset("motherboard", {"name": "Asus PRIME B650-PLUS WIFI", "socket": "AM5", "form_factor": "ATX"})
B550 = from_dataset("motherboard", {"name": "MSI B550 GAMING GEN3", "socket": "AM4", "form_factor": "ATX"})
B450 = from_dataset("motherboard", {"name": "MSI B450 TOMAHAWK MAX", "socket": "AM4", "form_factor": "ATX"})
Z790 = from_dataset("motherboard", {"name": "MSI PRO Z790-A WIFI", "socket": "LGA1700", "form_factor": "ATX"})
B760_D4 = from_dataset("motherboard", {"name": "MSI PRO B760M-A DDR4 II", "socket": "LGA1700", "form_factor": "Micro ATX"})
B650I = from_dataset("motherboard", {"name": "Gigabyte B650I AORUS ULTRA", "socket": "AM5", "form_factor": "Mini ITX"})

DDR5_6000 = from_dataset("memory", {"name": "Corsair Vengeance RGB 32 GB", "speed": [5, 6000], "modules": [2, 16]})
DDR4_3200 = from_dataset("memory", {"name": "Corsair Vengeance LPX 16 GB", "speed": [4, 3200], "modules": [2, 8]})

RTX5070TI = from_dataset("video-card", {"name": "MSI VENTUS 3X OC", "chipset": "GeForce RTX 5070 Ti", "length": 303})
RTX4090_STRIX = from_dataset("video-card", {"name": "Asus ROG STRIX GAMING OC", "chipset": "GeForce RTX 4090", "length": 358})
PSU_650 = from_dataset("power-supply", {"name": "Corsair RM650e", "type": "ATX", "wattage": 650})
PSU_750 = from_dataset("power-supply", {"name": "Corsair RM750e", "type": "ATX", "wattage": 750})
PSU_850 = from_dataset("power-supply", {"name": "Corsair RM850x", "type": "ATX", "wattage": 850})

NR200P = card("case", "Cooler Master MasterBox NR200P", type="Mini ITX Tower", psu_form_factors=["SFX", "SFX-L"], max_gpu_length_mm=330, max_cooler_height_mm=155)
NORTH = card("case", "Fractal Design North", type="ATX Mid Tower", max_gpu_length_mm=355, max_cooler_height_mm=145)
LANCOOL216 = card("case", "Lian Li Lancool 216", type="ATX Mid Tower", max_gpu_length_mm=392, max_cooler_height_mm=180)
NH_D15 = card("cooler", "Noctua NH-D15", height_mm=168, sockets=["AM4", "AM5", "LGA1700", "LGA1851"])
PA120 = card("cooler", "Thermalright Peerless Assassin 120 SE", height_mm=155, sockets=["AM4", "AM5", "LGA1700", "LGA1851"])
SSD_990 = from_dataset("internal-hard-drive", {"name": "Samsung 990 Pro", "form_factor": "M.2-2280", "interface": "M.2 PCIe 4.0 X4"})


# 1-7 CPU socket
def test_zen5_on_am5_passes_with_bios_note():
    out = check_fit([R7_9800X3D, B650])
    assert rule(out, "fit.cpu_socket")["verdict"] == "pass"
    assert any("BIOS" in n for n in out["notes"])


def test_am5_cpu_on_am4_board_fails():
    out = check_fit([R7_9800X3D, B550])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.cpu_socket"
    assert "AM5" in out["reasons"][0] and "AM4" in out["reasons"][0]


def test_am4_cpu_on_am5_board_fails():
    assert check_fit([R7_5800X3D, B650])["verdict"] == "fail"


def test_zen3_on_b450_passes_with_bios_note():
    out = check_fit([R5_5600X, B450])
    assert out["verdict"] == "pass" and any("BIOS" in n for n in out["notes"])


def test_raptor_lake_on_z790_passes():
    assert rule(check_fit([I5_14600K, Z790]), "fit.cpu_socket")["verdict"] == "pass"


def test_arrow_lake_on_lga1700_fails():
    out = check_fit([U7_265K, Z790])
    assert out["verdict"] == "fail" and "LGA1851" in out["reasons"][0]


def test_threadripper_socket_is_not_guessed():
    assert TR_7960X["attrs"].get("socket") is None
    assert check_fit([TR_7960X, B650])["verdict"] == "uncertain"


# 8-11 RAM
def test_ddr4_on_am5_board_fails():
    out = check_fit([B650, DDR4_3200])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.ram_type"


def test_ddr5_on_am5_board_passes():
    assert check_fit([B650, DDR5_6000])["verdict"] == "pass"


def test_lga1700_board_memory_type_unknown_is_uncertain():
    out = check_fit([Z790, DDR5_6000])
    assert rule(out, "fit.ram_type")["verdict"] == "uncertain"


def test_ddr5_on_ddr4_named_board_fails():
    assert check_fit([B760_D4, DDR5_6000])["rule_id"] == "fit.ram_type"


# 12-14 PSU wattage and connectors
def test_5070ti_9800x3d_on_650w_is_underpowered():
    out = check_fit([R7_9800X3D, RTX5070TI, PSU_650])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.psu_wattage"


def test_5070ti_9800x3d_on_850w_has_headroom():
    assert rule(check_fit([R7_9800X3D, RTX5070TI, PSU_850]), "fit.psu_wattage")["verdict"] == "pass"


def test_4090_14900k_on_750w_fails():
    assert check_fit([I9_14900K, RTX4090_STRIX, PSU_750])["rule_id"] == "fit.psu_wattage"


def test_16pin_gpu_on_psu_with_one_8pin_fails():
    psu = card("psu", "old 850", wattage=850, form_factor="ATX", pcie_8pin=1, pcie_16pin=0)
    out = check_fit([R7_9800X3D, RTX5070TI, psu])
    assert rule(out, "fit.gpu_connectors")["verdict"] == "fail"


def test_16pin_gpu_on_native_12v2x6_psu_passes():
    psu = card("psu", "RM850x 2024", wattage=850, form_factor="ATX", pcie_8pin=4, pcie_16pin=1)
    assert rule(check_fit([RTX5070TI, psu]), "fit.gpu_connectors")["verdict"] == "pass"


# 15-16 GPU length
def test_strix_4090_too_long_for_north():
    out = check_fit([RTX4090_STRIX, NORTH])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.gpu_length"


def test_ventus_5070ti_fits_nr200p():
    assert rule(check_fit([RTX5070TI, NR200P]), "fit.gpu_length")["verdict"] == "pass"


def test_case_without_gpu_clearance_is_uncertain():
    case = card("case", "unknown case", type="ATX Mid Tower")
    assert rule(check_fit([RTX5070TI, case]), "fit.gpu_length")["verdict"] == "uncertain"


# 17-18 cooler height
def test_nh_d15_too_tall_for_nr200p():
    out = check_fit([NH_D15, NR200P])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.cooler_height"


def test_pa120_exactly_fits_nr200p():
    assert rule(check_fit([PA120, NR200P]), "fit.cooler_height")["verdict"] == "pass"


# 19 form factor
def test_atx_board_in_itx_case_fails():
    out = check_fit([B650, NR200P])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.form_factor"


def test_itx_board_in_itx_case_passes():
    assert rule(check_fit([B650I, NR200P]), "fit.form_factor")["verdict"] == "pass"


# 20 storage
def test_nvme_on_board_without_m2_fails():
    board = card("motherboard", "old board", socket="AM4", form_factor="ATX", memory_type="DDR4", m2_slots=0, sata_ports=6)
    assert check_fit([board, SSD_990])["rule_id"] == "fit.storage"


def test_nvme_on_am5_board_passes():
    assert rule(check_fit([B650, SSD_990]), "fit.storage")["verdict"] == "pass"


# aggregation and safety
def test_full_demo_build_passes():
    out = check_fit([R7_9800X3D, B650, DDR5_6000, RTX5070TI, PSU_850, LANCOOL216, PA120, SSD_990])
    connectors = rule(out, "fit.gpu_connectors")["verdict"]
    assert connectors == "uncertain"  # dataset PSU rows carry no connector counts
    assert out["verdict"] == "uncertain" and out["rule_id"] == "fit.gpu_connectors"


def test_fail_outranks_uncertain():
    out = check_fit([TR_7960X, B650, DDR4_3200])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.ram_type"


def test_empty_attrs_never_raise():
    out = check_fit([card("cpu"), card("motherboard"), card("gpu"), card("psu"), card("case")])
    assert out["verdict"] == "uncertain"


def test_atx_psu_in_sfx_only_case_fails():
    out = check_fit([PSU_850, NR200P])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.psu_form_factor"


# review fixes (Vidyut, Fri 22:00)
def test_cpu_card_without_power_info_is_uncertain_not_gpu_only():
    psu = card("psu", "1000 W", wattage=1000, form_factor="ATX")
    gpu = card("gpu", "5090", chipset="RTX 5090", length_mm=304)
    assert rule(check_fit([card("cpu"), gpu, psu]), "fit.psu_wattage")["verdict"] == "uncertain"


def test_eatx_board_in_atx_mid_tower_by_type_is_uncertain():
    board = card("motherboard", "EATX board", socket="AM5", form_factor="EATX")
    case = card("case", "mid tower", type="ATX Mid Tower")
    assert rule(check_fit([board, case]), "fit.form_factor")["verdict"] == "uncertain"


def test_sfx_psu_in_atx_tower_is_uncertain():
    sfx = card("psu", "SF750", wattage=750, form_factor="SFX")
    assert rule(check_fit([sfx, NORTH]), "fit.psu_form_factor")["verdict"] == "uncertain"
    listed = card("case", "atx case", type="ATX Mid Tower", psu_form_factors=["ATX"])
    assert rule(check_fit([sfx, listed]), "fit.psu_form_factor")["verdict"] == "uncertain"


def test_5070ti_adapter_needs_two_8pin_per_nvidia():
    psu = card("psu", "850 two 8-pin", wattage=850, form_factor="ATX", pcie_8pin=2, pcie_16pin=0)
    assert rule(check_fit([R7_9800X3D, RTX5070TI, psu]), "fit.gpu_connectors")["verdict"] == "pass"


def test_pa120_does_not_fit_the_north():  # fractal-design.com: 145 mm cooler clearance
    assert check_fit([PA120, NORTH])["rule_id"] == "fit.cooler_height"


def test_psu_exactly_at_need_passes_and_ten_below_fails():
    import re
    need = int(re.search(r"need (\d+) W", rule(check_fit([R7_9800X3D, RTX5070TI, PSU_850]), "fit.psu_wattage")["reason"]).group(1))
    at = lambda w: rule(check_fit([R7_9800X3D, RTX5070TI, card("psu", "x", wattage=w, form_factor="ATX")]), "fit.psu_wattage")["verdict"]
    assert at(need) == "pass" and at(need - 10) == "fail"
