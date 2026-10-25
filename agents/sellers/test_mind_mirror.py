"""Central Comp MIRROR (seller_6): a dated real listing as a price anchor, re-checked each round, never orderable."""
import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from advocate import checks as advocate  # noqa: E402
import common  # noqa: E402
from agents.sellers import mirror_live  # noqa: E402
from agents.sellers.policy import make_bid, mirror_seller  # noqa: E402
from data.mirror import not_partners  # noqa: E402

SKU = "rtx 5070 ti"
NOW = datetime(2026, 10, 25, 2, 30, 4, tzinfo=timezone.utc)


def need():
    return {"id": "need-m", "source": "live", "owned": {}, "items": [
        {"sku_spec": SKU, "condition": "new", "variant": "retail", "quantity": 1}]}


def base():
    return mirror_seller("central_computers_sf", 305) | {"id": "seller_6", "orderable": False}


def live(price, state=None, quoted=None):
    quoted = quoted if quoted is not None else base()["listings"][SKU]["price"]
    state = state or ("ok" if abs(price - quoted) < 0.005 else "price_changed")
    return lambda listing, now=None: {"state": state, "price": price, "fetched_at": NOW.isoformat(), "origin": "LIVE",
                                      "quoted": quoted}


def result(state, **kw):
    return lambda listing, now=None: {"state": state, "price": None, "fetched_at": None, "origin": "MIRROR", **kw}


def test_no_key_means_no_fetch_and_the_dated_snapshot_labelled_with_its_capture_time(monkeypatch):
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False)
    from data.baselines import brightdata
    monkeypatch.setattr(brightdata, "_one", lambda *a, **k: pytest.fail("a network scrape was attempted with no key"))
    s = base()
    out, anchor = mirror_live.refresh(s, now=NOW)
    assert anchor["source"] == "snapshot" and anchor["state"] == "not_configured"
    assert anchor["as_of"] == "2026-10-24 21:12 UTC"
    assert "Snapshot captured 2026-10-24 21:12 UTC" in anchor["label"] and "no Bright Data key is set" in anchor["label"]
    assert out["listings"][SKU]["price"] == s["listings"][SKU]["price"]
    assert anchor["label"] in out["trace_prefix"]


def test_a_live_read_replaces_the_snapshot_price_and_says_when():
    s = base()
    out, anchor = mirror_live.refresh(s, recheck_fn=live(1199.99), now=NOW)
    assert anchor["source"] == "live" and anchor["price"] == 1199.99 and anchor["quoted"] == s["listings"][SKU]["price"]
    assert "Re-checked live through Bright Data at 02:30:04 UTC" in anchor["label"]
    assert "was $1,249.99 in the snapshot" in anchor["label"]
    bid = mirror_live.annotate(make_bid(need(), out), anchor)
    common.validate("Bid", bid)
    assert bid["lines"][0]["unit_price"] == 1199.99 == bid["total_landed_price"]
    assert bid["origin"] == "MIRROR" and bid["price_anchor"]["source"] == "live"
    assert s["listings"][SKU]["price"] == 1249.99                       # the input is not changed


def test_an_unchanged_live_price_is_still_labelled_live():
    out, anchor = mirror_live.refresh(base(), recheck_fn=live(1249.99), now=NOW)
    assert anchor["source"] == "live" and "(unchanged)" in anchor["label"]


def test_the_floor_follows_the_live_price_so_a_big_drop_is_bid_as_read():
    out, _ = mirror_live.refresh(base(), recheck_fn=live(900.0), now=NOW)
    assert out["listings"][SKU]["floor"] == round(900.0 * 0.93, 2)
    assert make_bid(need(), out)["lines"][0]["unit_price"] == 900.0


def test_out_of_stock_now_means_no_bid_and_says_so():
    out, anchor = mirror_live.refresh(base(), recheck_fn=lambda l, now=None: {
        "state": "out_of_stock", "price": 1249.99, "fetched_at": NOW.isoformat(), "origin": "LIVE"}, now=NOW)
    assert out is None and "Out of stock at the store" in anchor["label"]


@pytest.mark.parametrize("state,why", [("empty", "returned no record"), ("slow", "too slow"),
                                       ("skipped", "off in this run"), ("not_configured", "no Bright Data key")])
def test_every_failed_recheck_keeps_the_snapshot_and_names_the_reason(state, why):
    s = base()
    out, anchor = mirror_live.refresh(s, recheck_fn=result(state), now=NOW)
    assert anchor["source"] == "snapshot" and why in anchor["label"]
    assert out["listings"][SKU]["price"] == s["listings"][SKU]["price"]


def test_a_raising_recheck_or_a_garbage_result_keeps_the_snapshot():
    def boom(listing, now=None):
        raise RuntimeError("secret detail that must not leak")
    out, anchor = mirror_live.refresh(base(), recheck_fn=boom, now=NOW)
    assert anchor["source"] == "snapshot" and "secret" not in anchor["label"] and "failed" in anchor["label"]
    out, anchor = mirror_live.refresh(base(), recheck_fn=lambda l, now=None: "nope", now=NOW)
    assert anchor["source"] == "snapshot"
    # a live state without a price, or a price not marked LIVE, is never trusted
    out, anchor = mirror_live.refresh(base(), recheck_fn=lambda l, now=None: {"state": "ok", "price": None, "origin": "LIVE"}, now=NOW)
    assert anchor["source"] == "snapshot"
    out, anchor = mirror_live.refresh(base(), recheck_fn=lambda l, now=None: {"state": "ok", "price": 5.0, "origin": "MIRROR"}, now=NOW)
    assert anchor["source"] == "snapshot" and out["listings"][SKU]["price"] == 1249.99


def test_a_slow_scrape_cannot_hold_the_round():
    def slow(listing, now=None):
        time.sleep(1.0)
        return {"state": "ok", "price": 1.0, "origin": "LIVE", "fetched_at": NOW.isoformat()}
    async def go():
        started = time.monotonic()
        got = await mirror_live.refresh_async(base(), recheck_fn=slow, timeout=0.1, now=NOW)
        return got, time.monotonic() - started
    (out, anchor), waited = asyncio.run(go())      # the worker thread finishes after; the round did not wait for it
    assert waited < 0.8
    assert anchor["source"] == "snapshot" and anchor["state"] == "timeout" and "did not answer in time" in anchor["label"]


def test_it_is_never_orderable_live_snapshot_or_otherwise_and_the_advocate_says_so():
    for fn in (live(1199.99), result("empty")):
        out, anchor = mirror_live.refresh(base(), recheck_fn=fn, now=NOW)
        assert out["orderable"] is False
        bid = mirror_live.annotate(make_bid(need(), out), anchor)
        assert bid["orderable"] is False and bid["origin"] == "MIRROR"
        assert not not_partners.orderable(bid)
        card = advocate.advise(need(), [bid], {}, {}, [], owned={})[0]
        assert card["recommendation"] == "veto"
        assert "advocate.mirror_not_orderable" in {w["rule_id"] for w in card["warnings"]}
