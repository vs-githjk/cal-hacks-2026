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
    assert check("Wireless Power Bank", "Anker", "anker", tmp_path)["status"] in ("possible", "unverified")  # #302: generic is never "none"


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


# --- #302 probes ---------------------------------------------------------------------------------------------------
def fake(items):
    return lambda url: json.dumps(items).encode()


def item(title, desc="", products=(), upcs=(), makers=()):  # SIM fixtures, not real recalls
    return {"Title": title, "Description": desc, "RecallDate": "2026-01-01T00:00:00", "URL": "https://www.cpsc.gov/Recalls/2026/sim",
            "Products": [{"Name": n, "Model": m} for n, m in products], "ProductUPCs": [{"UPC": u} for u in upcs],
            "Manufacturers": [{"Name": m} for m in makers], "Hazards": [], "Remedies": []}


def test_a_brand_with_no_product_is_unverified_never_none(tmp_path):  # probe 1
    r = check("", "Anker", "anker", tmp_path)
    assert r["status"] == "unverified" and r["summary"].startswith("UNVERIFIED: no model")


def test_a_generic_only_name_is_possible_on_a_category_match(tmp_path):  # probe 1: the real fixture has "Anker Power Banks Recalled"
    r = check("Anker Power Bank", "Anker", "anker", tmp_path)
    assert r["status"] == "possible" and r["matches"] == [] and r["possible"][0]["match_on"].startswith("product category")


def test_a_generic_only_name_with_no_category_match_is_unverified(tmp_path):
    r = check_product("Gaming Mouse", "Anker", fetch=fake([item("Anker Recalls Power Banks", products=[("Anker power bank", "A1263")])]),
                      now=NOW, cache_dir=tmp_path)
    assert r["status"] == "unverified"


def test_a_model_named_only_in_the_description_is_possible_not_recalled(tmp_path):  # probe 2
    rec = item("Anker Recalls Chargers", desc="Model A1229 is NOT affected.", products=[("Anker charger", "B77")])
    r = check_product("Charger A1229", "Anker", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "possible" and r["matches"] == [] and "description only" in r["possible"][0]["match_on"]


def test_a_model_in_the_product_model_field_is_recalled(tmp_path):
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")])
    assert check_product("Charger B77", "Anker", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)["status"] == "recalled"


def test_a_upc_a_matches_the_same_code_listed_as_ean_13(tmp_path):  # probe 3
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["0841234567890"])
    r = check_product("Charger", "Anker", upc="841234567890", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled" and r["matches"][0]["match_on"] == "UPC 841234567890"


def test_a_upc_match_needs_no_brand_text(tmp_path):  # probe 4
    rec = item("Power Banks Recalled Due to Fire Hazard", products=[("power bank", "X1")], upcs=["841234567890"])
    r = check_product("Power Bank", "Anker", upc="841234567890", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled"


def test_a_non_dict_products_entry_does_not_crash(tmp_path):
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")])
    rec["Products"].append("junk")
    assert check_product("Charger B77", "Anker", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)["status"] == "recalled"


def test_sizes_and_clock_speeds_are_not_model_tokens():
    model, _ = _tokens("Galaxy S24 Ultra 256GB 2.4GHz 128G", "Samsung")
    assert model == {"s24"}
