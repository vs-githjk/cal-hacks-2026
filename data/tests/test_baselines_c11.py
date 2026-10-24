"""c11 (#204): dated baselines from 2 sources, a recorded price feed, and saved Bright Data rows read without calling Bright Data."""
import json

import data.baselines as b
from data.baselines import baseline, observations, write_feed


def test_every_feed_row_has_a_timestamp_url_and_source_label(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "HERE", tmp_path)
    feed = write_feed()
    assert feed["from"] and feed["to"] and feed["from"] <= feed["to"]
    for r in feed["rows"]:
        assert r["observed_at"] and r["url"] and r["origin"] in ("LIVE", "MIRROR")
    assert json.loads((tmp_path / "feed.json").read_text())["to"] == feed["to"]


def test_demo_item_baseline_rows_are_dated_with_urls_from_two_owners():
    rows = observations()
    at = max(r["observed_at"] for r in rows)
    out = baseline("rtx 5070 ti", at, rows)
    assert out["status"] == "ok" and len(out["owners"]) >= 2
    assert out["rows"] and all(r["observed_at"] and r["url"] for r in out["rows"])


def _bd_row(price, url, at="2026-10-24T12:00:00+00:00"):
    return {"provider": "brightdata", "store": "bestbuy", "sku": "rtx 5070 ti", "title": "RTX 5070 Ti", "price": price, "in_stock": True,
            "condition": "new", "kind": "ask", "observed_at": at, "sold_date": None, "url": url, "snapshot_id": "s1", "origin": "LIVE"}


def test_saved_bright_data_rows_are_read_as_mirror_and_never_fetched(tmp_path, monkeypatch):
    import data.baselines.brightdata as bd
    monkeypatch.setattr(bd, "observations", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Bright Data was called")))
    (tmp_path / "brightdata-20261024.json").write_text(json.dumps([_bd_row(1249.99, "https://www.bestbuy.com/x"), _bd_row(None, "https://www.bestbuy.com/y")]))
    monkeypatch.setattr(b, "RECORDED", tmp_path)
    got = [r for r in observations() if r["provider"] == "brightdata"]
    assert [(r["price"], r["origin"]) for r in got] == [(1249.99, "MIRROR")]  # stored rows are MIRROR; a row with no price is dropped


def test_no_recorded_folder_means_no_bright_data_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "RECORDED", tmp_path / "missing")
    assert not [r for r in observations() if r["provider"] == "brightdata"]


def test_a_saved_row_missing_a_field_baseline_reads_is_skipped(tmp_path, monkeypatch):  # review Low on #229
    rows = [_bd_row(1249.99, "https://www.bestbuy.com/x")] + [{k: v for k, v in _bd_row(1, "https://www.bestbuy.com/y").items() if k != drop}
                                                               for drop in ("sku", "kind", "store", "in_stock", "condition")]
    (tmp_path / "brightdata-20261024.json").write_text(json.dumps(rows))
    monkeypatch.setattr(b, "RECORDED", tmp_path)
    got = [r for r in observations() if r["provider"] == "brightdata"]
    assert [r["price"] for r in got] == [1249.99]
    baseline("rtx 5070 ti", "2026-10-24T13:00:00+00:00", got)  # no KeyError
