"""Private owner-chat transport for the existing mandate-bound approval service."""
from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from pay.approval import CODE_TTL_SECONDS, ApprovalError
from pay.mandate import parse_ts
from pay.voice_cartesia import VoiceResult
from uagents_core.types import DeliveryStatus, MsgStatus

from . import checkout

_CALL_UNAVAILABLE = {"quiet_hours", "not_configured", "unavailable"}


def format_approval_result(result: VoiceResult, deal_id: str) -> str:
    """Fixed, private owner-facing approval outcome; approval is not payment confirmation."""
    if result.approved and isinstance(result.record, Mapping) and result.record.get("result") == "approved":
        return f"Approval confirmed for deal {deal_id}. Payment is not confirmed by this approval."
    reason = result.reason or "approval_unavailable"
    if reason.startswith(("no_answer", "no_transcript", "no_buyer_speech", "dial_no_answer")):
        return f"No answer for deal {deal_id}; approval was not granted."
    reason_code = reason.split(":", 1)[0]
    safe_reason = reason_code if re.fullmatch(r"[a-z][a-z0-9_]{0,39}", reason_code) else "approval_unavailable"
    return f"Approval not granted for deal {deal_id} (reason: {safe_reason})."


async def approve_in_chat(transaction: Mapping[str, Any], *, sender: str, bound_owner: str,
                          send_private: Callable[[str], Awaitable[Any]],
                          call_ready: Callable[[], tuple[bool, str]],
                          wait_for_typed: Callable[[str, str, str, float], Awaitable[tuple[str, str] | None]],
                          client: Any, service: Any, buyer_name: str = "Vidyut") -> VoiceResult:
    """Approve one frozen offer from its authenticated owner's original private chat session.

    `send_private` captures the current owner context. `wait_for_typed` returns (sender, text); it must
    wait only for the supplied owner/deal and must not persist the code, context, or live session.
    """
    if not isinstance(sender, str) or not sender or sender != bound_owner:
        return VoiceResult(False, "wrong_owner")
    loop = asyncio.get_running_loop()

    async def send(text: str) -> None:
        result = send_private(text)
        if inspect.isawaitable(result):
            result = await result
        if result is False or (isinstance(result, MsgStatus) and result.status != DeliveryStatus.DELIVERED):
            raise RuntimeError

    def send_from_worker(text: str, timeout: float) -> None:
        if timeout <= 0:
            raise PermissionError("private approval delivery expired")
        future = asyncio.run_coroutine_threadsafe(send(text), loop)
        try:
            future.result(timeout=min(10.0, timeout))
        except Exception:
            future.cancel()
            raise PermissionError("private approval delivery failed") from None

    async def typed_wait(session, *, prompt: bool) -> str | None:
        remaining = max(0.0, (session.expires_at - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            return None
        if prompt:
            await send("The call did not connect. You can type the same one-time code before it expires.")
        deadline = loop.time() + remaining
        while (remaining := deadline - loop.time()) > 0:
            try:
                answer = await asyncio.wait_for(
                    wait_for_typed(bound_owner, tx["deal_id"], mandate["hash"], remaining), timeout=remaining)
            except Exception:
                return None
            if answer is None:
                return None
            if (not isinstance(answer, tuple) or len(answer) != 2
                    or not isinstance(answer[0], str) or not isinstance(answer[1], str)):
                return None
            if answer[0] == bound_owner:
                return answer[1]
        return None

    async def finish(result: VoiceResult, deal_id: str) -> VoiceResult:
        try:
            await send(format_approval_result(result, deal_id))
        except Exception:
            return VoiceResult(False, "private_result_delivery_failed", attempts=result.attempts)
        return result

    try:
        tx, mandate, deal = checkout._bound_transaction(transaction, approval_phase=True)
    except (ValueError, PermissionError):
        return await finish(VoiceResult(False, "transaction_invalid"), "this deal")
    deal_id = tx["deal_id"]
    if mandate.get("within_allowance") is True:
        return await finish(VoiceResult(False, "voice_approval_not_required"), deal_id)

    try:
        try:
            ready, unavailable_reason = call_ready()
        except Exception:
            ready, unavailable_reason = False, "unavailable"
        if not isinstance(ready, bool):
            ready, unavailable_reason = False, "unavailable"

        if not ready:
            reason = (unavailable_reason if isinstance(unavailable_reason, str)
                      and unavailable_reason in _CALL_UNAVAILABLE else "unavailable")
            await send(f"Voice approval is unavailable ({reason}); you can approve with a typed code instead.")
            try:
                session, code = service.issue(mandate, channel="browser")
            except ApprovalError as error:
                return await finish(VoiceResult(False, error.reason), deal_id)
            session.expires_at = min(session.expires_at,
                                     session.issued_at + timedelta(seconds=CODE_TTL_SECONDS))
            try:
                await send(f"One-time approval code: {code}")
            except Exception:
                session.silence()
                return await finish(VoiceResult(False, "private_code_delivery_failed"), deal_id)
            while not session.terminal:
                typed = await typed_wait(session, prompt=False)
                if typed is None:
                    break
                decision = session.approve_typed(typed)
                if decision.final:
                    return await finish(VoiceResult(decision.approved, decision.reason, record=decision.record,
                                                    attempts=session.attempts), deal_id)
            if not session.terminal and datetime.now(timezone.utc) >= session.expires_at:
                decision = session.approve_typed("", now=session.expires_at)
            else:
                decision = session.silence()
            return await finish(VoiceResult(False, decision.reason or "no_answer", record=decision.record,
                                            attempts=session.attempts), deal_id)

        prompt_sent = False

        def on_code(code: str) -> None:
            deadline = min(service.code_ttl.total_seconds(),
                           (parse_ts(mandate["expires_at"]) - datetime.now(timezone.utc)).total_seconds())
            send_from_worker(f"One-time approval code: {code}. Voice approval is starting now.", deadline)

        def typed_input(session) -> str | None:
            nonlocal prompt_sent
            remaining = max(0.0, (session.expires_at - datetime.now(timezone.utc)).total_seconds())
            if remaining <= 0:
                return None
            prompt = not prompt_sent
            prompt_sent = True
            future = None
            try:
                future = asyncio.run_coroutine_threadsafe(typed_wait(session, prompt=prompt), loop)
                return future.result(timeout=remaining)
            except Exception:
                if future is not None:
                    future.cancel()
                return None

        try:
            result = await asyncio.to_thread(checkout.approve_offer, tx, client, service,
                on_code=on_code, buyer_name=buyer_name, typed_input=typed_input)
            return await finish(result, deal_id)
        except PermissionError:
            return await finish(VoiceResult(False, "private_code_delivery_failed"), deal_id)
    except Exception:
        return await finish(VoiceResult(False, "private_approval_unavailable"), deal_id)


def format_settlement_result(envelope: Mapping[str, Any]) -> str:
    """Describe only the exact status and identifiers returned by checkout settlement."""
    settlement = envelope.get("settlement") if isinstance(envelope, Mapping) else None
    result = envelope.get("settlement_result") if isinstance(envelope, Mapping) else None
    if not isinstance(settlement, Mapping) or not isinstance(result, Mapping):
        return "Payment result unavailable; do not mark this purchase paid."
    mandate_hash = settlement.get("mandate_hash")
    deal_id = settlement.get("deal_id")
    cents = settlement.get("amount_cents")
    if (not isinstance(mandate_hash, str) or len(mandate_hash) != 64
            or not isinstance(deal_id, str) or not deal_id
            or isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0):
        return "Payment result unavailable; do not mark this purchase paid."
    prefix = mandate_hash[:12]
    if result.get("status") == "charged":
        charge_id = result.get("charge_id")
        origin = result.get("origin")
        if (result.get("mandate_hash") != mandate_hash or origin not in ("SIM", "stripe_test")
                or not isinstance(charge_id, str) or not charge_id.startswith(("pi_", "ch_"))):
            return "Payment result unavailable; do not mark this purchase paid."
        return (f"{origin} payment confirmed for deal {deal_id}: ${cents // 100}.{cents % 100:02d}, "
                f"reference {charge_id}, mandate {prefix}.")
    if result.get("status") == "refused" or result.get("status") == "uncertain":
        return f"Payment {result['status']} for deal {deal_id}; mandate {prefix}."
    return "Payment result unavailable; do not mark this purchase paid."
