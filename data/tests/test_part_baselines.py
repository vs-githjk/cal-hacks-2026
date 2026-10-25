"""#342 step 6: dated price baselines for the Build Story parts, keyed by the exact maker model. Fakes only: no network, no spend."""
import json
import sys
import types
from pathlib import Path

import pytest

import data.baselines as baselines
from data.baselines import refresh
from data.fit_checker import part_specs
from data.mirror import normalize, parts, price_spread, run_actors

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents"))

ROWS = {"cpu": [{"brand": "AMD", "name": "AMD Ryzen 7 9700X", "model_number": "100-100001404WOF", "match": r"ryzen\W*\s*7\s+9700x(?![0-9a-z])",
                 "socket": "AM5", "tdp_w": 65, "source": "https://www.amd.com/x", "checked": "2026-10-24"}],
        "motherboard": [], "memory": [], "storage": [], "cooler": []}
T1, T2 = "2026-10-24T18:00:00+00:00", "2026-10-24T18:10:00+00:00"
AT = "2026-10-24T20:00:00+00:00"


@pytest.fixture
def specs(tmp_path, monkeypatch):
    f = tmp_path / "part_specs.json"
    f.write_text(json.dumps(ROWS))
    monkeypatch.setattr(part_specs, "DATA", f)


def card(store, title, price, url, at=T1, **extra):
    c = normalize.to_spec_card(store, {"title": title, "price": price, "url": url, **extra}, f"{store}-cpu-x-20261024T1800Z", at, part="cpu")
    return c


def write(root, name, cards):
    root.mkdir(exist_ok=True)
    (root / f"{name}.json").write_text(json.dumps(cards))


@pytest.fixture
def snaps(tmp_path, specs, monkeypatch):
    root = tmp_path / "parts_snapshots"
    write(root, "bestbuy-cpu-ryzen-7-9700x-20261024T1800Z", [card("bestbuy", "AMD Ryzen 7 9700X", 299.99, "https://bb/1"),
                                                              card("bestbuy", "AMD Ryzen 5 7600X", 199.0, "https://bb/2")])
    write(root, "microcenter-cpu-ryzen-7-9700x-20261024T1800Z", [card("microcenter", "Ryzen 7 9700X Granite Ridge AM5", 289.99, "https://mc/1", at=T2)])
    write(root, "ebay_sold-cpu-ryzen-7-9700x-20261024T1800Z", [
        card("ebay_sold", "AMD Ryzen 7 9700X 8-Core", 240.0, "https://eb/1", soldDate="2026-10-20"),
        card("ebay_sold", "AMD Ryzen 7 9700X CPU", 250.0, "https://eb/2", soldDate="2026-10-21")])
    write(root, "centralcomputers-cpu-category-page-20261024T1800Z", [
        {**card("centralcomputers", "AMD Ryzen 7 9700X", 1.0, "https://cc/1"), "listing": {"price": 1.0, "url": "https://cc/1", "availability": "in_stock_sf_store"}}])
    write(root, "amazon-cpu-ryzen-7-9700x-20261024T1800Z", [card("amazon", "AMD Ryzen 7 9700X", 2.0, "https://amz/1", seller={"name": "Amazon.com"})])
    monkeypatch.setattr(baselines, "PARTS", root)
    return root


def test_part_rows_are_keyed_by_the_exact_maker_model_and_unknown_models_have_none(snaps):
    rows = baselines.part_observations()
    keys = {r["sku"] for r in rows}
    assert keys == {baselines.part_key("100-100001404WOF")}
    assert all(r["origin"] == "MIRROR" and r["observed_at"] and r["url"] for r in rows)


def test_two_owners_with_two_prices_each_inside_24h_give_an_ok_baseline(snaps):
    b = baselines.part_baseline("100-100001404WOF", AT)
    assert b["status"] == "ok" and b["median"] == 294.99 and b["n"] == 2
    assert b["owners"] == ["eBay sold", "retailer listings (Apify)"] and b["sold"]["n"] == 2


def test_central_computers_and_amazon_rows_never_move_the_median(snaps):
    b = baselines.part_baseline("100-100001404wof", AT)
    assert {r["store"] for r in b["rows"]} == {"bestbuy", "microcenter"}   # the $1 and $2 rows are not in it


def test_a_model_with_one_retail_ask_is_thin_and_has_no_median(snaps):
    (snaps / "microcenter-cpu-ryzen-7-9700x-20261024T1800Z.json").unlink()
    b = baselines.part_baseline("100-100001404WOF", AT)
    assert b["status"] == "thin" and b["median"] is None


def test_prices_older_than_24_hours_are_stale(snaps):
    assert baselines.part_baseline("100-100001404WOF", "2026-10-26T00:00:00+00:00")["status"] == "stale"


def test_a_model_we_never_captured_is_empty(snaps):
    assert baselines.part_baseline("NOPE-123")["status"] == "empty"


def test_the_gpu_readers_never_read_parts_snapshots(snaps, monkeypatch):
    """GPU median, claim scan and pulse read data/mirror/snapshots*/ only; parts live in parts_snapshots on purpose."""
    real = Path(parts.__file__).resolve().parent
    assert parts.SNAPSHOTS.name == "parts_snapshots" and not parts.SNAPSHOTS.name.startswith("snapshots")
    assert price_spread.SNAPS.resolve() == (real / "snapshots").resolve() and baselines.SECOND.name == "snapshots_b"
    from data.claim_check import real_scan
    assert not any("parts_snapshots" in str(p) for p in real_scan.snapshot_files())
    gpu_ids = {r.get("snapshot_id") for r in baselines.observations()}
    part_ids = {p.stem for p in (real / "parts_snapshots").glob("*.json")}
    assert not gpu_ids & part_ids


# ---- the advocate -----------------------------------------------------------------------------------------------------
@pytest.fixture
def rd(monkeypatch):
    monkeypatch.setitem(sys.modules, "common", types.ModuleType("common"))
    sys.modules.pop("advocate.checks", None)
    from advocate import checks, real_data
    return types.SimpleNamespace(real_data=real_data, checks=checks)


def bid(sku, url, cat="cpu", price=299.0):
    return {"lines": [{"sku_spec": sku, "unit_price": price, "listing_url": url, "attrs": {"category": cat}}]}


def test_a_part_line_on_our_own_listing_gets_the_part_baseline_with_the_gpu_label_format(rd, snaps):
    base, notes = rd.real_data.part_baseline_for([bid("ryzen 7 9700x box", "https://bb/1")], need={"items": []}, as_of=AT)
    entry = base["ryzen 7 9700x box"]
    assert entry["unit_price"] == 294.99 and entry["source"] == "MIRROR" and entry["model"] == "100-100001404WOF"
    assert entry["label"] == "MIRROR baseline as of 2026-10-24, 2 retail asks, 2 sources" and not notes


def test_the_buyers_own_sku_can_name_the_model(rd, snaps):
    base, notes = rd.real_data.part_baseline_for([bid("AMD Ryzen 7 9700X", "https://seller.example/x")],
                                                 need={"items": [{"sku_spec": "AMD Ryzen 7 9700X"}]}, as_of=AT)
    assert base["amd ryzen 7 9700x"]["model"] == "100-100001404WOF" and not notes


def test_seller_text_alone_never_picks_the_model(rd, snaps):
    """The seller wrote a model name on a page we do not hold, and the buyer asked for something else: no key, no baseline."""
    base, notes = rd.real_data.part_baseline_for([bid("AMD Ryzen 7 9700X", "https://seller.example/x")],
                                                 need={"items": [{"sku_spec": "a cpu for gaming"}]}, as_of=AT)
    assert base == {} and [n["rule_id"] for n in notes] == ["advocate.baseline_unverified"]
    assert "Price baseline unavailable" in notes[0]["text"] and "AMD Ryzen" not in notes[0]["text"].split("(unverified)")[1]


def test_a_matched_model_without_two_owners_is_unverified(rd, snaps):
    (snaps / "ebay_sold-cpu-ryzen-7-9700x-20261024T1800Z.json").unlink()
    base, notes = rd.real_data.part_baseline_for([bid("x", "https://bb/1")], need={"items": []}, as_of=AT)
    assert base == {} and notes[0]["rule_id"] == "advocate.baseline_unverified" and "one data owner" in notes[0]["text"]


def test_gpu_lines_are_left_to_the_gpu_path(rd, snaps):
    assert rd.real_data.part_baseline_for([bid("rtx 5070 ti", "https://bb/1", cat="gpu")], need={"items": []}, as_of=AT) == ({}, [])


def test_advice_inputs_includes_part_baselines(rd, snaps):
    base, _, _, notes = rd.real_data.advice_inputs({"items": []}, [bid("ryzen 7 9700x box", "https://bb/1")], as_of=AT, rows=[],
                                                   fetch=lambda url: b"[]", cache_dir=snaps.parent / "cache")
    assert base["ryzen 7 9700x box"]["unit_price"] == 294.99


# ---- refresh --parts ---------------------------------------------------------------------------------------------------
class Out(list):
    def __call__(self, *a):
        self.append(" ".join(str(x) for x in a))


def test_refresh_parts_dry_run_plans_retail_and_ebay_sold_only_under_two_dollars(snaps):
    out = Out()
    assert refresh.main(["--parts", "--dry-run"], env={}, out=out) == 0
    text = "\n".join(out)
    assert "centralcomputers" not in text and "(b)" not in text and "amazon" not in text
    assert any(l.startswith("estimated Apify cost: $") for l in out) and "nothing was run" in text
    plan = refresh.parts_refresh_plan()
    assert {r["store"] for r in plan} == {"bestbuy", "microcenter", "bh", "ebay_sold"} and not any(r["second"] for r in plan)
    assert sum(r["worst_usd"] for r in plan) <= 2.0


def test_refresh_parts_needs_spend_typed_and_honours_the_cap(snaps, monkeypatch):
    calls = []
    monkeypatch.setattr(run_actors, "run_parts", lambda *a, **k: calls.append(a) or [])
    out = Out()
    assert refresh.main(["--parts"], env={"APIFY_TOKEN": "t"}, out=out, confirm=lambda p: "yes", isatty=lambda: True) == 2
    assert refresh.main(["--parts", "--cap", "0.01"], env={"APIFY_TOKEN": "t"}, out=out, confirm=lambda p: "SPEND", isatty=lambda: True) == 2
    assert calls == []
    refresh.main(["--parts"], env={"APIFY_TOKEN": "t"}, out=out, confirm=lambda p: "SPEND", isatty=lambda: True)
    assert len(calls) == 1 and calls[0][1] == 2.0   # run_parts(plan, cap=2.0)


def test_refresh_parts_prints_a_status_per_model(snaps):
    out = Out()
    refresh.main(["--parts", "--dry-run"], env={}, out=out, now=baselines._ts(AT))
    assert any("100-100001404WOF" in l and "status ok" in l for l in out)


def test_yes_spend_never_skips_the_parts_prompt(snaps, monkeypatch):
    calls = []
    monkeypatch.setattr(run_actors, "run_parts", lambda *a, **k: calls.append(a) or [])
    assert refresh.main(["--parts", "--yes-spend"], env={"APIFY_TOKEN": "t"}, out=Out(), confirm=lambda p: "", isatty=lambda: True) == 2
    assert refresh.main(["--parts", "--yes-spend"], env={"APIFY_TOKEN": "t"}, out=Out(), confirm=lambda p: "SPEND", isatty=lambda: False) == 2
    assert calls == []
