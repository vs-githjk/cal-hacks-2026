import asyncio
import copy
import importlib
import json
import sys
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agents.buyer import replay, state
from agents.buyer.replay import run_replay
from agents.buyer.replay_market import ReplayMarketAdapter, SimProvider, SimTransport


T0 = datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)


class SimClock:
    def __init__(self, now=T0):
        self.value = now

    def now(self):
        return self.value

    def advance_to(self, value):
        assert value >= self.value
        self.value = value


def scenario(until, origin="MIRROR", buyer_id="buyer-1"):
    return {"run_id": "run-1", "buyer_id": buyer_id, "goal_id": "goal-1", "mode": "SIM",
            "transport": "SIM", "input_origin": origin, "until": until}


def row(at, *, kind="ask", price=100.0, origin="MIRROR"):
    return {"provider": "synthetic", "store": "demo-store", "sku": "rtx 4070 super 12gb", "price": price,
            "in_stock": True, "condition": "new", "kind": kind, "observed_at": at.isoformat(),
            "url": "https://shop.example/listing/1", "snapshot_id": f"snapshot-{at.timestamp()}",
            "origin": origin}


def seed_goal(path, buyer, *, deadline, goal_state="ACTIVE", buyer_id="buyer-1"):
    goal, _ = buyer.parse_goal("a new RTX 4070 Super under $800 by 2026-10-28", buyer_id, T0)
    goal.update(id="goal-1", deadline=deadline.isoformat(), state=goal_state)
    db = state.open_state(path)
    try:
        state.save_goal(db, goal)
    finally:
        db.close()


def stored_transaction(deal_id, phase):
    return {"deal_id": deal_id, "buyer_id": "buyer-1", "goal_id": "goal-1", "need_id": "need-1",
            "bid_id": "bid-1", "phase": phase,
            "deal": {"id": deal_id, "goal_id": "goal-1", "bid_id": "bid-1", "need_id": "need-1",
                     "amount": 400, "payee": "seller-1"}, "order": None,
            "mandate": {"id": f"mandate-{deal_id}", "deal_id": deal_id, "buyer_id": "buyer-1",
                        "goal_id": "goal-1", "amount": 400, "currency": "USD", "payee": "seller-1",
                        "nonce": f"nonce-{deal_id}", "created_at": T0.isoformat(),
                        "expires_at": (T0 + timedelta(minutes=10)).isoformat(), "hash": "a" * 64,
                        "within_allowance": False, "status": "pending", "origin": "SIM"},
            "advocate_card": {"need_id": "need-1", "bid_id": "bid-1", "warnings": [],
                              "recommendation": "buy", "wait_until": "", "claim_checks": [],
                              "rule_id": "advocate.ok", "reason": "No problems found in the checks",
                              "source_url": "https://example.com/review",
                              "call_reason": {"rule_id": "advocate.ok", "summary": "No problems found in the checks",
                                              "source_url": "https://example.com/review"}}}


@pytest.fixture
def buyer(monkeypatch):
    agents_dir = str(Path(__file__).resolve().parents[1])
    monkeypatch.syspath_prepend(agents_dir)
    fake_agent = Mock()
    fake_agent.on_message.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_interval.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_rest_post.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_rest_get.side_effect = lambda *a, **k: lambda fn: fn
    old_module = sys.modules.pop("buyer_agent", None)
    with patch("uagents.Agent", return_value=fake_agent):
        module = importlib.import_module("buyer_agent")
    module.ROUND.clear()
    module.APPROVALS.clear()
    module.USED.clear()
    module.ALLOWANCE = 0
    yield module
    module.ROUND.clear()
    module.APPROVALS.clear()
    module.USED.clear()
    sys.modules.pop("buyer_agent", None)
    if old_module is not None:
        sys.modules["buyer_agent"] = old_module


class FakeChecker:
    async def check_sellers(self, now):
        return {}

    def screen(self, *args, **kwargs):
        return {"verdict": "allow", "reasons": [], "rule_ids": []}

    def screen_bid(self, *args, **kwargs):
        return {"verdict": "allow", "reasons": [], "rule_ids": []}


class FakeProvider(SimProvider):
    def __init__(self, *, bids=True):
        self.include_bids = bids
        self.seen = []

    def bids(self, listing, need, now):
        self.seen.append(listing["kind"])
        if not self.include_bids or not listing["in_stock"]:
            return []
        bid = {"id": f"bid-{listing['snapshot_id']}", "need_id": need["id"], "supplier_id": "seller_1",
               "persona": "Synthetic seller", "lines": [{"sku_spec": item["sku_spec"],
                            "unit_price": listing["price"], "quantity": item["quantity"],
                            "qty_available": item["quantity"], "condition": "new", "offered_condition": "new",
                            "offered_spec": listing["sku"], "shipping": 0, "origin": "SIM",
                            "source": listing["url"]} for item in need["items"]],
               "total_landed_price": listing["price"], "perks": [], "claims": [],
               "floor_check_passed": True, "mirror_snapshot_id": listing["snapshot_id"],
               "decision_trace": "SIM provider observation", "expires_at": (now + timedelta(seconds=60)).isoformat(),
               "source": listing["url"], "origin": "SIM"}
        return [(self.sender, self.message(bid_json=json.dumps(bid), persona_line="synthetic evidence"))]

    def review(self, request, now):
        bids = json.loads(request.bids_json)
        cards = [{"need_id": bid["need_id"], "bid_id": bid["id"], "warnings": [], "recommendation": "buy",
                  "wait_until": "", "claim_checks": [], "rule_id": "advocate.ok",
                  "reason": "No problems found in the checks", "source_url": "https://example.com/review",
                  "call_reason": {"rule_id": "advocate.ok", "summary": "No problems found in the checks",
                                  "source_url": "https://example.com/review"}} for bid in bids]
        return self.advice_message(cards_json=json.dumps(cards))

    sender = ""
    message = None
    advice_message = None


@pytest.fixture
def replay_stack(buyer, monkeypatch):
    from common import BidReply, AdviceReply, address

    checker = FakeChecker()
    provider = FakeProvider()
    provider.sender = address("seller_1")
    provider.message = BidReply
    provider.advice_message = AdviceReply
    transport = SimTransport()
    monkeypatch.delenv("CRS_API_KEY", raising=False)
    monkeypatch.delenv("CRS_USERNAME", raising=False)
    monkeypatch.delenv("CRS_PASSWORD", raising=False)
    clock = SimClock()
    with ReplayMarketAdapter(clock=clock, checker=checker, provider=provider, transport=transport) as adapter:
        yield buyer, provider, transport, adapter, clock


def test_actual_buyer_callbacks_select_and_notify_without_payment(tmp_path, replay_stack):
    buyer, provider, transport, adapter, clock = replay_stack
    state_path = tmp_path / ".state" / "replay.sqlite3"
    deadline = T0 + timedelta(days=4)
    seed_goal(state_path, buyer, deadline=deadline)
    observed = [row(T0 + timedelta(seconds=1), price=500), row(T0 + timedelta(seconds=2), kind="sold", price=1)]
    sc = scenario(T0 + timedelta(hours=1))

    report = asyncio.run(run_replay(observed, sc, adapter, clock, state_path))

    assert provider.seen == ["ask"]
    assert buyer.ROUND["phase"] == "decided"
    assert buyer.ROUND["goal"]["state"] == "HOLD_FOR_CALL"
    assert "APPROVE 1" in " ".join(msg.text() for _, msg in transport.sent if hasattr(msg, "text"))
    assert not any(type(msg).__name__ in {"RequestPayment", "CommitPayment"} for _, msg in transport.sent)
    assert report["source_counts"] == {"synthetic": 2}


def test_actual_tick_retries_and_pauses_in_three_day_sim_without_sleep(tmp_path, replay_stack):
    buyer, provider, transport, adapter, clock = replay_stack
    provider.include_bids = False
    state_path = tmp_path / ".state" / "retries.sqlite3"
    seed_goal(state_path, buyer, deadline=T0 + timedelta(days=3))
    started = datetime.now(timezone.utc)

    report = asyncio.run(run_replay([row(T0 + timedelta(seconds=1), origin="SIM")],
                                    scenario(T0 + timedelta(days=3), origin="SIM"), adapter, clock, state_path))

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    assert elapsed < 60
    assert buyer.ROUND["attempts"] == buyer.hunt.MAX_ATTEMPTS
    assert buyer.ROUND["goal"]["state"] == "PAUSED"
    assert report["wakeup_count"] >= buyer.hunt.MAX_ATTEMPTS
    assert "paused this goal" in " ".join(msg.text() for _, msg in transport.sent if hasattr(msg, "text"))
    assert not any(type(msg).__name__ in {"RequestPayment", "CommitPayment"} for _, msg in transport.sent)
    db = state.open_state(state_path)
    try:
        assert state.load_goal(db, "goal-1", "buyer-1")["state"] == "PAUSED"
    finally:
        db.close()


def test_restart_recovers_persisted_transaction_phases_without_charge(tmp_path, replay_stack):
    buyer, provider, transport, adapter, clock = replay_stack
    state_path = tmp_path / ".state" / "restart.sqlite3"
    seed_goal(state_path, buyer, deadline=T0 + timedelta(days=1), goal_state="PAUSED")
    db = state.open_state(state_path)
    try:
        for deal_id, phase in (("pending", "pending_approval"), ("submitted", "submitted"),
                               ("paused", "paused"), ("uncertain", "uncertain")):
            state.save_transaction(db, stored_transaction(deal_id, phase))
    finally:
        db.close()

    asyncio.run(run_replay([row(T0 + timedelta(seconds=1))], scenario(T0 + timedelta(minutes=1)),
                           adapter, clock, state_path))

    db = state.open_state(state_path)
    try:
        phases = {deal_id: state.load_transaction(db, deal_id, "buyer-1")["phase"]
                  for deal_id in ("pending", "submitted", "paused", "uncertain")}
    finally:
        db.close()
    assert phases == {"pending": "paused", "submitted": "uncertain", "paused": "paused", "uncertain": "uncertain"}
    assert provider.seen == []
    assert not transport.sent
    assert not any(type(msg).__name__ in {"RequestPayment", "CommitPayment"} for _, msg in transport.sent)


def test_actual_tick_expires_goal_at_virtual_deadline(tmp_path, replay_stack):
    buyer, provider, transport, adapter, clock = replay_stack
    provider.include_bids = False
    state_path = tmp_path / ".state" / "expiry.sqlite3"
    seed_goal(state_path, buyer, deadline=T0 + timedelta(seconds=30))

    report = asyncio.run(run_replay([row(T0 + timedelta(seconds=1))], scenario(T0 + timedelta(minutes=1)),
                                    adapter, clock, state_path))

    assert buyer.ROUND["goal"]["state"] == "EXPIRED"
    assert "goal_expired" in [event["kind"] for event in report["events"]]
    assert "EXPIRED" in " ".join(msg.text() for _, msg in transport.sent if hasattr(msg, "text"))
    assert not any(type(msg).__name__ in {"RequestPayment", "CommitPayment"} for _, msg in transport.sent)


def test_first_observation_after_goal_deadline_expires_before_starting_round(tmp_path, replay_stack):
    buyer, provider, transport, adapter, clock = replay_stack
    state_path = tmp_path / ".state" / "already-expired.sqlite3"
    seed_goal(state_path, buyer, deadline=T0 + timedelta(seconds=30))

    report = asyncio.run(run_replay([row(T0 + timedelta(seconds=31))],
                                    scenario(T0 + timedelta(seconds=40)), adapter, clock, state_path))

    assert buyer.ROUND["goal"]["state"] == "EXPIRED"
    assert provider.seen == []
    assert not any(isinstance(msg, buyer.common.BidRequest) for _, msg in transport.sent)
    assert "goal_expired" in [event["kind"] for event in report["events"]]
    db = state.open_state(state_path)
    try:
        assert state.load_goal(db, "goal-1", "buyer-1")["state"] == "EXPIRED"
    finally:
        db.close()


def test_sequential_adapters_restore_mutable_buyer_runtime_globals(tmp_path, buyer, monkeypatch):
    from common import BidReply, AdviceReply, address

    buyer.APPROVALS["existing"] = {"phase": "pending_approval"}
    buyer.USED.add("existing-mandate")
    buyer.WEB_OUTBOX.append("existing web reply")
    initial_round = copy.deepcopy(buyer.ROUND)
    initial_approvals = copy.deepcopy(buyer.APPROVALS)
    initial_used = set(buyer.USED)
    initial_outbox = list(buyer.WEB_OUTBOX)
    initial_diag = copy.deepcopy(buyer.CHAT_DIAG.__dict__)

    for index in (1, 2):
        checker, provider, transport = FakeChecker(), FakeProvider(bids=False), SimTransport()
        provider.sender, provider.message, provider.advice_message = address("seller_1"), BidReply, AdviceReply
        clock = SimClock()
        adapter = ReplayMarketAdapter(clock=clock, checker=checker, provider=provider, transport=transport)
        state_path = tmp_path / ".state" / f"sequential-{index}.sqlite3"
        seed_goal(state_path, buyer, deadline=T0 + timedelta(seconds=30))
        with adapter:
            asyncio.run(run_replay([row(T0 + timedelta(seconds=1))], scenario(T0 + timedelta(minutes=1)),
                                   adapter, clock, state_path))
        assert buyer.ROUND == initial_round
        assert buyer.APPROVALS == initial_approvals
        assert buyer.USED == initial_used
        assert buyer.WEB_OUTBOX == initial_outbox
        assert buyer.CHAT_DIAG.__dict__ == initial_diag


def test_reserved_web_owner_is_rejected_before_state_or_transport_changes(tmp_path, replay_stack):
    buyer, provider, transport, adapter, clock = replay_stack
    state_path = tmp_path / ".state" / "web-owner.sqlite3"
    seed_goal(state_path, buyer, deadline=T0 + timedelta(days=1), buyer_id="web")

    with pytest.raises(replay.ReplayError, match="SIM dispatch failed"):
        asyncio.run(run_replay([row(T0 + timedelta(seconds=1))],
                               scenario(T0 + timedelta(minutes=1), buyer_id="web"), adapter, clock, state_path))

    assert not transport.sent
    assert provider.seen == []
    db = state.open_state(state_path)
    try:
        assert state.load_goal(db, "goal-1", "web")["state"] == "ACTIVE"
    finally:
        db.close()


def test_replay_context_blocks_outbound_socket_and_dns(replay_stack):
    _, _, _, _, _ = replay_stack

    with pytest.raises(replay.ReplayError, match="outbound network is disabled"):
        socket.create_connection(("203.0.113.9", 443), timeout=0.01)
    with pytest.raises(replay.ReplayError, match="outbound network is disabled"):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(replay.ReplayError, match="outbound network is disabled"):
        socket.socket.sendto(object(), b"SIM probe", ("203.0.113.9", 443))
    if hasattr(socket.socket, "sendmsg"):
        with pytest.raises(replay.ReplayError, match="outbound network is disabled"):
            socket.socket.sendmsg(object(), [b"SIM probe"], address=("203.0.113.9", 443))


def test_replay_rejects_unmarked_provider(buyer):
    class UnmarkedProvider:
        def bids(self, *args):
            return []

        def review(self, *args):
            return None

    with pytest.raises(replay.ReplayError, match="explicit SimProvider"):
        ReplayMarketAdapter(clock=SimClock(), checker=FakeChecker(), provider=UnmarkedProvider(),
                            transport=SimTransport())

\n