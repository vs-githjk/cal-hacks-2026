from data.fit_checker import check_fit
from data.mirror.normalize import attrs_from_title, to_spec_card


def test_gpu_title_gives_chipset_the_fit_tables_know():
    cat, attrs = attrs_from_title("MSI GeForce RTX 5070 Ti 16G VENTUS 3X OC Graphics Card")
    assert cat == "gpu" and attrs["chipset"] == "RTX 5070 Ti"


def test_trademark_symbol_does_not_hide_chipset():
    assert attrs_from_title("PNY NVIDIA GeForce RTX\u2122 5070 Ti OC")[1]["chipset"] == "RTX 5070 Ti"


def test_psu_title_gives_wattage():
    assert attrs_from_title("Corsair RM850x 850W 80 PLUS Gold Fully Modular ATX Power Supply") == ("psu", {"wattage": 850, "form_factor": "ATX"})


def test_listing_normalizes_with_snapshot_and_unknowns_absent():
    item = {"title": "ASUS TUF RTX 5070 Ti OC Open Box", "url": "https://example.test/p/1",
            "price": "$749.99", "condition": "Open Box", "seller": {"name": "Shop"}}
    card = to_spec_card("newegg", item, "newegg-20261023T2200Z", "2026-10-23T22:00:00+00:00")
    assert card["origin"] == "MIRROR" and card["snapshot_id"] == "newegg-20261023T2200Z"
    assert card["condition"] == "open-box" and card["price"] == 749.99 and card["listing"]["seller"] == "Shop"
    assert "stock" not in card["listing"]


def test_mirrored_gpu_and_psu_feed_the_fit_checker():
    gpu = to_spec_card("x", {"title": "Gigabyte RTX 5070 Ti WINDFORCE"}, "s", "d")
    psu = to_spec_card("x", {"title": "Corsair RM650e 650W ATX Power Supply"}, "s", "d")
    assert check_fit([gpu, psu])["rule_id"] == "fit.psu_wattage"
