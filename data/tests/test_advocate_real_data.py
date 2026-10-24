"""#283 T3: the advocate prices against our dated baseline and CPSC, with an unverified fallback. Fakes only, no network.

Each test names the line it guards; deleting that line makes it fail."""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents"))


@pytest.fixture
def rd(monkeypatch):
    monkeypatch.setitem(sys.modules, "common", types.ModuleType("common"))  # checks.py imports common only to find data.*; uagents is not needed here
    sys.modules.pop("advocate.checks", None)
    from advocate import checks, real_data
    return types.SimpleNamespace(real_data=real_data, checks=checks)


def row(store, price, at="2026-10-24T05:08:00+00:00", provider="apify", kind="ask", url=None, sold=None):
    return {"provider": provider, "store": store, "sku": "rtx 5070 ti", "price": price, "in_stock": True, "condition": "new", "kind": kind,
            "observed_at": at, "sold_date": sold, "url": url or f"https://{store}.example/p/{price}", "origin": "MIRROR"}


ROWS = [row("bestbuy", 1249.99), row("microcenter", 1269.99), row("bh", 1299.99),
        row("ebay_sold", 880.0, provider="ebay-sold", kind="sold", sold="2026-10-20T00:00:00+00:00")]
AT = "2026-10-24T06:00:00+00:00"


def test_a_dated_baseline_from_two_owners_gives_a_real_source_page(rd):
    base, notes = rd.real_data.baseline_for(["RTX 5070 Ti"], as_of=AT, rows=ROWS)
    b = base["rtx 5070 ti"]
    assert notes == [] and b["unit_price"] == 1269.99 and b["source"] == "MIRROR" and b["n"] == 3
    assert b["source_url"] == "https://microcenter.example/p/1269.99" and "example.com" not in b["source_url"]
    assert "MIRROR dated 2026-10-24" in b["label"]


def test_a_stale_baseline_is_unverified_with_a_labelled_note(rd):
    base, notes = rd.real_data.baseline_for(["rtx 5070 ti"], as_of="2026-10-26T06:00:00+00:00", rows=ROWS)
    assert "rtx 5070 ti" not in base and notes[0]["rule_id"] == "advocate.baseline_unverified" and "more than 24 h old" in notes[0]["text"]
    assert "Price baseline unavailable" in notes[0]["text"]


def test_one_data_owner_is_unverified_not_a_price(rd):
    base, notes = rd.real_data.baseline_for(["rtx 5070 ti"], as_of=AT, rows=ROWS[:3])
    assert base == {} and "only one data owner" in notes[0]["text"]


def test_a_failing_lookup_is_unverified_never_a_silent_pass(rd, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("feed unreadable")
    monkeypatch.setattr(rd.real_data.price_baselines, "baseline", boom)
    base, notes = rd.real_data.baseline_for(["rtx 5070 ti"], as_of=AT)
    assert base == {} and "price lookup failed" in notes[0]["text"]


def test_a_sku_with_no_real_data_never_falls_back_to_a_sample_price(rd):  # guards: no mock_data fallback
    base, notes = rd.real_data.baseline_for(["rtx 4070 super 12gb"], as_of=AT, rows=ROWS)
    assert base == {} and notes[0]["text"].startswith("Price baseline unavailable for rtx 4070 super 12gb (unverified)")
    assert "no sample price was used" in notes[0]["text"]


def test_an_unknown_sku_with_no_data_is_unverified(rd):
    base, notes = rd.real_data.baseline_for(["rtx 9999 xt"], as_of=AT, rows=ROWS)
    assert base == {} and "we hold no price data" in notes[0]["text"]


NEED = {"id": "need-1", "items": [{"sku_spec": "rtx 5070 ti", "condition": "new", "quantity": 1}], "owned": {}}


def bid(price, brand="MSI"):
    return {"id": f"b{price}", "need_id": "need-1", "supplier_id": "seller_1", "origin": "MIRROR", "total_landed_price": price, "floor_check_passed": True,
            "lines": [{"sku_spec": "rtx 5070 ti", "unit_price": price, "quantity": 1, "offered_condition": "new", "page_condition": "new",
                       "listing_url": "https://www.microcenter.com/product/696024/x", "attrs": {"category": "gpu", "chipset": "RTX 5070 Ti", "brand": brand}}]}


def advise(rd, bids, **kw):
    base, records, recalls, notes = rd.real_data.advice_inputs(NEED, bids, as_of=kw.pop("as_of", AT), rows=kw.pop("rows", ROWS),
                                                              fetch=kw.pop("fetch", lambda url: b"[]"), cache_dir=kw.pop("cache_dir"))
    return rd.real_data.with_notes(rd.checks.advise(NEED, bids, base, records, recalls, owned={}), notes)


def test_the_price_check_fires_from_the_dated_baseline_with_a_real_source(rd, tmp_path):
    cards = advise(rd, [bid(1499.0)], cache_dir=tmp_path)  # 18% above the $1,269.99 baseline
    price = next(w for w in cards[0]["warnings"] if w["kind"] == "price")
    assert "$1269.99 (MIRROR, dated 2026-10-24)" in price["text"] and price["source_url"] == "https://microcenter.example/p/1269.99"
    assert "example.com" not in price["source_url"] and cards[0]["recommendation"] == "caution"


def test_a_fair_price_raises_no_price_warning(rd, tmp_path):
    cards = advise(rd, [bid(1275.0)], cache_dir=tmp_path)
    assert not [w for w in cards[0]["warnings"] if w["kind"] == "price"]


def test_a_stale_baseline_means_no_price_warning_and_a_note_that_never_changes_the_recommendation(rd, tmp_path):
    cards = advise(rd, [bid(1499.0)], as_of="2026-10-26T06:00:00+00:00", cache_dir=tmp_path)
    kinds = [w["kind"] for w in cards[0]["warnings"]]
    assert "price" not in kinds and "note" in kinds
    assert any(w["rule_id"] == "advocate.baseline_unverified" for w in cards[0]["warnings"])
    assert cards[0]["recommendation"] in ("buy", "caution")  # INFO notes never veto


def test_a_cpsc_recall_for_the_model_vetoes_with_the_recall_page(rd, tmp_path):  # the recall is a SIM fixture, not a real recall
    recall = [{"Title": "MSI Recalls GeForce RTX 5070 Ti Graphics Cards (SIM fixture)", "RecallDate": "2026-09-01T00:00:00",
               "URL": "https://www.cpsc.gov/Recalls/2026/msi-5070-ti", "Products": [{"Name": "MSI GeForce RTX 5070 Ti graphics card"}], "Manufacturers": []}]
    seen = []
    cards = advise(rd, [bid(1275.0)], fetch=lambda url: seen.append(url) or json.dumps(recall).encode(), cache_dir=tmp_path)
    assert seen and cards[0]["recommendation"] == "veto"
    rec = next(w for w in cards[0]["warnings"] if w["kind"] == "recall")
    assert rec["source_url"] == "https://www.cpsc.gov/Recalls/2026/msi-5070-ti"


def test_a_bid_that_names_no_brand_gets_a_recall_unverified_note_and_no_lookup(rd, tmp_path):
    seen = []
    b = bid(1275.0)
    del b["lines"][0]["attrs"]["brand"]
    cards = advise(rd, [b], fetch=lambda url: seen.append(url) or b"[]", cache_dir=tmp_path)
    assert seen == [] and any(w["rule_id"] == "advocate.recall_unverified" and "no brand" in w["text"] for w in cards[0]["warnings"])


def test_a_failing_recall_lookup_is_unverified_not_none(rd, tmp_path):
    def down(url):
        raise OSError("cpsc down")
    cards = advise(rd, [bid(1275.0)], fetch=down, cache_dir=tmp_path)
    assert any(w["rule_id"] == "advocate.recall_unverified" for w in cards[0]["warnings"]) and cards[0]["recommendation"] != "veto"


def test_the_buyers_shield_baseline_is_real_only(rd):
    ref = rd.real_data.shield_baseline(as_of=AT, rows=ROWS)
    assert ref["rtx 5070 ti"]["source"] == "MIRROR" and list(ref) == ["rtx 5070 ti"]  # real only, no sample prices


def test_the_agents_import_the_real_data_module_not_mock_data():
    adv = (ROOT / "agents" / "advocate" / "advocate_agent.py").read_text()
    buyer = (ROOT / "agents" / "buyer" / "buyer_agent.py").read_text()
    assert "real_data" in adv and "mock_data.BASELINE" not in adv and "mock_data.RECALLS" not in adv
    assert "advocate.real_data import shield_baseline" in buyer and "from advocate.mock_data import BASELINE" not in buyer



def test_a_recall_miss_means_no_veto_and_no_note(rd, tmp_path):
    cards = advise(rd, [bid(1275.0)], fetch=lambda url: b"[]", cache_dir=tmp_path)
    assert cards[0]["recommendation"] == "buy" and not [w for w in cards[0]["warnings"] if w["kind"] in ("recall", "note")]


def test_there_are_no_sample_seller_records(rd, tmp_path):
    base, records, recalls, notes = rd.real_data.advice_inputs(NEED, [bid(1275.0)], as_of=AT, rows=ROWS, fetch=lambda url: b"[]", cache_dir=tmp_path)
    assert records == {}


def test_the_price_check_needs_the_baseline_call(rd, monkeypatch, tmp_path):  # mutation guard: drop the call and this goes red
    calls = []
    real = rd.real_data.price_baselines.baseline
    monkeypatch.setattr(rd.real_data.price_baselines, "baseline", lambda *a, **k: calls.append(a) or real(*a, **k))
    cards = advise(rd, [bid(1499.0)], cache_dir=tmp_path)
    assert calls and any(w["kind"] == "price" for w in cards[0]["warnings"])
