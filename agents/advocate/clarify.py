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
_PROFILE_TEXT = re.compile(r"send buying goals to @", re.I)  # the closing line of every agent's profile chat text


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
        # address -> one open question: [future for the reply, number of requests waiting on it, the question text sent].
        # A second request to a seller with a question already open joins it instead of asking again (still ONE question),
        # so concurrent requests cannot take each other's answer.
        self._pending: dict[str, list] = {}

    def is_waiting(self, sender: str) -> bool:
        """True while a question to this address is open: its next chat message is the answer, not a conversation."""
        entry = self._pending.get(sender)
        return entry is not None and not entry[0].done()

    def offer(self, sender: str, text: str, allowed: bool = True) -> bool:
        """True when this message answered an open question (it is then consumed). allowed=False is Smell Test's block."""
        entry = self._pending.get(sender)
        if entry is None or entry[0].done():
            return False
        entry[0].set_result((str(text or ""), bool(allowed)))
        return True

    async def _ask(self, address: str, q: str) -> tuple[str, str | None, str, str, str]:
        """(status, condition, excerpt, answered_at, question sent) for one question to one address."""
        entry = self._pending.get(address)
        fresh = entry is None or entry[0].done()
        if fresh:
            entry = self._pending[address] = [asyncio.get_running_loop().create_future(), 0, q]
        entry[1] += 1
        fut, sent = entry[0], entry[2]
        try:
            if fresh:
                try:
                    await self._send(address, q)
                except Exception:
                    if not fut.done():
                        fut.set_result(None)  # every request waiting on this question fails with it
                    return "cannot_ask", None, "", "", sent
            got = await asyncio.wait_for(asyncio.shield(fut), self._timeout)
        except asyncio.TimeoutError:
            return "no_answer", None, "", "", sent
        except Exception:
            return "cannot_ask", None, "", "", sent
        finally:
            entry[1] -= 1
            if entry[1] == 0 and self._pending.get(address) is entry:  # the last waiter closes the question
                del self._pending[address]
        if got is None:
            return "cannot_ask", None, "", "", sent
        text, allowed = got
        when = self._clock()
        if not allowed:
            return "blocked", None, "", when, sent
        # a seller that only sends its profile text ("I am ReNew Refurb... send buying goals to @...") has not answered
        condition = None if _PROFILE_TEXT.search(text) else parse_answer(text)
        return ("answered" if condition else "unclear"), condition, _excerpt(text), when, sent

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
                result = ("cannot_ask", None, "", "", q)
            else:
                result = await self._ask(address, q)
            status, condition, excerpt, when, sent = result  # `sent` is the question actually asked (a joined request shares it)
            for b in group:
                out[b["id"]] = {"status": status, "condition": condition, "question": sent, "answer_excerpt": excerpt,
                                "answered_at": when, "seller": sid, "skus": gaps[b["id"]]}

        await asyncio.gather(*(one(sid, group) for sid, group in by_seller.items()))
        return out
