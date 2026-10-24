from advocate.same_seller import exclude_same_seller


def candidate(seller_id, *urls, **fields):
    return {
        "id": fields.pop("id", seller_id),
        "supplier_id": seller_id,
        "lines": [{"listing_url": url} for url in urls],
        **fields,
    }


def trusted(provenance="registry", **identity):
    return {"provenance": provenance, **identity}


def test_shared_trusted_payee_excludes_later_seller_and_keeps_best_first():
    best = candidate("seller-a", id="best")
    later = candidate("seller-b", id="later")

    kept, exclusions = exclude_same_seller(
        [best, later],
        {"seller-a": trusted(payee="Payee@Example.test"),
         "seller-b": trusted("bound_state", payee="payee@example.test")},
    )

    assert kept == [best]
    assert exclusions == [{
        "kept_seller_id": "seller-a",
        "excluded_seller_id": "seller-b",
        "reason": {
            "rule_id": "advocate.same_seller",
            "summary": "This seller shares trusted identity evidence with a higher-ranked seller",
            "source_url": "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/same_seller.py",
        },
    }]


def test_shared_trusted_owner_groups_sellers():
    best = candidate("seller-a")
    later = candidate("seller-b")

    kept, exclusions = exclude_same_seller(
        [best, later],
        {"seller-a": trusted(owner="Acme Parts LLC"),
         "seller-b": trusted("mirror", owner="acme parts llc")},
    )

    assert kept == [best]
    assert [(e["kept_seller_id"], e["excluded_seller_id"]) for e in exclusions] == [("seller-a", "seller-b")]


def test_untrusted_seller_claims_and_marketplace_hosts_do_not_group_sellers():
    bids = [candidate("ebay-seller-a", "https://www.ebay.com/itm/1",
                      competitor_owner="Same Corporation"),
            candidate("ebay-seller-b", "https://stores.ebay.com/shop/2",
                      competitor_owner="Same Corporation")]

    kept, exclusions = exclude_same_seller(
        bids,
        {"ebay-seller-a": trusted("seller_claim", owner="Same Corporation"),
         "ebay-seller-b": trusted("seller_claim", owner="Same Corporation")},
    )

    assert kept == bids
    assert exclusions == []


def test_lookalike_marketplace_host_is_eligible_and_exact_host_groups():
    best = candidate("seller-a", "https://shop.ebay.com.evil.example/item")
    later = candidate("seller-b", "http://SHOP.EBAY.COM.EVIL.EXAMPLE./listing/2")

    kept, exclusions = exclude_same_seller([best, later], {})

    assert kept == [best]
    assert [(e["kept_seller_id"], e["excluded_seller_id"]) for e in exclusions] == [("seller-a", "seller-b")]


def test_placeholders_reserved_hosts_and_code_owned_sources_are_ignored():
    candidates = [
        candidate("example", "https://example.com/listing/1"),
        candidate("test", "https://store.example.test/item"),
        candidate("github", "https://github.com/vs-githjk/cal-hacks-2026/blob/main/x"),
        candidate("cpsc", "https://www.cpsc.gov/Recalls/1"),
        candidate("example-subdomain", "https://shop.example.com/listing/2"),
        candidate("test-subdomain", "https://example.test/offer"),
    ]

    kept, exclusions = exclude_same_seller(candidates, {})

    assert kept == candidates
    assert exclusions == []


def test_transitive_groups_are_deterministic_and_keep_all_candidates_for_best_seller():
    best = candidate("seller-a", "https://parts.example.org/a", id="best")
    duplicate_best = candidate("seller-a", id="best-duplicate")
    middle = candidate("seller-b", "https://parts.example.org/b", id="middle")
    last = candidate("seller-c", id="last", evidence_url="https://shop.vendor.test/page")
    # .test cannot connect seller-c; use a trusted owner to connect it transitively through seller-b.
    identities = {
        "seller-a": trusted(payee="shared-payee"),
        "seller-b": trusted(payee="shared-payee", owner="shared-owner"),
        "seller-c": trusted(owner="shared-owner"),
    }

    kept, exclusions = exclude_same_seller([best, duplicate_best, middle, last], identities)

    assert kept == [best, duplicate_best]
    assert [(e["kept_seller_id"], e["excluded_seller_id"]) for e in exclusions] == [
        ("seller-a", "seller-b"), ("seller-a", "seller-c")]
    assert exclude_same_seller([best, duplicate_best, middle, last], identities) == (kept, exclusions)


def test_duplicate_seller_ids_without_cross_seller_match_are_untouched():
    bids = [candidate("seller-a", id="first"), candidate("seller-a", id="second")]

    kept, exclusions = exclude_same_seller(bids, {})

    assert kept == bids
    assert exclusions == []


def test_missing_supplier_id_is_rejected():
    try:
        exclude_same_seller([{"lines": []}], {})
    except ValueError as exc:
        assert "supplier_id" in str(exc)
    else:
        raise AssertionError("candidate without supplier_id must be rejected")


def test_all_marketplace_hosts_are_excluded_from_grouping():
    domains = ("amazon.com", "ebay.com", "bestbuy.com", "newegg.com", "microcenter.com", "bhphotovideo.com")
    bids = []
    for index, domain in enumerate(domains):
        bids.extend([
            candidate(f"seller-{index}-a", f"https://{domain}/listing/1"),
            candidate(f"seller-{index}-b", f"https://shop.{domain}/listing/2"),
        ])

    kept, exclusions = exclude_same_seller(bids, {})

    assert kept == bids
    assert exclusions == []


def test_candidate_and_line_evidence_url_fields_can_match():
    best = candidate("seller-a", evidence_url="https://merchant.example.org/about")
    later = {"supplier_id": "seller-b", "lines": [{"source_url": "http://MERCHANT.EXAMPLE.ORG./product"}]}

    kept, exclusions = exclude_same_seller([best, later], {})

    assert kept == [best]
    assert [(e["kept_seller_id"], e["excluded_seller_id"]) for e in exclusions] == [("seller-a", "seller-b")]
