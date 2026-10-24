"""Private-safe transport diagnostics for the buyer's Chat Protocol replies."""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable


def _opaque(value: object) -> str:
    return hashlib.sha256(str(value).encode('utf-8', errors='replace')).hexdigest()[:12]


class ChatDiagnostics:
    """Correlate send results and ACKs without logging identities, sessions, or message bodies."""

    def __init__(self, log: Callable[[str], None], *, clock=time.monotonic,
                 now=lambda: datetime.now(timezone.utc).isoformat(), ttl_s: float = 120,
                 max_pending: int = 128):
        self._log = log
        self._clock = clock
        self._now = now
        self._ttl_s = ttl_s
        self._max_pending = max_pending
        self._seq = 0
        self._pending: OrderedDict[str, dict] = OrderedDict()

    def _emit(self, event: str, **fields) -> None:
        self._seq += 1
        tail = ' '.join(f'{key}={value}' for key, value in fields.items())
        self._log(f'CHAT_DIAG seq={self._seq} at={self._now()} event={event}' + (f' {tail}' if tail else ''))

    def _expire(self) -> None:
        now = self._clock()
        while self._pending:
            message_id, row = next(iter(self._pending.items()))
            if now - row['at'] < self._ttl_s:
                break
            self._pending.pop(message_id)
            if not row['acked']:
                self._emit('unacknowledged', msg=_opaque(message_id), to=_opaque(row['to']),
                           session=_opaque(row['session']), round=_opaque(row['round']))

    def expire(self) -> None:
        """Emit timeout diagnostics even when no later chat activity arrives."""
        self._expire()

    def inbound(self, message_id: object, sender: str, session: object, round_id: object) -> None:
        self._expire()
        self._emit('inbound', msg=_opaque(message_id), sender=_opaque(sender),
                   session=_opaque(session), round=_opaque(round_id))

    def send_started(self, message_id: object, recipient: str, session: object, round_id: object) -> None:
        self._expire()
        key = str(message_id)
        if key in self._pending:
            self._pending.pop(key)
        while len(self._pending) >= self._max_pending:
            old_id, row = self._pending.popitem(last=False)
            if not row['acked']:
                self._emit('unacknowledged', msg=_opaque(old_id), to=_opaque(row['to']),
                           session=_opaque(row['session']), round=_opaque(row['round']))
        self._pending[key] = {'to': recipient, 'session': str(session), 'round': str(round_id),
                              'at': self._clock(), 'acked': False}
        self._emit('send_started', msg=_opaque(key), to=_opaque(recipient),
                   session=_opaque(session), round=_opaque(round_id))

    def send_result(self, message_id: object, result: object) -> None:
        self._expire()
        key = str(message_id)
        row = self._pending.get(key)
        if not row:
            return
        raw = getattr(result, 'status', result)
        raw = getattr(raw, 'value', getattr(raw, 'name', raw))
        status = str(raw).lower()
        if status not in {'sent', 'delivered', 'failed'}:
            status = 'unknown'
        self._emit('send_result', msg=_opaque(key), status=status)

    def send_exception(self, message_id: object, exc: BaseException) -> None:
        self._expire()
        key = str(message_id)
        if key in self._pending:
            self._emit('send_result', msg=_opaque(key), status='failed', error=type(exc).__name__)

    def ack_send_result(self, message_id: object, acknowledged_id: object, recipient: str,
                        session: object, result: object = None, error: BaseException | None = None) -> None:
        if error is not None:
            self._emit('ack_send_result', msg=_opaque(message_id), acknowledged=_opaque(acknowledged_id),
                       to=_opaque(recipient), session=_opaque(session), status='failed',
                       error=type(error).__name__)
            return
        raw = getattr(result, 'status', result)
        raw = getattr(raw, 'value', getattr(raw, 'name', raw))
        status = str(raw).lower()
        if status not in {'sent', 'delivered', 'failed'}:
            status = 'unknown'
        self._emit('ack_send_result', msg=_opaque(message_id), acknowledged=_opaque(acknowledged_id),
                   to=_opaque(recipient), session=_opaque(session), status=status)

    def acknowledged(self, message_id: object, sender: str) -> bool:
        self._expire()
        key = str(message_id)
        row = self._pending.get(key)
        if not row:
            self._emit('ack_ignored', msg=_opaque(key), sender=_opaque(sender), reason='unknown_or_expired')
            return False
        if sender != row['to']:
            self._emit('ack_ignored', msg=_opaque(key), sender=_opaque(sender), reason='foreign_sender')
            return False
        if row['acked']:
            self._emit('ack_ignored', msg=_opaque(key), sender=_opaque(sender), reason='duplicate')
            return False
        row['acked'] = True
        self._emit('ack_received', msg=_opaque(key), sender=_opaque(sender))
        return True
