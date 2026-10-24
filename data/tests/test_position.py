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
    sold = row("ebay_sold", 1500.0, kind="sold", provider="ebay-sold", sold_date="2026-10-23", url="https://ebay.example/1")
    out = price_position(SKU, 1299.99, "new", AS_OF, rows=BASE + [sold])
    assert out["status"] == "ok" and out["sentence"].endswith("and $200.01 under the 30-day eBay sold median (mixed condition, n = 1)")
    above = price_position(SKU, 1600.0, "new", AS_OF, rows=BASE + [sold])
    assert "under" not in above["sentence"] and "(30-day eBay sold median, mixed condition: $1,500.00, n = 1)" in above["sentence"]
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
    assert out["tied_with"] == [{"store": "microcenter", "url": "https://microcenter.example/prime"}]
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
