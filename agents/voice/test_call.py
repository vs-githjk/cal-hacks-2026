"""Done-check from Lane D, against the real pay/ code: the call reads the deal, a wrong code denies,
the right code + "approve" approves once, then can_charge passes. Silence denies and reissues a code."""
from datetime import datetime, timedelta, timezone

import pytest

import common  # noqa: F401
from pay.approval import ApprovalService
from pay.mandate import can_charge
from pay.replay import NonceStore
from voice.call import Call, number_for, register_number

import payment

SELLER = "agent1qseller"
REASON = {"rule_id": "advocate.condition", "summary": "The listing page shows a different condition than the seller claims",
          "source_url": "https://example.com/sim/frankie"}


def setup():
    svc = ApprovalService(secret="test-secret-at-least-16-chars")
    m = payment.make_mandate("order-1", 581.99, SELLER, buyer_id="tony", within_allowance=False)
    return svc, m, Call(svc, m, REASON)


def t(s):
    return datetime.now(timezone.utc) + timedelta(seconds=s)


def test_reads_deal_then_right_code_approves_once_and_can_charge():
    svc, m, call = setup()
    spoken = call.start(t(0))
    assert "five hundred eighty one" in spoken and "approve" in spoken.lower()
    assert call.code not in spoken  # the code is only on the buyer's screen
    assert call.heard(f"{call.code} approve", 0.95, t(2)) == call.script.approved_line and call.done
    assert call.heard(f"{call.code} approve", 0.95, t(3)) == ""  # approves once
    ok = can_charge(m, t(4), deal_id="order-1", amount=581.99, payee=SELLER, store=NonceStore())
    assert ok.ok, ok


def test_wrong_code_denies_and_cannot_charge():
    svc, m, call = setup()
    call.start(t(0))
    reply = call.heard("banana rocket approve", 0.95, t(2))
    assert reply in (call.script.denied_line, "That did not match. Say the two word code from your screen, then say approve")
    assert not call.session.state == "approved"
    assert not can_charge(m, t(3), deal_id="order-1", amount=581.99, payee=SELLER, store=NonceStore()).ok


def test_why_answers_from_advocate_and_spends_no_attempt():
    svc, m, call = setup()
    call.start(t(0))
    answer = call.heard("why not the cheaper one?", 0.9, t(2))
    assert "listing page shows a different condition" in answer and "FlashDeal" not in answer
    assert svc.attempts_used(m["hash"]) == 0
    assert call.heard(f"{call.code} approve", 0.95, t(4)) == call.script.approved_line


def test_silence_denies_then_fresh_code_still_works():
    svc, m, call = setup()
    call.start(t(0))
    first = call.code
    assert call.silence(t(11)) == call.script.denied_line
    assert call.code != first and m["status"] == "pending"
    call.start(t(12))
    assert call.heard(f"{call.code} approve", 0.95, t(13)) == call.script.approved_line


def test_only_registered_number():
    with pytest.raises(PermissionError):
        number_for("nobody")
    register_number("tony", "+14155550100")
    assert number_for("tony") == "+14155550100"
    with pytest.raises(ValueError):
        register_number("tony", "4155550100")


def test_line_agent_drives_the_same_call(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from voice import cartesia
    monkeypatch.setattr(cartesia, "_say", lambda text: text)
    svc, m, call = setup()
    agent = cartesia.ApprovalCallAgent(call)
    CallStarted = type("CallStarted", (), {})
    UserTurnEnded = type("UserTurnEnded", (), {})

    async def run(event):
        return [x async for x in agent.process(None, event)]

    said = asyncio.run(run(CallStarted()))
    assert "five hundred eighty one" in said[0]
    turn = UserTurnEnded()
    turn.content = [SimpleNamespace(content=f"{call.code} approve")]
    assert asyncio.run(run(turn)) == [call.script.approved_line] and m["status"] == "approved"


def test_unknown_call_gets_no_agent():
    import asyncio
    from types import SimpleNamespace
    from voice import cartesia
    with pytest.raises(PermissionError):
        asyncio.run(cartesia.get_agent(None, SimpleNamespace(agent_call_id="nope")))
