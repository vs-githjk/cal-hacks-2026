from data.mirror.price_spread import summarize


def card(store, price, condition="new", stock=None, sold_date=None):
    listing = {"price": price, "stock": stock}
    if sold_date:
        listing["sold_date"] = sold_date
    return {"id": f"{store}:{price}", "category": "gpu", "price": price, "condition": condition, "listing": listing,
            "snapshot_date": "2026-10-24T05:08:00+00:00", "source": store, "snapshot_id": f"{store}-x", "attrs": {"chipset": "RTX 5070 Ti"}}


def test_asks_vs_dated_sold_baseline():
    cards = {"bestbuy": [card("bestbuy", 1200.0), card("bestbuy", 1300.0)], "bh": [card("bh", None), card("bh", 999.0, stock="out_of_stock")],
             "ebay_sold": [card("ebay_sold", 800.0, "used", sold_date="2026-10-23"), card("ebay_sold", 1000.0, sold_date="2026-10-23"),
                           card("ebay_sold", 900.0, sold_date="2026-10-22")]}
    s = summarize(cards)
    assert s["asks"]["n"] == 2 and s["asks"]["min"] == 1200.0 and s["asks"]["median"] == 1250.0
    assert s["baseline"]["n"] == 3 and s["baseline"]["median"] == 900.0
    assert s["baseline"]["dates"] == ("2026-10-22", "2026-10-23")
    assert s["ask_vs_baseline_pct"]["median"] == 39  # 1250 vs 900
    assert s["no_price"] == 1 and s["out_of_stock"] == 1  # the $999 out-of-stock ask is not in the range
