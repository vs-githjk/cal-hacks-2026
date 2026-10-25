"""normalize.landed reads eBay's stated "+$N delivery|shipping" as a shipping cost (issue #175)."""
from data.mirror.normalize import landed


def test_plus_dollar_delivery_and_shipping_are_read_as_cost():
    for text in ("+$12.99 delivery", "+ $12.99 shipping", "+$1,012.50 Delivery."):
        out = landed({"shipping": text}, 100.0)
        assert out["shipping_captured"] is True
    assert landed({"shipping": "+$12.99 delivery"}, 100.0)["landed_price"] == 112.99


def test_other_currencies_and_conditions_stay_unknown():
    for text in ("+C $12.99 delivery", "+$12.99 delivery in 3 days or free over $35", "+12.99 shipping"):
        out = landed({"shipping": text}, 100.0)
        assert out["shipping_cost"] is None and out["landed_price"] is None
