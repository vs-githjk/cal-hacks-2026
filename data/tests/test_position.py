from data.baselines.position import price_position

AS_OF = "2026-10-24T09:00:00+00:00"
SKU = "rtx 5070 ti"
ASUS = "ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition"      # 304 mm, fits
VENTUS = "MSI GeForce RTX 5070 Ti VENTUS 3X OC Black 16G"         # 303 mm, fits
TRIO = "MSI - NVIDIA GeForce RTX 5070 Ti 16G GAMING TRIO OC"      # 338 mm, too long


def row(store, price, title=ASUS, stock=True, condition="new", at="2026-10-24T05:00:00+00:00", kind="ask", url=None, **kw):
    return {"provider": "apify", "store": store, "sku": SKU, "title": title, "price": price, "in_stock": stock, "condition": condition,
            "kind": kind, "observed_at": at, "url": url or f"https://{store}.example/{price}", "origin": "MIRROR", **kw}


BASE = [row("bestbuy", 1299.99), row("microcenter", 1399.0, VENTUS), row("bh", 1349.0, VENTUS)]


def test_one_source_wording_has_no_sold_clause_and_never_says_savings():
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=BASE)
    assert out["status"] == "one_source" and out["rank"] == 1 and out["of_n"] == 3
    assert out["sentence"] == "Cheapest fitting new card of 3 listings at 3 stores, Oct 24"
    assert "savings" not in out["sentence"].lower() and "sold" not in out["sentence"]


def test_ok_wording_adds_the_sold_clause_only_when_price_is_under_it():
    sold = [row("ebay_sold", 1500.0, kind="sold", provider="ebay-sold", sold_date="2026-10-23", url=f"https://ebay.example/{i}") for i in (1, 2)]
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=BASE + sold)
    assert out["status"] == "ok" and out["sentence"].endswith("and $200.01 under the 30-day eBay sold median (mixed condition, n = 2)")
    above = price_position(SKU, 1600.0, "new", AS_OF, rows=BASE + sold)
    assert "under" not in above["sentence"] and "(30-day eBay sold median, mixed condition: $1,500.00, n = 2)" in above["sentence"]
    assert above["sentence"].startswith("4th cheapest fitting new card")


def test_other_condition_and_out_of_stock_listings_are_excluded():
    rows = BASE + [row("newegg", 999.0, condition="used"), row("newegg", 1000.0, stock=False, url="https://newegg.example/oos"),
                   row("newegg", 1001.0, condition="open-box", url="https://newegg.example/ob")]
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=rows)
    assert out["of_n"] == 3 and out["rank"] == 1


def test_a_card_too_long_for_the_case_is_not_fitting():
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=BASE + [row("newegg", 1100.0, TRIO)])
    assert out["of_n"] == 3 and out["too_long"] == 1 and out["rank"] == 1
    assert price_position(SKU, 1299.99, "new", AS_OF, max_gpu_length_mm=340, rows=BASE + [row("newegg", 1100.0, TRIO)])["of_n"] == 4


def test_unidentifiable_model_is_counted_not_assumed_to_fit():
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=BASE + [row("newegg", 1000.0, "NVIDIA GeForce RTX 5070 Ti 16GB")])
    assert out["unknown_fit"] == 1 and out["of_n"] == 3 and out["rank"] == 1


def test_a_relisted_url_counts_once_and_old_captures_drop_out():
    rows = BASE + [row("bestbuy", 1289.99, url="https://bestbuy.example/1299.99", at="2026-10-24T08:00:00+00:00"),
                   row("bh", 900.0, VENTUS, at="2026-10-22T05:00:00+00:00", url="https://bh.example/old")]
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=rows)
    assert out["of_n"] == 3 and out["cheapest_fitting"]["price"] == 1289.99


def test_singular_wording():
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=BASE[:1])
    assert out["sentence"] == "Cheapest fitting new card of 1 listing at 1 store, Oct 24"


def test_unknown_condition_at_a_first_party_retailer_counts_as_new_only_for_new():
    mc = row("microcenter", 1250.0, "NVIDIA GeForce RTX 5070 Ti PRIME Overclocked Triple Fan 16GB", condition="unknown")
    assert price_position(SKU, 1299.99, "new", AS_OF, rows=BASE + [mc])["of_n"] == 4
    assert price_position(SKU, 1299.99, "open-box", AS_OF, rows=BASE + [mc])["of_n"] == 0
    assert price_position(SKU, 1299.99, "open-box", AS_OF, rows=BASE + [mc])["rank"] is None


def test_a_tie_at_rank_one_is_said_and_names_the_other_listing():
    rows = BASE + [row("microcenter", 1299.99, ASUS, url="https://microcenter.example/prime")]
    out = price_position(SKU, 1299.99, "new", AS_OF, subject_url="https://bestbuy.example/1299.99", rows=rows)
    assert out["rank"] == 1 and out["sentence"].startswith("Tied cheapest fitting new card of 4 listings at 3 stores")
    assert out["tied_with"] == [{"store": "microcenter", "url": "https://microcenter.example/prime", "price": 1299.99,
                                 "observed_at": "2026-10-24T05:00:00+00:00"}]
    assert price_position(SKU, 1299.99, "new", AS_OF, rows=BASE)["tied_with"] == []
    assert price_position(SKU, 1299.99, "new", AS_OF, rows=BASE)["sentence"].startswith("Cheapest fitting")
    assert not price_position(SKU, 1349.0, "new", AS_OF, rows=rows)["sentence"].startswith("Tied")


def test_unknown_length_listings_change_the_sentence_at_rank_one():  # #155
    rows = BASE + [row("newegg", 1000.0, "NVIDIA GeForce RTX 5070 Ti 16GB"), row("bh", 1100.0, "NVIDIA GeForce RTX 5070 Ti OC", url="https://bh.example/u2")]
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=rows)
    assert out["unknown_fit"] == 2 and out["rank"] == 1
    assert "cheapest of the listings we can confirm fit; 2 of unknown length not counted" in out["sentence"]
    assert "Cheapest" not in out["sentence"]
    assert price_position(SKU, 1500.0, "new", AS_OF, rows=rows)["sentence"].startswith("4th cheapest")  # not rank 1: unchanged


# PL-26: each price carries its own capture time; a listing missing from its store's newest capture is not counted.
BB_URL = "https://bestbuy.example/prime"
NEWEST = "2026-10-24T08:00:00+00:00"


def test_every_counted_price_carries_its_own_capture_time():
    rows = [row("bestbuy", 1299.99, ASUS, url=BB_URL, at="2026-10-24T05:00:00+00:00"),
            row("microcenter", 1299.99, ASUS, url="https://microcenter.example/prime", at="2026-10-24T08:30:00+00:00"),
            row("bh", 1349.0, VENTUS, at="2026-10-24T07:00:00+00:00")]
    out = price_position(SKU, 1299.99, "new", AS_OF, subject_url=BB_URL, rows=rows)
    assert out["rank"] == 1 and out["cheapest_fitting"]["store"] == "bestbuy"   # a tie: the first by capture time
    assert out["cheapest_fitting"]["observed_at"] == "2026-10-24T05:00:00+00:00"
    assert out["tied_with"] == [{"store": "microcenter", "url": "https://microcenter.example/prime", "price": 1299.99,
                                 "observed_at": "2026-10-24T08:30:00+00:00"}]
    assert {x["store"]: x["observed_at"] for x in out["listings"]} == {"microcenter": "2026-10-24T08:30:00+00:00",
                                                                       "bh": "2026-10-24T07:00:00+00:00",
                                                                       "bestbuy": "2026-10-24T05:00:00+00:00"}
    assert out["subject"] == {"store": "bestbuy", "price": 1299.99, "url": BB_URL, "observed_at": "2026-10-24T05:00:00+00:00",
                              "newest_capture": "2026-10-24T05:00:00+00:00", "in_newest_capture": True}


def stale_prime_rows():
    """The Oct 25 case: Best Buy was captured again and the ASUS Prime was not in that capture."""
    return [row("bestbuy", 1299.99, ASUS, url=BB_URL, at="2026-10-24T05:00:00+00:00"),
            row("bestbuy", 1400.0, VENTUS, url="https://bestbuy.example/ventus", at=NEWEST),
            row("microcenter", 1299.99, ASUS, url="https://microcenter.example/prime", at="2026-10-24T08:30:00+00:00"),
            row("bh", 1349.0, VENTUS, at="2026-10-24T08:30:00+00:00")]


def test_a_listing_missing_from_its_stores_newest_capture_is_not_counted_and_is_marked_with_its_own_time():
    out = price_position(SKU, 1299.99, "new", AS_OF, subject_url=BB_URL, rows=stale_prime_rows())
    assert out["of_n"] == 3 and {x["url"] for x in out["listings"]} == {"https://bestbuy.example/ventus", "https://microcenter.example/prime",
                                                                         "https://bh.example/1349.0"}
    assert out["left_out"] == [{"store": "bestbuy", "url": BB_URL, "price": 1299.99, "last_seen": "2026-10-24T05:00:00+00:00",
                                "newest_capture": NEWEST}]
    assert out["subject"] == {"store": "bestbuy", "price": 1299.99, "url": BB_URL, "observed_at": "2026-10-24T05:00:00+00:00",
                              "newest_capture": NEWEST, "in_newest_capture": False}
    assert "last seen Oct 24 05:00 UTC" in out["sentence"] and "not in Best Buy's newest capture (Oct 24 08:00 UTC)" in out["sentence"]


def test_the_stale_listing_never_stands_in_for_the_winner_when_it_alone_made_the_tie():
    rows = [r for r in stale_prime_rows() if r["store"] != "microcenter"]
    out = price_position(SKU, 1299.99, "new", AS_OF, subject_url=BB_URL, rows=rows)
    assert out["tied_with"] == [] and all(x["url"] != BB_URL for x in out["listings"])
    assert out["rank"] == 1 and out["of_n"] == 2


def test_a_listing_only_one_provider_saw_is_not_dropped_by_another_providers_newer_capture():
    a = row("bestbuy", 1299.99, ASUS, url=BB_URL, at="2026-10-24T05:00:00+00:00")
    b = row("bestbuy", 1400.0, VENTUS, url="https://bestbuy.example/ventus", at=NEWEST, provider="apify-b")
    out = price_position(SKU, 1299.99, "new", AS_OF, subject_url=BB_URL, rows=[a, b])
    assert out["of_n"] == 2 and out["left_out"] == [] and out["subject"]["in_newest_capture"] is True


def test_a_provider_that_saw_the_listing_before_and_captured_the_store_later_without_it_drops_it():
    a = row("bestbuy", 1299.99, ASUS, url=BB_URL, at="2026-10-24T05:00:00+00:00")
    b_old = row("bestbuy", 1299.99, ASUS, url=BB_URL, at="2026-10-24T04:00:00+00:00", provider="apify-b")
    b_new = row("bestbuy", 1400.0, VENTUS, url="https://bestbuy.example/ventus", at=NEWEST, provider="apify-b")
    out = price_position(SKU, 1299.99, "new", AS_OF, subject_url=BB_URL, rows=[a, b_old, b_new])
    assert [x["url"] for x in out["listings"]] == ["https://bestbuy.example/ventus"] and out["left_out"][0]["url"] == BB_URL


def test_a_newer_out_of_stock_capture_of_a_url_beats_an_older_in_stock_one():
    old = row("newegg", 1100.0, ASUS, url="https://newegg.example/x", at="2026-10-24T05:00:00+00:00")
    new = row("newegg", 1100.0, ASUS, stock=False, url="https://newegg.example/x", at=NEWEST)
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=BASE + [old, new])
    assert out["of_n"] == 3 and out["rank"] == 1 and all(x["url"] != "https://newegg.example/x" for x in out["listings"])
    assert price_position(SKU, 1299.99, "new", AS_OF, rows=BASE + [old])["rank"] == 2   # without the newer capture it still counts


def test_captures_after_as_of_do_not_hide_listings_as_of_then():
    later = row("bestbuy", 1400.0, VENTUS, url="https://bestbuy.example/ventus", at="2026-10-24T12:00:00+00:00")
    out = price_position(SKU, 1299.99, "new", AS_OF, subject_url=BB_URL, rows=stale_prime_rows()[:1] + [later])
    assert out["of_n"] == 1 and out["subject"]["in_newest_capture"] is True and out["left_out"] == []


def test_an_unknown_subject_url_has_no_capture_time_and_no_stale_clause():
    out = price_position(SKU, 1299.99, "new", AS_OF, subject_url="https://bestbuy.example/never-seen", rows=BASE)
    assert out["subject"]["observed_at"] is None and out["subject"]["in_newest_capture"] is None
    assert "last seen" not in out["sentence"]


def test_the_day_label_follows_the_counted_listings_not_the_as_of_clock():
    rows = [row("bestbuy", 1299.99, ASUS, at="2026-10-23T23:00:00+00:00"), row("bh", 1349.0, VENTUS, at="2026-10-24T08:30:00+00:00")]
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=rows)
    assert out["sentence"] == "Cheapest fitting new card of 2 listings at 2 stores, Oct 23 to Oct 24"
