from data.baselines import baseline, observations

AT = "2026-10-24T06:00:00+00:00"


def obs(provider, store, price, at="2026-10-24T05:08:00+00:00", stock=True, condition="new", sold=False):
    return {"provider": provider, "store": store, "sku": "rtx 5070 ti", "price": price, "in_stock": stock, "condition": condition,
            "kind": "sold" if sold else "ask", "observed_at": at, "url": f"https://{store}.example/x", "origin": "MIRROR"}


def test_sold_and_out_of_stock_never_enter_the_retail_median():
    rows = [obs("apify", "bestbuy", 1249.99), obs("apify", "microcenter", 1299.99), obs("apify", "bh", 999.0, stock=False),
            obs("ebay-sold", "ebay_sold", 640.0, sold=True), {**obs("ebay-sold", "ebay_sold", 640.0, sold=True), "url": "https://ebay.example/2"}]
    b = baseline("rtx 5070 ti", AT, rows=rows)
    assert b["n"] == 2 and b["ask_median"] == 1274.99 and b["median"] == 1274.99 and b["sold"]["n"] == 2 and b["sold"]["median"] == 640.0


def test_one_provider_is_not_enough():
    b = baseline("rtx 5070 ti", AT, rows=[obs("apify", "bestbuy", 1249.99), obs("apify", "microcenter", 1299.99)])
    assert b["status"] == "one_source" and b["providers"] == ["apify"]
    assert b["median"] is None and b["reference_unconfirmed"] == 1274.99


def test_amazon_rows_stay_out_of_the_median():
    rows = [obs("apify", "bestbuy", 1249.99), obs("apify", "amazon", 1389.99)]
    assert baseline("rtx 5070 ti", AT, rows=rows)["n"] == 1


def test_negative_utc_offset_parses():
    rows = [obs("apify", "bestbuy", 1249.99, at="2026-10-23T22:30:00-07:00")]
    assert baseline("rtx 5070 ti", AT, rows=rows)["n"] == 1


def test_two_providers_within_24h_make_a_baseline():
    rows = [obs("apify", "bestbuy", 1249.99), obs("apify", "microcenter", 1249.99),
            obs("brightdata", "newegg", 1269.99, at="2026-10-23T09:00:00+00:00"), obs("brightdata", "bh", 1269.99, at="2026-10-23T09:00:00+00:00")]
    b = baseline("rtx 5070 ti", AT, rows=rows)
    assert b["status"] == "ok" and b["providers"] == ["apify", "brightdata"] and b["median"] == 1259.99
    assert b["from"] == "2026-10-23T09:00:00+00:00" and b["to"] == "2026-10-24T05:08:00+00:00"


def test_observations_older_than_24h_are_stale():
    rows = [obs("apify", "bestbuy", 1249.99, at="2026-10-22T05:00:00+00:00"), obs("brightdata", "newegg", 1269.99, at="2026-10-22T06:00:00+00:00")]
    assert baseline("rtx 5070 ti", AT, rows=rows)["status"] == "stale"


def test_real_snapshots_load_as_retail_asks_and_sold_separately():
    rows = observations()
    assert rows and all(r["origin"] == "MIRROR" and r["provider"] in ("apify", "apify-b", "ebay-sold") for r in rows)
    assert {r["kind"] for r in rows if r["store"] == "ebay_sold"} == {"sold"}


def test_second_actor_family_rows_carry_their_own_provider():  # #47
    rows = observations()
    b_rows = [r for r in rows if r["provider"] == "apify-b"]
    assert b_rows and all(r["origin"] == "MIRROR" and r["store"] == "bestbuy" for r in b_rows)


def test_real_feed_has_a_two_provider_baseline():
    rows = observations()
    b = baseline("rtx 5070 ti", max(r["observed_at"] for r in rows), rows=rows)
    assert b["status"] == "ok" and b["providers"] == ["apify", "apify-b"] and b["median"] is not None


def test_same_listing_from_two_providers_is_counted_once():  # fixes for #109
    a, b = obs("apify", "bestbuy", 1249.99), obs("apify-b", "bestbuy", 1249.99, at="2026-10-24T08:51:00+00:00")
    c = obs("apify", "bestbuy", 1259.99)
    for r, u in ((a, "u1"), (b, "u1"), (c, "u2")):
        r["url"] = u
    out = baseline("rtx 5070 ti", "2026-10-24T09:00:00+00:00", [a, b, c])
    assert out["n"] == 2 and out["ask_median"] == 1254.99 and out["providers"] == ["apify", "apify-b"] and out["status"] == "one_source"
    assert "re-check" in out["note"]


def sold_obs(price, sold_date, url="https://ebay.example/1"):
    return {**obs("ebay-sold", "ebay_sold", price, sold=True), "sold_date": sold_date, "url": url}


def test_two_owners_make_a_baseline_and_the_two_medians_stay_apart():  # #124
    rows = [obs("apify", "bestbuy", 1249.99), obs("apify", "microcenter", 1299.99), sold_obs(640.0, "2026-10-23"),
            sold_obs(640.0, "2026-10-22", "https://ebay.example/2")]
    b = baseline("rtx 5070 ti", AT, rows=rows)
    assert b["status"] == "ok" and b["owners"] == ["eBay sold", "retailer listings (Apify)"]
    assert b["ask_median"] == 1274.99 == b["median"] and b["sold"]["median"] == 640.0
    assert baseline("rtx 5070 ti", AT, rows=rows + [sold_obs(100.0, "2026-10-22", "https://ebay.example/3")])["ask_median"] == 1274.99


def test_one_observation_from_an_owner_is_a_thin_baseline_not_a_median():  # #291: one ask plus one sold row is n=1 per owner
    rows = [obs("apify", "bestbuy", 1249.99), sold_obs(640.0, "2026-10-23")]
    b = baseline("rtx 5070 ti", AT, rows=rows)
    assert b["status"] == "thin" and b["median"] is None and set(b["thin_owners"]) == {"eBay sold", "retailer listings (Apify)"}
    b = baseline("rtx 5070 ti", AT, rows=rows + [obs("apify", "microcenter", 1299.99)])
    assert b["status"] == "thin" and b["thin_owners"] == ["eBay sold"] and b["median"] is None


def test_two_apify_families_on_the_same_urls_are_one_owner():
    rows = [obs("apify", "bestbuy", 1249.99), obs("apify-b", "bestbuy", 1249.99, at="2026-10-24T05:30:00+00:00")]
    b = baseline("rtx 5070 ti", AT, rows=rows)
    assert b["status"] == "one_source" and b["owners"] == ["retailer listings (Apify)"]


def test_two_apify_families_on_different_urls_are_still_one_owner():
    other = {**obs("apify-b", "microcenter", 1299.99), "url": "https://other.example/y"}
    assert baseline("rtx 5070 ti", AT, rows=[obs("apify", "bestbuy", 1249.99), other])["status"] == "one_source"


def test_sold_older_than_30_days_is_excluded():
    rows = [obs("apify", "bestbuy", 1249.99), sold_obs(640.0, "2026-09-01")]
    b = baseline("rtx 5070 ti", AT, rows=rows)
    assert b["status"] == "one_source" and b["sold"]["n"] == 0 and b["sold"]["median"] is None
