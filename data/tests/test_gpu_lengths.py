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


MAKER_HOSTS = ("https://www.msi.com/", "https://www.gigabyte.com/", "https://www.asus.com/", "https://www.pny.com/")


def test_every_in_cap_mirror_listing_has_a_maker_length_or_says_why_not():  # #116
    from data.fit_checker.gpu_lengths import report
    rows = [r for r in report() if r["origin"] == "MIRROR" and r["price"] and r["price"] <= 1300]
    assert rows
    for r in rows:
        assert (r["length_used_mm"] and r["source"].startswith(MAKER_HOSTS)) or r["note"] == "model not identifiable from listing", r["title"]


def test_listing_length_from_title_and_url():
    from data.fit_checker.gpu_lengths import listing_length
    url = ("https://www.bestbuy.com/product/asus-prime-nvidia-geforce-rtx-5070-ti-oc-edition-16gb-gddr7-pci-express-5-0-"
           "graphics-card-black/JJGGLHJX4K/sku/6614742")
    out = listing_length(url, "ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition")
    assert out["length_mm"] == 304 and out["source"].startswith("https://www.asus.com/")
    assert listing_length("", "NVIDIA GeForce RTX 5070 Ti 16GB") == {"length_mm": None, "note": "model not identifiable from listing"}
