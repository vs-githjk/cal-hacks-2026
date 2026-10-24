"""The general recall check (#271): exact model or UPC is recalled, a product line or product word is possible, a failure is
unverified. Fixtures are the real CPSC answers for Anker and Samsung read on Oct 24 2026; no network."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.recall_checker import _tokens, check_product
from data.recalls import brand_in, recalls_for

FIX = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)


def serve(brand):
    data = (FIX / f"recalls_{brand}_real.json").read_bytes()
    return lambda url: data


def check(product, brand, fixture, tmp_path, **kw):
    return check_product(product, brand, fetch=serve(fixture), now=NOW, cache_dir=tmp_path, **kw)


def test_the_recalled_anker_power_bank_model_is_recalled_with_hazard_remedy_and_units(tmp_path):
    r = check("PowerCore 10000 A1263", "Anker", "anker", tmp_path)
    assert r["status"] == "recalled" and r["summary"].startswith("RECALLED: Anker PowerCore 10000 A1263 matches 1 CPSC recall(s) on model A1263")
    m = r["matches"][0]
    assert m["date"] == "2025-06-12" and m["url"].startswith("https://www.cpsc.gov/Recalls/2025/")
    assert "overheat" in m["hazard"] and "replacement" in m["remedy"] and m["units"] == "About 1,158,000"


def test_another_model_on_the_same_line_is_possible_never_recalled(tmp_path):
    r = check("PowerCore 10000 A1229", "Anker", "anker", tmp_path)
    assert r["status"] == "possible" and r["matches"] == [] and r["possible"][0]["match_on"] == "product line 10000"


def test_the_galaxy_note7_is_recalled(tmp_path):
    r = check("Galaxy Note7", "Samsung", "samsung", tmp_path)
    assert r["status"] == "recalled" and len(r["matches"]) == 2 and r["matches"][0]["date"] == "2016-10-13"


def test_a_product_with_no_recall_is_none_and_says_us_cpsc_only(tmp_path):
    r = check("Nano Charger 30W", "Anker", "anker", tmp_path)
    assert r["status"] == "none" and "U.S. CPSC recalls only" in r["summary"]


def test_a_product_word_is_a_lead_but_a_generic_word_is_not(tmp_path):
    assert check("Soundcore Motion 300", "Anker", "anker", tmp_path)["possible"][0]["match_on"] == "product name soundcore"
    assert check("Wireless Power Bank", "Anker", "anker", tmp_path)["status"] == "none"  # "power bank" alone is generic


def test_the_brand_must_be_a_whole_word():  # Anker's CPSC search also returns Trankerloop bath seats
    assert brand_in("Anker", "Anker Power Banks Recalled") and not brand_in("Anker", "Trankerloop Baby Bath Seats Recalled")
    items = json.loads((FIX / "recalls_anker_real.json").read_text())
    assert any("Trankerloop" in i["Title"] for i in items)  # the real answer really contains it


def test_the_trankerloop_recall_is_never_matched_to_anker(tmp_path):
    r = check("Baby Bath Seat 2380", "Anker", "anker", tmp_path)
    assert all("Trankerloop" not in x["title"] for x in r["matches"] + r["possible"])


def test_a_upc_match_is_recalled(tmp_path):
    item = {"Title": "Acme Recalls Chargers", "RecallDate": "2026-01-02T00:00:00", "URL": "https://www.cpsc.gov/Recalls/x",
            "Products": [{"Name": "Acme charger"}], "ProductUPCs": [{"UPC": "8-41234-56789-0"}], "Hazards": [], "Remedies": []}
    r = check_product("Charger", "Acme", upc="841234567890", fetch=lambda url: json.dumps([item]).encode(), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled" and r["matches"][0]["match_on"] == "UPC 841234567890"


def test_no_brand_is_unverified_with_no_lookup(tmp_path):
    seen = []
    r = check_product("PowerCore A1263", "  ", fetch=lambda url: seen.append(url) or b"[]", now=NOW, cache_dir=tmp_path)
    assert r["status"] == "unverified" and seen == [] and "no brand given" in r["summary"]


@pytest.mark.parametrize("fetch", [lambda url: (_ for _ in ()).throw(OSError("down")), lambda url: b"not json", lambda url: b'{"error": 1}'])
def test_a_failed_or_odd_lookup_is_unverified_never_none(tmp_path, fetch):
    r = check_product("PowerCore A1263", "Anker", fetch=fetch, now=NOW, cache_dir=tmp_path)
    assert r["status"] == "unverified" and r["summary"].startswith("UNVERIFIED: the CPSC recall lookup for Anker failed")


def test_sizes_are_product_lines_not_models():
    model, line = _tokens("PowerCore 10000mAh 65W A1263", "Anker")
    assert model == {"a1263"} and line == {"10000"}


def test_the_gpu_recall_check_still_works_after_the_shared_lookup_refactor(tmp_path):
    r = recalls_for("ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition", "ASUS", fetch=serve("asus"), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "none"
