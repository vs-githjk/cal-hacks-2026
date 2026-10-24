import json
from datetime import datetime, timedelta, timezone
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


def test_coordinator_posts_goal_need_then_opens_a_separate_referee_round():
    goal = {"id": "goal-1", "type": "part_by_date", "cap": 900, "deadline": "2026-10-30T00:00:00Z",
            "items": [{"sku_spec": "gpu", "condition": "new", "variant": "retail", "quantity": 1}]}
    need = {"id": "need-1", "delivery_window": "by Friday", "spend_limit": 900, "consent": True,
            "auction_window_s": 12, "items": [{"sku_spec": "gpu", "condition": "new", "variant": "retail",
                                                   "quantity": 1, "unit": "each"}]}
    buyer_client = FakeMarket(sql_rows=[[], [{"id": "goal-1", "buyerId": "vidyut", "type": "part_by_date",
        "cap": 900, "deadline": "2026-10-30T00:00:00Z"}], [{"skuSpec": "gpu", "condition": "new",
        "variant": "retail", "quantity": 1, "skippedOwnedPartId": ""}]])
    buyer = MarketBridge("buyer", client=buyer_client)
    buyer.post_goal(goal, buyer_id="vidyut")
    buyer.post_need(need, buyer_id="vidyut", goal_id="goal-1")
    referee_client = FakeMarket()
    MarketBridge("referee", client=referee_client).open_round("round-1", "need-1", 12)
    assert buyer_client.calls[0][0] == "post_goal"
    assert buyer_client.calls[0][1]["cap"] == 900
    assert buyer_client.calls[1][0] == "post_need"
    assert buyer_client.calls[1][1]["items"][0]["allowed_conditions"] == ["new"]
    assert referee_client.calls == [("open_round", {"round_id": "round-1", "need_id": "need-1", "window_s": 12})]


def test_role_and_rule_id_validation_fail_closed():
    with pytest.raises(MarketBridgeError, match="market_role_mismatch"):
        MarketBridge("buyer", client=FakeMarket()).open_round("r", "n", 12)
    with pytest.raises(MarketBridgeError, match="market_review_invalid"):
        MarketBridge("referee", client=FakeMarket()).attach_verdict(
            bid_id="b", verdict="allow", rule_ids=["x" * 129])


@pytest.mark.parametrize("review_deadline, expected", [
    ({"1": []}, None),
    ({"0": [1_798_848_000_000_000]}, "2027-01-02T00:00:00Z"),
])
def test_round_status_decodes_optional_sats_review_deadline(review_deadline, expected):
    bridge = MarketBridge("referee", client=FakeMarket(sql_rows=[[{
        "id": "round-1", "needId": "need-1", "state": "review",
        "deadline": [1_798_848_000_000_000], "reviewDeadline": review_deadline}]]))
    assert bridge.round_status("round-1")["review_deadline"] == expected


def test_round_status_rejects_unknown_optional_deadline_arm():
    bridge = MarketBridge("referee", client=FakeMarket(sql_rows=[[{
        "id": "round-1", "needId": "need-1", "state": "review",
        "deadline": [1_798_848_000_000_000], "reviewDeadline": {"2": []}}]]))
    with pytest.raises(MarketBridgeError, match="market_option_invalid"):
        bridge.round_status("round-1")


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


def test_publish_bid_accepts_exact_spacetime_product_line_arrays_on_sql_readback():
    canonical = [{**META[0], "provenance": {"origin": "SIM", "source": "fixture"},
                  "attrs": {"category": "gpu", "power_connector": ["8pin", 1], "z": "last"}}]
    stored = json.dumps(canonical, separators=(",", ":"))
    row = ["bid-1", "round-1", "seller-a", "Seller A", [["gpu", "", "", 40.0, 5.0]],
           0.0, [], [], "SIM", "simulated", stored]
    market = FakeMarket(sql_rows=[[row], [row]])
    bridge = MarketBridge("seller", client=market)
    bridge.publish_bid(bid_id="bid-1", round_id="round-1", seller_id="seller-a", persona="Seller A",
        lines=[{"sku_spec": "gpu", "unit_price": 40.0, "quantity": 5}], line_metadata=META)
    assert [call[0] for call in market.calls] == ["set_bid_line_meta"]


@pytest.mark.parametrize("line", [["gpu", "", "", 40.0], ["gpu", "", "", 40.0, True]])
def test_publish_bid_refuses_malformed_spacetime_product_lines(line):
    row = ["bid-1", "round-1", "seller-a", "Seller A", [line], 0.0, [], [], "SIM", "simulated", "[]"]
    bridge = MarketBridge("seller", client=FakeMarket(sql_rows=[[row]]))
    with pytest.raises(MarketBridgeError):
        bridge.publish_bid(bid_id="bid-1", round_id="round-1", seller_id="seller-a", persona="Seller A",
            lines=[{"sku_spec": "gpu", "unit_price": 40.0, "quantity": 5}], line_metadata=META)


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
        "lineMetaJson": json.dumps(META), "origin": "SIM", "source": "fixture", "bindingHash": "b" * 64,
    }]])
    winner = MarketBridge("buyer", client=market).authoritative_winner(
        "round-1", [{"sku_spec": "gpu", "quantity": 2}],
    )
    assert winner is not None
    assert winner["landed"] == 92
    assert winner["binding_hash"] == "b" * 64
    assert winner["lines"] == [{
        "sku_spec": "gpu", "unit_price": 40.0, "quantity": 2.0, "qty_available": 5.0,
        "original_line_index": 0, "listing_id": "https://example.test/listing",
        "listing_hash": "a" * 64, "shipping": 12.0,
    }]
    assert "spend_limit" not in market.queries[0] and "floor" not in market.queries[0]


def test_authoritative_winner_normalizes_spacetime_outer_and_bidline_products():
    row = ["bid-1", "seller-a", 1, 92.0, [], [["gpu", "", "", 40.0, 5.0]],
           json.dumps(META), "SIM", "fixture", "b" * 64]
    winner = MarketBridge("buyer", client=FakeMarket(sql_rows=[[row]])).authoritative_winner(
        "round-1", [{"sku_spec": "gpu", "quantity": 2}])
    assert winner is not None and winner["landed"] == 92.0
    assert winner["lines"][0]["original_line_index"] == 0


@pytest.mark.parametrize("line", [["gpu", "", "", 40.0], ["gpu", "", "", 40.0, True]])
def test_authoritative_winner_rejects_malformed_spacetime_bidline_products(line):
    row = ["bid-1", "seller-a", 1, 92.0, [], [line], json.dumps(META), "SIM", "fixture", "b" * 64]
    bridge = MarketBridge("buyer", client=FakeMarket(sql_rows=[[row]]))
    with pytest.raises(MarketBridgeError):
        bridge.authoritative_winner("round-1", [{"sku_spec": "gpu", "quantity": 2}])


def test_decimal_cent_order_total_tolerates_only_server_float_representation_noise():
    meta = [{**META[0], "shipping": 2.0}]
    market = FakeMarket(sql_rows=[[{
        "bidId": "bid-1", "sellerId": "seller-a", "rank": 1, "landed": 61.849999999999994,
        "reasons": [], "lines": [{"skuSpec": "gpu", "unitPrice": 19.95, "quantity": 5}],
        "lineMetaJson": json.dumps(meta), "origin": "SIM", "source": "fixture", "bindingHash": "b" * 64,
    }]])
    winner = MarketBridge("buyer", client=market).authoritative_winner(
        "round-1", [{"sku_spec": "gpu", "quantity": 3}],
    )
    assert winner is not None
    assert winner["landed"] == 61.85
    assert winner["landed_cents"] == 6185


def test_unrepresentable_large_amount_cannot_use_a_wide_float_tolerance():
    market = FakeMarket(sql_rows=[[{
        "bidId": "bid-1", "sellerId": "seller-a", "rank": 1, "landed": 2e16,
        "reasons": [], "lines": [{"skuSpec": "gpu", "unitPrice": 1e16, "quantity": 2}],
        "lineMetaJson": json.dumps([{**META[0], "shipping": 0}]), "origin": "SIM", "source": "fixture",
        "bindingHash": "b" * 64,
    }]])
    bridge = MarketBridge("buyer", client=market)
    with pytest.raises(MarketBridgeError, match="winner_amount_unrepresentable"):
        bridge.authoritative_winner("round-1", [{"sku_spec": "gpu", "quantity": 2}])


@pytest.mark.parametrize("mutation", [
    {"rank": 0},
    {"reasons": ["veto"]},
    {"lines": [{"skuSpec": "gpu", "unitPrice": 40.0, "quantity": 5}]},
])
def test_incomplete_or_nonwinning_result_never_becomes_order(mutation):
    row = {"bidId": "bid-1", "sellerId": "seller-a", "rank": 1, "landed": 92.0,
           "reasons": [], "lines": [{"skuSpec": "gpu", "unitPrice": 40.0, "quantity": 5}],
           "lineMetaJson": json.dumps(META), "origin": "SIM", "source": "fixture", "bindingHash": "b" * 64}
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


def _purchase_status(*, mandate=None, mandate_id="md-1", amount=40.0, payee="seller-a", expiry=None,
                     reserved=True, retired=False, settled=False, approval=None,
                     payment_ref=None, payment_amount=None, payment_mode=None):
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    expiry = expiry or now + timedelta(minutes=9)
    if isinstance(expiry, str):
        expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    micros = int(expiry.timestamp()) * 1_000_000
    return {"mandateHash": mandate or "a" * 64, "mandateId": mandate_id, "dealId": "deal-1",
        "goalId": "goal-1", "needId": "need-1", "amount": amount, "payee": payee,
        "expiry": [micros], "origin": "SIM", "withinAllowance": False, "retired": retired,
        "reservationMatches": reserved, "settled": settled,
        "approvalMethod": {"0": approval} if approval is not None else {"1": []},
        "approvedAt": {"0": [micros]} if approval is not None else {"1": []},
        "paymentRef": {"0": payment_ref} if payment_ref is not None else {"1": []},
        "paymentAmount": {"0": payment_amount} if payment_amount is not None else {"1": []},
        "paymentMode": {"0": payment_mode} if payment_mode is not None else {"1": []},
        "paidAt": {"1": []}}


def test_purchase_status_is_buyer_private_and_normalizes_sats_fields():
    market = FakeMarket(sql_rows=[[_purchase_status(approval="typed_code", payment_ref="ch_test",
        payment_amount=40.0, payment_mode="sim")]])
    bridge = MarketBridge("buyer", client=market)
    row = bridge.purchase_status("a" * 64)
    assert row["approval_method"] == "typed_code"
    assert row["payment_ref"] == "ch_test" and row["payment_mode"] == "sim"
    assert row["expiry"] == "2026-10-24T00:09:00Z"
    assert "FROM my_purchase_status" in market.queries[0]
    assert "SELECT *" not in market.queries[0]
    with pytest.raises(MarketBridgeError, match="purchase_status_binding_invalid"):
        MarketBridge("referee", client=FakeMarket()).purchase_status("a" * 64)
    with pytest.raises(MarketBridgeError, match="purchase_status_binding_invalid"):
        bridge.purchase_status("x" * 64)


def test_purchase_status_rejects_missing_foreign_and_malformed_rows():
    with pytest.raises(MarketBridgeError, match="purchase_status_readback_missing"):
        MarketBridge("buyer", client=FakeMarket()).purchase_status("a" * 64)
    foreign = _purchase_status(mandate="b" * 64)
    with pytest.raises(MarketBridgeError, match="purchase_status_readback_invalid"):
        MarketBridge("buyer", client=FakeMarket(sql_rows=[[foreign]])).purchase_status("a" * 64)
    malformed = _purchase_status() | {"expiry": [True]}
    with pytest.raises(MarketBridgeError, match="market_timestamp_invalid"):
        MarketBridge("buyer", client=FakeMarket(sql_rows=[[malformed]])).purchase_status("a" * 64)


def test_seller_loss_report_projection_is_role_checked_and_normalizes_timestamp():
    row = {"id": "loss-1", "roundId": "round-1", "sellerId": "seller-a", "won": False,
        "gapBand": "within5", "reason": "price", "sourceUrl": "https://example.test/listing",
        "createdAt": [1_798_848_000_000_000]}
    bridge = MarketBridge("seller", client=FakeMarket(sql_rows=[[row]]))
    report = bridge.my_loss_reports()[0]
    assert report["seller_id"] == "seller-a" and report["created_at"].endswith("Z")
    assert set(report) == {"id", "round_id", "seller_id", "won", "gap_band", "reason", "source_url", "created_at"}
    from agents.sellers.learning import _validate_report
    assert _validate_report(report, "seller-a")["id"] == "loss-1"
    assert "FROM my_loss_reports" in bridge._client.queries[0]
    assert "SELECT *" not in bridge._client.queries[0]
    with pytest.raises(MarketBridgeError, match="loss_reports_role_mismatch"):
        MarketBridge("buyer", client=FakeMarket()).my_loss_reports()


@pytest.mark.parametrize("change", [
    {"mandateHash": "b" * 64}, {"amount": 41.0}, {"payee": "seller-b"},
    {"reservationMatches": False}, {"retired": True}, {"withinAllowance": True},
])
def test_create_mandate_requires_exact_private_readback(change):
    from pay.mandate import new_mandate
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    mandate = new_mandate(deal_id="deal-1", buyer_id="vidyut", goal_id="goal-1", amount=40.0,
        payee="seller-a", within_allowance=False, origin="SIM", now=now)
    status = _purchase_status(mandate=mandate["hash"], mandate_id=mandate["id"],
                              expiry=mandate["expires_at"]) | change
    market = FakeMarket(sql_rows=[[status]])
    bridge = MarketBridge("buyer", client=market)
    with pytest.raises(MarketBridgeError):
        bridge.create_mandate(mandate, need_id="need-1", buyer_id="vidyut", now=now)
    assert market.calls[0][0] == "create_mandate"
    assert market.calls[0][1] == {"hash": mandate["hash"], "id": mandate["id"], "deal_id": "deal-1",
        "buyer_id": "vidyut", "amount": 40.0, "payee": "seller-a", "expiry_minutes": 10,
        "nonce": mandate["nonce"], "requested_by": "", "origin": "SIM", "goal_id": "goal-1", "need_id": "need-1"}


def test_create_mandate_accepts_exact_buyer_private_readback():
    from pay.mandate import new_mandate
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    mandate = new_mandate(deal_id="deal-1", buyer_id="vidyut", goal_id="goal-1", amount=40.0,
        payee="seller-a", within_allowance=False, origin="SIM", now=now)
    status = _purchase_status(mandate=mandate["hash"], mandate_id=mandate["id"],
                              expiry=mandate["expires_at"])
    bridge = MarketBridge("buyer", client=FakeMarket(sql_rows=[[status]]))
    assert bridge.create_mandate(mandate, need_id="need-1", buyer_id="vidyut", now=now)["mandate_hash"] == mandate["hash"]


@pytest.mark.parametrize("mode", ["sim", "stripe_test"])
def test_referee_records_only_canonical_payment_mode(mode):
    market = FakeMarket()
    bridge = MarketBridge("referee", client=market)
    assert bridge.record_payment(mandate_hash="a" * 64, payment_ref="ch_test", amount=40.0, mode=mode) == {"recorded": True}
    assert market.calls == [("record_payment", {"mandate_hash": "a" * 64,
        "payment_ref": "ch_test", "amount": 40.0, "mode": mode})]
    with pytest.raises(MarketBridgeError, match="payment_binding_invalid"):
        bridge.record_payment(mandate_hash="a" * 64, payment_ref="ch_test", amount=40.0, mode="SIM")
