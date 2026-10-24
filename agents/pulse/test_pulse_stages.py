"""#337: Market Pulse records every knockout stage offer, so tactics can be compared later."""
import pytest

from agents.pulse import market_pulse as P

RESULT = {
    "offers": [
        {"stage": 1, "seller_id": "best-buy", "condition": "new", "tactic": "hold", "price": 1299.99, "previous": None},
        {"stage": 1, "seller_id": "gadget-grove", "condition": "open-box", "tactic": "step", "price": 1286.02, "previous": None},
        {"stage": 2, "seller_id": "best-buy", "condition": "new", "tactic": "hold", "price": 1299.99, "previous": 1299.99},
        {"stage": 2, "seller_id": "gadget-grove", "condition": "open-box", "tactic": "step", "price": 1276.02, "previous": 1286.02},
    ],
    "stages": [
        {"stage": 1, "entries": [{"seller_id": "best-buy", "status": "advancing"}, {"seller_id": "gadget-grove", "status": "advancing"}]},
        {"stage": 2, "entries": [{"seller_id": "best-buy", "status": "champion"},
                                 {"seller_id": "gadget-grove", "status": "knocked_out", "rule_id": "knockout.last_place"}]},
    ],
    "champion": {"seller_id": "best-buy", "stage": 2, "landed": 1299.99},
}
TS = "2026-10-24T22:40:00Z"


def test_every_stage_offer_is_a_bid_tick_and_the_champion_a_win():
    rows = P.stage_ticks(RESULT, round_id="round-1", sku="rtx 5070 ti", ts=TS)
    bids = [r for r in rows if r["event"] == "bid"]
    assert len(bids) == 4 and {r["round_id"] for r in bids} == {"round-1/stage-1", "round-1/stage-2"}
    assert {(r["seller_id"], r["price_cents"]) for r in bids if r["round_id"].endswith("stage-2")} == {
        ("best-buy", 129999), ("gadget-grove", 127602)}
    assert [r for r in rows if r["event"] == "win"] == [
        {"ts": TS, "round_id": "round-1/stage-2", "sku": "rtx 5070 ti", "seller_id": "best-buy", "price_cents": 129999, "event": "win"}]


def test_the_tactic_table_shows_each_sellers_offers_and_outcome():
    t = P.tactic_table(RESULT)
    assert t["gadget-grove"] == {"tactic": "step", "offers": [1286.02, 1276.02], "outcome": "out in stage 2 (knockout.last_place)"}
    assert t["best-buy"]["outcome"] == "champion after stage 2"


def test_record_stages_says_not_configured_without_tiger(monkeypatch):
    monkeypatch.delenv("TIGER_DATA_SERVICE_URL", raising=False)
    out = P.record_stages(RESULT, round_id="round-1", sku="rtx 5070 ti", ts=TS)
    assert out == {"status": "not_configured", "rows": 5}


def test_record_stages_writes_through_the_given_writer_and_reports_errors():
    seen = []
    assert P.record_stages(RESULT, round_id="round-1", sku="rtx 5070 ti", ts=TS,
                           write=lambda rows: seen.extend(rows) or {"submitted": len(rows), "inserted": len(rows)}) == {
        "status": "stored", "submitted": 5, "inserted": 5}
    assert len(seen) == 5

    def boom(rows):
        raise RuntimeError("connection refused postgres://user:secret@host")
    out = P.record_stages(RESULT, round_id="round-1", sku="rtx 5070 ti", ts=TS, write=boom)
    assert out["status"] == "error" and "secret" not in str(out)


@pytest.mark.parametrize("price", [float("nan"), -1.0, 0.0, True, "1299.99"])
def test_a_bad_offer_price_is_skipped_not_stored(price):
    bad = {**RESULT, "offers": [{**RESULT["offers"][0], "price": price}], "champion": None}
    assert P.stage_ticks(bad, round_id="round-1", sku="rtx 5070 ti", ts=TS) == []
