

def test_local_or_ip_source_is_never_spoken():
    from pay.callscript import _speakable_host
    assert not _speakable_host("127.0.0.1") and not _speakable_host("localhost")
    assert _speakable_host("bestbuy.com")


# #197 L1: the item and seller text read aloud get the steering-word check too
import pytest  # noqa: E402

from pay.callscript import clean_deal_facts  # noqa: E402


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
