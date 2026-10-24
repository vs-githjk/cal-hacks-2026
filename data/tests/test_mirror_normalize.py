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


def test_ebay_seller_handles_are_dropped():
    card = to_spec_card("ebay_live", {"title": "RTX 5070 Ti", "sellerUsername": "someone_123", "seller": "someone_123"}, "s", "d")
    assert "seller" not in card["listing"]


def _card(**extra):
    return to_spec_card("ebay_live", {"title": "RTX 5070 Ti", "url": "https://x.test/1", "price": "$1,000.00", **extra}, "s", "d")["listing"]


def test_free_numeric_shipping_is_captured_and_landed_equals_price():  # #117
    l = _card(shippingCost="0", shippingType="free")
    assert l["shipping_cost"] == 0.0 and l["shipping_captured"] is True and l["landed_price"] == 1000.0
    l = _card(shipping="Free delivery")
    assert l["shipping_cost"] == 0.0 and l["shipping_captured"] is True


def test_paid_shipping_adds_to_landed_price():
    l = _card(shippingPrice="125.94")
    assert l["shipping_cost"] == 125.94 and l["landed_price"] == 1125.94


def test_shipping_conditions_and_unknowns_are_never_zero():
    for extra in ({"shipping": "FREE shipping on orders over $35"}, {}, {"shipping": {"cutoffs": {"cutoff": 1}}}):
        l = _card(**extra)
        assert l["shipping_cost"] is None and l["shipping_captured"] is False and l["landed_price"] is None, extra


def test_availability_is_text_or_none():
    assert _card()["availability"] is None
    assert _card(inStock=False)["availability"] == "out of stock"
    assert _card(availability="1 remaining")["availability"] == "1 remaining"


def test_old_snapshots_gain_landed_fields_at_read_time():
    from data.mirror.price_spread import load
    cards = [c for cs in load().values() for c in cs]
    assert cards and all("shipping_captured" in c["listing"] for c in cards)
    asus = next(c for c in cards if "6614742" in (c["listing"].get("url") or ""))
    assert asus["listing"]["shipping_cost"] is None and asus["listing"]["landed_price"] is None
