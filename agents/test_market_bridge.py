import json
from pathlib import Path
from uuid import uuid4

import pytest

from market_bridge import MarketBridge, MarketBridgeError


META = [{
    "lineIndex": 0, "shipping": 12.0, "listingId": "https://example.test/listing",
    "listingHash": "a" * 64, "source": "fixture", "snapshotId": "snap-1",
    "provenance": {"source": "fixture", "origin": "SIM"},
    "attrs": {"z": "last", "power_connector": ["8pin", 1], "category": "gpu"},
}]


def bid_row(*, price=40.0, metadata="[]"):
    return {
        "id": "bid-1", "roundId": "round-1", "sellerId": "seller-a", "persona": "Seller A",
        "lines": [{"skuSpec": "gpu", "offeredSpec": "", "offeredCondition": "", "unitPrice": price, "quantity": 5}],
        "statedTotal": 0.0, "perks": [], "claims": [], "origin": "SIM", "source": "simulated",
        "lineMetaJson": metadata,
    }


class FakeMarket:
    def __init__(self, *, sql_rows=None, fail_call=None):
        self.calls = []
        self.queries = []
        self.sql_rows = list(sql_rows or [])
        self.fail_call = fail_call

    def call(self, reducer, **args):
        self.calls.append((reducer, args))
        if reducer == self.fail_call:
            raise RuntimeError("secret endpoint response must not escape")

    def sql(self, query):
        self.queries.append(query)
        return self.sql_rows.pop(0) if self.sql_rows else []


def test_missing_role_token_fails_before_market_constructor():
    constructed = []
    missing = Path(__file__).with_name(f".missing-market-token-{uuid4().hex}.json")
    with pytest.raises(MarketBridgeError, match="market_identity_unavailable"):
        MarketBridge("seller", token_file=missing, market_factory=lambda **kw: constructed.append(kw))
    assert constructed == []


def test_publish_bid_sets_original_index_metadata_then_reads_back_canonical_value():
    canonical = [{**META[0], "provenance": {"origin": "SIM", "source": "fixture"},
                  "attrs": {"category": "gpu", "power_connector": ["8pin", 1], "z": "last"}}]
    stored = json.dumps(canonical, separators=(",", ":"))
    market = FakeMarket(sql_rows=[[], [bid_row(metadata=stored)]])
    bridge = MarketBridge("seller", client=market)

    result = bridge.publish_bid(
        bid_id="bid-1", round_id="round-1", seller_id="seller-a", persona="Seller A",
        lines=[{"sku_spec": "gpu", "unit_price": 40, "quantity": 5}], line_metadata=META,
    )

    assert [call[0] for call in market.calls] == ["place_bid", "set_bid_line_meta"]
    assert market.calls[1][1]["line_meta_json"] == stored
    assert all("WHERE id = 'bid-1'" in query for query in market.queries)
    assert result["line_metadata"] == canonical


def test_exact_existing_bid_retry_resumes_only_metadata_write():
    stored = json.dumps(META, separators=(",", ":"))
    market = FakeMarket(sql_rows=[[bid_row()], [bid_row(metadata=stored)]])
    bridge = MarketBridge("seller", client=market)
    result = bridge.publish_bid(
        bid_id="bid-1", round_id="round-1", seller_id="seller-a", persona="Seller A",
        lines=[{"sku_spec": "gpu", "unit_price": 40, "quantity": 5}], line_metadata=META,
    )
    assert [call[0] for call in market.calls] == ["set_bid_line_meta"]
    assert result["seller_id"] == "seller-a"


def test_changed_price_on_existing_bid_is_rejected_before_any_reducer_call():
    market = FakeMarket(sql_rows=[[bid_row(price=39.0)]])
    bridge = MarketBridge("seller", client=market)
    with pytest.raises(MarketBridgeError, match="existing_bid_mismatch"):
        bridge.publish_bid(
            bid_id="bid-1", round_id="round-1", seller_id="seller-a", persona="Seller A",
            lines=[{"sku_spec": "gpu", "unit_price": 40, "quantity": 5}], line_metadata=META,
        )
    assert market.calls == []


def test_publish_bid_does_not_forward_reducer_error_text():
    market = FakeMarket(fail_call="place_bid")
    bridge = MarketBridge("seller", client=market)
    with pytest.raises(MarketBridgeError, match="market_reducer_failed") as error:
        bridge.publish_bid(bid_id="bid-1", round_id="round-1", seller_id="seller-a", persona="Seller A",
                           lines=[{"sku_spec": "gpu", "unit_price": 40, "quantity": 5}], line_metadata=META)
    assert "secret endpoint" not in str(error.value)


def test_candidate_projection_is_referee_view_and_excludes_buyer_cap_and_seller_floor():
    market = FakeMarket(sql_rows=[[{
        "roundId": "round-1", "needId": "need-1", "bidId": "bid-1", "sellerId": "seller-a",
        "origin": "SIM", "rank": 1, "landed": 92.0,
        "linesJson": json.dumps([{"line_index": 0, "sku_spec": "gpu", "unit_price": 40,
                                  "quantity": 5, "shipping": 12}]),
        "lineMetaJson": json.dumps(META), "bindingHash": "b" * 64,
    }]])
    candidates = MarketBridge("referee", client=market).review_candidates("round-1")
    assert candidates[0]["lines"][0]["quantity"] == 5
    assert candidates[0]["binding_hash"] == "b" * 64
    assert "cap" not in str(candidates[0]).lower()
    assert "floor" not in str(candidates[0]).lower()
    assert "SELECT *" not in market.queries[0]


def test_authoritative_winner_bills_need_quantity_and_shipping_once_not_available_stock():
    market = FakeMarket(sql_rows=[[{
        "bidId": "bid-1", "sellerId": "seller-a", "rank": 1, "landed": 92.0,
        "reasons": [], "lines": [{"skuSpec": "gpu", "unitPrice": 40.0, "quantity": 5}],
        "lineMetaJson": json.dumps(META), "origin": "SIM", "source": "fixture",
    }]])
    winner = MarketBridge("buyer", client=market).authoritative_winner(
        "round-1", [{"sku_spec": "gpu", "quantity": 2}],
    )
    assert winner is not None
    assert winner["landed"] == 92
    assert winner["lines"] == [{
        "sku_spec": "gpu", "unit_price": 40.0, "quantity": 2.0, "qty_available": 5.0,
        "original_line_index": 0, "listing_id": "https://example.test/listing",
        "listing_hash": "a" * 64, "shipping": 12.0,
    }]
    assert "spend_limit" not in market.queries[0] and "floor" not in market.queries[0]


def test_decimal_cent_order_total_tolerates_only_server_float_representation_noise():
    meta = [{**META[0], "shipping": 2.0}]
    market = FakeMarket(sql_rows=[[{
        "bidId": "bid-1", "sellerId": "seller-a", "rank": 1, "landed": 61.849999999999994,
        "reasons": [], "lines": [{"skuSpec": "gpu", "unitPrice": 19.95, "quantity": 5}],
        "lineMetaJson": json.dumps(meta), "origin": "SIM", "source": "fixture",
    }]])
    winner = MarketBridge("buyer", client=market).authoritative_winner(
        "round-1", [{"sku_spec": "gpu", "quantity": 3}],
    )
    assert winner is not None
    assert winner["landed"] == 61.85
    assert winner["landed_cents"] == 6185


@pytest.mark.parametrize("mutation", [
    {"rank": 0},
    {"reasons": ["veto"]},
    {"lines": [{"skuSpec": "gpu", "unitPrice": 40.0, "quantity": 5}]},
])
def test_incomplete_or_nonwinning_result_never_becomes_order(mutation):
    row = {"bidId": "bid-1", "sellerId": "seller-a", "rank": 1, "landed": 92.0,
           "reasons": [], "lines": [{"skuSpec": "gpu", "unitPrice": 40.0, "quantity": 5}],
           "lineMetaJson": json.dumps(META), "origin": "SIM", "source": "fixture"}
    row.update(mutation)
    bridge = MarketBridge("buyer", client=FakeMarket(sql_rows=[[row]]))
    if row["rank"] != 1:
        # No rank-1 row is an ordinary no-winner result.
        assert bridge.authoritative_winner("round-1", [{"sku_spec": "gpu", "quantity": 2}]) is None
    elif row["reasons"]:
        with pytest.raises(MarketBridgeError, match="winner_readback_invalid"):
            bridge.authoritative_winner("round-1", [{"sku_spec": "gpu", "quantity": 2}])
    else:
        assert bridge.authoritative_winner("round-1", [
            {"sku_spec": "gpu", "quantity": 2}, {"sku_spec": "cpu", "quantity": 1},
        ]) is None
