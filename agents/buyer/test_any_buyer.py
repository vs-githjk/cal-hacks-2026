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
    buyer.MARKET_BUYER.buyer_profile.return_value = profile
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
