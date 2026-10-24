from data.baselines import baseline, observations

AT = "2026-10-24T06:00:00+00:00"


def obs(provider, store, price, at="2026-10-24T05:08:00+00:00", stock=True, condition="new", sold=False):
    return {"provider": provider, "store": store, "sku": "rtx 5070 ti", "price": price, "in_stock": stock, "condition": condition,
            "kind": "sold" if sold else "ask", "observed_at": at, "url": f"https://{store}.example/x", "origin": "MIRROR"}


def test_sold_and_out_of_stock_never_enter_the_retail_median():
    rows = [obs("apify", "bestbuy", 1249.99), obs("apify", "microcenter", 1299.99), obs("apify", "bh", 999.0, stock=False),
            obs("apify", "ebay_sold", 640.0, sold=True)]
    b = baseline("rtx 5070 ti", AT, rows=rows)
    assert b["n"] == 2 and b["median"] == 1274.99 and b["sold"]["n"] == 1


def test_one_provider_is_not_enough():
    b = baseline("rtx 5070 ti", AT, rows=[obs("apify", "bestbuy", 1249.99), obs("apify", "microcenter", 1299.99)])
    assert b["status"] == "one_source" and b["providers"] == ["apify"]


def test_two_providers_within_24h_make_a_baseline():
    rows = [obs("apify", "bestbuy", 1249.99), obs("brightdata", "newegg", 1269.99, at="2026-10-23T09:00:00+00:00")]
    b = baseline("rtx 5070 ti", AT, rows=rows)
    assert b["status"] == "ok" and b["providers"] == ["apify", "brightdata"]
    assert b["from"] == "2026-10-23T09:00:00+00:00" and b["to"] == "2026-10-24T05:08:00+00:00"


def test_observations_older_than_24h_are_stale():
    rows = [obs("apify", "bestbuy", 1249.99, at="2026-10-22T05:00:00+00:00"), obs("brightdata", "newegg", 1269.99, at="2026-10-22T06:00:00+00:00")]
    assert baseline("rtx 5070 ti", AT, rows=rows)["status"] == "stale"


def test_real_snapshots_load_as_retail_asks_and_sold_separately():
    rows = observations()
    assert rows and all(r["origin"] == "MIRROR" and r["provider"] == "apify" for r in rows)
    assert {r["kind"] for r in rows if r["store"] == "ebay_sold"} == {"sold"}
