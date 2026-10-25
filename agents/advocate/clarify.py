"""Ask before vetoing. When the listing page leaves a condition open, the Advocate asks that seller ONE question over
the chat protocol, waits a few seconds, and checks.advise decides from the reply, which it cites. No reply is an
unverified veto. Code decides everything here: the reply is read through a closed vocabulary (parse_answer), screened
by Smell Test before it is read, and never copied into a card's text.

Seller side: the seller's own chat handler must answer in plain words ("open box"). Sellers that only send their profile
text are treated as silent, so the safe outcome (unverified veto) is the default.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable

from advocate import checks
from data.mirror import not_partners

ASK_TIMEOUT_S = float(os.environ.get("ADVOCATE_ASK_TIMEOUT_S", "4"))  # inside the buyer's 15 s advice wait, and run beside the lookups
EXCERPT_CHARS = 120
_NEGATED = re.compile(r"\b(?:not|isn't|is not|never|no longer)\s+(?:a\s+)?(?:brand\s+)?(?:new|used|open[- ]?box|refurb\w*)\b", re.I)
_WORDS = {"new": re.compile(r"\bnew\b", re.I), "open box": re.compile(r"\bopen[- ]?box(?:ed)?\b", re.I),
          "refurbished": re.compile(r"\brefurb\w*|\brenewed\b|\bre-?conditioned\b", re.I),
          "used": re.compile(r"\bused\b|\bpre[- ]?owned\b|\bsecond[- ]?hand\b", re.I)}
_LIKE_NEW = re.compile(r"\blike[- ]new\b", re.I)


def ambiguities(bids: list[dict]) -> dict[str, list[str]]:
    """{bid_id: [sku_spec, ...]} for lines whose condition the page leaves open and that a question could settle.
    A page that states a different condition is a mismatch, not a gap (#333), so it is never asked about."""
    out = {}
    for bid in bids:
        if not bid.get("lines") or not not_partners.orderable(bid):  # a never-orderable MIRROR store is vetoed anyway
            continue
        skus = []
        for line in bid["lines"]:
            offered, page = checks._norm(line.get("offered_condition")), checks._norm(line.get("page_condition"))
            if page in checks.CONDITIONS or page not in checks.UNSTATED | {""}:
                continue
            if page in checks.UNSTATED and offered in checks.CONDITIONS:
                continue
            skus.append(line["sku_spec"])
        if skus:
            out[bid["id"]] = skus
    return out


def parse_answer(text) -> str | None:
    """One condition from the closed set, or None when the reply names none or more than one."""
    text = _NEGATED.sub(" ", str(text or ""))
    if _LIKE_NEW.search(text):
        return None
    found = {cond for cond, rx in _WORDS.items() if rx.search(text)}
    return next(iter(found)) if len(found) == 1 else None


def _excerpt(text) -> str:
    return " ".join(re.sub(r"[^A-Za-z0-9 .,'%$/-]", " ", str(text or "")).split())[:EXCERPT_CHARS]


def question(items: list[str]) -> str:
    return (f"Fish Market Quality Advocate here, checking your bid for {' and '.join(items)}. The listing page does not "
            "state the condition. Is it new, open-box, refurbished or used? Please reply with one of those words.")


Send = Callable[[str, str], Awaitable[None]]


class Clarifier:
    """Sends the question and holds the open waits. The agent's chat handler calls offer() with every message that
    could be an answer; only a sender with an open question is taken as one."""

    def __init__(self, send: Send, resolve: Callable[[str], str], *, timeout: float = ASK_TIMEOUT_S, clock=None):
        self._send, self._resolve, self._timeout = send, resolve, timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self._pending: dict[str, asyncio.Future] = {}

    def is_waiting(self, sender: str) -> bool:
        """True while a question to this address is open: its next chat message is the answer, not a conversation."""
        fut = self._pending.get(sender)
        return fut is not None and not fut.done()

    def offer(self, sender: str, text: str, allowed: bool = True) -> bool:
        """True when this message answered an open question (it is then consumed). allowed=False is Smell Test's block."""
        fut = self._pending.get(sender)
        if fut is None or fut.done():
            return False
        fut.set_result((str(text or ""), bool(allowed)))
        return True

    async def _ask(self, address: str, q: str) -> tuple[str, str | None, str, str]:
        """(status, condition, excerpt, answered_at) for one question to one address."""
        loop = asyncio.get_running_loop()
        fut = self._pending[address] = loop.create_future()
        try:
            await self._send(address, q)
            text, allowed = await asyncio.wait_for(asyncio.shield(fut), self._timeout)
        except asyncio.TimeoutError:
            return "no_answer", None, "", ""
        except Exception:
            return "cannot_ask", None, "", ""
        finally:
            self._pending.pop(address, None)
        when = self._clock()
        if not allowed:
            return "blocked", None, "", when
        condition = parse_answer(text)
        return ("answered" if condition else "unclear"), condition, _excerpt(text), when

    async def ask_all(self, need: dict, bids: list[dict]) -> dict[str, dict]:
        """One question per seller for all of that seller's open bids, asked at the same time. {bid_id: record}."""
        gaps = ambiguities(bids)
        wanted = {i["sku_spec"] for i in need.get("items", [])}
        by_seller: dict[str, list[dict]] = {}
        for bid in bids:
            if bid["id"] in gaps:
                by_seller.setdefault(bid.get("supplier_id") or bid.get("seller_id") or "", []).append(bid)
        out: dict[str, dict] = {}

        async def one(sid: str, group: list[dict]):
            skus = sorted({s for b in group for s in gaps[b["id"]]})
            q = question([s if s in wanted else "this item" for s in skus][:3])
            try:
                address = self._resolve(sid)
            except Exception:
                result = ("cannot_ask", None, "", "")
            else:
                result = await self._ask(address, q)
            status, condition, excerpt, when = result
            for b in group:
                out[b["id"]] = {"status": status, "condition": condition, "question": q, "answer_excerpt": excerpt,
                                "answered_at": when, "seller": sid, "skus": gaps[b["id"]]}

        await asyncio.gather(*(one(sid, group) for sid, group in by_seller.items()))
        return out
