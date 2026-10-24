"""#308: Central Computers (SF), a real store, as a MIRROR seller from 12 Apify rows captured Oct 24 21:12 UTC."""
import json

from data import baselines
from data.fit_checker import check_fit
from data.fit_checker.gpu_lengths import listing_length
from data.mirror import central_computers as cc
from data.mirror.price_spread import load

LABEL = "MIRROR: real Central Computers listing captured Oct 24 21:12 UTC via Apify. Central Computers is not a partner."
SF_IN_STOCK = {"G507T-16V3ZCB", "PROART-RTX5070TI-O16G", "ROG-STRIX-RTX5070TI-O16G-GAMIN", "PRIME-RTX5070TI-16G",
               "PRIME-RTX5070TI-O16G", "TUF-RTX5070TI-O16G-WHITE-GAMIN", "TUF-RTX5070TI-O16G-GAMING"}


def test_snapshot_has_the_12_rows_in_the_existing_snapshot_format():
    rows = cc.rows()
    assert len(rows) == 12 and len({r["id"] for r in rows}) == 12
    existing = json.loads((cc.SNAPSHOT.parent / "bh-20261024T0508Z.json").read_text())[0]
    for r in rows:
        assert set(existing) <= set(r)  # every field an existing snapshot row has
        assert r["origin"] == "MIRROR" and r["snapshot_id"] == cc.SNAPSHOT_ID == cc.SNAPSHOT.stem
        assert r["snapshot_date"] == "2026-10-24T21:12:13+00:00" and r["condition"] == "unknown"
        assert r["source"] == r["listing"]["url"].strip() and r["source"].startswith("https://www.centralcomputer.com/")
        assert r["listing"]["apify_actor"] == "apify/website-content-crawler" and r["listing"]["seller"] == "Central Computers"
    assert "centralcomputers" in load() and len(load()["centralcomputers"]) == 12


def test_only_the_seven_listings_in_stock_at_the_sf_store_can_bid():
    offers = cc.in_stock_sf()
    assert {o["model_number"] for o in offers} == SF_IN_STOCK
    assert all(o["sf_store_qty"] > 0 for o in offers)
    assert [o["price"] for o in offers] == sorted(o["price"] for o in offers)
    # the Gigabyte card is stocked only at other stores, the rest are special order: never bid
    others = {r["model_number"] for r in cc.rows()} - SF_IN_STOCK
    assert "GV-N507TWF3OC-16GD" in others and len(others) == 5


def test_floor_is_a_few_percent_under_the_listed_price():
    for o in cc.in_stock_sf():
        assert o["floor"] == round(o["price"] * 0.93, 2) and o["floor"] < o["price"]


def test_fit_against_the_305_mm_case_from_maker_lengths():
    by_model = {o["model_number"]: o for o in cc.in_stock_sf()}
    assert {m for m, o in by_model.items() if o["length_mm"] is not None and o["length_mm"] <= 305} == {
        "G507T-16V3ZCB", "PROART-RTX5070TI-O16G", "PRIME-RTX5070TI-16G", "PRIME-RTX5070TI-O16G"}
    assert by_model["TUF-RTX5070TI-O16G-GAMING"]["length_mm"] == 329 == by_model["TUF-RTX5070TI-O16G-WHITE-GAMIN"]["length_mm"]
    assert by_model["ROG-STRIX-RTX5070TI-O16G-GAMIN"]["length_mm"] is None  # not in the maker table: unknown, no guess
    assert by_model["G507T-16V3ZCB"]["length_source"].startswith("https://www.msi.com/") and \
        "PZ-OC" in by_model["G507T-16V3ZCB"]["length_source"]
    assert listing_length("", "ASUS PRIME-RTX5070TI-16G PRIME GeForce")["source"].endswith("/prime-rtx5070ti-16g/techspec/")


def _gpu_length_verdict(length_mm, clearance=305):
    cards = [{"id": "gpu", "category": "gpu", "name": "gpu", "attrs": {"chipset": "RTX 5070 Ti", "length_mm": length_mm}},
             {"id": "case", "category": "case", "name": "case", "attrs": {"max_gpu_length_mm": clearance}}]
    return next(c for c in check_fit(cards)["checks"] if c["rule_id"] == "fit.gpu_length")["verdict"]


def test_an_unknown_or_too_long_card_is_never_bid_for_a_305_mm_round():
    pick, withheld = cc.choose(305)
    assert pick["model_number"] == "G507T-16V3ZCB" and pick["price"] == 1249.99 and pick["length_mm"] == 303
    assert _gpu_length_verdict(pick["length_mm"]) == "pass"
    reasons = {w["model_number"]: w["reason"] for w in withheld}
    assert set(reasons) == {"ROG-STRIX-RTX5070TI-O16G-GAMIN", "TUF-RTX5070TI-O16G-WHITE-GAMIN", "TUF-RTX5070TI-O16G-GAMING"}
    assert "unknown" in reasons["ROG-STRIX-RTX5070TI-O16G-GAMIN"] and "329 mm is over the 305 mm" in reasons["TUF-RTX5070TI-O16G-GAMING"]
    for w in withheld:
        assert w["length_mm"] is None or _gpu_length_verdict(w["length_mm"]) == "fail"


def test_without_a_shared_clearance_unknown_length_is_still_withheld(monkeypatch):
    real = cc.in_stock_sf()
    only_unknown_and_long = [o for o in real if o["length_mm"] is None or o["length_mm"] > 305]
    monkeypatch.setattr(cc, "in_stock_sf", lambda: only_unknown_and_long)
    pick, withheld = cc.choose(305)
    assert pick is None and len(withheld) == 3 and cc.seller(305) is None
    pick, withheld = cc.choose(None)  # no clearance shared: a confirmed length may bid, an unknown one never
    assert pick["length_mm"] == 329 and [w["model_number"] for w in withheld] == ["ROG-STRIX-RTX5070TI-O16G-GAMIN"]


def test_seller_is_labelled_mirror_and_never_a_partner():
    s = cc.seller()
    assert s["origin"] == "MIRROR" and s["name"] == "Central Computers (SF)" and s["mirror_label"] == LABEL == cc.LABEL
    line = s["listings"]["rtx 5070 ti"]
    assert line["condition"] == line["page_condition"] == "unknown" and line["price"] == 1249.99 and line["floor"] == 1162.49
    assert line["qty_available"] == 3 and line["listing_url"].startswith("https://www.centralcomputer.com/msi-g507t-16v3zcb")
    assert s["claims"] == []  # the store made no claim to us; we never write one for it
    text = json.dumps(s).lower()
    for word in ("partner of", "joined", "our partner", "official seller"):
        assert word not in text
    raw = json.dumps(s, ensure_ascii=False)
    assert "not a partner" in s["trace_prefix"].lower() and chr(0x2014) not in raw and chr(0x2013) not in raw  # no em or en dashes


def test_rows_stay_out_of_the_retail_baseline_median():
    assert "centralcomputers" in baselines.LOCAL_STORE and not baselines.LOCAL_STORE & baselines.RETAIL
    rows = baselines.observations()
    mine = [r for r in rows if r["store"] == "centralcomputers"]
    assert len(mine) == 12 and all(r["kind"] == "ask" and r["origin"] == "MIRROR" for r in mine)
    at = "2026-10-24T21:30:00+00:00"
    with_cc = baselines.baseline("rtx 5070 ti", at, rows)
    without = baselines.baseline("rtx 5070 ti", at, [r for r in rows if r["store"] != "centralcomputers"])
    assert with_cc == without and with_cc["median"] == 1259.99
    assert not [r for r in with_cc["rows"] if r["store"] == "centralcomputers"]


def test_stage_offers_for_lane_d_hold_only_the_sf_in_stock_rows():
    offers = cc.stage_offers()
    assert {o["card"]["model_number"] for o in offers} == SF_IN_STOCK
    assert all(o["prefix"] == "centralcomputers" and o["listing"]["availability"] == "in_stock_sf_store" for o in offers)


def test_the_stage_round_does_not_pick_the_store_up_by_itself():
    from demo.sellers import load_offers
    offers, _ = load_offers()
    assert offers and not [o for o in offers if o["prefix"] == "centralcomputers"]
