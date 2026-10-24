import json

from data.timeseries import FOOTER, daily_min, latest_per_listing, load, price_series, win_rates


def row(url, price, at, store="bestbuy", stock=True, kind="ask", sku="rtx 5070 ti"):
    return {"provider": "apify", "store": store, "sku": sku, "price": price, "in_stock": stock, "condition": "new", "kind": kind,
            "observed_at": at, "url": url, "origin": "MIRROR"}


ROWS = [row("u1", 1300.0, "2026-10-24T09:00:00+00:00"), row("u1", 1250.0, "2026-10-23T09:00:00+00:00"), row("u2", 1400.0, "2026-10-24T05:00:00+00:00", store="bh"),
        row("u3", 900.0, "2026-10-24T05:00:00+00:00", store="newegg", stock=False), row("u4", 640.0, "2026-10-24T05:00:00+00:00", store="ebay_sold", kind="sold"),
        row("u5", 800.0, "2026-10-24T05:00:00+00:00", sku="rtx 5080")]


def test_price_series_is_ordered_by_time():
    db = load(ROWS, run_files=[])
    assert price_series(db, "u1") == [("2026-10-23T09:00:00+00:00", 1250.0), ("2026-10-24T09:00:00+00:00", 1300.0)]


def test_latest_per_listing_picks_the_newest():
    db = load(ROWS, run_files=[])
    out = {r[0]: r[3] for r in latest_per_listing(db, "rtx 5070 ti")}
    assert out["u1"] == 1300.0 and set(out) == {"u1", "u2", "u3", "u4"}


def test_daily_min_ignores_out_of_stock_and_sold_rows():
    db = load(ROWS, run_files=[])
    assert daily_min(db, "rtx 5070 ti") == [("2026-10-23", 1250.0), ("2026-10-24", 1300.0)]


def test_win_rates_sum_to_one_per_archetype_with_none_as_its_own_entry(tmp_path):
    run = tmp_path / "wind_tunnel-fixture.json"
    held = lambda rows: [{"builder": f"b{i}", "archetype": a, "winner_trained": w, "winner_untrained": None} for i, (a, w) in enumerate(rows)]
    run.write_text(json.dumps({"learning": {"seeds": [
        {"seed": 0, "held_out": held([("small_case", "gadget-grove"), ("small_case", None), ("sff", "bargain-bin")])},
        {"seed": 1, "held_out": held([("small_case", "gadget-grove"), ("sff", "bargain-bin")])}]}}))
    db = load([], run_files=[run])
    rates = win_rates(db, run.name)
    assert rates["small_case"] == {"gadget-grove": 2 / 3, "none": 1 / 3}
    assert rates["sff"] == {"bargain-bin": 1.0}
    assert all(abs(sum(d.values()) - 1) < 1e-9 for d in rates.values())


def test_footer_says_tiger_data_was_not_used():
    assert "no account was set up" in FOOTER and "not used here" in FOOTER
