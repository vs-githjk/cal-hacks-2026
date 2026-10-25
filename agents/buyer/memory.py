"""Short conversation memory for the Buyer chat (RT-6).

Each message in ASI:One reaches the Buyer alone. When it asked "new or open-box?" and the owner answers "new", the
answer means nothing without the goal it belongs to. This keeps the last unfinished goal per sender for ten minutes
and hands it back so the next message can be merged into it. Pure state: no I/O, no LLM, injectable clock.

A partial goal is a plain JSON-safe dict (see understand.new_draft). The memory never holds a finished goal, an
approval or a payment fact: when the goal is complete the caller clears the entry.
"""
from __future__ import annotations

import copy
import time
from typing import Callable

TTL_S = 600.0  # ten minutes
MAX_SENDERS = 500  # a public chat agent: bound the table so strangers cannot grow it without limit


class ConversationMemory:
    def __init__(self, ttl_s: float = TTL_S, clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.clock = ttl_s, clock
        self._rows: dict[str, tuple[float, dict]] = {}

    def _expire(self) -> None:
        now = self.clock()
        for sender in [s for s, (at, _) in self._rows.items() if now - at > self.ttl_s]:
            del self._rows[sender]

    def get(self, sender: str) -> dict | None:
        """A copy of the sender's unfinished goal, or None when there is none or it is older than the TTL."""
        self._expire()
        row = self._rows.get(sender)
        return copy.deepcopy(row[1]) if row else None

    def put(self, sender: str, partial: dict) -> None:
        """Keep (or refresh) the sender's unfinished goal; the ten minutes run from this write."""
        self._expire()
        if sender not in self._rows and len(self._rows) >= MAX_SENDERS:
            del self._rows[min(self._rows, key=lambda s: self._rows[s][0])]  # drop the stalest sender
        self._rows[sender] = (self.clock(), copy.deepcopy(partial))

    def clear(self, sender: str) -> None:
        self._rows.pop(sender, None)


MEMORY = ConversationMemory()  # the Buyer's process-wide memory
