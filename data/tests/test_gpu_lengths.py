from data.fit_checker.gpu_lengths import fits, maker_length


def test_gaming_trio_is_338mm_from_msi_and_misses_a_305mm_case():
    row = maker_length("MSI - NVIDIA GeForce RTX 5070 Ti 16G GAMING TRIO OC 16GB GDDR7")
    assert row["length_mm"] == 338 and row["source"].startswith("https://www.msi.com/")
    assert fits(row["length_mm"], 305) is False and fits(row["length_mm"], 340) is True


def test_ventus_fits_305_and_unknown_models_stay_unknown():
    assert fits(maker_length("MSI GeForce RTX 5070 Ti VENTUS 3X OC Black 16G")["length_mm"], 305) is True
    assert maker_length("NVIDIA GeForce RTX 5070 Ti Overclocked Triple Fan 16GB") is None  # brand not named: no guess
    assert fits(None, 305) is None


def test_every_row_has_a_maker_source():
    import json
    from data.fit_checker.gpu_lengths import TABLE
    hosts = ("https://www.msi.com/", "https://www.gigabyte.com/", "https://www.asus.com/", "https://www.pny.com/")
    for r in json.loads(TABLE.read_text())["models"]:
        assert r["source"].startswith(hosts) and r["length_mm"] > 0
