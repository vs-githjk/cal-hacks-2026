"""Offline end-to-end containment checks for Shield held-out misses.

The rows are derived from shield.bench itself on every run. The text is supplied only
through seller-controlled BidReply fields; buyer and advocate production callbacks,
selection, order construction, and payment authorization remain real.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import http.client
import importlib
import json
import socket
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "agents"
sys.path.insert(0, str(AGENTS))
sys.path.insert(0, str(AGENTS / "buyer"))
sys.path.insert(0, str(AGENTS / "advocate"))

from shield.bench import SETS, bench
from pay.approval import ApprovalService
from pay.mandate import mandate_hash, new_mandate, verify as verify_mandate
from pay.merchant_sim import MerchantSim
from pay.replay import NonceStore
from pay.tap import keyring, verify_request
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pay.tests import test_merchant_sim as merchant_helpers
from shield.receipt import verify_allow_receipt


BUYER_ID = "buyer-agent-1"
NEED_ID = "need-containment-143"
GOAL_ID = "goal-containment-143"
GPU = "rtx 4070 super 12gb"
GPU_ATTRS = {"category": "gpu", "chipset": "RTX 4070 SUPER", "length_mm": 267,
             "power_connector": ["8pin", 1]}


class LocalContext:
    """The production callbacks only need a local message sink and logger."""

    def __init__(self):
        self.logger = Mock()
        self.sent = []
        self.session = uuid4()

    async def send(self, recipient, message):
        self.sent.append((recipient, message))


@pytest.fixture
def lane(monkeypatch):
    # Prevent Agent construction from writing identity data. In particular, common.py
    # must not load a local .env while this offline test imports the real handlers.
    fake_agent = Mock()
    fake_agent.on_message.side_effect = lambda *args, **kwargs: lambda fn: fn
    fake_agent.on_interval.side_effect = lambda *args, **kwargs: lambda fn: fn
    fake_agent.on_rest_post.side_effect = lambda *args, **kwargs: lambda fn: fn
    fake_agent.on_rest_get.side_effect = lambda *args, **kwargs: lambda fn: fn
    exists = Path.exists
    with patch("uagents.Agent", return_value=fake_agent), patch.object(
            Path, "exists", lambda p: False if p.name == ".env" else exists(p)):
        buyer = importlib.import_module("buyer_agent")
        advocate = importlib.import_module("advocate.advocate_agent")

    # Explicit service boundary fakes: only Shield's network boundary and the CRS
    # service are replaced. Message handlers, advocate checks and buyer selection run.
    screen_calls = []

    def allow_at_shield_boundary(message_id, sender, text, context=None):
        screen_calls.append((sender, text))
        return {"verdict": "allow", "reasons": [], "rule_ids": [], "message_id": message_id}

    monkeypatch.setattr(buyer.common, "screen", allow_at_shield_boundary)
    monkeypatch.setattr(buyer, "CHAT_DIAG", Mock())
    network_attempts = []

    def forbidden_network(*args, **kwargs):
        network_attempts.append((args, kwargs))
        raise AssertionError("containment test attempted external network access")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_network)
    monkeypatch.setattr(urllib.request, "build_opener", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", forbidden_network)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", forbidden_network)
    import crs

    async def checks(_now):
        return {
            seller: {
                "signal": {"supplier_id": seller, "stability": "verified_stable",
                           "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                           "source": "sandbox"},
                "reason": crs.REASON_VERIFIED,
            }
            for seller in buyer.common.SELLERS
        }

    monkeypatch.setattr(crs, "check_sellers", checks)
    monkeypatch.setattr(crs, "eligible", lambda _seller, check, _now: bool(check and check.get("signal")))
    monkeypatch.setattr(buyer, "ALLOWANCE", 0)  # exercise real owner approval/requote callbacks
    real_pick_best = buyer.hunt.pick_best
    pick_results = []

    def observe_pick_best(*args, **kwargs):
        result = real_pick_best(*args, **kwargs)
        pick_results.append(result)
        return result

    monkeypatch.setattr(buyer.hunt, "pick_best", observe_pick_best)
    buyer.ROUND.clear()
    buyer.APPROVALS.clear()
    yield SimpleNamespace(buyer=buyer, advocate=advocate, screen_calls=screen_calls, pick_results=pick_results,
                          monkeypatch=monkeypatch,
                          network_attempts=network_attempts)
    buyer.ROUND.clear()
    buyer.APPROVALS.clear()


def _held_out_misses():
    result = bench({"held_out": SETS["held_out"]})["held_out"]
    assert "missed" in result, f"held-out Shield bench did not produce a scored result: {result}"
    assert result["errors"] == [], f"held-out Shield bench had unscored rows: {result['errors']}"
    rows = [json.loads(line) for line in SETS["held_out"].read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {row["id"]: row for row in rows}
    return [by_id[attack_id] for attack_id in result["missed"]]


def _bid(buyer, seller, bid_id, price, *, attack=None, page_condition="new"):
    item = buyer.ROUND["need"]["items"][0]
    text = attack or "A normal seller note."
    return {
        "id": bid_id,
        "need_id": NEED_ID,
        "persona": "Seller offer" if attack is None else text,
        "supplier_id": seller,
        "lines": [{"sku_spec": item["sku_spec"], "unit_price": price, "quantity": 1,
                   "offered_condition": "new", "page_condition": page_condition,
                   "listing_url": f"https://example.invalid/listing/{bid_id}", "attrs": dict(GPU_ATTRS)}],
        "total_landed_price": price,
        "perks": [],
        "claims": [] if attack is None else [text],
        "floor_check_passed": True,
        "mirror_snapshot_id": "",
        "decision_trace": "SIM containment fixture",
        "expires_at": "2099-01-01T00:00:00Z",
        "source": "SIM containment fixture",
        "origin": "SIM",
    }


def _seed_round(buyer):
    buyer.ROUND.clear()
    buyer.APPROVALS.clear()
    now = datetime.now(timezone.utc)
    goal = {"id": GOAL_ID, "buyer_id": BUYER_ID, "type": "budget_cap",
            "items": [{"part": "gpu", "sku_spec": GPU, "condition": "new",
                       "variant": "retail", "quantity": 1}],
            "cap": 800.0, "deadline": "2099-01-01T00:00:00Z", "state": "HUNTING",
            "reserved_amount": 0, "created_at": now.isoformat(), "notes": "trusted test fixture"}
    need = {"id": NEED_ID, "buyer_id": BUYER_ID,
            "items": [{"sku_spec": GPU, "condition": "new", "variant": "retail",
                       "quantity": 1, "unit": "each", "grade": "new", "pack_size": "retail"}],
            "delivery_window": "by 2099-01-01", "spend_limit": 800.0, "consent": True,
            "auction_window_s": 12, "source": "simulated"}
    buyer.common.validate("Goal", goal)
    buyer.common.validate("Need", need)
    checks = {seller: {"signal": {"supplier_id": seller, "stability": "verified_stable",
                                   "checked_at": now.isoformat().replace("+00:00", "Z"), "source": "sandbox"},
                       "reason": "verified"}
              for seller in buyer.common.SELLERS}
    buyer.ROUND.update(owner=BUYER_ID, goal=goal, need=need, owned=[], phase="bidding",
                       deadline=time.time() + 60, round_token=uuid4().hex, bids=[], personas={},
                       cards={}, seller_checks=checks, attempts=0, last_sent={})


def _run_real_buyer_callbacks(lane, attack=None, prices=(749.0, 779.0), page_conditions=("new", "new"),
                              listing_conditions=("new", "new")):
    buyer, advocate = lane.buyer, lane.advocate
    _seed_round(buyer)
    lane.pick_results.clear()
    ctx = LocalContext()
    # Synthetic read-only listing transport. Page facts are held separately from
    # seller Bid fields, so page_condition cannot manufacture its own evidence.
    listing_facts = {
        f"https://example.invalid/listing/bid-one": listing_conditions[0],
        f"https://example.invalid/listing/bid-two": listing_conditions[1],
    }

    def synthetic_check_claim(claim, fetch=None):
        observed = listing_facts.get(claim.get("evidence_url"))
        result = "unverified" if observed is None else (
            "verified" if claim.get("value") == observed else "false")
        return {"result": result, "evidence_url": claim.get("evidence_url", ""),
                "checked_at": "2026-10-24T12:00:00Z",
                "evidence_hash": hashlib.sha256(f"synthetic-listing:{observed}".encode()).hexdigest()
                if observed is not None else "",
                "method": "fetched page, synthetic test transport",
                "reason": "condition matched synthetic listing" if result == "verified"
                else "condition did not match synthetic listing" if result == "false"
                else "listing fixture unavailable"}

    from data import claim_check
    lane.monkeypatch.setattr(claim_check, "check_claim", synthetic_check_claim)
    bids = [_bid(buyer, "seller_1", "bid-one", prices[0], attack=attack,
                 page_condition=page_conditions[0]),
            _bid(buyer, "seller_2", "bid-two", prices[1], page_condition=page_conditions[1])]

    async def drive():
        for bid in bids:
            seller = bid["supplier_id"]
            persona_line = attack if attack is not None and seller == "seller_1" else "A normal seller note."
            await buyer.on_bid(ctx, buyer.common.address(seller), buyer.common.BidReply(
                bid_json=json.dumps(bid), persona_line=persona_line))
        buyer.ROUND["deadline"] = time.time() - 1
        await buyer.tick(ctx)
        request = next(message for _, message in ctx.sent if isinstance(message, buyer.common.AdviceRequest))
        await advocate.on_advice(ctx, buyer.common.address("buyer"), request)
        reply = next(message for _, message in reversed(ctx.sent) if isinstance(message, buyer.common.AdviceReply))
        await buyer.on_advice(ctx, buyer.common.address("advocate"), reply)
        assert len(lane.pick_results) == 1, "conclude must call the real pick_best exactly once"
        recommended_index = lane.pick_results[0]
        if recommended_index is None:
            assert buyer.ROUND["phase"] == "waiting"
            return
        assert buyer.ROUND["phase"] == "decided"
        recommended_bid = buyer.ROUND["bids"][recommended_index - 1]
        await buyer.handle_text(ctx, BUYER_ID, f"APPROVE {recommended_index}")
        assert buyer.ROUND["phase"] == "requote"
        await buyer.on_requote(ctx, dict(recommended_bid))
        assert buyer.ROUND["order"]["bid_id"] == recommended_bid["id"]

    asyncio.run(drive())
    assert any(sender == buyer.common.address("seller_1") for sender, _text in lane.screen_calls)
    assert any(sender == buyer.common.address("advocate") for sender, _text in lane.screen_calls)
    recommendation_index = lane.pick_results[0]
    recommended_bid_id = (buyer.ROUND["bids"][recommendation_index - 1]["id"]
                          if recommendation_index is not None else None)
    return {
        "recommended_index": recommendation_index,
        "recommended_bid_id": recommended_bid_id,
        "order": copy.deepcopy(buyer.ROUND.get("order")),
        "mandate": copy.deepcopy(buyer.ROUND.get("mandate")),
        "card": copy.deepcopy(buyer.ROUND["cards"].get(recommended_bid_id)) if recommended_bid_id else None,
        "cards": copy.deepcopy(buyer.ROUND["cards"]),
        "bids": copy.deepcopy(buyer.ROUND["bids"]),
    }


def _payment_transaction(result, *, foreign_approval=False, now):
    """Adapt the actual buyer order/card into payment's persisted transaction shape."""
    order, source_mandate = result["order"], result["mandate"]
    mandate = copy.deepcopy(source_mandate)
    # Reach the trusted-approval gate with every earlier purchase binding valid. This
    # is explicitly only a candidate approved state, without a same-hash auth record.
    mandate["status"] = "approved"
    mandate["approval_id"] = "candidate-approval-without-record"
    transaction = {
        "deal_id": order["id"], "buyer_id": mandate["buyer_id"], "goal_id": mandate["goal_id"],
        "need_id": order["need_id"], "bid_id": order["bid_id"], "phase": "approved",
        "deal": {"id": order["id"], "goal_id": mandate["goal_id"], "need_id": order["need_id"],
                 "bid_id": order["bid_id"], "amount": order["amount"], "payee": mandate["payee"]},
        "order": copy.deepcopy(order), "mandate": mandate,
        "advocate_card": copy.deepcopy(result["card"]),
        "voice_approval": None, "allowance_authorization": None,
    }
    foreign_record = None
    if foreign_approval:
        other = new_mandate(deal_id=mandate["deal_id"], buyer_id=mandate["buyer_id"],
                            goal_id=mandate["goal_id"], amount=mandate["amount"], payee=mandate["payee"],
                            within_allowance=False, now=now)
        service = ApprovalService("containment-test-secret-value-143")
        session, code = service.issue(other, now=now)
        session.start_call(now=now)
        session.begin_listening(now=now)
        decision = session.approve(code + " approve", now=now + timedelta(seconds=1))
        assert decision.approved and decision.record
        assert decision.record["mandate_hash"] != mandate["hash"]
        foreign_record = decision.record
        transaction["voice_approval"] = foreign_record
    return transaction


def _merchant_result(transaction, tmp_path, now):
    tap_private = Ed25519PrivateKey.generate()
    receipt_private = Ed25519PrivateKey.generate()
    stripe = merchant_helpers.FakeStripe()
    sim = MerchantSim(keys=keyring(tap_private.public_key()),
        receipt_keys=keyring(receipt_private.public_key()),
        store=NonceStore(str(tmp_path / f"merchant-{uuid4().hex}.sqlite")),
        approvals=lambda deal_id, buyer_id: transaction
        if (deal_id, buyer_id) == (transaction["deal_id"], transaction["buyer_id"]) else None,
        charger=stripe)
    mandate = transaction["mandate"]
    request = merchant_helpers.signed(tap_private, receipt_private, mandate, now=now)
    # Independently verify request/mandate, TAP and Shield receipt bindings so the
    # MerchantSim result isolates the trusted-approval denial rather than bad input.
    assert mandate["hash"] == mandate_hash(mandate)
    assert verify_mandate(mandate, now)
    assert verify_allow_receipt(request["receipt"], keyring(receipt_private.public_key()),
        message_id=request["message_id"], request_json=request["body"].decode("utf-8"),
        deal_id=mandate["deal_id"], mandate_hash=mandate["hash"], amount_cents=74900,
        currency=mandate["currency"], payee=mandate["payee"], now=now)
    tap_verdict = verify_request(method=request["method"], url=request["url"], headers=request["headers"],
        body=request["body"], keys=keyring(tap_private.public_key()),
        store=NonceStore(str(tmp_path / f"tap-preflight-{uuid4().hex}.sqlite")), now=now,
        expected_mandate_hash=mandate["hash"], mandate=mandate)
    assert tap_verdict
    outcome = sim.handle(**request, now=now)
    return outcome, stripe, mandate


def test_held_out_misses_cannot_change_real_buyer_order_or_pay_without_same_hash_approval(lane, tmp_path):
    misses = _held_out_misses()
    assert misses, "held-out Shield benchmark has no misses to replay"
    baseline = _run_real_buyer_callbacks(lane)
    assert baseline["recommended_bid_id"] is not None and baseline["order"]
    baseline_preserved = 0
    coded_refusals = 0
    coded_recommendation_changes = 0
    evaluated = 0
    for row in misses:
        attack_label = row["id"]
        evaluated += 1
        try:
            attacked = _run_real_buyer_callbacks(lane, attack=row["message"])
            # These untrusted ingress differences may yield only a production-coded
            # advocate rule. Validate every real card against the production template
            # table and source sanitizer; a seller string cannot become its own rule.
            for card in attacked["cards"].values():
                assert card["rule_id"] in lane.advocate.checks.CALL_SUMMARIES, f"{attack_label}: unknown rule"
                assert card["reason"] == lane.advocate.checks.CALL_SUMMARIES[card["rule_id"]]
                assert card["call_reason"] == {"rule_id": card["rule_id"], "summary": card["reason"],
                                               "source_url": card["source_url"]}
                assert lane.advocate.checks._safe_source_url(card["source_url"]) == card["source_url"]
            recommendation_changed = attacked["recommended_bid_id"] != baseline["recommended_bid_id"]
            if attacked["recommended_bid_id"] is None:
                assert attacked["order"] is None and attacked["mandate"] is None, (
                    f"{attack_label}: no recommendation must remain a zero-order refusal")
                assert all(card["recommendation"] == "veto" for card in attacked["cards"].values()), (
                    f"{attack_label}: no recommendation lacked production veto evidence")
                assert not lane.buyer.APPROVALS, f"{attack_label}: refusal unexpectedly created approval state"
                coded_refusals += 1
                continue
            assert attacked["order"] and attacked["mandate"]
            assert attacked["order"]["bid_id"] == attacked["recommended_bid_id"]
            if recommendation_changed:
                # A winner change is acceptable only when a real code-owned card
                # changes the baseline recommendation's production selection rank.
                old_card = baseline["cards"][baseline["recommended_bid_id"]]
                new_card = attacked["cards"][baseline["recommended_bid_id"]]

                def selection_rank(card):
                    kinds = {warning["kind"] for warning in card["warnings"]}
                    return ("spec" in kinds, card["recommendation"] != "buy")

                assert new_card != old_card, f"{attack_label}: winner changed without a changed advocate card"
                assert (new_card["recommendation"] == "veto" or
                        selection_rank(new_card) > selection_rank(old_card)), (
                            f"{attack_label}: winner changed without a code-owned rank change")
                selected = next(bid for bid in attacked["bids"] if bid["id"] == attacked["recommended_bid_id"])
                assert attacked["mandate"]["payee"] == lane.buyer.common.address(selected["supplier_id"])
                assert attacked["mandate"]["amount"] == selected["total_landed_price"]
            else:
                assert attacked["mandate"]["payee"] == baseline["mandate"]["payee"], f"{attack_label}: payee changed"
                assert attacked["mandate"]["amount"] == baseline["mandate"]["amount"], f"{attack_label}: amount changed"

            for foreign_approval in (False, True):
                now = datetime.now(timezone.utc).replace(microsecond=0)
                transaction = _payment_transaction(attacked, foreign_approval=foreign_approval, now=now)
                mandate = transaction["mandate"]
                request = lane.buyer.payment.payment_request(mandate, mandate["payee"])
                assert transaction["mandate"]["hash"] == attacked["mandate"]["hash"]
                assert transaction["deal"]["need_id"] == attacked["order"]["need_id"]
                assert transaction["deal"]["bid_id"] == attacked["recommended_bid_id"]
                # Real commit logic rejects missing and foreign-hash approval for this exact
                # transaction before it can construct a CommitPayment.
                with pytest.raises(PermissionError):
                    lane.buyer.payment.commit(request, transaction, now=now)

                outcome, stripe, merchant_mandate = _merchant_result(transaction, tmp_path, now)
                assert merchant_mandate["hash"] == attacked["mandate"]["hash"]
                assert outcome["reason"] == "no_trusted_approval", f"{attack_label}: {outcome}"
                assert outcome["mandate_hash"] == attacked["mandate"]["hash"]
                assert stripe.calls == [], f"{attack_label}: charger called without matching approval"
            if recommendation_changed:
                coded_recommendation_changes += 1
            else:
                baseline_preserved += 1
        except AssertionError:
            completed = baseline_preserved + coded_refusals + coded_recommendation_changes
            print(f"Shield-off buyer/payment behavioral progress: {evaluated} of {len(misses)} rows started, "
                  f"{completed} fully checked; failure at {attack_label}")
            raise
    assert lane.network_attempts == []
    assert baseline_preserved + coded_refusals + coded_recommendation_changes == len(misses)
    print(f"Shield-off buyer/payment behavioral result: {baseline_preserved} of {len(misses)} derived misses "
          f"preserved the baseline recommendation; coded refusals: {coded_refusals}; "
          f"coded recommendation changes: {coded_recommendation_changes}; "
          f"miss IDs: {', '.join(row['id'] for row in misses)}; network attempts: {len(lane.network_attempts)}")
    assert evaluated == len(misses)


def test_real_recommendation_drives_approval_and_requote_for_second_bid(lane):
    # Equal prices preserve fixture order. A separately supplied synthetic listing
    # has an open-box condition for bid one, while its seller claim says new.
    # The buyer must veto that claim from checker evidence, not from page_condition.
    result = _run_real_buyer_callbacks(lane, prices=(749.0, 749.0),
                                       page_conditions=("new", "new"),
                                       listing_conditions=("open-box", "new"))
    assert result["recommended_index"] == 2
    assert result["recommended_bid_id"] == "bid-two"
    assert result["cards"]["bid-one"]["recommendation"] == "veto"
    assert result["order"] and result["order"]["bid_id"] == "bid-two"
    assert result["mandate"]["amount"] == 749.0
    assert result["mandate"]["payee"] == lane.buyer.common.address("seller_2")


def test_actual_advocate_card_contract_is_closed_and_rejects_extra_fields(lane):
    result = _run_real_buyer_callbacks(lane)
    card = result["card"]
    schema_path = ROOT / "contracts" / "AdvocateCard.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator, ValidationError

    assert schema.get("additionalProperties") is False, "canonical AdvocateCard schema is still open"
    warning_schema = schema["properties"]["warnings"]["items"]
    reason_schema = schema["properties"]["call_reason"]
    assert warning_schema.get("additionalProperties") is False, "AdvocateCard warning schema is still open"
    assert reason_schema.get("additionalProperties") is False, "AdvocateCard call_reason schema is still open"
    assert schema["properties"]["recommendation"].get("enum"), "AdvocateCard recommendation is not enumerated"
    Draft202012Validator(schema).validate(card)
    lane.buyer.common.validate("AdvocateCard", card)
    with pytest.raises(ValidationError):
        lane.buyer.common.validate("AdvocateCard", {**card, "untrusted_extra": "rejected"})
    assert card["warnings"], "fixture should produce a real advocate warning for nested closure checks"
    warning_extra = copy.deepcopy(card)
    warning_extra["warnings"][0]["untrusted_extra"] = "rejected"
    with pytest.raises(ValidationError):
        lane.buyer.common.validate("AdvocateCard", warning_extra)
    reason_extra = copy.deepcopy(card)
    reason_extra["call_reason"]["untrusted_extra"] = "rejected"
    with pytest.raises(ValidationError):
        lane.buyer.common.validate("AdvocateCard", reason_extra)
    invalid_enum = copy.deepcopy(card)
    invalid_enum["recommendation"] = "untrusted-choice"
    with pytest.raises(ValidationError):
        lane.buyer.common.validate("AdvocateCard", invalid_enum)
