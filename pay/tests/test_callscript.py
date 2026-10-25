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


# #345: one call for a whole build reads "N parts from M sellers" beside the amount, from our own counts only

def _mandate(amount=1968.0):
    return {"amount": amount, "payee": "build-goal-build-1"}


def test_a_build_call_reads_the_part_count_the_seller_count_and_the_total():
    from pay.callscript import script_for
    s = script_for(_mandate(), None, {"parts": 6, "sellers": 3})
    assert s.deal_line == "Your whole build, 6 parts from 3 sellers, for one thousand nine hundred sixty eight dollars"
    assert "6 parts from 3 sellers" in s.spoken() and "One purchase" not in s.spoken()


def test_a_build_of_one_part_from_one_seller_reads_in_the_singular():
    from pay.callscript import script_for
    assert script_for(_mandate(250.0), None, {"parts": 1, "sellers": 1}).deal_line.startswith("Your whole build, 1 part from 1 seller, for ")


@pytest.mark.parametrize("deal", [{"parts": 0, "sellers": 3}, {"parts": 6}, {"sellers": 3}, {"parts": True, "sellers": 3},
                                  {"parts": "6", "sellers": 3}, {"parts": 6, "sellers": 3.5}, {"parts": 100, "sellers": 3}])
def test_a_bad_build_count_is_dropped_and_the_call_falls_back_to_one_purchase(deal):
    from pay.callscript import script_for
    kept, dropped = clean_deal_facts(deal)
    assert "parts" not in kept and "sellers" not in kept and dropped
    assert script_for(_mandate(), None, deal).deal_line.startswith("One purchase")


def test_the_build_approved_line_names_the_counts_and_never_the_payee_id():
    from pay.callscript import script_for
    s = script_for(_mandate(), None, {"parts": 6, "sellers": 3})
    assert "6 parts from 3 sellers" in s.approved_line and "build-goal-build-1" not in s.approved_line
