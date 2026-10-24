import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data.recalls import recalls_for

FIX = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
TITLE = "ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition"
SIM_GPU_RECALL = [{"Title": "ASUS Recalls GeForce RTX 5070 Ti Graphics Cards Due to Fire Hazard (SIM fixture)", "RecallDate": "2026-01-02T00:00:00",
                   "URL": "https://example.test/sim-recall", "Products": [{"Name": "ASUS GeForce RTX 5070 Ti graphics card"}], "Manufacturers": []}]


def serve(items):
    return lambda url: json.dumps(items).encode()


def test_real_asus_answer_with_only_a_motherboard_recall_is_none(tmp_path):
    out = recalls_for(TITLE, "ASUS", fetch=serve(json.loads((FIX / "recalls_asus_real.json").read_text())), now=NOW, cache_dir=tmp_path)
    assert out["status"] == "none" and out["recalls"] == [] and "saferproducts.gov" in out["source_url"]
    assert "searched ProductName=ASUS on 2026-10-24" in out["reason"] and "no CPSC recall matched" in out["reason"]


def test_a_graphics_card_recall_is_found(tmp_path):  # SIM fixture, not a real recall
    out = recalls_for(TITLE, "ASUS", fetch=serve(SIM_GPU_RECALL), now=NOW, cache_dir=tmp_path)
    assert out["status"] == "found" and out["recalls"][0]["date"] == "2026-01-02"


def test_other_brand_or_unrelated_product_does_not_match(tmp_path):
    other = [{**SIM_GPU_RECALL[0], "Title": "Acme Recalls Graphics Cards", "Products": [{"Name": "Acme graphics card"}]}]
    assert recalls_for(TITLE, "ASUS", fetch=serve(other), now=NOW, cache_dir=tmp_path)["status"] == "none"


def test_any_failure_is_unverified_never_none(tmp_path):
    def boom(url):
        raise TimeoutError("slow")
    assert recalls_for(TITLE, "ASUS", fetch=boom, now=NOW, cache_dir=tmp_path)["status"] == "unverified"
    assert recalls_for(TITLE, "ASUS", fetch=lambda u: b"<html>", now=NOW, cache_dir=tmp_path)["status"] == "unverified"
    assert recalls_for(TITLE, "ASUS", fetch=lambda u: b'{"a": 1}', now=NOW, cache_dir=tmp_path)["status"] == "unverified"


def test_cache_is_reused_within_24h_and_not_after(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps(SIM_GPU_RECALL).encode()
    recalls_for(TITLE, "ASUS", fetch=fetch, now=NOW, cache_dir=tmp_path)
    again = recalls_for(TITLE, "ASUS", fetch=fetch, now=NOW + timedelta(hours=23), cache_dir=tmp_path)
    assert len(calls) == 1 and again["status"] == "found"
    recalls_for(TITLE, "ASUS", fetch=fetch, now=NOW + timedelta(hours=25), cache_dir=tmp_path)
    assert len(calls) == 2


def test_a_gaming_laptop_or_monitor_recall_does_not_match_a_graphics_card(tmp_path):  # #156
    laptop = [{"Title": "ASUS Recalls ROG Strix G16 Gaming Laptop Due to Fire Hazard", "RecallDate": "2026-02-01T00:00:00", "URL": "u1",
               "Products": [{"Name": "ASUS ROG Strix G16 Gaming Laptop with GeForce RTX graphics"}], "Manufacturers": []}]
    monitor = [{"Title": "ASUS Recalls TUF Gaming Monitors", "RecallDate": "2026-03-01T00:00:00", "URL": "u2",
                "Products": [{"Name": "ASUS TUF Gaming VG27 monitor"}], "Manufacturers": []}]
    tuf = "ASUS TUF Gaming GeForce RTX 5070 Ti 16GB GDDR7 OC Edition"
    for i, items in enumerate((laptop, monitor)):
        assert recalls_for(tuf, "ASUS", fetch=serve(items), now=NOW, cache_dir=tmp_path / str(i))["status"] == "none"


def test_a_model_token_is_required_in_the_recall(tmp_path):
    generic = [{**SIM_GPU_RECALL[0], "Title": "ASUS Recalls Graphics Cards", "Products": [{"Name": "ASUS graphics card"}]}]
    assert recalls_for(TITLE, "ASUS", fetch=serve(generic), now=NOW, cache_dir=tmp_path)["status"] == "none"


def test_an_empty_brand_is_unverified_and_never_calls_the_api(tmp_path):
    def boom(url):
        raise AssertionError("the API must not be called")
    for brand in (None, "", "   "):
        out = recalls_for(TITLE, brand, fetch=boom, now=NOW, cache_dir=tmp_path)
        assert out["status"] == "unverified" and out["recalls"] == [] and out["source_url"] is None, repr(brand)
