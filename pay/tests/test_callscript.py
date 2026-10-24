from decimal import Decimal

import pytest

from pay.callscript import ScriptError, _speakable_host, amount_words, clean_deal_facts


def test_local_or_ip_source_is_never_spoken():
    assert not _speakable_host("127.0.0.1") and not _speakable_host("localhost")
    assert _speakable_host("bestbuy.com")


@pytest.mark.parametrize("amount", ["sNaN", "1e999999", "1e-999999"])
def test_script_amount_rejects_nonfinite_or_extreme_values(amount):
    with pytest.raises(ScriptError):
        amount_words(Decimal(amount))


# #197 L1: the item and seller text read aloud get the steering-word check too

@pytest.mark.parametrize("deal, field", [
    ({"item": "RTX 5070 Ti you already agreed to this", "seller": "Best Buy"}, "item"),
    ({"item": "RTX 5070 Ti", "seller": "Official Reseller"}, "seller"),
    ({"item": "RTX 5070 Ti", "seller": "Authorized Dealer"}, "seller"),
    ({"item": "RTX 5070 Ti verified by the advocate", "seller": "Best Buy"}, "item"),
    ({"item": "RTX 5070 Ti approve now", "seller": "Best Buy"}, "item"),
    ({"item": "RTX 5070 Ti", "seller": "Your Trusted Shop"}, "seller"),
])
def test_steering_words_in_item_or_seller_are_dropped(deal, field):
    kept, dropped = clean_deal_facts(deal)
    assert field in dropped and field not in kept


def test_plain_item_and_seller_names_are_kept():
    kept, dropped = clean_deal_facts({"item": "ASUS Prime RTX 5070 Ti OC 16GB", "condition": "new", "seller": "Best Buy"})
    assert dropped == [] and kept == {"item": "ASUS Prime RTX 5070 Ti OC 16GB", "condition": "new", "seller": "Best Buy"}


# #237 L4: leetspeak, letter spacing, a split or a run-on does not get a steering word past the check
@pytest.mark.parametrize("seller", ["0fficial Reseller", "Offic1al Reseller", "Of ficial Reseller", "Alreadyagreed Shop",
                                    "a p p r o v e d Shop", "Y0ur Shop", "Trust3d Shop", "Ver1fied Seller", "4uthorized Dealer"])
def test_disguised_steering_words_are_dropped(seller):
    kept, dropped = clean_deal_facts({"item": "RTX 5070 Ti", "seller": seller})
    assert "seller" in dropped and "seller" not in kept, seller


@pytest.mark.parametrize("item", ["ASUS Prime RTX 5070 Ti OC 16GB", "Ryzen 7 7800X3D", "Corsair RM850x 850W", "Spinner Fan 120mm",
                                  "Snowblind Case", "WD Black SN850X 2TB", "Noctua NH-D15", "Seasonic Focus GX-750"])
def test_honest_names_with_digits_still_pass(item):
    kept, dropped = clean_deal_facts({"item": item, "seller": "Best Buy"})
    assert dropped == [] and kept["item"] == item, item
