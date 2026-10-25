"""Any market buyerId (not a hard-coded default) drives the hunt and the approval hand-off."""
from __future__ import annotations

import asyncio
import importlib
import re
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

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
    buyer.LAST_GOAL_POLL = float("-inf")
    buyer.MARKET_REFEREE.open_goals.return_value = [{**_open_goal_row(buyer), "buyer_id": "vidyut"}, _open_goal_row(buyer)]
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    assert asyncio.run(buyer.adopt_open_goal(Context())) is True
    assert buyer.ROUND["market_buyer_id"] == BID and buyer.ROUND["owner"] is None
    need_call = buyer.MARKET_REFEREE.post_need.call_args
    assert need_call.kwargs == {"buyer_id": BID, "goal_id": "goal-web1"}
    assert not buyer.MARKET_BUYER.post_need.called and not buyer.MARKET_BUYER.post_goal.called
    assert asyncio.run(buyer.adopt_open_goal(Context())) is False  # a round is in progress; the goal is handled


def _web_approval(buyer, monkeypatch, issue_error=None, voice=None):
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
        if voice is not None:
            return voice
        return VoiceResult(True, None, record={"id": "va-1", "channel": "phone", "result": "approved",
                                               "mandate_hash": mandate["hash"], "mandate_id": mandate["id"]})

    monkeypatch.setattr(checkout, "approve_offer", fake_approve)
    save = buyer.buyer_state.save_transaction  # the fake call record is not a full VoiceApproval row
    monkeypatch.setattr(buyer.buyer_state, "save_transaction",
                        lambda db, tx: save(db, tx) if not tx.get("voice_approval") else (
                            save(db, {**tx, "voice_approval": None}) if tx.get("phase") != "approved" else None))
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
    assert referee.record_approval.call_args.kwargs == {"mandate_hash": mandate_hash, "method": "voice_code", "approved_by": BID,
                                                        "voice_approval_id": "va-1"}
    assert len(used) == 1 and used[0].to == "+14155550111"
    assert not buyer.MARKET_BUYER.mock_calls
    assert not any(isinstance(m, buyer.ChatMessage) for _to, m in ctx.sent)  # no owner chat message at all


def test_web_buyer_fails_closed_when_the_code_cannot_be_issued(runtime, monkeypatch):
    buyer, _db = runtime
    ctx, used, _make = _web_approval(buyer, monkeypatch, issue_error=RuntimeError("down"))
    assert not buyer.MARKET_REFEREE.record_approval.called
    assert not any(not isinstance(m, buyer.ChatMessage) for _to, m in ctx.sent)  # no OrderPlaced either


def _fake_stripe(monkeypatch, result=None, error=None):
    import urllib.request
    from pay import merchant_sim
    calls = []

    def charge(self, **kw):
        calls.append(kw)
        if error:
            raise error
        return result if result is not None else {"id": "pi_test_1", "status": "succeeded"}

    monkeypatch.setattr(merchant_sim.StripeTestCharger, "charge", charge)
    monkeypatch.setattr(urllib.request, "urlopen", Mock(side_effect=AssertionError("network call")))
    return calls


def _orders(buyer, ctx):
    return [(to, m) for to, m in ctx.sent if isinstance(m, buyer.common.OrderPlaced)]


def test_web_approval_pays_in_stripe_test_mode_then_sends_order_and_frees_the_next_web_goal(runtime, monkeypatch, caplog):
    import json
    buyer, db = runtime
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    calls = _fake_stripe(monkeypatch)
    with caplog.at_level("INFO", logger="buyer_agent"):
        ctx, _used, _make = _web_approval(buyer, monkeypatch)
    mandate = buyer.ROUND["mandate"]
    assert len(calls) == 1
    assert calls[0]["amount_cents"] == buyer.payment._cents(mandate["amount"])
    assert calls[0]["idempotency_key"] == "mandate:" + mandate["hash"]
    assert calls[0]["metadata"]["mandate_hash"] == mandate["hash"] and calls[0]["currency"] == "USD"
    assert buyer.MARKET_REFEREE.record_payment.call_args.kwargs == {
        "mandate_hash": mandate["hash"], "payment_ref": "pi_test_1", "amount": mandate["amount"], "mode": "stripe_test"}
    (to, placed), = _orders(buyer, ctx)
    assert to == buyer.common.address(buyer.ROUND["bids"][0]["supplier_id"])
    assert json.loads(placed.order_json)["payment_ref"] == "pi_test_1"
    assert _stored_phases(db) == ["settled"]
    assert buyer.ROUND["phase"] == "done" and not buyer.ROUND.get("pending_hold")
    assert f"web buyer {BID}: paid deal" in caplog.text and "pi_test_1 (Stripe test mode)" in caplog.text
    assert "424242" not in caplog.text and "sk_test_x" not in caplog.text and "+1415" not in caplog.text
    assert not buyer.MARKET_BUYER.mock_calls
    assert _next_web_goal_adopted(buyer, db) is True
    assert buyer.MARKET_REFEREE.post_need.call_args.kwargs["goal_id"] == "goal-web2"


@pytest.mark.parametrize("key", [None, "", "sk_live_x", "rk_test_x"])
def test_web_approval_without_a_test_key_uses_a_labelled_sim_stub_and_never_the_network(runtime, monkeypatch, caplog, key):
    buyer, db = runtime
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    if key is not None:
        monkeypatch.setenv("STRIPE_SECRET_KEY", key)
    calls = _fake_stripe(monkeypatch)
    with caplog.at_level("INFO", logger="buyer_agent"):
        ctx, _used, _make = _web_approval(buyer, monkeypatch)
    assert not calls
    kw = buyer.MARKET_REFEREE.record_payment.call_args.kwargs
    assert kw["mode"] == "sim" and kw["payment_ref"].startswith("ch_sim_")
    assert len(_orders(buyer, ctx)) == 1 and _stored_phases(db) == ["settled"]
    assert "SIM stub, no money moved" in caplog.text
    assert not key or key not in caplog.text


@pytest.mark.parametrize("kind", ["denied", "paused"])
def test_web_denied_or_unanswered_call_never_charges_or_orders(runtime, monkeypatch, kind):
    buyer, _db = runtime
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    calls = _fake_stripe(monkeypatch)
    ctx, _used, _make = _web_approval(buyer, monkeypatch, voice=_voice(kind))
    assert not calls and not buyer.MARKET_REFEREE.record_payment.called and not _orders(buyer, ctx)


@pytest.mark.parametrize("kw", [{"error": RuntimeError("card_declined")},
                                {"result": {"id": "pi_x", "status": "requires_action"}},
                                {"result": {"id": "evil_1", "status": "succeeded"}}])
def test_web_failed_stripe_charge_sends_no_order_and_releases_the_round(runtime, monkeypatch, kw):
    buyer, db = runtime
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    calls = _fake_stripe(monkeypatch, **kw)
    ctx, _used, _make = _web_approval(buyer, monkeypatch)
    assert len(calls) == 1 and not _orders(buyer, ctx) and not buyer.MARKET_REFEREE.record_payment.called
    assert _stored_phases(db) == ["expired"]
    assert buyer.ROUND["phase"] == "done" and not buyer.ROUND.get("pending_hold") and buyer.ROUND.get("transaction") is None


def test_web_market_payment_row_failure_does_not_undo_the_charge_or_block_the_order(runtime, monkeypatch, caplog):
    buyer, db = runtime
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    _fake_stripe(monkeypatch)
    buyer.MARKET_REFEREE.record_payment.side_effect = buyer.MarketBridgeError("down")
    with caplog.at_level("WARNING", logger="buyer_agent"):
        ctx, _used, _make = _web_approval(buyer, monkeypatch)
    assert len(_orders(buyer, ctx)) == 1 and _stored_phases(db) == ["settled"]
    assert "market row failed" in caplog.text


def _adopt(buyer):
    buyer.LAST_GOAL_POLL = float("-inf")
    return asyncio.run(buyer.adopt_open_goal(Context()))


def test_handled_goal_survives_restart_and_is_not_hunted_again(runtime):
    buyer, db = runtime
    buyer.MARKET_REFEREE.open_goals.return_value = [_open_goal_row(buyer)]
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    assert _adopt(buyer) is True
    buyer.ROUND.clear()  # a restart: no in-memory round, same DB
    buyer.MARKET_REFEREE.post_need.reset_mock()
    assert _adopt(buyer) is False
    assert not buyer.MARKET_REFEREE.post_need.called


def test_past_deadline_goal_is_skipped_and_a_later_one_adopted(runtime):
    buyer, db = runtime
    old = {**_open_goal_row(buyer), "id": "goal-old", "deadline": "2000-01-01T00:00:00Z"}
    buyer.MARKET_REFEREE.open_goals.return_value = [old, _open_goal_row(buyer)]
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    assert _adopt(buyer) is True
    assert buyer.MARKET_REFEREE.post_need.call_args.kwargs["goal_id"] == "goal-web1"


def test_goal_with_an_existing_transaction_is_skipped(runtime):
    buyer, db = runtime
    buyer.MARKET_REFEREE.open_goals.return_value = [_open_goal_row(buyer)]
    import json as _json
    db.execute("INSERT INTO transactions (deal_id, buyer_id, phase, payload) VALUES ('d1', ?, 'approved', ?)",
               (BID, _json.dumps({"goal_id": "goal-web1"})))
    db.commit()
    assert _adopt(buyer) is False
    assert not buyer.MARKET_REFEREE.post_need.called


def test_goal_poll_is_rate_limited(runtime, monkeypatch):
    buyer, db = runtime
    buyer.MARKET_REFEREE.open_goals.return_value = []
    clock = [1000.0]
    monkeypatch.setattr(buyer.time, "monotonic", lambda: clock[0])
    buyer.LAST_GOAL_POLL = float("-inf")
    asyncio.run(buyer.adopt_open_goal(Context()))
    clock[0] += 3
    asyncio.run(buyer.adopt_open_goal(Context()))
    assert buyer.MARKET_REFEREE.open_goals.call_count == 1
    clock[0] += 6
    asyncio.run(buyer.adopt_open_goal(Context()))
    assert buyer.MARKET_REFEREE.open_goals.call_count == 2


def _restart_then_adopt_next(buyer, db, monkeypatch):
    buyer.ROUND.clear()  # a restart: no in-memory round, same DB
    monkeypatch.setattr(buyer, "state_db", lambda: db)
    monkeypatch.setattr(buyer, "nonce_store", lambda: Mock(recover_submitted_attempts=lambda: 0))
    buyer.recover_buyer_state()
    buyer.MARKET_REFEREE.open_goals.return_value = [{**_open_goal_row(buyer), "id": "goal-web2"}]
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    assert _adopt(buyer) is True
    assert not buyer.ROUND.get("pending_hold")
    assert buyer.MARKET_REFEREE.post_need.call_args.kwargs["goal_id"] == "goal-web2"


def _voice(kind):
    from pay.voice_cartesia import VoiceResult
    if kind == "paused":
        return VoiceResult(False, "no_answer", record=None)
    return VoiceResult(False, "denied", record={"id": "va-2", "channel": "phone", "result": "denied"})


def test_web_approved_round_survives_restart_without_wedging(runtime, monkeypatch):
    buyer, db = runtime
    _web_approval(buyer, monkeypatch)
    _restart_then_adopt_next(buyer, db, monkeypatch)


def test_web_paused_round_survives_restart_without_wedging(runtime, monkeypatch):
    buyer, db = runtime
    _web_approval(buyer, monkeypatch, voice=_voice("paused"))
    _restart_then_adopt_next(buyer, db, monkeypatch)


def test_web_denied_round_survives_restart_without_wedging(runtime, monkeypatch):
    buyer, db = runtime
    _web_approval(buyer, monkeypatch, voice=_voice("denied"))
    _restart_then_adopt_next(buyer, db, monkeypatch)


def test_old_web_row_without_owner_is_skipped_by_recovery(runtime, monkeypatch):
    import json as _json
    buyer, db = runtime
    db.execute("INSERT INTO transactions (deal_id, buyer_id, phase, payload) VALUES ('d-old', 'b_x', 'approved', ?)",
               (_json.dumps({"deal_id": "d-old", "buyer_id": "b_x", "goal_id": "g-old", "deal": {}}),))
    db.commit()
    monkeypatch.setattr(buyer, "state_db", lambda: db)
    monkeypatch.setattr(buyer, "nonce_store", lambda: Mock(recover_submitted_attempts=lambda: 0))
    buyer.ROUND.clear()
    buyer.recover_buyer_state()
    assert not buyer.ROUND.get("pending_hold")


def test_chat_goal_during_web_round_does_not_wipe_it(runtime):
    buyer, _db = runtime
    buyer.MARKET_REFEREE.open_goals.return_value = [_open_goal_row(buyer)]
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    assert _adopt(buyer) is True
    buyer.ROUND["phase"] = "waiting"
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, "owner", "a new GPU under $800 by Friday"))
    assert buyer.ROUND["goal"]["id"] == "goal-web1" and buyer.ROUND["owner"] is None
    assert buyer.ROUND["phase"] == "waiting"


def test_failed_start_round_leaves_goal_unmarked_until_the_third_failure(runtime, monkeypatch):
    buyer, db = runtime
    buyer.MARKET_REFEREE.open_goals.return_value = [_open_goal_row(buyer)]

    async def boom(ctx, need=None):
        return False

    monkeypatch.setattr(buyer, "start_round", boom)
    for _ in range(2):
        assert _adopt(buyer) is False
        assert not buyer.buyer_state.goal_handled(db, "goal-web1")
    assert _adopt(buyer) is False
    assert buyer.buyer_state.goal_handled(db, "goal-web1")


def _two_goal_rows(buyer):
    return [_open_goal_row(buyer), {**_open_goal_row(buyer), "id": "goal-web2"}]


def test_one_always_refused_goal_is_given_up_after_three_tries_and_the_next_goal_is_adopted(runtime):
    buyer, db = runtime
    referee = buyer.MARKET_REFEREE
    referee.open_goals.return_value = _two_goal_rows(buyer)
    referee.round_status.return_value = {"state": "open"}

    def post_need(need, *, buyer_id, goal_id):
        if goal_id == "goal-web1":
            raise MarketBridgeError("refused")

    referee.post_need.side_effect = post_need
    for _ in range(3):
        assert _adopt(buyer) is False
    assert [c.kwargs["goal_id"] for c in referee.post_need.call_args_list] == ["goal-web1"] * 3
    assert buyer.buyer_state.goal_handled(db, "goal-web1")
    assert _adopt(buyer) is True
    assert referee.post_need.call_args.kwargs["goal_id"] == "goal-web2"


def test_goal_with_nothing_left_to_buy_is_marked_handled_at_once(runtime, monkeypatch):
    buyer, db = runtime
    buyer.MARKET_REFEREE.open_goals.return_value = _two_goal_rows(buyer)
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    real = buyer.need_from_goal
    monkeypatch.setattr(buyer, "need_from_goal", lambda g: {**real(g), "items": []} if g["id"] == "goal-web1" else real(g))
    assert _adopt(buyer) is False
    assert buyer.buyer_state.goal_handled(db, "goal-web1") and not buyer.MARKET_REFEREE.post_need.called
    assert _adopt(buyer) is True
    assert buyer.MARKET_REFEREE.post_need.call_args.kwargs["goal_id"] == "goal-web2"


def _stored_phases(db):
    return [r[0] for r in db.execute("SELECT phase FROM transactions")]


def _next_web_goal_adopted(buyer, db):
    buyer.LAST_GOAL_POLL = float("-inf")
    buyer.buyer_state.mark_goal_handled(db, "goal-web1", BID)
    buyer.MARKET_REFEREE.open_goals.return_value = [_open_goal_row(buyer), {**_open_goal_row(buyer), "id": "goal-web2"}]
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    return asyncio.run(buyer.adopt_open_goal(Context()))


def test_web_referee_record_failure_frees_the_agent(runtime, monkeypatch, caplog):
    buyer, db = runtime
    buyer.MARKET_REFEREE.record_approval.side_effect = buyer.MarketBridgeError("down")
    with caplog.at_level("WARNING"):
        _web_approval(buyer, monkeypatch)
    assert buyer.ROUND["phase"] == "done" and not buyer.ROUND.get("pending_hold")
    assert buyer.ROUND.get("transaction") is None
    assert _stored_phases(db) == ["expired"]
    assert "424242" not in caplog.text and "+1415" not in caplog.text
    assert _next_web_goal_adopted(buyer, db) is True
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, "owner", "a new GPU under $800 by Friday"))
    texts = " ".join(getattr(m.content[0], "text", "") for _to, m in ctx.sent if hasattr(m, "content"))
    assert "A buyer session is active" not in texts and "held" not in texts


def test_web_buyer_without_phone_frees_the_agent(runtime, monkeypatch):
    buyer, db = runtime
    from buyer import checkout
    called = []
    monkeypatch.setattr(checkout, "approve_offer", lambda *a, **k: called.append(1))
    ready_for_requote(buyer)
    buyer.ROUND.update(owner=None, market_buyer_id=BID)
    buyer.ROUND["goal"]["market_buyer_id"] = BID
    referee = buyer.MARKET_REFEREE
    referee.buyer_contact.return_value = {"display_name": "Web"}
    referee.create_mandate.side_effect = lambda mandate, **_k: {"mandate_hash": mandate["hash"]}
    monkeypatch.setattr(buyer, "_approval_service", lambda: object())
    monkeypatch.setattr("pay.voice_cartesia.load_env", lambda *a, **k: {})
    asyncio.run(buyer._auto_web_approval(Context(), 1))
    assert not called
    assert buyer.ROUND["phase"] == "done" and buyer.ROUND.get("transaction") is None
    assert not buyer.ROUND.get("pending_hold")
    assert _stored_phases(db) == ["expired"]
    assert _next_web_goal_adopted(buyer, db) is True


# ---- #449 item 1: approval calls are limited to an allowlist during the beta ----
def _beta_env(monkeypatch, allow="+14155550999"):
    monkeypatch.setattr("pay.voice_cartesia.load_env", lambda *a, **k: {"APPROVAL_CALL_ALLOWLIST": allow})


def test_profile_phone_off_the_allowlist_builds_no_client_and_logs_no_digits(runtime, monkeypatch, caplog):
    buyer, _db = runtime
    monkeypatch.setattr(buyer, "MARKET_BUYER_ID", "")
    buyer.MARKET_REFEREE.buyer_contact.return_value = {"display_name": "Asha", "phone": "+14155550111"}
    _beta_env(monkeypatch)
    with patch("pay.voice_cartesia.CartesiaClient.from_env", side_effect=_Client) as make, caplog.at_level("INFO"):
        assert buyer._approval_call(BID) == (None, "beta_limited", "Asha")
    assert not make.called
    assert BID in caplog.text and not re.search(r"\d{7,}", caplog.text.replace(BID, ""))
    _beta_env(monkeypatch, "+14155550111")
    with patch("pay.voice_cartesia.CartesiaClient.from_env", side_effect=_Client):
        assert buyer._approval_call(BID)[1] == ""


def test_web_buyer_off_the_allowlist_gets_no_call_and_frees_the_agent(runtime, monkeypatch, caplog):
    buyer, db = runtime
    from buyer import checkout
    called = []
    monkeypatch.setattr(checkout, "approve_offer", lambda *a, **k: called.append(1))
    ready_for_requote(buyer)
    buyer.ROUND.update(owner=None, market_buyer_id=BID)
    buyer.ROUND["goal"]["market_buyer_id"] = BID
    referee = buyer.MARKET_REFEREE
    referee.buyer_contact.return_value = {"display_name": "Web", "phone": "+14155550111"}
    referee.create_mandate.side_effect = lambda mandate, **_k: {"mandate_hash": mandate["hash"]}
    monkeypatch.setattr(buyer, "_approval_service", lambda: object())
    _beta_env(monkeypatch)
    with patch("pay.voice_cartesia.CartesiaClient.from_env", side_effect=_Client) as make, caplog.at_level("INFO"):
        asyncio.run(buyer._auto_web_approval(Context(), 1))
    assert not called and not make.called
    assert buyer.ROUND["phase"] == "done" and buyer.ROUND.get("transaction") is None and not buyer.ROUND.get("pending_hold")
    assert _stored_phases(db) == ["expired"]
    assert not re.search(r"\d{7,}", caplog.text.replace(BID, "")) and "4155550111" not in caplog.text
    assert _next_web_goal_adopted(buyer, db) is True


def test_chat_owner_off_the_allowlist_is_told_the_beta_limit(runtime, monkeypatch):
    buyer, db = runtime
    ready_for_requote(buyer)
    buyer.ROUND["market_buyer_id"] = BID
    buyer.MARKET_REFEREE.buyer_contact.return_value = {"display_name": "Asha", "phone": "+14155550111"}
    buyer.MARKET_REFEREE.create_mandate.side_effect = lambda mandate, **_k: {"mandate_hash": mandate["hash"]}
    monkeypatch.setattr(buyer, "MARKET_BUYER_ID", "")
    monkeypatch.setattr(buyer, "_approval_service", lambda: object())
    _beta_env(monkeypatch)
    ctx = Context()
    with patch("pay.voice_cartesia.CartesiaClient.from_env", side_effect=_Client) as make:
        transaction = buyer._create_pending_transaction(1)
        asyncio.run(buyer._run_owner_approval(ctx, 1, buyer.ROUND["owner"], transaction))
    texts = " ".join(getattr(m.content[0], "text", "") for _to, m in ctx.sent if hasattr(m, "content"))
    assert "limited during the beta" in texts and "Nothing was paid" in texts and "4155550111" not in texts
    assert not make.called and buyer.ROUND["phase"] == "done" and buyer.ROUND.get("transaction") is None
    assert _stored_phases(db) == ["expired"]


def _real_service(buyer, monkeypatch):
    from buyer import state
    from pay.approval import ApprovalService
    from pay.replay import NonceStore
    service = ApprovalService("throwaway-test-secret-0123456789", store=NonceStore(str(state.DEFAULT_DB_PATH)))
    monkeypatch.setattr(buyer, "_approval_service", lambda: service)


class _Limited:
    approval_call_to = "+14155550111"

    def __init__(self):
        self.attempts = []

    def create_call(self, to, variables):
        from pay.voice_cartesia import CallLimited
        self.attempts.append(to)
        raise CallLimited("rate_limited")


def test_a_rate_limited_dial_is_final_and_not_retried_on_the_web_path(runtime, monkeypatch):
    buyer, db = runtime
    limited = _Limited()
    monkeypatch.setattr(buyer, "_approval_call", lambda _b: (limited, "", "Web"))
    _real_service(buyer, monkeypatch)
    ready_for_requote(buyer)
    buyer.ROUND.update(owner=None, market_buyer_id=BID)
    buyer.ROUND["goal"]["market_buyer_id"] = BID
    buyer.MARKET_REFEREE.create_mandate.side_effect = lambda mandate, **_k: {"mandate_hash": mandate["hash"]}
    asyncio.run(buyer._auto_web_approval(Context(), 1))
    assert len(limited.attempts) == 1
    assert not buyer.MARKET_REFEREE.record_approval.called
    assert buyer.ROUND["phase"] == "done" and _stored_phases(db) == ["expired"]


def test_a_rate_limited_dial_tells_the_chat_owner_about_the_beta_limit(runtime, monkeypatch):
    buyer, db = runtime
    limited = _Limited()
    monkeypatch.setattr(buyer, "_approval_call", lambda _b: (limited, "", "Asha"))
    _real_service(buyer, monkeypatch)
    ready_for_requote(buyer)
    buyer.ROUND["market_buyer_id"] = BID
    buyer.MARKET_REFEREE.create_mandate.side_effect = lambda mandate, **_k: {"mandate_hash": mandate["hash"]}
    ctx = Context()
    transaction = buyer._create_pending_transaction(1)
    asyncio.run(buyer._run_owner_approval(ctx, 1, buyer.ROUND["owner"], transaction))
    texts = " ".join(getattr(m.content[0], "text", "") for _to, m in ctx.sent if hasattr(m, "content"))
    assert len(limited.attempts) == 1 and "limited during the beta" in texts and "Nothing was paid" in texts
    assert not buyer.MARKET_REFEREE.record_approval.called

STRANGER = "agent1qstranger"
GOAL_TEXT = "a new RTX 4070 Super under $800 by Friday"  # a named card: a bare GPU gets a question (RT-15)


@pytest.fixture(autouse=True)
def _forget_strangers():
    mod = sys.modules.get("buyer_agent")
    if mod is not None and hasattr(mod, "STRANGER_TOLD"):
        mod.STRANGER_TOLD.clear()


def _texts(ctx):
    return " ".join(getattr(m.content[0], "text", "") for _to, m in ctx.sent if hasattr(m, "content"))


def test_non_owner_chat_goal_gets_one_friendly_reply_and_touches_nothing(runtime):
    """#449 item 2: a stranger's complete goal never posts a goal or need, opens a round or changes ROUND."""
    buyer, db = runtime
    before = dict(buyer.ROUND)
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, STRANGER, GOAL_TEXT))
    assert "fishmarket.dev/start" in _texts(ctx) and "owner only" in _texts(ctx)
    assert len(ctx.sent) == 1
    assert not buyer.MARKET_BUYER.mock_calls and not buyer.MARKET_REFEREE.mock_calls
    assert buyer.ROUND == before == {}
    assert db.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0


def test_non_owner_is_refused_even_while_a_round_or_hold_is_live_and_never_told_it_is_busy(runtime):
    buyer, _db = runtime
    buyer.ROUND.update(owner="owner", phase="bidding", pending_hold=True, goal={"state": "HUNTING"})
    before = dict(buyer.ROUND)
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, STRANGER, GOAL_TEXT))
    assert "fishmarket.dev/start" in _texts(ctx) and "session is active" not in _texts(ctx)
    assert buyer.ROUND == before and not buyer.MARKET_BUYER.mock_calls and not buyer.MARKET_REFEREE.mock_calls


def test_non_owner_chat_is_acknowledged_then_refused_by_on_chat(runtime):
    buyer, _db = runtime
    ctx = Context()
    msg = buyer.ChatMessage(content=[buyer.TextContent(type="text", text=GOAL_TEXT)])
    asyncio.run(buyer.on_chat(ctx, STRANGER, msg))
    assert any(isinstance(m, buyer.ChatAcknowledgement) for _to, m in ctx.sent)
    assert "fishmarket.dev/start" in _texts(ctx) and not buyer.ROUND


def test_unpinned_owner_env_refuses_every_chat_sender_but_not_the_web_chat(runtime, monkeypatch):
    buyer, _db = runtime
    monkeypatch.delenv("MARKET_BUYER_OWNER_SENDER")
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, "owner", GOAL_TEXT))
    assert "fishmarket.dev/start" in _texts(ctx) and not buyer.ROUND
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    asyncio.run(buyer.handle_text(Context(), buyer.WEB, GOAL_TEXT))
    assert buyer.ROUND["owner"] == buyer.WEB  # the local web chat path is exempt


def test_owner_chat_goal_still_starts_a_round(runtime):
    buyer, _db = runtime
    buyer.MARKET_REFEREE.round_status.return_value = {"state": "open"}
    buyer.MARKET_BUYER_ID = BID
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, "owner", GOAL_TEXT))
    assert buyer.ROUND["owner"] == "owner" and buyer.ROUND["phase"] == "bidding"
    assert "fishmarket.dev/start" not in _texts(ctx)


def test_web_goal_is_adopted_at_once_right_after_a_refused_stranger_goal(runtime):
    buyer, db = runtime
    asyncio.run(buyer.handle_text(Context(), STRANGER, GOAL_TEXT))
    assert not buyer.ROUND  # the stranger never took the round
    assert _next_web_goal_adopted(buyer, db) is True
    assert buyer.MARKET_REFEREE.post_need.call_args.kwargs["goal_id"] == "goal-web2"


def test_unconfigured_owner_approval_refusal_is_terminal_and_frees_the_next_web_goal(runtime, monkeypatch):
    """#449 item 2: the refusal used to leave phase 'decided', which round_finished() never counts as finished."""
    buyer, db = runtime
    monkeypatch.delenv("MARKET_BUYER_OWNER_SENDER")
    ready_for_requote(buyer)
    asyncio.run(buyer.on_requote(Context(), dict(buyer.ROUND["bids"][0])))
    assert buyer.ROUND["phase"] == "done" and buyer.round_finished() is True
    assert not buyer.ROUND.get("transaction") and not buyer.ROUND.get("pending_hold")
    assert _next_web_goal_adopted(buyer, db) is True
    assert buyer.MARKET_REFEREE.post_need.call_args.kwargs["goal_id"] == "goal-web2"


def test_never_joined_store_refusal_at_requote_is_terminal_and_frees_the_next_web_goal(runtime, monkeypatch):
    buyer, db = runtime
    ready_for_requote(buyer)
    monkeypatch.setattr(buyer.not_partners, "orderable", lambda _bid: False)
    asyncio.run(buyer.on_requote(Context(), dict(buyer.ROUND["bids"][0])))
    assert buyer.ROUND["phase"] == "done" and buyer.round_finished() is True
    assert not buyer.MARKET_BUYER.create_mandate.called
    assert _next_web_goal_adopted(buyer, db) is True


def test_a_stranger_is_answered_once_not_in_a_loop(runtime):
    buyer, _db = runtime
    ctx = Context()
    for _ in range(3):
        asyncio.run(buyer.handle_text(ctx, STRANGER, GOAL_TEXT))
    assert len(ctx.sent) == 1 and not buyer.ROUND
