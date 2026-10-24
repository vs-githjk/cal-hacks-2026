import asyncio
from datetime import datetime, timezone

import pytest

from agents.advocate.checks import CALL_SUMMARIES
from agents.buyer.chat_approval import approve_in_chat, format_settlement_result
from pay.approval import ApprovalService, code_hash
from pay.mandate import new_mandate
from pay.replay import NonceStore
from uagents_core.types import DeliveryStatus, MsgStatus

OWNER = "owner-authenticated-address"


def transaction():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    mandate = new_mandate(deal_id="deal-chat", buyer_id="vidyut", goal_id="goal-chat", amount=75.25,
                          payee="seller-chat", within_allowance=False, now=now)
    summary = CALL_SUMMARIES["advocate.ok"]
    return {"deal_id": "deal-chat", "buyer_id": "vidyut", "goal_id": "goal-chat", "need_id": "need-chat",
            "bid_id": "bid-chat", "phase": "pending_approval", "deal": {"id": "deal-chat",
            "goal_id": "goal-chat", "need_id": "need-chat", "bid_id": "bid-chat", "amount": 75.25,
            "payee": "seller-chat"}, "order": None, "mandate": mandate, "voice_approval": None,
            "allowance_authorization": None, "settlement": None, "settlement_result": None,
            "advocate_card": {"need_id": "need-chat", "bid_id": "bid-chat", "warnings": [],
                "claim_checks": [], "recommendation": "buy", "wait_until": "",
                "call_reason": {"rule_id": "advocate.ok", "summary": summary,
                "source_url": "https://example.com/check"},
                "rule_id": "advocate.ok", "reason": summary,
                "source_url": "https://example.com/check"}}


class FakeApprovalService(ApprovalService):
    def __init__(self, code_ttl_seconds=300):
        super().__init__("chat-approval-test-secret-123456", store=NonceStore(),
                         code_ttl_seconds=code_ttl_seconds)
        self.issued = []
        self.channels = []

    def issue(self, mandate, *, channel="browser", now=None):
        issued = super().issue(mandate, channel=channel, now=now)
        self.issued.append(issued[0])
        self.channels.append(channel)
        return issued


class FakeVoiceClient:
    approval_call_to = "+14155550123"

    def __init__(self, transcript="approve", failed=False):
        self.transcript = transcript
        self.failed = failed
        self.code = None
        self.variables = None
        self.calls = 0

    def create_call(self, _to, variables):
        self.calls += 1
        self.variables = dict(variables)
        return "call-chat-test"

    def get_call(self, call_id):
        if self.failed:
            return {"id": call_id, "status": "failed", "end_reason": "dial_no_answer", "transcript": []}
        return {"id": call_id, "status": "completed", "end_reason": "agent_hangup",
                "start_time": datetime.now(timezone.utc).isoformat(), "transcript": [
                    {"role": "user", "text": f"{self.code} {self.transcript}", "start_timestamp": 1.0}]}


class PrivateChat:
    def __init__(self, fail_code=False, false_code=False, status_code=None):
        self.messages = []
        self.fail_code = fail_code
        self.false_code = false_code
        self.status_code = status_code
        self.code = None

    async def send_private(self, text):
        if self.fail_code and text.startswith("One-time approval code:"):
            raise RuntimeError("private channel failed")
        if self.false_code and text.startswith("One-time approval code:"):
            return False
        if self.status_code is not None and text.startswith("One-time approval code:"):
            return MsgStatus(status=self.status_code, detail="offline", destination="owner",
                             endpoint="offline", session="chat-test")
        self.messages.append(text)
        if text.startswith("One-time approval code:"):
            self.code = text.split(": ", 1)[1].split(".", 1)[0]
        return None


def invoke(tx, service, client, private, **overrides):
    async def send_private(text):
        result = await private.send_private(text)
        if text.startswith("One-time approval code:"):
            client.code = private.code
        return result

    async def call():
        args = {"send_private": send_private, "call_ready": lambda: (True, ""),
                "client": client, "service": service}
        args.update(overrides)
        return await approve_in_chat(tx, sender=OWNER, bound_owner=OWNER, **args)
    return asyncio.run(call())


def test_approve_in_chat_has_no_typed_input_parameter():
    import inspect
    assert "wait_for_typed" not in inspect.signature(approve_in_chat).parameters


def test_voice_approval_uses_real_generated_code_only_in_private_owner_message():
    tx, service, private = transaction(), FakeApprovalService(), PrivateChat()
    client = FakeVoiceClient()
    result = invoke(tx, service, client, private)
    assert result.approved and result.record["result"] == "approved"
    assert result.record["channel"] == "phone"
    assert service.channels == ["phone"]
    assert service.issued[0].mandate_hash == tx["mandate"]["hash"]
    assert private.code and result.record["code_hash"] == code_hash(private.code)
    assert sum(m.startswith("One-time approval code:") for m in private.messages) == 1
    code_message = next(m for m in private.messages if m.startswith("One-time approval code:"))
    assert "Calling your phone now" in code_message  # the call status is posted with the code
    assert private.code not in repr(client.variables) and private.code not in repr(result)
    assert private.code not in " ".join(m for m in private.messages if m != code_message)
    assert client.calls == 1
    assert private.messages[-1] == "Approval confirmed for deal deal-chat. Payment is not confirmed by this approval."


@pytest.mark.parametrize("transcript,expected", [("deny", "denied"), ("approve", "approved")])
def test_explicit_voice_decision_is_final(transcript, expected):
    tx, service, private = transaction(), FakeApprovalService(), PrivateChat()
    client = FakeVoiceClient(transcript=transcript)
    result = invoke(tx, service, client, private)
    assert ("approved" if result.approved else "denied") == expected
    final = private.messages[-1]
    assert ("Approval confirmed" if expected == "approved"
            else f"reason: {result.reason.split(':', 1)[0]}") in final
    if expected == "approved":
        assert "Payment is not confirmed" in final


def test_voice_no_answer_stays_denied_and_never_falls_back_to_a_typed_code():
    tx, service, private, client = transaction(), FakeApprovalService(), PrivateChat(), FakeVoiceClient(failed=True)
    result = invoke(tx, service, client, private)
    assert not result.approved and result.record["result"] == "no_answer"
    assert result.reason == "no_answer:dial_no_answer" and service.channels == ["phone"]
    assert len(service.issued) == 1 and client.calls == 1
    assert service.issued[0].terminal
    assert private.messages[-1] == "No answer for deal deal-chat; approval was not granted."
    assert not any("type" in m.lower() for m in private.messages)


def test_chat_approval_rejects_falsey_non_callable_clock():
    class Falsey:
        def __bool__(self):
            return False

    tx, service, private, client = transaction(), FakeApprovalService(), PrivateChat(), FakeVoiceClient()
    result = invoke(tx, service, client, private, now=Falsey())
    assert not result.approved and result.reason == "transaction_invalid"


@pytest.mark.parametrize("reason", ["quiet_hours", "not_configured", "rate_limited", "unavailable", "weird"])
def test_call_not_ready_fails_closed_with_a_clear_owner_message(reason):
    tx, service, private, client = transaction(), FakeApprovalService(), PrivateChat(), FakeVoiceClient()
    result = invoke(tx, service, client, private, call_ready=lambda: (False, reason))
    expected = reason if reason != "weird" else "unavailable"
    assert not result.approved and result.reason == expected and result.record is None
    assert client.calls == 0 and not service.issued  # no code issued, no session, no call
    assert len(private.messages) == 1
    assert "Nothing was approved and nothing was ordered" in private.messages[0]
    assert expected in private.messages[0]
    assert not any(m.startswith("One-time approval code:") for m in private.messages)


def test_missing_client_fails_closed_even_if_call_ready_says_yes():
    tx, service, private = transaction(), FakeApprovalService(), PrivateChat()
    result = invoke(tx, service, None, private)
    assert not result.approved and result.record is None and not service.issued
    assert "Nothing was approved" in private.messages[0]


def test_call_ready_errors_fail_closed():
    tx, service, private, client = transaction(), FakeApprovalService(), PrivateChat(), FakeVoiceClient()

    def boom():
        raise RuntimeError("x")

    assert not invoke(tx, service, client, private, call_ready=boom).approved
    assert not invoke(tx, service, client, private, call_ready=lambda: ("yes", "")).approved
    assert client.calls == 0 and not service.issued


def test_chat_approval_uses_injected_business_clock_for_session_issue():
    tx, service, private, client = transaction(), FakeApprovalService(), PrivateChat(), FakeVoiceClient()
    issued_at = datetime.fromisoformat(tx["mandate"]["created_at"].replace("Z", "+00:00"))
    clock = lambda: issued_at

    invoke(tx, service, client, private, now=clock)
    assert service.issued[0].issued_at == issued_at


def test_wrong_owner_and_private_delivery_failure_never_dial():
    tx, service, private, client = transaction(), FakeApprovalService(), PrivateChat(), FakeVoiceClient()

    async def wrong_owner():
        return await approve_in_chat(tx, sender="foreign", bound_owner=OWNER,
            send_private=private.send_private, call_ready=lambda: (True, ""), client=client, service=service)

    wrong = asyncio.run(wrong_owner())
    assert wrong.reason == "wrong_owner" and client.calls == 0 and not service.issued
    assert not private.messages

    private.fail_code = True
    result = invoke(tx, service, client, private)
    assert not result.approved and result.reason == "private_code_delivery_failed"
    assert service.issued[0].terminal and client.calls == 0


def test_async_false_private_delivery_is_terminal_and_never_dials():
    tx, service, private, client = transaction(), FakeApprovalService(), PrivateChat(false_code=True), FakeVoiceClient()
    result = invoke(tx, service, client, private)
    assert not result.approved and result.reason == "private_code_delivery_failed"
    assert service.issued[0].terminal and client.calls == 0
    assert not any(message.startswith("One-time approval code:") for message in private.messages)
    assert private.messages[-1] == "Approval not granted for deal deal-chat (reason: private_code_delivery_failed)."


def test_async_failed_sdk_status_private_delivery_is_terminal_and_never_dials():
    tx, service, private, client = (transaction(), FakeApprovalService(),
                                    PrivateChat(status_code=DeliveryStatus.FAILED), FakeVoiceClient())
    result = invoke(tx, service, client, private)
    assert not result.approved and result.reason == "private_code_delivery_failed"
    assert service.issued[0].terminal and client.calls == 0
    assert private.messages[-1] == "Approval not granted for deal deal-chat (reason: private_code_delivery_failed)."


def test_settlement_formatter_uses_only_matching_returned_envelope():
    mandate_hash = "a" * 64
    envelope = {"settlement": {"deal_id": "deal-1", "amount_cents": 7525, "mandate_hash": mandate_hash,
                                "mode": "SIM"},
        "settlement_result": {"status": "charged", "charge_id": "pi_test_1", "mandate_hash": mandate_hash,
                              "origin": "SIM"}}
    text = format_settlement_result(envelope)
    assert text == f"SIM payment confirmed for deal deal-1: $75.25, reference pi_test_1, mandate {mandate_hash[:12]}."
    assert "confirmed" not in format_settlement_result({**envelope, "settlement_result": {
        **envelope["settlement_result"], "mandate_hash": "b" * 64}})
    assert "confirmed" not in format_settlement_result({**envelope, "settlement_result": {
        **envelope["settlement_result"], "origin": "untrusted-origin"}})
    uncertain = format_settlement_result({**envelope, "settlement_result": {"status": "uncertain"}})
    assert uncertain.startswith("Payment uncertain")
    for invalid_mode in (None, "untrusted", "stripe_test; charged"):
        invalid = {**envelope, "settlement": {**envelope["settlement"], "mode": invalid_mode}}
        assert format_settlement_result(invalid) == "Payment mode unavailable; do not mark this purchase paid."
    assert "confirmed" not in format_settlement_result({**envelope, "settlement_result": {
        **envelope["settlement_result"], "origin": "stripe_test"}})
    assert "confirmed" not in format_settlement_result({**envelope, "settlement_result": {
        **envelope["settlement_result"], "charge_id": "pi_\nforged"}})
    assert "unavailable" in format_settlement_result({**envelope, "settlement": {
        **envelope["settlement"], "mandate_hash": "A" * 64}})
