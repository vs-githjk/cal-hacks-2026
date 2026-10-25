"""Market Pulse fair-price band: fair_band(part_sku) -> {low, median, high, n, as_of, source}.
No network, no key: Tiger Data is a fake rows provider, the MIRROR snapshots and the SIM catalog are in-memory lists."""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agents.pulse import fair_band as FB  # noqa: E402
from data.tiger import store  # noqa: E402

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
SKU = "rtx 5070 ti"
CORE = {"low", "median", "high", "n", "as_of", "source"}


def trow(cents, days_ago, origin="MIRROR"):
    return {"price_cents": cents, "ts": NOW - timedelta(days=days_ago, hours=1), "origin": origin}


def tiger(rows, status="ok"):
    calls = []

    def provider(sku, days):
        calls.append((sku, days))
        return {"status": status, "rows": rows if status == "ok" else []}
    provider.calls = calls
    return provider


def snap(price, observed="2026-10-24T05:08:39.627Z", **kw):
    row = {"sku": SKU, "price": price, "in_stock": True, "kind": "ask", "store": "bestbuy", "condition": "new",
           "observed_at": observed, "origin": "MIRROR"}
    row.update(kw)
    return row


CATALOG = [{"seller": "seller_1", "sku": SKU, "price": 1299.99}, {"seller": "seller_3", "sku": SKU, "price": 1199.0},
           {"seller": "seller_5", "sku": SKU, "price": 1259.5}]


def bands(rows=None, *, status="ok", snapshots=(), catalog=()):
    return FB.FairBands(tiger_rows=tiger(rows or [], status), snapshots=lambda: list(snapshots), catalog=lambda: list(catalog), now=lambda: NOW)


# ---- the interface ----------------------------------------------------------

def test_fair_band_returns_low_median_high_n_as_of_source_in_dollars_from_tiger_rows():
    rows = [trow(c, 1) for c in (120000, 125000, 127900, 130000, 135000)]
    out = bands(rows).band(SKU)
    assert CORE <= set(out)
    assert (out["low"], out["median"], out["high"], out["n"]) == (1250.00, 1279.00, 1300.00, 5)
    assert out["as_of"] == "2026-10-24" and out["origin"] == "MIRROR" and out["window_days"] == 7
    assert out["source"].startswith("Tiger Data price_obs") and "last 7 days" in out["source"]


def test_the_module_function_takes_a_sku_and_the_same_injected_pieces():
    rows = [trow(c, 2) for c in (100000, 110000, 120000)]
    out = FB.fair_band("  RTX 5070 Ti ", tiger_rows=tiger(rows), snapshots=lambda: [], catalog=lambda: [], now=lambda: NOW)
    assert CORE <= set(out) and out["sku"] == SKU and out["median"] == 1100.00


@pytest.mark.parametrize("bad", ["", "   ", None, 5, ["rtx"]])
def test_a_bad_sku_is_a_value_error_not_a_guess(bad):
    with pytest.raises(ValueError):
        bands().band(bad)


def test_a_thin_seven_day_window_falls_back_to_the_thirty_day_window_and_both_are_listed():
    rows = [trow(120000, 1), trow(121000, 2)] + [trow(c, d) for c, d in ((100000, 10), (110000, 15), (115000, 20), (118000, 25))]
    out = bands(rows).band(SKU)
    assert out["window_days"] == 30 and out["n"] == 6 and out["thin"] is False
    assert out["windows"]["7"]["n"] == 2 and out["windows"]["30"]["n"] == 6
    assert "last 30 days" in out["source"]


def test_a_band_of_fewer_than_three_prices_is_marked_thin_and_never_padded():
    out = bands([trow(120000, 1), trow(130000, 2)]).band(SKU)
    assert out["thin"] is True and out["n"] == 2 and out["low"] == 1225.0 and out["high"] == 1275.0


def test_rows_older_than_thirty_days_or_in_the_future_are_ignored():
    rows = [trow(100000, 40), trow(110000, 31), trow(120000, -3), trow(130000, 1)]
    out = bands(rows).band(SKU)
    assert out["n"] == 1 and out["median"] == 1300.0


def test_origin_is_the_origin_of_the_rows_and_a_stored_live_reads_as_mirror():
    sim = bands([trow(c, 1, "SIM") for c in (100000, 110000, 120000)]).band(SKU)
    assert sim["origin"] == "SIM" and "SIM" in sim["label"]
    mixed = bands([trow(100000, 1, "SIM"), trow(110000, 1, "MIRROR"), trow(120000, 1, "LIVE")]).band(SKU)
    assert mixed["origin"] == "MIRROR+SIM"
    assert bands([trow(100000, 1, "weird")] * 3).band(SKU)["origin"] == "SIM"       # unknown origin never reads as real


# ---- the fallbacks ----------------------------------------------------------

def test_without_tiger_rows_the_dated_mirror_snapshots_give_the_band_and_say_so():
    snaps = [snap(p) for p in (1199.99, 1249.99, 1249.99, 1299.99)]
    out = bands(status="not_configured", snapshots=snaps).band(SKU)
    assert out["origin"] == "MIRROR" and out["tiger"] == "not_configured"
    assert out["n"] == 4 and out["median"] == 1249.99 and out["as_of"] == "2026-10-24"
    assert "MIRROR snapshots" in out["source"] and "2026-10-24" in out["source"] and "Tiger Data" in out["source"]


def test_a_tiger_error_never_raises_and_falls_back_with_the_state_named():
    out = bands(status="error", snapshots=[snap(1250.0)] * 3).band(SKU)
    assert out["tiger"] == "error" and out["origin"] == "MIRROR" and out["n"] == 3


def test_tiger_configured_but_empty_also_falls_back_and_says_no_rows():
    out = bands([], snapshots=[snap(1250.0)] * 3).band(SKU)
    assert out["tiger"] == "no_rows" and out["origin"] == "MIRROR"


def test_snapshots_that_are_not_comparable_asks_never_enter_the_band():
    junk = [snap(640.0, kind="sold", store="ebay_sold"), snap(100.0, in_stock=False), snap(900.0, store="centralcomputers"),
            snap(950.0, store="ebay_live"), snap(10.0, condition="open-box"), snap(None), snap(float("nan")), snap(-5.0),
            snap(1200.0, sku="rtx 4070 super 12gb"), snap(1111.0, observed="2026-08-01T00:00:00Z"), snap(1250.0), snap(1260.0), snap(1270.0)]
    out = bands(status="not_configured", snapshots=junk).band(SKU)
    assert out["n"] == 3 and (out["low"], out["median"], out["high"]) == (1255.0, 1260.0, 1265.0)


FIVE_SIM = [{"seller": f"seller_{i}", "sku": SKU, "price": p} for i, p in enumerate((1199.0, 1259.5, 1279.0, 1299.99, 1349.0), 1)]


def test_with_no_snapshot_either_enough_sim_listings_give_a_band_labelled_sim():
    out = bands(status="not_configured", catalog=FIVE_SIM).band(SKU)
    assert out["origin"] == "SIM" and out["n"] == 5 and out["median"] == 1279.0
    assert out["window_days"] is None and out["windows"] == {}
    assert "SIM" in out["source"] and "no price history" in out["label"]


@pytest.mark.parametrize("count", [1, 2, 3])
def test_too_few_sim_listings_give_no_numbers_because_a_median_would_be_a_rivals_price(count):
    out = bands(status="not_configured", catalog=FIVE_SIM[:count]).band(SKU)
    assert out["n"] == 0 and out["low"] is out["median"] is out["high"] is None and out["origin"] == "no data"
    assert "revealing" in out["label"] and not re.search(r"\$\d", out["label"])


def test_two_sim_listings_cannot_be_turned_back_into_the_rivals_price():
    """Seller_1 asks about rx 7800 xt with one rival listed: the median of 2 prices would give the rival's price away (2*median - own)."""
    two = [{"seller": "seller_1", "sku": "rx 7800 xt", "price": 489.99}, {"seller": "seller_3", "sku": "rx 7800 xt", "price": 449.0}]
    for asker in (None, "seller_1", "seller_3"):
        out = bands(status="not_configured", catalog=two).band("rx 7800 xt", exclude_seller=asker)
        assert out["median"] is None and out["low"] is None and out["high"] is None


def test_the_askers_own_listing_is_left_out_and_four_others_are_needed():
    four_others_plus_asker = FIVE_SIM + [{"seller": "asker", "sku": SKU, "price": 1111.0}]
    out = bands(status="not_configured", catalog=four_others_plus_asker[:4] + four_others_plus_asker[5:]).band(SKU, exclude_seller="asker")
    assert out["n"] == 4 and out["origin"] == "SIM" and 1111.0 not in (out["low"], out["median"], out["high"])
    three_others = bands(status="not_configured", catalog=FIVE_SIM[:3] + [FIVE_SIM[3] | {"seller": "asker"}]).band(SKU, exclude_seller="asker")
    assert three_others["n"] == 0                                  # 3 others + the asker is 4 listings, but only 3 rivals: refused
    public_four = bands(status="not_configured", catalog=FIVE_SIM[:4]).band(SKU)
    assert public_four["n"] == 0                                   # no asker known: it may be one of the 4, so 5 are needed


def test_one_seller_listing_twice_counts_once():
    dup = FIVE_SIM[:2] + [{"seller": "seller_1", "sku": SKU, "price": 1200.0}] * 5
    assert bands(status="not_configured", catalog=dup).band(SKU)["n"] == 0


def test_the_sim_rule_does_not_touch_dated_prices():
    out = bands([trow(125000, 1)] * 3, catalog=FIVE_SIM[:1]).band(SKU, exclude_seller="seller_1")
    assert out["origin"] == "MIRROR" and out["n"] == 3


def test_a_part_nothing_knows_has_no_numbers_and_says_so():
    out = bands(status="not_configured").band("unobtainium 9000")
    assert out["n"] == 0 and out["low"] is out["median"] is out["high"] is None and out["as_of"] is None
    assert out["origin"] == "no data" and out["source"] and "no data" in out["label"]


def test_the_provider_is_asked_once_for_the_thirty_day_window():
    provider = tiger([trow(100000, 1)] * 3)
    FB.FairBands(tiger_rows=provider, snapshots=lambda: [], catalog=lambda: [], now=lambda: NOW).band(SKU)
    assert provider.calls == [(SKU, 30)]


# ---- the public pulse -------------------------------------------------------

def test_the_pulse_has_a_band_for_every_part_a_time_and_labels(tmp_path):
    b = bands([trow(c, 1) for c in (120000, 125000, 127900)], snapshots=[])
    pulse = FB.build_pulse([SKU, "psu 750w", SKU], bands=b)
    assert pulse["kind"] == "market-pulse" and pulse["published_at"] == "2026-10-25T12:00:00Z"
    assert list(pulse["bands"]) == [SKU, "psu 750w"]                       # no duplicates, order kept
    assert CORE <= set(pulse["bands"][SKU]) and pulse["bands"][SKU]["median"] == 1250.0
    assert pulse["labels"] == ["MIRROR"] and pulse["sourced"] is True


def test_publish_pulse_writes_one_json_file_the_buyer_can_read(tmp_path):
    path = tmp_path / "pulse" / "latest.json"
    b = bands([trow(c, 1) for c in (120000, 125000, 127900)])
    pulse = FB.publish_pulse([SKU], path=path, bands=b)
    assert json.loads(path.read_text()) == pulse
    assert not list(path.parent.glob("*.tmp"))
    assert FB.read_pulse(path, now=NOW)["bands"][SKU]["n"] == 3


def test_read_pulse_refuses_a_missing_old_or_unreadable_file():
    assert FB.read_pulse(Path("/nonexistent/x.json")) is None
    for text in ("", "not json", "[]", json.dumps({"kind": "other"})):
        p = Path(__file__).with_name("_tmp_pulse.json")
        try:
            p.write_text(text)
            assert FB.read_pulse(p) is None
        finally:
            p.unlink(missing_ok=True)


def test_read_pulse_refuses_a_pulse_older_than_the_max_age(tmp_path):
    path = tmp_path / "latest.json"
    FB.publish_pulse([SKU], path=path, bands=bands([trow(100000, 1)] * 3))
    assert FB.read_pulse(path, now=NOW + timedelta(seconds=FB.PULSE_MAX_AGE_S - 1)) is not None
    assert FB.read_pulse(path, now=NOW + timedelta(seconds=FB.PULSE_MAX_AGE_S + 1)) is None


# ---- is Tiger holding rows? --------------------------------------------------

class FakeCursor:
    def __init__(self, rows):
        self.rows, self.sql = rows, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.autocommit = False

    def cursor(self):
        return FakeCursor(self.rows)

    def close(self):
        pass


def test_tiger_row_counts_reports_rows_per_origin_and_the_newest_day(monkeypatch):
    monkeypatch.setenv(store.ENV, "postgres://user:pw@example.invalid/db")
    out = FB.tiger_row_counts(connect=lambda: FakeConn([("MIRROR", 40, NOW), ("SIM", 3, NOW - timedelta(days=2))]))
    assert out == {"status": "ok", "rows": 43, "by_origin": {"MIRROR": 40, "SIM": 3}, "newest": "2026-10-25"}
    assert "pw" not in json.dumps(out)


def test_tiger_row_counts_says_not_configured_without_the_url(monkeypatch):
    monkeypatch.delenv(store.ENV, raising=False)
    assert FB.tiger_row_counts() == {"status": "not_configured", "rows": 0, "by_origin": {}, "newest": None}


def test_tiger_prices_reads_rows_for_one_sku_and_never_leaks_the_url(monkeypatch):
    monkeypatch.setenv(store.ENV, "postgres://user:secretpw@example.invalid/db")
    seen = {}

    class Cur(FakeCursor):
        def execute(self, sql, params=None):
            seen["params"] = params
            seen["sql"] = sql

    class Conn(FakeConn):
        def cursor(self):
            return Cur([(125000, NOW - timedelta(hours=2), "MIRROR", "https://shop.example/p/1"), (None, NOW, "SIM", None)])
    out = FB.tiger_prices(SKU, 30, connect=lambda: Conn([]))
    assert out["status"] == "ok" and out["rows"] == [{"price_cents": 125000, "ts": NOW - timedelta(hours=2), "origin": "MIRROR",
                                                      "url": "https://shop.example/p/1"}]
    assert seen["params"][0] == SKU and "in_stock" in seen["sql"] and "LIMIT" in seen["sql"]


def test_tiger_prices_not_configured_and_error_have_no_rows(monkeypatch):
    monkeypatch.delenv(store.ENV, raising=False)
    assert FB.tiger_prices(SKU, 30) == {"status": "not_configured", "rows": []}
    monkeypatch.setenv(store.ENV, "postgres://u:p@example.invalid/db")

    def boom():
        raise store.TigerError("connection failed (X)")
    assert FB.tiger_prices(SKU, 30, connect=boom) == {"status": "error", "rows": []}


# ---- the command line --------------------------------------------------------

def test_cli_prints_the_band_as_json(monkeypatch, capsys):
    monkeypatch.delenv(store.ENV, raising=False)
    monkeypatch.setattr(FB, "default_snapshots", lambda: [snap(p) for p in (1200.0, 1250.0, 1300.0)])
    assert FB.main([SKU, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["median"] == 1250.0 and out["origin"] == "MIRROR"


def test_cli_tiger_check_says_whether_tiger_holds_rows(monkeypatch, capsys):
    monkeypatch.delenv(store.ENV, raising=False)
    assert FB.main(["--tiger-check"]) == 0
    assert "not_configured" in capsys.readouterr().out


# ---- the buyer's advisory call: fair_band(sku) -> {low, high, as_of, source_url} or None -----------------------------

def test_the_buyers_call_gets_low_high_as_of_and_a_source_url_from_dated_tiger_rows():
    rows = [dict(trow(c, d), url=u) for c, d, u in ((120000, 3, "https://shop.example/old"), (125000, 1, "https://shop.example/new"),
                                                    (130000, 2, ""))]
    out = FB.fair_band(SKU, tiger_rows=tiger(rows), snapshots=lambda: [], catalog=lambda: [], now=lambda: NOW)
    assert {"low", "high", "as_of", "source_url"} <= set(out)
    assert isinstance(out["low"], float) and isinstance(out["high"], float) and out["low"] <= out["high"]
    assert out["as_of"] == "2026-10-24" and out["source_url"] == "https://shop.example/new"      # the newest price that names its page


def test_the_buyers_call_takes_the_page_of_a_dated_snapshot_when_tiger_has_no_rows():
    snaps = [snap(1250.0, url="https://www.bestbuy.com/p/1"), snap(1260.0, url="not a url"), snap(1270.0, observed="2026-10-23T05:00:00Z")]
    out = FB.fair_band(SKU, tiger_rows=tiger([], "not_configured"), snapshots=lambda: snaps, catalog=lambda: [], now=lambda: NOW)
    assert out["source_url"] == "https://www.bestbuy.com/p/1" and out["origin"] == "MIRROR" and out["as_of"] == "2026-10-24"


def test_the_buyers_call_is_none_when_there_is_no_dated_data_even_if_sim_listings_exist():
    none = dict(tiger_rows=tiger([], "not_configured"), snapshots=lambda: [], now=lambda: NOW)
    assert FB.fair_band("unobtainium 9000", catalog=lambda: [], **none) is None
    assert FB.fair_band(SKU, catalog=lambda: FIVE_SIM, **none) is None                  # a SIM band is not dated price data
    sim_rows = [trow(c, 1, "SIM") for c in (100000, 110000, 120000)]
    assert FB.fair_band(SKU, tiger_rows=tiger(sim_rows), snapshots=lambda: [], catalog=lambda: [], now=lambda: NOW) is None


@pytest.mark.parametrize("bad", ["", "   ", None, 5, ["rtx"]])
def test_the_buyers_call_never_raises_on_a_bad_sku(bad):
    assert FB.fair_band(bad, tiger_rows=tiger([]), snapshots=lambda: [], catalog=lambda: [], now=lambda: NOW) is None


def test_the_buyers_call_is_deterministic_and_never_changes_its_inputs():
    rows = [trow(c, 1) for c in (120000, 125000, 127900, 130000, 135000)]
    snapshot = list(rows)
    args = dict(tiger_rows=tiger(rows), snapshots=lambda: [], catalog=lambda: [], now=lambda: NOW)
    assert FB.fair_band(SKU, **args) == FB.fair_band(SKU, **args) and rows == snapshot


def test_the_buyers_call_works_from_the_agents_folder_import_path_with_no_data():
    import subprocess
    code = "import sys; sys.path.insert(0, 'agents'); from pulse.fair_band import fair_band; print(fair_band('zzz unknown part'))"
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "None"
