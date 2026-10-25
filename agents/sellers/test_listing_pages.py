"""RT-19 follow-up: SIM listing pages state their facts the way a real store does (schema.org Product/Offer JSON-LD), so the
claim check reads them on any host while it still ignores the <script id="listing"> block off our own demo pages."""
import json

from agents.sellers import listing_pages
from data.claim_check import LIAR_PAGE_HOSTS, page_facts, script_blocks

LINE = {"sku_spec": "rtx 5070 ti", "unit_price": 1249.99, "offered_condition": "new", "page_condition": "new"}
URL = "https://shop.example/sim/rtx-5070-ti"


def page(**kw):
    return listing_pages.render(listing_pages.facts_for_line(LINE, seller_id="s", **kw), "rtx 5070 ti (new)")


def test_the_page_states_its_facts_as_schema_org_json_ld():
    blocks = [(t, b) for t, b in script_blocks(page(warranty_months=12, return_days=30)) if "ld+json" in t]
    assert len(blocks) == 1
    product = json.loads(blocks[0][1])
    offer = product["offers"]
    assert product["@type"] == "Product" and offer["@type"] == "Offer"
    assert offer["price"] == 1249.99 and offer["priceCurrency"] == "USD"
    assert offer["itemCondition"] == "https://schema.org/NewCondition"
    assert offer["availability"] == "https://schema.org/InStock"
    assert product["warranty"]["durationOfWarranty"]["value"] == 12
    assert offer["hasMerchantReturnPolicy"]["merchantReturnDays"] == 30


def test_the_claim_check_reads_those_facts_on_a_host_that_is_not_ours():
    assert not any(h in URL for h in LIAR_PAGE_HOSTS)
    facts, how = page_facts(page(warranty_months=12, return_days=30), URL)
    assert how == "page JSON-LD"
    assert facts["price"] == 1249.99 and facts["currency"] == "USD" and facts["condition"] == "new"
    assert facts["warranty_months"] == 12 and facts["return_policy"] == "30-day returns" and facts["stock"] == "InStock"


def test_every_condition_a_line_can_carry_reads_back_the_same():
    for cond in ("new", "refurbished", "used", "open-box"):
        facts, _ = page_facts(page(condition=cond), URL)
        assert facts["condition"] == cond, cond


def test_a_condition_the_page_does_not_know_states_none():   # a MIRROR line is "unknown": the page must not invent one
    facts, _ = page_facts(page(condition="unknown"), URL)
    assert "condition" not in facts


def test_the_old_listing_block_is_gone_and_a_page_cannot_close_its_own_script():
    assert 'id="listing"' not in page()
    out = listing_pages.render({"price": 1, "condition": "new"}, "x </script><b>")
    assert "</script><b>" not in out
    assert json.loads(next(b for t, b in script_blocks(out) if "ld+json" in t))["name"] == "x </script><b>"
