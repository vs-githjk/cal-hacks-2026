"""A stated delivery cost is part of the landed price (found on main: an eBay '+$29.95 delivery' listing at $1,299.00
won as if shipping were free, and it is $1,328.95 landed, over the $1,300 cap). Same-day snapshots list a URL once."""
from datetime import datetime, timezone

from demo.beats import owned_attrs
from demo.goal import build_goal, need_from_goal, vidyut_owned_parts
from demo.round import run_round
from demo.sellers import all_sellers, load_offers, mirror_sellers

NOW = datetime(2026, 10, 24, 5, 40, 0, tzinfo=timezone.utc)
ASUS_URL = "https://www.ebay.com/itm/407307072531?_skw=RTX+5070+Ti+new"


def ebay_offer(price, shipping, shipping_cost=None, item="407307072531"):
    listing = {"stock": "1 remaining", "shipping": shipping, "shipping_cost": shipping_cost}
    card = {"id": f"ebay_live:{item}", "name": "ASUS Prime GeForce RTX 5070 Ti 16GB", "price": price, "condition": "new",
            "source": f"https://www.ebay.com/itm/{item}?_skw=x", "snapshot_id": "ebay_live-test", "snapshot_date": "2026-10-24T12:17:26+00:00"}
    return {"prefix": "ebay_live", "card": card, "listing": listing}


def seller_of(price, shipping, shipping_cost=None):
    (seller,) = mirror_sellers([ebay_offer(price, shipping, shipping_cost)])
    return seller


def test_a_paid_delivery_text_becomes_the_seller_shipping_and_is_captured():
    s = seller_of(1299.00, "+$29.95 delivery")
    assert s.shipping == 29.95 and s.shipping_captured is True


def test_a_free_delivery_is_captured_as_zero():
    s = seller_of(1239.99, "Free delivery")
    assert s.shipping == 0.0 and s.shipping_captured is True


def test_a_a_stated_shipping_cost_field_wins_over_the_text():
    s = seller_of(1299.00, "see listing", shipping_cost=19.99)
    assert s.shipping == 19.99 and s.shipping_captured is True


def test_a_no_delivery_text_stays_not_captured():
    s = seller_of(1299.00, None)
    assert s.shipping == 0.0 and s.shipping_captured is False


def test_a_a_shipping_date_range_is_not_a_cost():
    s = seller_of(1299.00, "November 15 - 24")
    assert s.shipping == 0.0 and s.shipping_captured is False


def _round(extra):
    goal = build_goal("RTX 5070 Ti that fits my case, under $1,300, by Friday, new or open-box", vidyut_owned_parts(NOW), NOW)
    sellers, _ = all_sellers()
    sellers = [s for s in sellers if s.id in ("best-buy", "shady-sam")] + extra
    return run_round(need_from_goal(goal), sellers, owned_attrs(vidyut_owned_parts(NOW)), 1300.0, NOW)


def test_b_paid_delivery_listing_over_the_cap_landed_does_not_win():
    """$1,299.00 + $29.95 = $1,328.95: cheaper than Best Buy's $1,299.99 sticker but over the cap landed."""
    res = _round([seller_of(1299.00, "+$29.95 delivery")])
    assert res["winner"]["seller_id"] == "best-buy"
    assert all(r["landed"] <= 1300.0 for r in res["ranking"]["ranked"])


def test_b_paid_delivery_listing_just_under_the_cap_landed_wins_and_says_shipping_included():
    """$1,260.00 + $29.95 = $1,289.95: under the cap and under Best Buy, so it wins with the shipping named."""
    res = _round([seller_of(1260.00, "+$29.95 delivery")])
    assert res["winner"]["seller_id"].startswith("ebay-")
    assert abs(res["winner"]["landed"] - 1289.95) < 0.005


def test_c_a_listing_in_two_same_day_snapshots_is_one_offer_and_the_newest_wins(tmp_path, monkeypatch):
    import json
    from demo import sellers

    def snap(sid, price):
        return [{"id": "bestbuy:1", "category": "gpu", "name": "ASUS Prime GeForce RTX 5070 Ti", "price": price,
                 "condition": "new", "source": "https://www.bestbuy.com/site/asus/1.p", "snapshot_id": sid,
                 "snapshot_date": "2026-10-24T05:08:00+00:00", "attrs": {"chipset": "RTX 5070 Ti"}, "listing": {"stock": True}}]
    (tmp_path / "bestbuy-20261024T0508Z.json").write_text(json.dumps(snap("bestbuy-20261024T0508Z", 1249.99)))
    (tmp_path / "bestbuy-20261024T0936Z.json").write_text(json.dumps(snap("bestbuy-20261024T0936Z", 1299.99)))
    monkeypatch.setattr(sellers, "SNAPSHOTS", tmp_path)
    offers, _ = load_offers()
    assert len(offers) == 1 and offers[0]["card"]["snapshot_id"] == "bestbuy-20261024T0936Z"


def test_c_withheld_lines_name_each_listing_once():
    sellers, _ = all_sellers()
    for s in sellers:
        urls = [w["listing_url"] for w in s.withheld]
        assert len(urls) == len(set(urls)), s.id


# #188: the demo reads delivery cost with the data lane's anchored rule (data.mirror.normalize.landed)
import pytest  # noqa: E402

from demo.sellers import stated_shipping  # noqa: E402


@pytest.mark.parametrize("text", [
    "+C $12.99 delivery",                       # not USD
    "+$12.99 delivery or free over $35",        # conditional
    "Free shipping on orders over $35",         # conditional free is not free
])
def test_foreign_or_conditional_delivery_text_is_not_a_cost(text):
    assert stated_shipping({"shipping": text}) is None
    s = seller_of(1299.00, text)
    assert s.shipping_captured is False


def test_the_demo_and_the_data_lane_agree_on_every_snapshot_listing():
    from data.mirror.normalize import landed
    offers, _ = load_offers()
    for o in offers:
        listing = o["listing"]
        if isinstance(listing.get("shipping_cost"), (int, float)) and not isinstance(listing.get("shipping_cost"), bool):
            continue                                 # a numeric field wins in both
        assert stated_shipping(listing) == landed(listing, None)["shipping_cost"], listing.get("shipping")


def test_the_demo_winner_is_still_the_asus_prime_at_best_buy():
    from demo.common import Narrator
    from demo.run_demo import run_all
    b2 = run_all(say=Narrator(False))["beats"]["2"]
    assert b2["winner"]["seller_id"] == "best-buy" and b2["winner"]["landed"] == 1299.99
