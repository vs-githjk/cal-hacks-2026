"""T7: the winning price is re-checked live (Bright Data) right before the call. Fake fetch only: no network, no key."""
import io
import socket
from datetime import datetime, timezone

import pytest

from data.baselines import brightdata
from demo import recheck, run_demo
from demo.approval_flow import run_beat4
from demo.common import Narrator
from demo.recheck import recheck as do_recheck

NOW = datetime(2026, 10, 24, 5, 40, 0, tzinfo=timezone.utc)
URL = "https://www.bestbuy.com/product/asus-prime/JJGGLHJX4K/sku/6614742"
LISTING = {"url": URL, "price": 1299.99, "cap": 1300.0, "snapshot_date": "2026-10-24T05:08:39.627Z"}


def row(price=1299.99, in_stock=True, at="2026-10-24T05:41:07+00:00", availability="In Stock"):
    return {"provider": "brightdata", "store": "bestbuy", "price": price, "in_stock": in_stock, "url": URL,
            "observed_at": at, "origin": "LIVE", "availability": availability}


def sold_out(**kw):
    return row(in_stock=False, availability="Sold Out", **kw)


def fake(rows, calls=None):
    def _f(*, urls=None, **kw):
        if calls is not None:
            calls.append(list(urls))
        return rows
    return _f


@pytest.fixture(scope="module")
def rounds():
    buf = io.StringIO()
    run = run_demo.run_all({2}, now=NOW, say=Narrator(False, buf))
    return run["beats"]["1"], run["beats"]["2"]


def beat4(rounds, fn):
    buf = io.StringIO()
    out = run_beat4(rounds[0], rounds[1], NOW, Narrator(True, buf), recheck_fn=fn)
    return out, buf.getvalue()


def via(rows, status="empty", calls=None):
    """A recheck_fn for beat 4: the fake fetch answers for whatever URL the winner has."""
    def fetch(*, urls=None, **kw):
        return [dict(r, url=urls[0]) for r in rows]
    return lambda listing: do_recheck(listing, fetch=fetch, status=lambda: {"last_result": status}, now=NOW)


# ---------- recheck() ----------

def test_a_not_configured_makes_no_request(monkeypatch):
    def no_net(*a, **k):
        raise AssertionError("tried to open a socket")
    monkeypatch.setattr(socket.socket, "connect", no_net)
    brightdata.reset()
    r = do_recheck(LISTING, now=NOW)   # real fetch, no key in the environment
    assert r["state"] == "not_configured" and r["price"] is None and r["origin"] == "MIRROR" and r["fetched_at"] is None


def test_b_same_price_is_ok_live():
    calls = []
    r = do_recheck(LISTING, fetch=fake([row()], calls), now=NOW)
    assert r["state"] == "ok" and r["price"] == 1299.99 and r["origin"] == "LIVE"
    assert r["fetched_at"] == "2026-10-24T05:41:07+00:00"
    assert calls == [[URL]]   # one call, the winner's URL only


def test_c_price_change_is_reported_in_both_directions():
    up = do_recheck(LISTING, fetch=fake([row(1349.0)]), now=NOW)
    down = do_recheck(LISTING, fetch=fake([row(1249.0)]), now=NOW)
    assert (up["state"], up["price"], up["origin"]) == ("price_changed", 1349.0, "LIVE")
    assert (down["state"], down["price"]) == ("price_changed", 1249.0)


def test_d_out_of_stock_beats_a_matching_price():
    r = do_recheck(LISTING, fetch=fake([sold_out()]), now=NOW)
    assert r["state"] == "out_of_stock" and r["price"] == 1299.99 and r["origin"] == "LIVE"


def test_e_slow_and_empty_fall_back_to_mirror_with_the_reason():
    slow = do_recheck(LISTING, fetch=fake([]), status=lambda: {"last_result": "slow"}, now=NOW)
    empty = do_recheck(LISTING, fetch=fake([]), status=lambda: {"last_result": "empty"}, now=NOW)
    blocked = do_recheck(LISTING, fetch=fake([]), status=lambda: {"last_result": "blocked"}, now=NOW)
    assert (slow["state"], slow["origin"], slow["price"]) == ("slow", "MIRROR", None)
    assert (empty["state"], empty["origin"]) == ("empty", "MIRROR")
    assert blocked["state"] == "empty" and blocked["detail"] == "blocked"   # never retried, never hidden


def test_other_url_rows_are_ignored():
    other = dict(row(1.0), url="https://www.bestbuy.com/other")
    r = do_recheck(LISTING, fetch=fake([other]), now=NOW)
    assert r["state"] == "empty" and r["price"] is None


def test_cap_edge_exact_cap_is_inside_one_cent_over_is_out():
    assert recheck.stop_reason({"state": "price_changed", "price": 1300.0}, 1300.0, 1300.0) is None   # equal to the cap, not above the quote
    r = recheck.stop_reason({"state": "price_changed", "price": 1300.01}, 1299.99, 1300.0)
    assert "above the $1,300.00 cap" in r and "$1,300.01" in r
    # a rise that stays inside the cap still stops the call: the mandate is for the quoted amount
    assert "rose" in recheck.stop_reason({"state": "price_changed", "price": 1300.0}, 1299.99, 1300.0)
    assert recheck.stop_reason({"state": "price_changed", "price": 1249.0}, 1299.99, 1300.0) is None   # cheaper: go on
    assert "out of stock" in recheck.stop_reason({"state": "out_of_stock", "price": 1299.99}, 1299.99, 1300.0)
    for s in ("ok", "slow", "empty", "not_configured", "skipped", "stock_unknown"):
        assert recheck.stop_reason({"state": s, "price": None}, 1299.99, 1300.0) is None


# ---------- beat 4 ----------

def test_beat4_not_configured_prints_the_mirror_line_and_continues(rounds):
    out, text = beat4(rounds, None)   # default recheck, no key
    assert "Live re-check: Bright Data not configured, using the MIRROR price from 2026-10-24" in text
    assert "fetching live price" not in text
    assert out["recheck"]["state"] == "not_configured" and out["charge"]["status"].startswith("succeeded")
    assert [a["decision"]["approved"] for a in out["attempts"]] == [False, False, True]


def test_beat4_same_price_prints_the_live_line_and_continues(rounds):
    out, text = beat4(rounds, via([row()]))
    assert "Live re-check through Bright Data: $1,299.99, in stock, 05:41:07 UTC" in text
    assert out["recheck"]["state"] == "ok" and out["recheck"]["origin"] == "LIVE"
    assert out["can_charge_after"]["ok"]


def test_beat4_price_rose_stops_before_the_mandate_and_the_approval(rounds):
    out, text = beat4(rounds, via([row(1349.0)]))
    assert out["stopped"]["at"] == "recheck" and "above the $1,300.00 cap" in out["stopped"]["reason"]
    assert out["recheck"]["state"] == "price_changed"
    assert "call NOT placed" in text and "mandate" not in text.split("call NOT placed")[1]
    for k in ("mandate", "attempts", "charge", "approval_record"):
        assert k not in out


def test_beat4_out_of_stock_stops_the_call(rounds):
    out, text = beat4(rounds, via([sold_out()]))
    assert "out of stock" in out["stopped"]["reason"] and "call NOT placed" in text and "attempts" not in out


def test_beat4_cheaper_live_price_goes_on_and_the_mandate_keeps_the_quote(rounds):
    out, text = beat4(rounds, via([row(1249.0)]))
    assert "stopped" not in out and out["mandate"]["amount"] == 1299.99
    assert "$1,249.00" in text and "mandate stays at the quoted $1,299.99" in text


def test_beat4_slow_prints_one_fetching_line_then_the_mirror_fallback(rounds):
    out, text = beat4(rounds, via([], status="slow"))
    assert text.count("fetching live price") == 1
    after = text.split("fetching live price")[1].split("\n")[1]
    assert after.lstrip().startswith("[MIRROR]") and "no answer in time" in after and "stands ($1,299.99)" in after
    assert out["recheck"]["state"] == "slow" and out["recheck"]["origin"] == "MIRROR" and "stopped" not in out


def test_run_all_with_a_stopped_beat4_reports_it_in_the_checks(monkeypatch):
    monkeypatch.setattr("demo.recheck.recheck", lambda listing, **kw: {"state": "out_of_stock", "price": 1299.99, "fetched_at": "x", "origin": "LIVE"})
    run = run_demo.run_all({4}, now=NOW, say=Narrator(False, io.StringIO()), live_recheck=True)
    assert run["checks"]["beat4_call_placed_after_live_recheck"] is False
    assert "mandate" not in run["artifacts"] and "beat4_approved_only_on_third_try" not in run["checks"]


# ---------- fix 1: the live re-check is opt-in, the bridge stays offline ----------

def test_run_all_default_makes_no_fetch_and_beat4_has_the_bridge_keys(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the default run fetched live")
    monkeypatch.setattr("demo.recheck.recheck", boom)
    monkeypatch.setattr("demo.recheck._fetch_default", boom)
    buf = io.StringIO()
    run = run_demo.run_all({4}, now=NOW, say=Narrator(True, buf))
    b4 = run["beats"]["4"]
    assert b4["recheck"]["state"] == "skipped" and b4["recheck"]["origin"] == "MIRROR" and "stopped" not in b4
    assert b4["mandate"] and b4["charge"]
    assert "Live re-check: off in this run, using the MIRROR price from 2026-10-24" in buf.getvalue()
    assert "fetching live price" not in buf.getvalue()


def test_bridge_plan_survives_an_out_of_stock_recheck_when_the_flag_is_off(monkeypatch):
    from demo import bridge
    monkeypatch.setattr("demo.recheck.recheck", lambda listing, **kw: {"state": "out_of_stock", "price": 1299.99, "fetched_at": "x", "origin": "LIVE"})
    run = run_demo.run_all(now=NOW, say=Narrator(False, io.StringIO()))   # exactly how bridge.py calls it
    assert "mandate" in run["beats"]["4"]
    assert any(st.reducer == "create_mandate" for st in bridge.plan(run))


def test_run_all_live_recheck_true_is_what_stops_the_call(monkeypatch):
    monkeypatch.setattr("demo.recheck.recheck", lambda listing, **kw: {"state": "out_of_stock", "price": 1299.99, "fetched_at": "x", "origin": "LIVE"})
    run = run_demo.run_all({4}, now=NOW, say=Narrator(False, io.StringIO()), live_recheck=True)
    assert "stopped" in run["beats"]["4"]


def test_main_turns_the_live_recheck_on(monkeypatch):
    seen = {}
    real = run_demo.run_all

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(run_demo, "run_all", spy)
    assert run_demo.main(["--beat", "4", "--no-write"]) == 0
    assert seen["live_recheck"] is True


# ---------- fix 2: an unreadable availability is not 'out of stock' ----------

@pytest.mark.parametrize("raw", [None, "", "Add to Cart", "Ship to Home"])
def test_unreadable_availability_is_stock_unknown_never_out_of_stock(raw):
    r = do_recheck(LISTING, fetch=fake([row(in_stock=False, availability=raw)]), now=NOW)
    assert r["state"] == "stock_unknown" and r["price"] == 1299.99 and r["origin"] == "LIVE" and r["availability"] == raw
    assert recheck.stop_reason(r, 1299.99, 1300.0) is None   # decision: unreadable stock alone keeps the quote and goes on


@pytest.mark.parametrize("raw", ["Sold Out", "Out of Stock", "Coming Soon"])
def test_recognised_sold_out_words_still_stop(raw):
    r = do_recheck(LISTING, fetch=fake([row(in_stock=False, availability=raw)]), now=NOW)
    assert r["state"] == "out_of_stock"


@pytest.mark.parametrize("raw,shown", [(None, "no value"), ("", "no value"), ("Add to Cart", "'Add to Cart'")])
def test_beat4_stock_unknown_prints_the_raw_value_and_continues_as_mirror(rounds, raw, shown):
    out, text = beat4(rounds, via([row(in_stock=False, availability=raw)]))
    line = next(ln for ln in text.splitlines() if "could not be read" in ln)
    assert line.lstrip().startswith("[MIRROR]") and f"stock could not be read ({shown})" in line and "$1,299.99" in line
    assert "OUT OF STOCK" not in text and "call NOT placed" not in text
    assert "stopped" not in out and out["recheck"]["state"] == "stock_unknown" and out["can_charge_after"]["ok"]


def test_beat4_stock_unknown_but_price_rose_still_stops(rounds):
    out, text = beat4(rounds, via([row(1349.0, in_stock=False, availability="Add to Cart")]))
    assert "above the $1,300.00 cap" in out["stopped"]["reason"] and "call NOT placed" in text and "OUT OF STOCK" not in text


def test_stock_state_words():
    for raw, state in (("Sold Out", "out"), ("In Stock", "in"), ("Add to Cart", "unknown"), (None, "unknown"), ("", "unknown")):
        assert brightdata.stock_state(raw) == state, raw
