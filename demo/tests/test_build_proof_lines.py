"""Sponsor proof on the deal card: the Bright Data "checked Ns ago" line and the Tiger Data 7 and 30 day line.
A fake price check and a fake Tiger read stand in for the sponsors: no network, no key, no database."""
from __future__ import annotations

import time

import pytest

from demo import build, sponsors_live as S
from demo.tests.test_build import ALLOW, mirror_catalog, ok_check, run_build
from demo.tests.test_build_view import rows


def trend(days, *, n=5, lo=119900, med=124900, held=None, origins=("MIRROR",), status="ok"):
    if status != "ok":
        return {"status": status, "sku": "x", "window_days": days, "days_of_data": 0, "n": 0, "min_cents": None, "median_cents": None, "origins": []}
    return {"status": "ok", "sku": "x", "window_days": days, "days_of_data": held if held is not None else days, "n": n,
            "min_cents": lo, "median_cents": med, "now_cents": med, "direction": "flat", "origins": list(origins), "rows": []}


# ---------------------------------------------------------------- history_entry (pure)

def test_both_windows_with_data_become_dollars_with_the_days_tiger_really_holds():
    e = build.history_entry({7: trend(7, lo=119900, med=124950, held=3), 30: trend(30, n=9, lo=114900, med=127000, held=3)})
    assert e["state"] == "ok" and e["origin"] == "MIRROR"
    assert e["windows"] == [{"days": 7, "low": 1199.0, "median": 1249.5, "n": 5, "daysOfData": 3},
                            {"days": 30, "low": 1149.0, "median": 1270.0, "n": 9, "daysOfData": 3}]


def test_a_window_with_no_rows_carries_no_numbers_and_all_empty_is_no_data():
    one = build.history_entry({7: trend(7, n=0, lo=None, med=None), 30: trend(30)})
    assert [w["days"] for w in one["windows"]] == [30]
    none = build.history_entry({7: trend(7, n=0, lo=None, med=None), 30: trend(30, n=0, lo=None, med=None)})
    assert none == {"state": "no_data", "origin": "SIM", "windows": []}


@pytest.mark.parametrize("status", ["not_configured", "error"])
def test_not_configured_and_failed_reads_say_so_and_invent_no_numbers(status):
    e = build.history_entry({7: trend(7, status=status), 30: trend(30, status=status)})
    assert e == {"state": status, "origin": "SIM", "windows": []}


def test_a_stored_live_origin_is_never_shown_as_live():
    e = build.history_entry({7: trend(7, origins=("LIVE",)), 30: trend(30, origins=("LIVE", "SIM"))})
    assert e["origin"] == "SIM"
    assert build.history_entry({7: trend(7, origins=("LIVE",)), 30: trend(30, origins=("LIVE",))})["origin"] == "MIRROR"


@pytest.mark.parametrize("bad", [None, "x", [], {"status": "ok", "n": "7", "min_cents": "1", "median_cents": 1},
                                 {"status": "ok", "n": 3, "min_cents": True, "median_cents": 5}])
def test_a_malformed_read_is_an_error_not_a_crash(bad):
    e = build.history_entry({7: bad, 30: bad})
    assert e["state"] == "error" and e["windows"] == []


# ---------------------------------------------------------------- build_view

def test_history_rides_on_a_part_with_a_champion_and_never_on_one_without():
    hist = {"gpu": {"state": "ok", "origin": "LIVE", "windows": [{"days": 7, "low": 1199.0, "median": 1249.0, "n": 4, "daysOfData": 7}]},
            "cpu": {"state": "no_data", "origin": "SIM", "windows": []}}
    r = rows(closed=["gpu"])
    r["priceHistory"] = hist
    v = build.build_view(r, [], [])
    gpu = next(p for p in v["parts"] if p["part"] == "gpu")
    cpu = next(p for p in v["parts"] if p["part"] == "cpu")
    assert gpu["history"]["state"] == "ok" and gpu["history"]["origin"] == "MIRROR"   # the label is clamped, a stored read is dated
    assert "history" not in cpu
    assert hist["gpu"]["origin"] == "LIVE"   # pure: the input is untouched


def test_the_live_check_names_its_source():
    live = {"gpu": {"state": "ok", "price": 1259.0, "fetchedAt": "2026-10-24T23:50:00Z", "origin": "LIVE", "quoted": 1259.0, "at": "t", "text": "x"}}
    v = build.build_view(rows(live=live), [], [])
    lc = next(p for p in v["parts"] if p["part"] == "gpu")["champion"]["liveCheck"]
    assert lc["source"] == "Bright Data" and lc["origin"] == "LIVE" and lc["fetchedAt"] == "2026-10-24T23:50:00Z"


# ---------------------------------------------------------------- the run

def test_a_run_reads_each_bought_part_for_7_and_30_days_by_its_lowercase_sku(tmp_path):
    seen = []

    def history(sku, days):
        seen.append((sku, days))
        return trend(days)
    r, out, *_ = run_build(tmp_path=tmp_path, catalog=mirror_catalog(), allowance=ALLOW, price_check=ok_check, history=history)
    assert out["status"] == "paid"
    parts = out["view"]["parts"]
    bought = [p for p in parts if p["status"] != "owned"]
    assert {s for s, _ in seen} == {p["label"].lower() for p in bought} and {d for _, d in seen} == {7, 30} and len(seen) == 2 * len(bought)
    assert all(p["history"]["state"] == "ok" and [w["days"] for w in p["history"]["windows"]] == [7, 30] for p in bought)
    assert all("history" not in p for p in parts if p["status"] == "owned")


def test_without_a_tiger_reader_the_part_says_not_configured(tmp_path):
    r, out, *_ = run_build(tmp_path=tmp_path, allowance=ALLOW)
    gpu = next(p for p in out["view"]["parts"] if p["part"] == "gpu")
    assert gpu["history"] == {"state": "not_configured", "origin": "SIM", "windows": []}


def test_a_failing_tiger_read_is_an_error_line_and_the_build_still_pays(tmp_path):
    def boom(sku, days):
        raise OSError("down")
    r, out, *_ = run_build(tmp_path=tmp_path, allowance=ALLOW, history=boom)
    assert out["status"] == "paid"
    assert next(p for p in out["view"]["parts"] if p["part"] == "gpu")["history"]["state"] == "error"


def test_a_slow_tiger_read_is_cut_off_and_never_holds_the_build(tmp_path):
    def slow(sku, days):
        time.sleep(1.5)
        return trend(days)
    t0 = time.monotonic()
    r, out, *_ = run_build(tmp_path=tmp_path, allowance=ALLOW, history=slow, history_timeout=0.2)
    assert time.monotonic() - t0 < 1.4 and out["status"] == "paid"
    assert next(p for p in out["view"]["parts"] if p["part"] == "gpu")["history"]["state"] == "error"


# ---------------------------------------------------------------- sponsors_live.price_history

def test_price_history_without_the_tiger_env_makes_no_connection(monkeypatch):
    monkeypatch.delenv("TIGER_DATA_SERVICE_URL", raising=False)
    got = S.price_history("rtx 5070 ti", 7, read=lambda sku, days: pytest.fail("connected without a url"))
    assert got["status"] == "not_configured" and got["min_cents"] is None


def test_price_history_with_the_env_calls_the_read_and_bounds_it(monkeypatch):
    monkeypatch.setenv("TIGER_DATA_SERVICE_URL", "postgres://never-connected.invalid/x")
    assert S.price_history("a", 7, read=lambda sku, days: trend(days))["n"] == 5
    assert S.price_history("a", 7, read=lambda sku, days: time.sleep(1.0), timeout=0.1)["status"] == "error"

    def boom(sku, days):
        raise ValueError("x")
    assert S.price_history("a", 7, read=boom)["status"] == "error"
