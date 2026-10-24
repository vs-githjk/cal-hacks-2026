"""Seller agent-readiness report (#171): saved fixtures only, no network."""
import socket

import pytest

from data import seller_report
from data.seller_report import findings_for, markdown, report

AS_OF = "2026-10-24T12:00:00+00:00"


def card(name, price, url, condition="new", stock="2 remaining", shipping="Free delivery", store="ebay_live"):
    return {"id": f"{store}:x", "category": "gpu", "name": name, "condition": condition, "attrs": {"chipset": "RTX 5070 Ti"},
            "price": price, "origin": "MIRROR", "source": url, "snapshot_id": f"{store}-fixture", "snapshot_date": "2026-10-24T09:00:00+00:00",
            "listing": {"url": url, "price": price, "stock": stock, "shipping": shipping}}


def ask(url, price, store="bestbuy"):
    return {"provider": "apify", "store": store, "sku": "rtx 5070 ti", "price": price, "in_stock": True, "condition": "new", "kind": "ask",
            "observed_at": "2026-10-24T09:00:00+00:00", "url": url, "origin": "MIRROR"}


OBS = [ask("https://bestbuy.example/a", 1249.99), ask("https://bestbuy.example/b", 1299.99), ask("https://microcenter.example/c", 1349.0, "microcenter")]
GOOD = card("ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition", 1299.99, "https://www.ebay.com/itm/1")
VAGUE = card("NVIDIA GeForce RTX 5070 Ti 16GB Video Card", 999.0, "https://www.ebay.com/itm/2", stock=None, shipping=None)
LIAR = card("ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition NEW & SEALED", 1299.99, "https://www.ebay.com/itm/3", condition="open-box")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


def rules(rep):
    return sorted(f["rule_id"] for f in rep["findings"])


def test_a_clean_listing_has_no_findings():
    assert report(["https://www.ebay.com/itm/1"], AS_OF, cards=[GOOD], observations=OBS)["findings"] == []


def test_each_rule_fires_with_a_source_and_a_severity():
    rep = report(["https://www.ebay.com/itm/2", "https://www.ebay.com/itm/3"], AS_OF, cards=[VAGUE, LIAR], observations=OBS)
    assert rules(rep) == ["claim.condition", "fit.length_unknown", "fit.power_unknown", "listing.shipping_unknown",
                          "listing.stock_unknown", "price.outside_band"]
    for f in rep["findings"]:
        assert f["source_url"].startswith("https://") and f["severity"] in ("blocks", "warns") and f["fix"]
    assert next(f for f in rep["findings"] if f["rule_id"] == "claim.condition")["severity"] == "blocks"
    band = next(f for f in rep["findings"] if f["rule_id"] == "price.outside_band")
    assert band["source_url"] == "https://bestbuy.example/a" and "below the dated band" in band["what_an_agent_sees"]


def test_a_finding_without_a_source_is_dropped():
    no_url = {**VAGUE, "source": "", "listing": {**VAGUE["listing"], "url": ""}}
    out = findings_for(no_url, None, [])
    assert out == [] and all(f["source_url"] for f in findings_for(VAGUE, None, []))


def test_wording_says_what_an_agent_sees_never_what_the_seller_did():
    rep = report(["https://www.ebay.com/itm/2", "https://www.ebay.com/itm/3"], AS_OF, cards=[VAGUE, LIAR], observations=OBS)
    text = markdown(rep).lower()
    for word in ("liar", "lied", "fraud", "scam", "cheat", "fake"):
        assert word not in text, word
    assert "(MIRROR)" in markdown(rep) and "uncertain" in text
    assert "Offered free to a seller in exchange for a signed commitment; no payment taken." in markdown(rep)


def test_a_mirror_seller_id_selects_by_store_and_item_id():
    rep = report("ebay_live:itm/2", AS_OF, cards=[GOOD, VAGUE], observations=OBS)
    assert [p["url"] for p in rep["listings"]] == ["https://www.ebay.com/itm/2"]


def test_the_committed_sample_report_is_labelled_mirror_and_dated():
    sample = sorted(seller_report.REPORTS.glob("ebay_live-*.md"))
    assert sample and "(MIRROR)" in sample[0].read_text() and sample[0].stem.endswith("2026-10-24")
