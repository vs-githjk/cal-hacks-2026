from advocate.same_seller import exclude_same_seller


def candidate(seller_id, **fields):
    return {"id": fields.pop("id", seller_id), "supplier_id": seller_id, **fields}


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
    bids = [candidate("ebay-seller-a", source_url="https://www.ebay.com/itm/1",
                      competitor_owner="Same Corporation"),
            candidate("ebay-seller-b", source_url="https://stores.ebay.com/shop/2",
                      competitor_owner="Same Corporation")]

    kept, exclusions = exclude_same_seller(
        bids,
        {"ebay-seller-a": trusted("seller_claim", owner="Same Corporation"),
         "ebay-seller-b": trusted("seller_claim", owner="Same Corporation")},
    )

    assert kept == bids
    assert exclusions == []


def test_lookalike_marketplace_host_is_eligible_and_exact_host_groups():
    best = candidate("seller-a")
    later = candidate("seller-b")

    kept, exclusions = exclude_same_seller([best, later], {
        "seller-a": trusted(listing_urls=["https://shop.ebay.com.evil.example/item"]),
        "seller-b": trusted(evidence_urls=["http://SHOP.EBAY.COM.EVIL.EXAMPLE./listing/2"]),
    })

    assert kept == [best]
    assert [(e["kept_seller_id"], e["excluded_seller_id"]) for e in exclusions] == [("seller-a", "seller-b")]


def test_placeholders_reserved_hosts_and_code_owned_sources_are_ignored():
    candidates = [candidate(seller_id) for seller_id in (
        "example", "test", "github", "cpsc", "example-subdomain", "test-subdomain")]
    identities = {
        "example": trusted(listing_urls=["https://example.com/listing/1"]),
        "test": trusted(listing_urls=["https://store.example.test/item"]),
        "github": trusted(listing_urls=["https://github.com/vs-githjk/cal-hacks-2026/blob/main/x"]),
        "cpsc": trusted(listing_urls=["https://www.cpsc.gov/Recalls/1"]),
        "example-subdomain": trusted(listing_urls=["https://shop.example.com/listing/2"]),
        "test-subdomain": trusted(listing_urls=["https://example.test/offer"]),
    }

    kept, exclusions = exclude_same_seller(candidates, identities)

    assert kept == candidates
    assert exclusions == []


def test_transitive_groups_are_deterministic_and_keep_all_candidates_for_best_seller():
    best = candidate("seller-a", id="best")
    duplicate_best = candidate("seller-a", id="best-duplicate")
    middle = candidate("seller-b", id="middle")
    last = candidate("seller-c", id="last", evidence_url="https://shared.example.org/citation")
    identities = {
        "seller-a": trusted(payee="shared-payee", listing_urls=["https://parts.example.org/a"]),
        "seller-b": trusted(payee="shared-payee", owner="shared-owner",
                             listing_urls=["https://parts.example.org/b"]),
        "seller-c": trusted(owner="shared-owner", listing_urls=["https://shop.vendor.test/page"]),
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


def test_missing_seller_id_is_rejected():
    for invalid in ({}, {"supplier_id": ""}, {"seller_id": "  "}):
        try:
            exclude_same_seller([invalid], {})
        except ValueError as exc:
            assert "seller_id" in str(exc)
        else:
            raise AssertionError("candidate without a nonempty seller ID must be rejected")


def test_different_supplier_and_seller_ids_are_rejected():
    try:
        exclude_same_seller([{"supplier_id": "seller-a", "seller_id": "seller-b"}], {})
    except ValueError as exc:
        assert "seller" in str(exc)
    else:
        raise AssertionError("conflicting seller ID aliases must be rejected")


def test_seller_id_alias_is_used_for_grouping_and_exclusion_output():
    best = {"seller_id": "seller-a", "id": "best"}
    later = {"seller_id": "seller-b", "id": "later"}

    kept, exclusions = exclude_same_seller([best, later], {
        "seller-a": trusted(payee="shared"), "seller-b": trusted(payee="shared")})

    assert kept == [best]
    assert [(e["kept_seller_id"], e["excluded_seller_id"]) for e in exclusions] == [("seller-a", "seller-b")]


def test_malformed_provenance_is_ignored():
    candidates = [candidate("seller-a"), candidate("seller-b"), candidate("seller-c")]
    identities = {
        "seller-a": {"provenance": [], "payee": "shared"},
        "seller-b": {"provenance": {"registry": True}, "payee": "shared"},
        "seller-c": {"provenance": 123, "payee": "shared"},
    }

    kept, exclusions = exclude_same_seller(candidates, identities)

    assert kept == candidates
    assert exclusions == []


def test_malformed_url_ports_are_ignored():
    best = candidate("seller-a")
    later = candidate("seller-b")

    kept, exclusions = exclude_same_seller([best, later], {
        "seller-a": trusted(listing_urls=["https://merchant.example.org:notaport/item"]),
        "seller-b": trusted(evidence_urls=["https://merchant.example.org:99999/item"]),
    })

    assert kept == [best, later]
    assert exclusions == []


def test_candidate_source_citation_is_not_merchant_ownership_evidence():
    best = candidate("seller-a", source_url="https://www.consumerreports.org/reviews/item")
    later = candidate("seller-b", source_url="https://www.consumerreports.org/reviews/item")
    identities = {
        "seller-a": trusted(listing_urls=["https://seller-a.example.org/product"]),
        "seller-b": trusted(listing_urls=["https://seller-b.example.net/product"]),
    }

    kept, exclusions = exclude_same_seller([best, later], identities)

    assert kept == [best, later]
    assert exclusions == []


def test_all_marketplace_hosts_are_excluded_from_grouping():
    domains = ("amazon.com", "ebay.com", "bestbuy.com", "newegg.com", "microcenter.com", "bhphotovideo.com")
    candidates = []
    identities = {}
    for index, domain in enumerate(domains):
        left, right = f"seller-{index}-a", f"seller-{index}-b"
        candidates.extend([candidate(left), candidate(right)])
        identities[left] = trusted(listing_urls=[f"https://{domain}/listing/1"])
        identities[right] = trusted(evidence_urls=[f"https://shop.{domain}/listing/2"])

    kept, exclusions = exclude_same_seller(candidates, identities)

    assert kept == candidates
    assert exclusions == []


def test_trusted_listing_and_evidence_url_fields_can_match():
    best = candidate("seller-a")
    later = candidate("seller-b")

    kept, exclusions = exclude_same_seller([best, later], {
        "seller-a": trusted(listing_urls=["https://merchant.example.org/about"]),
        "seller-b": trusted(evidence_urls=["http://MERCHANT.EXAMPLE.ORG./product"]),
    })

    assert kept == [best]
    assert [(e["kept_seller_id"], e["excluded_seller_id"]) for e in exclusions] == [("seller-a", "seller-b")]
