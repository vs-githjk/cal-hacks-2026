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


def row(store, price, at="2026-10-24T05:08:00+00:00", provider="apify", kind="ask", url=None, sold=None, title=None):
    return {"title": title, "provider": provider, "store": store, "sku": "rtx 5070 ti", "price": price, "in_stock": True, "condition": "new", "kind": kind,
            "observed_at": at, "sold_date": sold, "url": url or f"https://{store}.example/p/{price}", "origin": "MIRROR"}


OUR_URL = "https://microcenter.example/p/1269.99"  # our own listing row, so its title names the brand (MSI)
ROWS = [row("bestbuy", 1249.99), row("microcenter", 1269.99, title="MSI GeForce RTX 5070 Ti 16G Ventus 3X"), row("bh", 1299.99),
        row("ebay_sold", 880.0, provider="ebay-sold", kind="sold", sold="2026-10-20T00:00:00+00:00"),
        row("ebay_sold", 900.0, provider="ebay-sold", kind="sold", sold="2026-10-21T00:00:00+00:00")]
AT = "2026-10-24T06:00:00+00:00"


def test_a_dated_baseline_from_two_owners_gives_a_real_source_page(rd):
    base, notes = rd.real_data.baseline_for(["RTX 5070 Ti"], as_of=AT, rows=ROWS)
    b = base["rtx 5070 ti"]
    assert notes == [] and b["unit_price"] == 1269.99 and b["source"] == "MIRROR" and b["n"] == 3
    assert b["source_url"] == "https://microcenter.example/p/1269.99" and "example.com" not in b["source_url"]
    assert b["label"] == "MIRROR baseline as of 2026-10-24, 3 retail asks, 2 sources"


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


def bid(price, brand="MSI", url=OUR_URL):
    return {"id": f"b{price}", "need_id": "need-1", "supplier_id": "seller_1", "origin": "MIRROR", "total_landed_price": price, "floor_check_passed": True,
            "lines": [{"sku_spec": "rtx 5070 ti", "unit_price": price, "quantity": 1, "offered_condition": "new", "page_condition": "new",
                       "listing_url": url, "attrs": {"category": "gpu", "chipset": "RTX 5070 Ti", "brand": brand}}]}


def advise(rd, bids, **kw):
    base, records, recalls, notes = rd.real_data.advice_inputs(NEED, bids, as_of=kw.pop("as_of", AT), rows=kw.pop("rows", ROWS),
                                                              fetch=kw.pop("fetch", lambda url: b"[]"), cache_dir=kw.pop("cache_dir"))
    return rd.real_data.with_notes(rd.checks.advise(NEED, bids, base, records, recalls, owned={}), notes)


def test_the_price_check_fires_from_the_dated_baseline_with_a_real_source(rd, tmp_path):
    cards = advise(rd, [bid(1499.0)], cache_dir=tmp_path)  # 18% above the $1,269.99 baseline
    price = next(w for w in cards[0]["warnings"] if w["kind"] == "price")
    assert "$1269.99 (MIRROR baseline as of 2026-10-24, 3 retail asks, 2 sources)" in price["text"] and price["source_url"] == "https://microcenter.example/p/1269.99"
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
    b = bid(1275.0, url="https://www.microcenter.com/product/696024/x")  # not in our rows
    del b["lines"][0]["attrs"]["brand"]
    cards = advise(rd, [b], fetch=lambda url: seen.append(url) or b"[]", cache_dir=tmp_path)
    assert seen == [] and any(w["rule_id"] == "advocate.recall_unverified" and "no brand" in w["text"] for w in cards[0]["warnings"])


def test_a_failing_recall_lookup_is_unverified_not_none(rd, tmp_path):
    def down(url):
        raise OSError("cpsc down")
    cards = advise(rd, [bid(1275.0)], fetch=down, cache_dir=tmp_path)
    assert any(w["rule_id"] == "advocate.recall_unverified" for w in cards[0]["warnings"]) and cards[0]["recommendation"] != "veto"


def test_the_buyers_shield_baseline_is_real_only(rd):
    ref = rd.real_data.shield_baseline(["rtx 5070 ti"], as_of=AT, rows=ROWS)
    assert ref["rtx 5070 ti"]["source"] == "MIRROR" and list(ref) == ["rtx 5070 ti"]  # real only, no sample prices


def test_the_agents_import_the_real_data_module_not_mock_data():
    adv = (ROOT / "agents" / "advocate" / "advocate_agent.py").read_text()
    buyer = (ROOT / "agents" / "buyer" / "buyer_agent.py").read_text()
    assert "real_data" in adv and "mock_data.BASELINE" not in adv and "mock_data.RECALLS" not in adv
    assert "advocate.real_data import cached_shield_baseline" in buyer and "from advocate.mock_data import BASELINE" not in buyer



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


# --- #291 probes ---------------------------------------------------------------------------------------------------
NEED_4070 = {"id": "need-1", "items": [{"sku_spec": "rtx 4070 super 12gb", "condition": "new", "quantity": 1}], "owned": {}}


def bid_4070(bid_id="b1", brand="MSI", price=599.0, url="https://www.microcenter.com/product/1/x"):
    attrs = {"category": "gpu", "chipset": "RTX 4070 Super"}
    if brand is not None:
        attrs["brand"] = brand
    return {"id": bid_id, "need_id": "need-1", "supplier_id": "seller_1", "origin": "MIRROR", "total_landed_price": price, "floor_check_passed": True,
            "lines": [{"sku_spec": "rtx 4070 super 12gb", "unit_price": price, "quantity": 1, "offered_condition": "new", "page_condition": "new",
                       "listing_url": url, "attrs": attrs}]}


def cpsc_item(title, name, url="https://www.cpsc.gov/Recalls/2026/sim"):  # SIM fixtures, not real recalls
    return {"Title": f"{title} (SIM fixture)", "RecallDate": "2026-09-01T00:00:00", "URL": url, "Products": [{"Name": name}], "Manufacturers": []}


def advise_4070(rd, bids, items, tmp_path, rows=ROWS, need=NEED_4070, **kw):
    fetch = kw.pop("fetch", lambda url: json.dumps(items).encode())
    base, records, recalls, notes = rd.real_data.advice_inputs(need, bids, as_of=AT, rows=rows, fetch=fetch, cache_dir=tmp_path)
    return rd.real_data.with_notes(rd.checks.advise(need, bids, base, records, recalls, owned={}), notes)


def test_a_one_token_recall_match_is_a_caution_never_a_veto(rd, tmp_path):  # probe 1: a 4070 Ti recall against a 4070 Super bid
    items = [cpsc_item("MSI Recalls GeForce RTX 4070 Ti Graphics Cards", "MSI GeForce RTX 4070 Ti graphics card")]
    card = advise_4070(rd, [bid_4070()], items, tmp_path)[0]
    assert card["recommendation"] == "caution"
    part = next(w for w in card["warnings"] if w["kind"] == "recall_partial")
    assert part["source_url"] == "https://www.cpsc.gov/Recalls/2026/sim" and "similar model" in part["text"]
    assert not [w for w in card["warnings"] if w["kind"] == "recall"]


def test_a_full_model_recall_vetoes_and_names_the_recall_title_and_date(rd, tmp_path):
    items = [cpsc_item("MSI Recalls GeForce RTX 4070 Super Graphics Cards", "MSI GeForce RTX 4070 Super graphics card")]
    card = advise_4070(rd, [bid_4070()], items, tmp_path)[0]
    rec = next(w for w in card["warnings"] if w["kind"] == "recall")
    assert card["recommendation"] == "veto" and "MSI Recalls GeForce RTX 4070 Super Graphics Cards" in rec["text"] and "2026-09-01" in rec["text"]


def test_a_recall_found_for_one_brand_never_vetoes_another_brands_bid(rd, tmp_path):
    items = [cpsc_item("MSI Recalls GeForce RTX 4070 Super Graphics Cards", "MSI GeForce RTX 4070 Super graphics card")]
    fetch = lambda url: json.dumps(items if "MSI" in url.upper() else []).encode()
    cards = {c["bid_id"]: c for c in advise_4070(rd, [bid_4070("b1", "MSI"), bid_4070("b2", "ASUS", 610.0)], items, tmp_path, fetch=fetch)}
    assert cards["b1"]["recommendation"] == "veto" and cards["b2"]["recommendation"] == "buy"


def test_a_seller_set_brand_never_dodges_the_recall_check(rd, tmp_path):  # probe 2: brand "Generic" on an MSI 4070 Super
    items = [cpsc_item("MSI Recalls GeForce RTX 4070 Super Graphics Cards", "MSI GeForce RTX 4070 Super graphics card")]
    url = "https://www.microcenter.com/product/42/x"
    rows = ROWS + [{**row("microcenter", 599.0, url=url), "sku": "rtx 4070 super 12gb", "title": "MSI GeForce RTX 4070 Super 12G Ventus 2X"}]
    seen = []
    fetch = lambda u: seen.append(u) or json.dumps(items if "MSI" in u.upper() else []).encode()
    card = advise_4070(rd, [bid_4070(brand="Generic", url=url)], items, tmp_path, rows=rows, fetch=fetch)[0]
    assert card["recommendation"] == "veto" and any("MSI" in u.upper() for u in seen)
    note = next(w for w in card["warnings"] if w["rule_id"] == "advocate.brand_mismatch")
    assert "generic" not in note["text"].lower() and "msi" in note["text"]  # the seller's own string is never echoed


def test_a_seller_brand_in_the_sku_spec_is_ours_and_a_different_attr_brand_only_adds_a_lookup(rd, tmp_path):
    b = bid_4070(brand="Generic")
    b["lines"][0]["sku_spec"] = "msi rtx 4070 super 12gb"
    brands, note = rd.real_data.brands_of(b["lines"][0])
    assert brands == {"msi", "generic"} and note and "the recall check used msi" in note


def test_an_unverified_check_never_says_no_problems_found(rd, tmp_path):  # probe 4: the spoken reason
    def down(url):
        raise OSError("cpsc down")
    card = advise(rd, [bid(1275.0)], fetch=down, cache_dir=tmp_path)[0]
    assert card["recommendation"] == "buy" and card["rule_id"] == "advocate.unverified"
    assert card["reason"] == "Some checks could not run" == card["call_reason"]["summary"]
    assert "No problems found" not in json.dumps(card)


def test_a_card_with_every_check_run_still_says_no_problems_found(rd, tmp_path):
    card = advise(rd, [bid(1275.0)], fetch=lambda url: b"[]", cache_dir=tmp_path)[0]
    assert card["rule_id"] == "advocate.ok" and card["reason"] == "No problems found in the checks"


def test_an_unexpected_fetch_error_is_unverified_and_cards_still_come_back(rd, tmp_path):  # probe 6
    def boom(url):
        raise RuntimeError("not an OSError")
    cards = advise(rd, [bid(1275.0)], fetch=boom, cache_dir=tmp_path)
    assert len(cards) == 1 and any(w["rule_id"] == "advocate.recall_unverified" for w in cards[0]["warnings"])


def test_slow_lookups_run_in_parallel_and_stop_at_the_budget(rd, tmp_path):  # probe 6: never past the buyer's 15 s
    import threading
    import time
    release = threading.Event()

    def slow(url):
        release.wait(5)
        return b"[]"
    bids = [bid_4070(f"b{i}", brand) for i, brand in enumerate(["MSI", "ASUS", "Gigabyte", "Zotac"])]
    t0 = time.monotonic()
    found, notes = rd.real_data.recalls_for_bids(bids, fetch=slow, cache_dir=tmp_path, rows=ROWS, budget_s=0.3)
    took = time.monotonic() - t0
    release.set()
    assert took < 2 and found == [] and len([n for n in notes if "no CPSC answer within 0.3 s" in n["text"]]) == 4


def test_the_new_spoken_reasons_are_in_lane_ds_table(rd):
    from pay import reasons
    from pay.callscript import clean_advocate_reason
    for rid in ("advocate.unverified", "advocate.recall_partial"):
        assert reasons.SUMMARIES[rid] == rd.checks.CALL_SUMMARIES[rid]
        kept, dropped = clean_advocate_reason({"rule_id": rid, "summary": reasons.SUMMARIES[rid]})
        assert dropped == [] and kept["summary"] == reasons.SUMMARIES[rid]


def test_a_pinned_clock_is_labelled(rd, monkeypatch):
    monkeypatch.setenv("BASELINE_AS_OF", AT)
    base, _ = rd.real_data.baseline_for(["rtx 5070 ti"], rows=ROWS)
    assert base["rtx 5070 ti"]["label"].endswith("clock pinned to 2026-10-24T06:00+00:00 by BASELINE_AS_OF")


def test_a_thin_baseline_is_unverified_with_the_reason(rd):
    base, notes = rd.real_data.baseline_for(["rtx 5070 ti"], as_of=AT, rows=ROWS[:4])  # one sold row
    assert base == {} and "thin baseline" in notes[0]["text"] and "eBay sold" in notes[0]["text"]


# --- #330 probes ---------------------------------------------------------------------------------------------------
MSI_5070TI_RECALL = [cpsc_item("MSI Recalls GeForce RTX 5070 Ti Graphics Cards", "MSI GeForce RTX 5070 Ti graphics card")]


def test_a_brand_only_the_seller_names_is_unverified_never_no_problems_found(rd, tmp_path):  # #330 item 1: the Generic probe
    seen = []
    fetch = lambda u: seen.append(u) or json.dumps(MSI_5070TI_RECALL if "MSI" in u.upper() else []).encode()
    card = advise(rd, [bid(1275.0, brand="Generic", url="https://shop.example/not-in-our-rows")], fetch=fetch, cache_dir=tmp_path)[0]
    assert seen and not any("MSI" in u.upper() for u in seen)  # the only lookup was the seller's brand
    assert card["rule_id"] == "advocate.unverified" and card["reason"] == "Some checks could not run"
    note = next(w for w in card["warnings"] if w["rule_id"] == "advocate.recall_unverified")
    assert "brand not confirmed from our data" in note["text"] and "generic" not in note["text"].lower()  # #89: never echoed
    assert "No problems found" not in json.dumps(card)


def test_a_known_brand_only_the_seller_names_is_still_unconfirmed(rd, tmp_path):  # #330 item 1: seller "MSI", URL not ours
    card = advise(rd, [bid(1275.0, brand="MSI", url="https://shop.example/not-in-our-rows")], fetch=lambda u: b"[]", cache_dir=tmp_path)[0]
    assert card["rule_id"] == "advocate.unverified"
    assert any("brand not confirmed from our data" in w["text"] for w in card["warnings"])


def test_a_brand_our_rows_confirm_is_no_unverified_note(rd, tmp_path):  # #330 item 1: the confirmed path stays advocate.ok
    card = advise(rd, [bid(1275.0, brand="Generic")], fetch=lambda u: b"[]", cache_dir=tmp_path)[0]
    assert not any("brand not confirmed" in w["text"] for w in card["warnings"])
    assert card["rule_id"] == "advocate.ok"


def test_the_advocate_runs_the_lookups_off_the_event_loop():  # #330 item 2
    adv = (ROOT / "agents" / "advocate" / "advocate_agent.py").read_text()
    assert "await asyncio.to_thread(real_data.advice_inputs, need, bids)" in adv
    assert "= real_data.advice_inputs(" not in adv


def test_the_buyers_references_are_re_read_past_the_ttl_and_follow_the_rounds_skus(rd, monkeypatch):  # #330 item 3
    rd.real_data._SHIELD_CACHE.clear()
    calls, t = [], [0.0]
    monkeypatch.setattr(rd.real_data, "shield_baseline", lambda skus, **kw: calls.append(tuple(skus)) or {s: {"unit_price": len(calls)} for s in skus})
    clock = lambda: t[0]
    first = rd.real_data.cached_shield_baseline(["RTX 4070 Super 12GB"], ttl_s=60, clock=clock)
    assert calls == [("rtx 4070 super 12gb",)] and first["rtx 4070 super 12gb"]["unit_price"] == 1  # not hard-coded to the 5070 Ti
    t[0] = 30
    assert rd.real_data.cached_shield_baseline(["rtx 4070 super 12gb"], ttl_s=60, clock=clock) is first and len(calls) == 1
    t[0] = 61
    assert rd.real_data.cached_shield_baseline(["rtx 4070 super 12gb"], ttl_s=60, clock=clock)["rtx 4070 super 12gb"]["unit_price"] == 2
    assert rd.real_data.cached_shield_baseline([], clock=clock) == {}
    buyer = (ROOT / "agents" / "buyer" / "buyer_agent.py").read_text()
    assert "BASELINE = shield_baseline()" not in buyer and "cached_shield_baseline(" in buyer


def test_a_stale_dated_baseline_drops_out_of_the_buyers_references(rd):  # #330 item 3: past 24 h there is no price reference
    rd.real_data._SHIELD_CACHE.clear()
    clock = iter([0.0, 1000.0]).__next__
    assert rd.real_data.cached_shield_baseline(["rtx 5070 ti"], ttl_s=300, clock=clock, as_of=AT, rows=ROWS)
    assert rd.real_data.cached_shield_baseline(["rtx 5070 ti"], ttl_s=300, clock=clock, as_of="2026-10-26T06:00:00+00:00", rows=ROWS) == {}


def test_a_non_dict_line_is_unverified_not_a_type_error(rd, tmp_path):  # #330 item 4
    junk = {**bid(1275.0), "lines": ["junk"]}
    found, notes = rd.real_data.recalls_for_bids([junk], fetch=lambda u: b"[]", cache_dir=tmp_path, rows=ROWS)
    assert found == [] and any(n["rule_id"] == "advocate.recall_unverified" and "could not be read" in n["text"] for n in notes)
    base, records, recalls, notes = rd.real_data.advice_inputs(NEED, [junk], as_of=AT, rows=ROWS, fetch=lambda u: b"[]", cache_dir=tmp_path)
    assert "rtx 5070 ti" in base and recalls == []
