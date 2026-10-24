import json

from data.claim_check import real_scan
from data.claim_check.real_scan import OUT, check_card, scan, snapshot_files


def test_saved_scan_matches_the_files_on_disk_and_reruns_offline():
    saved = json.loads(OUT.read_text())
    files = snapshot_files()
    assert saved["origin"] == "MIRROR" and saved["scanned"]["files"] == [f.name for f in files]
    assert saved["scanned"]["listings"] == sum(len(json.loads(f.read_text())) for f in files)
    cards = {(c["snapshot_id"], (c["listing"] or {}).get("url") or c["source"]): c for f in files for c in json.loads(f.read_text())}
    for catch in saved["catches"]:  # each saved catch reproduces from its own snapshot row, no network
        card = cards[(catch["snapshot_id"], catch["url"])]
        again = [r for r in check_card(card, []) if r["rule_id"] == catch["rule_id"]]
        assert again and again[0]["result"] == catch["result"] == "false"


def test_the_scan_is_deterministic_and_never_fetches(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network")
    monkeypatch.setattr("socket.create_connection", boom)
    first, second = scan(observations=[]), scan(observations=[])
    assert first == second
    saved = json.loads(OUT.read_text())
    assert first["scanned"] == saved["scanned"] or first["scanned"]["listings"] >= saved["scanned"]["listings"]


def card(name, condition="unknown", stock=None, was=None, url="https://store.example/p"):
    return {"name": name, "condition": condition, "price": 100.0, "snapshot_id": "fixture", "snapshot_date": "2026-10-24T00:00:00+00:00",
            "source": url, "listing": {"url": url, "stock": stock, "was_price": was}}


def test_the_scanner_does_flag_a_title_that_differs_from_its_own_data():  # fixture, not a real listing
    assert [r["result"] for r in check_card(card("GPU NEW & SEALED", condition="open-box"), [])] == ["false"]
    assert [r["result"] for r in check_card(card("GPU NEW & SEALED", condition="new"), [])] == ["verified"]
    assert [r["result"] for r in check_card(card("GPU - in stock", stock="out_of_stock"), [])] == ["false"]
    assert check_card(card("GPU, was $200"), []) == [] or check_card(card("GPU, was $200"), [])[0]["result"] == "unverified"


def test_was_price_above_every_dated_capture_is_flagged_only_with_captures():
    rows = [{"url": "https://store.example/p", "observed_at": "2026-10-20T00:00:00+00:00", "price": 90.0},
            {"url": "https://store.example/p", "observed_at": "2026-10-22T00:00:00+00:00", "price": 100.0}]
    out = check_card(card("GPU was $200"), rows)
    assert [r["result"] for r in out if r["rule_id"] == "was_price"] == ["false"]
    assert [r["result"] for r in check_card(card("GPU was $200"), []) if r["rule_id"] == "was_price"] == ["unverified"]


def test_distinct_listings_counts_urls_not_snapshot_rows():  # #155
    saved = json.loads(OUT.read_text())["scanned"]
    cards = [c for f in snapshot_files() for c in json.loads(f.read_text())]
    urls = {(c.get("listing") or {}).get("url") or c.get("source") for c in cards}
    assert saved["distinct_listings"] == len(urls) and saved["listings"] == len(cards) and len(urls) < len(cards)
    assert scan(observations=[])["scanned"]["distinct_listings"] == len(urls)
