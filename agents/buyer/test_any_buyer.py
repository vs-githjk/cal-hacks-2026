"""Any market buyerId (not a hard-coded default) drives the hunt and the approval hand-off."""
from __future__ import annotations

import asyncio
import importlib
import re
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_runtime_checkout import (Context, NOW, ready_for_requote, runtime)  # noqa: F401
from goal import parse_goal
from market_bridge import MarketBridgeError

BID = "b_test1234"
ROOT = Path(__file__).resolve().parents[1]


def _arm(buyer):
    goal, _ = parse_goal("a new GPU under $800 by Friday", "owner", now=NOW)
    goal["market_buyer_id"] = BID
    buyer.ROUND.update(goal=goal, owner="owner")
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    return goal


def test_hunt_and_handoff_carry_the_fresh_buyer_id(runtime, monkeypatch):
    buyer, _db = runtime
    monkeypatch.setattr(buyer, "MARKET_BUYER_ID", "")
    _arm(buyer)
    assert asyncio.run(buyer.start_round(Context(), None)) is not False
    assert buyer.ROUND["market_buyer_id"] == BID
    assert buyer.MARKET_BUYER.post_goal.call_args.kwargs["buyer_id"] == BID
    assert buyer.MARKET_BUYER.post_goal.call_args.args[0]["buyer_id"] == BID
    need_call = buyer.MARKET_BUYER.post_need.call_args
    assert need_call.kwargs["buyer_id"] == BID and need_call.args[0]["buyer_id"] == BID

    buyer.MARKET_BUYER.reset_mock()
    ready_for_requote(buyer)
    buyer.ROUND.update(market_buyer_id=BID)
    buyer.MARKET_BUYER.create_mandate.side_effect = lambda mandate, **_k: {
        "mandate_hash": mandate["hash"], "reservation_matches": True, "within_allowance": False, "retired": False}
    asyncio.run(buyer.on_requote(Context(), dict(buyer.ROUND["bids"][0])))
    tx = buyer.ROUND["transaction"]
    assert tx["buyer_id"] == BID
    assert buyer.MARKET_BUYER.create_mandate.call_args.kwargs["buyer_id"] == BID
    assert tx["mandate"]["buyer_id"] == BID
    calls = repr(buyer.MARKET_BUYER.mock_calls) + repr(tx)
    assert "vidyut" not in calls.lower()


def test_start_round_fails_closed_without_any_buyer_id(runtime, monkeypatch):
    buyer, _db = runtime
    monkeypatch.setattr(buyer, "MARKET_BUYER_ID", "")
    goal = _arm(buyer)
    goal.pop("market_buyer_id")
    assert asyncio.run(buyer.start_round(Context(), None)) is False
    assert not buyer.MARKET_BUYER.post_goal.called


class _Client:
    def __init__(self, env):
        self.to = env["APPROVAL_CALL_TO"]


def _call(buyer, monkeypatch, buyer_id, profile, default=""):
    monkeypatch.setattr(buyer, "MARKET_BUYER_ID", default)
    buyer.MARKET_REFEREE.buyer_contact.return_value = profile
    monkeypatch.setattr("pay.voice_cartesia.load_env", lambda *a, **k: {"APPROVAL_CALL_TO": "+14155550999"})
    with patch("pay.voice_cartesia.CartesiaClient.from_env", side_effect=_Client):
        return buyer._approval_call(buyer_id)


def test_approval_dials_only_the_buyers_own_profile_phone(runtime, monkeypatch):
    buyer, _db = runtime
    client, why, name = _call(buyer, monkeypatch, BID, {"display_name": "Asha", "phone": "+14155550111"})
    assert client.to == "+14155550111" and why == "" and name == "Asha"
    assert _call(buyer, monkeypatch, BID, {"display_name": "Asha", "phone": None})[:2] == (None, "not_configured")
    assert _call(buyer, monkeypatch, BID, None)[:2] == (None, "not_configured")
    client, _why, name = _call(buyer, monkeypatch, "env_buyer", None, default="env_buyer")
    assert client.to == "+14155550999" and name == "there"


def test_no_phone_refusal_is_logged_without_digits(runtime, monkeypatch, caplog):
    buyer, _db = runtime
    with caplog.at_level("INFO"):
        assert _call(buyer, monkeypatch, BID, {"display_name": "Asha", "phone": None})[:2] == (None, "not_configured")
    assert f"approval call refused for buyer {BID}: no phone on file" in caplog.text
    assert not re.search(r"\d{7,}", caplog.text.replace(BID, ""))


def _run_phone_approval(buyer, monkeypatch, tx, client):
    from buyer import checkout
    from pay.voice_cartesia import VoiceResult
    used = []

    def fake_approve(transaction, cl, service, *, on_code, **kw):
        used.append(cl)
        on_code("424242")
        return VoiceResult(False, "denied")

    monkeypatch.setattr(checkout, "approve_offer", fake_approve)
    send = Mock()

    async def send_private(text):
        send(text)
        return True
    asyncio.run(buyer._phone_approval(tx, send_private, client, object()))
    return send, used


def test_web_buyer_code_never_sent_privately_and_chat_buyer_still_gets_it(runtime, monkeypatch, caplog):
    buyer, _db = runtime
    assert buyer._is_web_buyer("b_x", "owner") and buyer._is_web_buyer("v1", "") and not buyer._is_web_buyer("v1", "agent1q")
    client, _why, _name = _call(buyer, monkeypatch, "b_test1234", {"display_name": "W", "phone": "+14155550111"})
    assert client.to == "+14155550111"
    with caplog.at_level("INFO"):
        send, used = _run_phone_approval(buyer, monkeypatch, {"buyer_id": "b_test1234", "deal_id": "d1",
                                                              "mandate": {"hash": "a" * 64}, "deal": {"owner_sender": "agent1qx"}}, client)
    assert not send.called and used == [client]
    assert "web buyer b_test1234: code shown on /buyer" in caplog.text and "424242" not in caplog.text
    send, _used = _run_phone_approval(buyer, monkeypatch, {"buyer_id": "v1", "deal_id": "d1",
                                                           "mandate": {"hash": "a" * 64}, "deal": {"owner_sender": "agent1qx"}}, client)
    assert any("424242" in c.args[0] for c in send.call_args_list)


def test_market_bridge_buyer_contact_reads_agent_view():
    from market_bridge import BUYER_CONTACT_VIEW, MarketBridge as MB

    def bridge(sql):
        b = MB.__new__(MB)
        b._sql = sql
        return b

    seen = []
    row = {"buyer_id": "b1", "display_name": "Asha", "phone": "+14155550111"}
    ok = bridge(lambda q: seen.append(q) or [row])
    assert ok.buyer_contact("b1") == row
    assert BUYER_CONTACT_VIEW in seen[0]

    def boom(q):
        raise RuntimeError("down")
    assert bridge(boom).buyer_contact("b1") is None
    assert bridge(lambda q: [{**row, "buyer_id": "other"}]).buyer_contact("b1") is None


def test_no_vidyut_default_in_agents(monkeypatch):
    monkeypatch.delenv("MARKET_BUYER_ID", raising=False)
    fake_agent = Mock()
    for d in ("on_message", "on_interval", "on_rest_post", "on_rest_get", "on_event"):
        getattr(fake_agent, d).side_effect = lambda *a, **k: lambda fn: fn
    with patch("uagents.Agent", return_value=fake_agent):
        mod = importlib.reload(importlib.import_module("buyer_agent"))
    assert mod.MARKET_BUYER_ID == ""
    for rel in ("buyer/buyer_agent.py", "buyer/checkout.py", "caller/relay.py"):
        assert not re.search(r"vidyut", (ROOT / rel).read_text(encoding="utf-8"), re.I), rel


def _open_goal_row(buyer):
    goal, _ = parse_goal("a new GPU under $800 by Friday", "owner", now=NOW)
    return {"id": "goal-web1", "buyer_id": BID, "type": "part_by_date", "cap": 800.0, "state": "ACTIVE",
            "deadline": "2099-01-01T00:00:00Z",
            "items": [{k: i.get(k) for k in ("sku_spec", "condition", "variant", "quantity")} for i in goal["items"]]}


def test_open_web_goal_is_adopted_and_need_posted_by_referee_on_that_goal(runtime):
    buyer, _db = runtime
    buyer.HANDLED_GOAL_IDS.clear()
    buyer.MARKET_REFEREE.open_goals.return_value = [{**_open_goal_row(buyer), "buyer_id": "vidyut"}, _open_goal_row(buyer)]
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    assert asyncio.run(buyer.adopt_open_goal(Context())) is True
    assert buyer.ROUND["market_buyer_id"] == BID and buyer.ROUND["owner"] is None
    need_call = buyer.MARKET_REFEREE.post_need.call_args
    assert need_call.kwargs == {"buyer_id": BID, "goal_id": "goal-web1"}
    assert not buyer.MARKET_BUYER.post_need.called and not buyer.MARKET_BUYER.post_goal.called
    assert asyncio.run(buyer.adopt_open_goal(Context())) is False  # a round is in progress; the goal is handled


def _web_approval(buyer, monkeypatch, issue_error=None):
    from buyer import checkout
    from pay.voice_cartesia import VoiceResult
    ready_for_requote(buyer)
    buyer.ROUND.update(owner=None, market_buyer_id=BID)
    buyer.ROUND["goal"]["market_buyer_id"] = BID
    referee = buyer.MARKET_REFEREE
    referee.buyer_contact.return_value = {"display_name": "Web", "phone": "+14155550111"}
    referee.issue_approval_code.side_effect = issue_error
    referee.create_mandate.side_effect = lambda mandate, **_k: {"mandate_hash": mandate["hash"]}
    referee.record_approval.return_value = {"approval_method": "voice_code"}
    monkeypatch.setattr(buyer, "_approval_service", lambda: object())
    monkeypatch.setattr("pay.voice_cartesia.load_env", lambda *a, **k: {})
    used = []

    def fake_approve(transaction, cl, service, *, on_code, **kw):
        used.append(cl)
        on_code("424242")
        mandate = transaction["mandate"]
        return VoiceResult(True, None, record={"id": "va-1", "channel": "phone", "result": "approved",
                                               "mandate_hash": mandate["hash"], "mandate_id": mandate["id"]})

    monkeypatch.setattr(checkout, "approve_offer", fake_approve)
    save = buyer.buyer_state.save_transaction  # the fake call record is not a full VoiceApproval row
    monkeypatch.setattr(buyer.buyer_state, "save_transaction",
                        lambda db, tx: save(db, tx) if not tx.get("voice_approval") else None)
    ctx = Context()
    with patch("pay.voice_cartesia.CartesiaClient.from_env", side_effect=_Client) as make:
        asyncio.run(buyer._auto_web_approval(ctx, 1))
    return ctx, used, make


def test_web_winner_goes_mandate_code_call_approval_on_referee_without_owner_chat(runtime, monkeypatch):
    buyer, _db = runtime
    ctx, used, make = _web_approval(buyer, monkeypatch)
    referee = buyer.MARKET_REFEREE
    mandate_hash = referee.create_mandate.call_args.args[0]["hash"]
    assert referee.create_mandate.call_args.kwargs["buyer_id"] == BID
    referee.issue_approval_code.assert_called_once_with(mandate_hash, "424242")
    assert referee.record_approval.call_args.kwargs == {"mandate_hash": mandate_hash, "method": "voice_code", "approved_by": BID}
    assert len(used) == 1 and used[0].to == "+14155550111"
    assert not buyer.MARKET_BUYER.mock_calls
    assert not ctx.sent  # no owner chat and no OrderPlaced: the web flow stops at approval


def test_web_buyer_fails_closed_when_the_code_cannot_be_issued(runtime, monkeypatch):
    buyer, _db = runtime
    ctx, used, _make = _web_approval(buyer, monkeypatch, issue_error=RuntimeError("down"))
    assert not buyer.MARKET_REFEREE.record_approval.called
    assert not any(not isinstance(m, buyer.ChatMessage) for _to, m in ctx.sent)  # no OrderPlaced either


def test_web_approval_stops_before_payment_and_frees_the_next_web_goal(runtime, monkeypatch, caplog):
    buyer, _db = runtime
    with caplog.at_level("INFO", logger="buyer_agent"):
        ctx, _used, _make = _web_approval(buyer, monkeypatch)
    assert buyer.ROUND["phase"] == "done" and not buyer.ROUND.get("pending_hold")
    assert f"web buyer {BID}: approved; payment leg not wired for web buyers (SIM)" in caplog.text
    assert not ctx.sent
    for name in ("purchase_status", "settle_goal", "record_payment"):
        assert not getattr(buyer.MARKET_BUYER, name).called and not getattr(buyer.MARKET_REFEREE, name).called
    buyer.HANDLED_GOAL_IDS.clear()
    buyer.HANDLED_GOAL_IDS.add("goal-web1")
    buyer.MARKET_REFEREE.open_goals.return_value = [_open_goal_row(buyer), {**_open_goal_row(buyer), "id": "goal-web2"}]
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    assert asyncio.run(buyer.adopt_open_goal(Context())) is True
    assert buyer.MARKET_REFEREE.post_need.call_args.kwargs["goal_id"] == "goal-web2"
