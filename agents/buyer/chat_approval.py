"""Private owner-chat transport for the existing mandate-bound approval service."""
from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from pay.mandate import parse_ts
from pay.voice_cartesia import VoiceResult
from uagents_core.types import DeliveryStatus, MsgStatus

from . import checkout

_CALL_UNAVAILABLE = {"quiet_hours", "not_configured", "rate_limited", "unavailable"}


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


def _utc_now(value: datetime) -> datetime:
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() != timedelta(0)):
        raise ValueError("business time must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


async def approve_in_chat(transaction: Mapping[str, Any], *, sender: str, bound_owner: str,
                          send_private: Callable[[str], Awaitable[Any]],
                          call_ready: Callable[[], tuple[bool, str]],
                          client: Any, service: Any, buyer_name: str = "Vidyut",
                          now: Callable[[], datetime] | None = None) -> VoiceResult:
    """Approve one frozen offer by phone call, with the status reported in the owner's private chat.

    The only approval is the spoken code on the call (checkout.approve_offer, pay.voice_cartesia). The chat
    shows the one-time code, says the call is starting, and reports the outcome; it never accepts a typed code or
    any chat text as approval. If the call is not configured this fails closed: no approval, no payment.
    `send_private` captures the current owner context and must not persist the code, context, or live session.
    """
    if not isinstance(sender, str) or not sender or sender != bound_owner:
        return VoiceResult(False, "wrong_owner")
    loop = asyncio.get_running_loop()
    business_clock = (lambda: datetime.now(timezone.utc)) if now is None else now
    if not callable(business_clock):
        return VoiceResult(False, "transaction_invalid")

    def current_time() -> datetime:
        return _utc_now(business_clock())

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

    async def finish(result: VoiceResult, deal_id: str) -> VoiceResult:
        try:
            await send(format_approval_result(result, deal_id))
        except Exception:
            return VoiceResult(False, "private_result_delivery_failed", attempts=result.attempts)
        return result

    try:
        tx, mandate, deal = checkout._bound_transaction(transaction, approval_phase=True, now=current_time())
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
        if not ready or client is None:
            reason = (unavailable_reason if isinstance(unavailable_reason, str)
                      and unavailable_reason in _CALL_UNAVAILABLE else "unavailable")
            await send(f"Phone approval is not available ({reason}). Nothing was approved and nothing was ordered. "
                       "Set up the approval call, then ask again.")
            return VoiceResult(False, reason)

        def on_code(code: str) -> None:
            deadline = min(service.code_ttl.total_seconds(),
                           (parse_ts(mandate["expires_at"]) - current_time()).total_seconds())
            send_from_worker(f"One-time approval code: {code}. Calling your phone now: say the code, then say approve.",
                             deadline)

        try:
            result = await asyncio.to_thread(checkout.approve_offer, tx, client, service,
                on_code=on_code, buyer_name=buyer_name, now=current_time)
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
    if (not isinstance(mandate_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", mandate_hash)
            or not isinstance(deal_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", deal_id)
            or isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0):
        return "Payment result unavailable; do not mark this purchase paid."
    prefix = mandate_hash[:12]
    if result.get("status") == "charged":
        charge_id = result.get("charge_id")
        origin = result.get("origin")
        mode = settlement.get("mode")
        if mode not in ("SIM", "stripe_test"):
            return "Payment mode unavailable; do not mark this purchase paid."
        if (result.get("mandate_hash") != mandate_hash or origin != "SIM"
                or not isinstance(charge_id, str)
                or not re.fullmatch(r"(?:pi|ch)_[A-Za-z0-9_]{1,128}", charge_id)):
            return "Payment result unavailable; do not mark this purchase paid."
        return (f"{mode} payment confirmed for deal {deal_id}: ${cents // 100}.{cents % 100:02d}, "
                f"reference {charge_id}, mandate {prefix}.")
    if result.get("status") == "refused" or result.get("status") == "uncertain":
        return f"Payment {result['status']} for deal {deal_id}; mandate {prefix}."
    return "Payment result unavailable; do not mark this purchase paid."
