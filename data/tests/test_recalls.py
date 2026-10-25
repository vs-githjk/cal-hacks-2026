import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data.recall_checker import check_product

FIX = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
TITLE = "ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition"
SIM_GPU_RECALL = [{"Title": "ASUS Recalls GeForce RTX 5070 Ti Graphics Cards Due to Fire Hazard (SIM fixture)", "RecallDate": "2026-01-02T00:00:00",
                   "URL": "https://example.test/sim-recall", "Products": [{"Name": "ASUS GeForce RTX 5070 Ti graphics card"}], "Manufacturers": []}]


def serve(items):
    return lambda url: json.dumps(items).encode()


def test_real_asus_answer_with_only_a_motherboard_recall_is_none(tmp_path):
    out = check_product(TITLE, "ASUS", fetch=serve(json.loads((FIX / "recalls_asus_real.json").read_text())), now=NOW, cache_dir=tmp_path)
    assert out["status"] == "none" and out["matches"] == [] and "saferproducts.gov" in out["source_url"]
    assert "read 2026-10-24" in out["searched"] and out["summary"].startswith("NONE: no CPSC recall of ASUS matches")


def test_a_graphics_card_recall_is_recalled(tmp_path):  # SIM fixture, not a real recall
    out = check_product(TITLE, "ASUS", fetch=serve(SIM_GPU_RECALL), now=NOW, cache_dir=tmp_path)
    assert out["status"] == "recalled" and out["matches"][0]["date"] == "2026-01-02"


def test_other_brand_or_unrelated_product_does_not_match(tmp_path):
    other = [{**SIM_GPU_RECALL[0], "Title": "Acme Recalls Graphics Cards", "Products": [{"Name": "Acme graphics card"}]}]
    assert check_product(TITLE, "ASUS", fetch=serve(other), now=NOW, cache_dir=tmp_path)["status"] == "none"


def test_any_failure_is_unverified_never_none(tmp_path):
    def boom(url):
        raise TimeoutError("slow")
    assert check_product(TITLE, "ASUS", fetch=boom, now=NOW, cache_dir=tmp_path)["status"] == "unverified"
    assert check_product(TITLE, "ASUS", fetch=lambda u: b"<html>", now=NOW, cache_dir=tmp_path)["status"] == "unverified"
    assert check_product(TITLE, "ASUS", fetch=lambda u: b'{"a": 1}', now=NOW, cache_dir=tmp_path)["status"] == "unverified"


def test_cache_is_reused_within_24h_and_not_after(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps(SIM_GPU_RECALL).encode()
    check_product(TITLE, "ASUS", fetch=fetch, now=NOW, cache_dir=tmp_path)
    again = check_product(TITLE, "ASUS", fetch=fetch, now=NOW + timedelta(hours=23), cache_dir=tmp_path)
    assert len(calls) == 1 and again["status"] == "recalled"
    check_product(TITLE, "ASUS", fetch=fetch, now=NOW + timedelta(hours=25), cache_dir=tmp_path)
    assert len(calls) == 2


def test_a_gaming_laptop_or_monitor_recall_does_not_match_a_graphics_card(tmp_path):  # #156
    laptop = [{"Title": "ASUS Recalls ROG Strix G16 Gaming Laptop Due to Fire Hazard", "RecallDate": "2026-02-01T00:00:00", "URL": "u1",
               "Products": [{"Name": "ASUS ROG Strix G16 Gaming Laptop with GeForce RTX graphics"}], "Manufacturers": []}]
    monitor = [{"Title": "ASUS Recalls TUF Gaming Monitors", "RecallDate": "2026-03-01T00:00:00", "URL": "u2",
                "Products": [{"Name": "ASUS TUF Gaming VG27 monitor"}], "Manufacturers": []}]
    tuf = "ASUS TUF Gaming GeForce RTX 5070 Ti 16GB GDDR7 OC Edition"
    for i, items in enumerate((laptop, monitor)):
        assert check_product(tuf, "ASUS", fetch=serve(items), now=NOW, cache_dir=tmp_path / str(i))["status"] == "none"


def test_a_model_token_is_required_in_the_recall(tmp_path):
    generic = [{**SIM_GPU_RECALL[0], "Title": "ASUS Recalls Graphics Cards", "Products": [{"Name": "ASUS graphics card"}]}]
    assert check_product(TITLE, "ASUS", fetch=serve(generic), now=NOW, cache_dir=tmp_path)["status"] == "none"


def test_an_empty_brand_is_unverified_and_never_calls_the_api(tmp_path):
    def boom(url):
        raise AssertionError("the API must not be called")
    for brand in (None, "", "   "):
        out = check_product(TITLE, brand, fetch=boom, now=NOW, cache_dir=tmp_path)
        assert out["status"] == "unverified" and out["matches"] == [] and out["source_url"] is None, repr(brand)


def _gpu_recall(name):  # SIM fixture, not a real recall
    return [{"Title": f"MSI Recalls {name} Graphics Cards (SIM fixture)", "RecallDate": "2026-02-03T00:00:00",
             "URL": "https://example.test/msi", "Products": [{"Name": f"MSI {name} graphics card"}], "Manufacturers": []}]


def test_one_model_token_with_a_different_variant_is_possible_never_recalled(tmp_path):  # #291: 4070 Ti recall, 4070 Super bid
    out = check_product("MSI rtx 4070 super 12gb", "MSI", fetch=serve(_gpu_recall("GeForce RTX 4070 Ti")), now=NOW, cache_dir=tmp_path)
    assert out["status"] == "possible" and out["matches"] == [] and out["possible"][0]["url"] == "https://example.test/msi"


def test_a_plain_model_against_a_ti_recall_is_possible(tmp_path):
    out = check_product("MSI rtx 4070 12gb", "MSI", fetch=serve(_gpu_recall("GeForce RTX 4070 Ti")), now=NOW, cache_dir=tmp_path)
    assert out["status"] == "possible"


def test_the_full_model_with_the_same_variant_is_recalled(tmp_path):
    out = check_product("MSI rtx 4070 super 12gb", "MSI", fetch=serve(_gpu_recall("GeForce RTX 4070 Super")), now=NOW, cache_dir=tmp_path)
    assert out["status"] == "recalled" and out["possible"] == []
