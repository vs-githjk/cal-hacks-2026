from data.fit_checker.power import check_power

PRIME = "ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition"
OWNED = {"wattage": 750, "pcie_16pin": 1, "pcie_8pin": 3}


def test_pass_with_750w_and_native_16pin():
    out = check_power(PRIME, OWNED)
    assert out["status"] == "pass" and out["rec_psu_w"] == 750 and "native" in out["reason"]
    assert out["source"].startswith("https://www.asus.com/")


def test_fail_when_the_psu_is_below_the_recommendation():
    assert check_power(PRIME, {**OWNED, "wattage": 650})["status"] == "fail"
    assert check_power("ASUS TUF Gaming GeForce RTX 5070 Ti", OWNED)["status"] == "fail"  # maker says 850 W


def test_caution_when_the_card_adapter_is_needed():
    out = check_power("GIGABYTE GeForce RTX 5070 Ti GAMING OC 16G", {"wattage": 750, "pcie_16pin": 0, "pcie_8pin": 3})
    assert out["status"] == "caution" and "adapter" in out["reason"]
    assert check_power("GIGABYTE GeForce RTX 5070 Ti GAMING OC 16G", {"wattage": 750, "pcie_16pin": 0, "pcie_8pin": 2})["status"] == "fail"


def test_unknown_model_and_unknown_wattage_is_uncertain():
    out = check_power("NVIDIA GeForce RTX 5070 Ti 16GB", {"pcie_16pin": 1})
    assert out["status"] == "uncertain" and out["rec_psu_w"] == 750 and "chipset" in out["reason"]
    assert check_power(PRIME, {"wattage": 750})["status"] == "uncertain"


def test_owned_psu_fixture_is_labelled_and_sourced():
    import json
    from data.fit_checker import power
    d = json.loads(power.OWNED_PSU.read_text())
    assert d["origin"] == "SIM ownership" and d["source"].startswith("https://www.corsair.com/")
    assert check_power(PRIME, d)["status"] == "pass"


def test_other_chipsets_never_pass_on_the_5070_ti_rows():  # #156
    for title, rec in (("ASUS PRIME GeForce RTX 5080 OC", 850), ("MSI GeForce RTX 5090 GAMING TRIO", 1000)):
        out = check_power(title, OWNED)
        assert out["rec_psu_w"] == rec and out["status"] == "fail" and "nvidia.com chipset reference" in out["source"], title
    unknown = check_power("ASUS PRIME GeForce RTX 9999", OWNED)
    assert unknown["status"] == "uncertain" and unknown["rec_psu_w"] is None
    assert check_power("some graphics card", OWNED)["status"] == "uncertain"


def test_brand_words_match_whole_words_only():
    for text in ("stuff RTX 5070 Ti 16GB", "Amazon Prime GeForce RTX 5070 Ti", "pnyx GeForce RTX 5070 Ti"):
        out = check_power(text, OWNED)
        assert "chipset reference" in out["source"] and out["rec_psu_w"] == 750, text
    assert check_power("PNY GeForce RTX 5070 Ti", OWNED)["source"].startswith("https://www.pny.com/")
