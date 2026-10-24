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


# --- #314 probes ---------------------------------------------------------------------------------------------------
def test_a_upc_miss_on_a_brand_only_check_is_unverified_never_none(tmp_path):  # HIGH: no real recall lists a UPC
    r = check("", "Anker", "anker", tmp_path, upc="000000000001")
    assert r["status"] == "unverified" and r["summary"].startswith("UNVERIFIED: no model")


def test_a_upc_miss_on_a_generic_only_name_with_no_category_hit_is_unverified(tmp_path):
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["841234567890"])
    r = check_product("Anker Power Bank", "Anker", upc="841234567891", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "unverified" and r["matches"] == [] and r["possible"] == []


def test_a_listed_upc_on_a_brand_only_check_is_still_recalled(tmp_path):
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["841234567890"])
    r = check_product("", "Anker", upc="841234567890", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled" and r["matches"][0]["match_on"] == "UPC 841234567890"


def test_a_name_with_only_a_size_is_unverified_never_none(tmp_path):  # MEDIUM: "128g" is a size, not a product signal
    assert check("Anker 128g", "Anker", "anker", tmp_path)["status"] == "unverified"
    assert check("128GB", "Anker", "anker", tmp_path)["status"] == "unverified"


def test_a_four_digit_product_line_still_counts(tmp_path):
    assert check("PowerCore 10000 A1229", "Anker", "anker", tmp_path)["possible"][0]["match_on"] == "product line 10000"
    assert check("10000", "Anker", "anker", tmp_path)["status"] == "possible"


def test_one_upc_field_holding_several_upcs_matches_each(tmp_path):  # MEDIUM: "a, b" used to become one long number
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["841234567890, 841234567891"])
    r = check_product("Charger", "Anker", upc="841234567891", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled" and r["matches"][0]["match_on"] == "UPC 841234567891"


def test_two_short_codes_never_join_into_a_false_upc_match(tmp_path):
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["1234, 5678"])
    r = check_product("Charger", "Anker", upc="12345678", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] != "recalled" and r["matches"] == []


@pytest.mark.parametrize("listed", ["841234567890 / 841234567891", "841234567890; 0841234567891", "841234567890 841234567891",
                                    "UPC 841234567891"])
def test_upc_lists_with_other_separators_match_each_code(tmp_path, listed):
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=[listed])
    r = check_product("Charger", "Anker", upc="841234567891", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled"


# --- #331 probes ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("product", ["Anker 20000mAh Power Bank", "Anker Power Bank 5000mAh"])
def test_a_capacity_never_turns_a_category_lead_into_none(tmp_path, product):  # item 1: "Anker Power Bank" is possible
    r = check(product, "Anker", "anker", tmp_path)
    assert r["status"] == "possible" and r["matches"] == []


@pytest.mark.parametrize("product", ["Anker 1000GB", "Anker 1080p webcam", "Anker 2024"])
def test_a_size_or_year_alone_is_never_a_product_signal(tmp_path, product):  # item 1
    assert check(product, "Anker", "anker", tmp_path)["status"] == "unverified"


@pytest.mark.parametrize("product", ["Anker 3-in-1 Charger", "Anker Charger 2-pack", "Anker USB3.0 Charger", "Anker Qi2 Charger",
                                     "Anker wifi6 Charger", "Anker 65W 2-port Charger", "Anker 3 pack", "Anker Charger kit",
                                     "Anker Charger pair", "Anker 2nd gen Charger"])
def test_spec_words_are_not_model_tokens(tmp_path, product):  # item 2: "Anker Charger" is unverified, so these must be too
    r = check(product, "Anker", "anker", tmp_path)
    assert r["status"] == check("Anker Charger", "Anker", "anker", tmp_path / "plain")["status"] != "none"
    assert r["matches"] == []


def test_spec_words_leave_the_real_model_token():
    model, _ = _tokens("Anker 3-in-1 Charger 2-pack USB3.0 Qi2 wifi6 2-port A2345", "Anker")
    assert model == {"a2345"}


def test_several_input_upcs_match_any_of_them(tmp_path):  # item 3
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["841234567891"])
    r = check_product("Charger", "Anker", upc="841234567890, 841234567891", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled" and r["matches"][0]["match_on"] == "UPC 841234567891"
    assert r["upc"] == "841234567890, 841234567891"


def test_a_long_spaced_field_splits_into_whole_codes(tmp_path):  # item 4
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["8 41234 56789 0 8 41234 56789 1"])
    r = check_product("Charger", "Anker", upc="841234567891", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled"


def test_a_spaced_upc_in_one_code_still_matches(tmp_path):
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["8 41234 56789 1"])
    r = check_product("Charger", "Anker", upc="8-41234-56789-1", fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] == "recalled"


@pytest.mark.parametrize("upc", ["12", "12345"])
def test_a_upc_shorter_than_six_digits_is_ignored(tmp_path, upc):  # item 5
    rec = item("Anker Recalls Chargers", products=[("Anker charger", "B77")], upcs=["12", "12345, 841234567890"])
    r = check_product("Charger", "Anker", upc=upc, fetch=fake([rec]), now=NOW, cache_dir=tmp_path)
    assert r["status"] != "recalled" and r["matches"] == []
