"""SIM adapter that drives the buyer's real handlers on the replay clock.

This starts a fresh volatile ROUND from an open persisted goal. Full production
ROUND restoration still depends on the Market startup hook.
"""
from __future__ import annotations

import copy
import importlib
import ipaddress
import socket
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agents.buyer import state
from agents.buyer.replay import ReplayError


class SimTransport:
    """Capture buyer sends in memory; this transport has no network implementation."""

    def __init__(self):
        self.sent: list[tuple[str, Any]] = []

    async def send(self, recipient: str, message: Any):
        self.sent.append((recipient, message))
        return None


class SimProvider:
    """Allowlisted provider base for deterministic replay-only bid and review fixtures."""

    def bids(self, listing: Mapping[str, Any], need: Mapping[str, Any], now: datetime):
        raise NotImplementedError

    def review(self, request: Any, now: datetime):
        raise NotImplementedError


class _Context:
    def __init__(self, transport: SimTransport):
        from uuid import uuid4

        self._transport = transport
        self.session = uuid4()
        self.logger = _Logger()

    async def send(self, recipient, message):
        return await self._transport.send(recipient, message)


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def _buyer_agent():
    agents_dir = str(Path(__file__).resolve().parents[1])
    if agents_dir not in sys.path:
        sys.path.insert(0, agents_dir)
    return importlib.import_module("buyer_agent")


class ReplayMarketAdapter:
    """Async `run_replay` dispatcher using production buyer callbacks and injected SIM dependencies."""

    def __init__(self, *, clock: Any, checker: Any, provider: Any, transport: SimTransport):
        if type(transport) is not SimTransport:
            raise ReplayError("replay requires the in-memory SIM transport")
        if not callable(getattr(clock, "now", None)):
            raise ReplayError("replay clock must provide now()")
        for method in ("check_sellers", "screen", "screen_bid"):
            if not callable(getattr(checker, method, None)):
                raise ReplayError(f"SIM checker requires {method}()")
        for method in ("bids", "review"):
            if not callable(getattr(provider, method, None)):
                raise ReplayError(f"SIM provider requires {method}()")
        if not isinstance(provider, SimProvider):
            raise ReplayError("replay provider must be an explicit SimProvider")
        self.buyer = _buyer_agent()
        if not callable(getattr(self.buyer, "business_now", None)):
            raise ReplayError("buyer business_now() clock seam is required")
        self.clock, self.checker, self.provider, self.transport = clock, checker, provider, transport
        self.ctx = _Context(transport)
        self._started = False
        self._entered = False

    def __enter__(self):
        if self._entered:
            raise ReplayError("replay adapter is already active")
        if self.buyer.ROUND:
            raise ReplayError("SIM replay requires an empty volatile buyer ROUND")
        try:
            self._runtime_snapshot = {
                "ROUND": copy.deepcopy(self.buyer.ROUND),
                "APPROVALS": copy.deepcopy(self.buyer.APPROVALS),
                "USED": copy.deepcopy(self.buyer.USED),
                "WEB_OUTBOX": copy.deepcopy(self.buyer.WEB_OUTBOX),
                "CHAT_DIAG": copy.deepcopy(self.buyer.CHAT_DIAG.__dict__),
            }
        except Exception as exc:
            raise ReplayError(f"buyer runtime globals cannot be isolated: {type(exc).__name__}") from None
        self._originals = (self.buyer.business_now, self.buyer.crs.check_sellers,
                           self.buyer.common.screen, self.buyer.common.screen_bid)
        self._socket_originals = (socket.socket.connect, socket.socket.connect_ex,
                                  socket.create_connection, socket.getaddrinfo,
                                  socket.socket.sendto, getattr(socket.socket, "sendmsg", None))
        self.buyer.business_now = self.clock.now
        self.buyer.crs.check_sellers = self.checker.check_sellers
        self.buyer.common.screen = self.checker.screen
        self.buyer.common.screen_bid = self.checker.screen_bid
        connect, connect_ex, create_connection, getaddrinfo, sendto, sendmsg = self._socket_originals

        def guarded_connect(sock, address):
            if _is_loopback_address(address):
                return connect(sock, address)
            return _deny_network(address)

        def guarded_connect_ex(sock, address):
            if _is_loopback_address(address):
                return connect_ex(sock, address)
            return _deny_network(address)

        def guarded_create_connection(address, *args, **kwargs):
            if _is_loopback_address(address):
                return create_connection(address, *args, **kwargs)
            return _deny_network(address)

        def guarded_getaddrinfo(host, *args, **kwargs):
            if _is_loopback_address(host):
                return getaddrinfo(host, *args, **kwargs)
            return _deny_network(host)

        def guarded_sendto(sock, *args, **kwargs):
            address = kwargs.get("address")
            if address is None and len(args) >= 2:
                address = args[-1]
            if _is_loopback_address(address):
                return sendto(sock, *args, **kwargs)
            return _deny_network(address)

        def guarded_sendmsg(sock, *args, **kwargs):
            address = kwargs.get("address")
            if address is None and len(args) >= 4:
                address = args[3]
            if _is_loopback_address(address):
                return sendmsg(sock, *args, **kwargs)
            return _deny_network(address)

        self._network_guards = (guarded_connect, guarded_connect_ex,
                                guarded_create_connection, guarded_getaddrinfo,
                                guarded_sendto, guarded_sendmsg)
        socket.socket.connect, socket.socket.connect_ex = guarded_connect, guarded_connect_ex
        socket.create_connection, socket.getaddrinfo = guarded_create_connection, guarded_getaddrinfo
        socket.socket.sendto = guarded_sendto
        if sendmsg is not None:
            socket.socket.sendmsg = guarded_sendmsg
        self._entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            (self.buyer.business_now, self.buyer.crs.check_sellers,
             self.buyer.common.screen, self.buyer.common.screen_bid) = self._originals
            (socket.socket.connect, socket.socket.connect_ex,
             socket.create_connection, socket.getaddrinfo,
             socket.socket.sendto, original_sendmsg) = self._socket_originals
            if original_sendmsg is not None:
                socket.socket.sendmsg = original_sendmsg
            for name in ("ROUND", "APPROVALS", "USED", "WEB_OUTBOX"):
                target, snapshot = getattr(self.buyer, name), self._runtime_snapshot[name]
                target.clear()
                if isinstance(target, dict):
                    target.update(snapshot)
                elif isinstance(target, set):
                    target.update(snapshot)
                else:
                    target.extend(snapshot)
            self.buyer.CHAT_DIAG.__dict__.clear()
            self.buyer.CHAT_DIAG.__dict__.update(self._runtime_snapshot["CHAT_DIAG"])
            self._started = False
        finally:
            self._entered = False
        return False

    async def __call__(self, event: Mapping[str, Any], *, now: datetime, db, scenario: Mapping[str, Any]) -> dict:
        if not self._entered:
            raise ReplayError("replay adapter must be used as a context manager")
        if scenario.get("buyer_id") == self.buyer.WEB:
            raise ReplayError("SIM replay does not support the reserved WEB owner")
        if self.clock.now() != now:
            raise ReplayError("buyer business clock does not match replay time")
        starting = not self._started
        before_goal_state = None
        if starting:
            persisted_goal = state.load_goal(db, scenario["goal_id"], scenario["buyer_id"])
            before_goal_state = persisted_goal.get("state") if persisted_goal else None
            await self._start(db, scenario)

        buyer = self.buyer
        round_state = buyer.ROUND
        before_phase = round_state.get("phase")
        if not starting:
            before_goal_state = round_state.get("goal", {}).get("state")
        before_round_token = round_state.get("round_token")
        events = []
        if event.get("kind") == "observation":
            listing = event.get("row")
            if not isinstance(listing, Mapping):
                raise ReplayError("observation must contain a listing row")
            before_bids = len(round_state.get("bids", []))
            if listing.get("kind") == "ask" and round_state.get("phase") == "bidding":
                replies = self.provider.bids(listing, round_state["need"], now)
                if not isinstance(replies, Sequence) or isinstance(replies, (str, bytes)):
                    raise ReplayError("SIM provider bids must be a sequence")
                for reply in replies:
                    if (not isinstance(reply, tuple) or len(reply) != 2
                            or not isinstance(reply[0], str)
                            or not isinstance(reply[1], buyer.common.BidReply)):
                        raise ReplayError("SIM provider returned an invalid bid reply")
                    await buyer.on_bid(self.ctx, reply[0], reply[1])
                if len(round_state.get("bids", [])) > before_bids:
                    events.append("bid_received")
            events.insert(0, "observation")
        elif event.get("kind") == "wakeup":
            sent_before = len(self.transport.sent)
            await buyer.tick(self.ctx)
            for _, message in self.transport.sent[sent_before:]:
                if isinstance(message, buyer.common.AdviceRequest):
                    reply = self.provider.review(message, now)
                    if not isinstance(reply, buyer.common.AdviceReply):
                        raise ReplayError("SIM provider returned an invalid advice reply")
                    await buyer.on_advice(self.ctx, buyer.common.address("advocate"), reply)
            if before_phase in {"bidding", "advice", "requote"}:
                events.append("deadline")
            if round_state.get("round_token") != before_round_token:
                events.append("round_started")
            if round_state.get("phase") == "waiting":
                events.append("retry")
            if round_state.get("phase") == "decided" and before_phase == "advice":
                events.append("deal_found")
        else:
            raise ReplayError("unsupported replay event")

        if starting and self._round_started:
            events.insert(0, "round_started")
        if round_state.get("goal", {}).get("state") == "EXPIRED" and before_goal_state != "EXPIRED":
            events.append("goal_expired")
        if round_state.get("goal"):
            state.save_goal(db, round_state["goal"])
        return {"next_wakeup_at": self._next_wakeup(),
                "events": [{"kind": kind, "at": now, "run_id": scenario["run_id"],
                            "buyer_id": scenario["buyer_id"], "goal_id": scenario["goal_id"]}
                           for kind in events]}

    async def _start(self, db, scenario):
        buyer = self.buyer
        if buyer.ROUND:
            raise ReplayError("SIM replay requires an empty volatile buyer ROUND")
        self._round_started = False
        state.recover_on_start(db)
        goal = state.load_goal(db, scenario["goal_id"], scenario["buyer_id"])
        if goal is None:
            raise ReplayError("scenario goal is not present for the requested buyer")
        owned = state.load_owned_parts(db, scenario["buyer_id"])
        buyer.ROUND.update(owner=scenario["buyer_id"], owner_context=self.ctx, goal=goal, owned=owned,
                           bids=[], personas={}, cards={}, attempts=0, last_sent={}, retired_need_ids=[],
                           phase="done")
        if goal["state"] in {"PAUSED", "EXPIRED", "DONE", "HOLD_FOR_CALL"}:
            pass
        else:
            await buyer.tick(self.ctx)
            if goal["state"] == "EXPIRED":
                self._started = True
                return
            need = buyer.need_from_goal(goal)
            buyer.ROUND["need"] = need
            if not need["items"]:
                buyer.set_state("DONE")
                buyer.ROUND["phase"] = "done"
            else:
                self._round_started = await buyer.start_round(self.ctx, need) is not False
        self._started = True

    def _next_wakeup(self) -> datetime | None:
        buyer, round_state = self.buyer, self.buyer.ROUND
        candidates = []
        goal = round_state.get("goal")
        if goal and goal.get("state") in buyer.hunt.OPEN:
            deadline = datetime.fromisoformat(goal["deadline"].replace("Z", "+00:00"))
            candidates.append(deadline.astimezone(timezone.utc) + timedelta(microseconds=1))
        phase = round_state.get("phase")
        if phase == "waiting":
            candidates.append(datetime.fromtimestamp(round_state["next_round_at"], timezone.utc))
        elif phase in {"bidding", "advice", "requote"}:
            candidates.append(datetime.fromtimestamp(round_state["deadline"], timezone.utc)
                              + timedelta(microseconds=1))
        return min((when for when in candidates if when > self.clock.now()), default=None)


def _deny_network(*args, **kwargs):
    raise ReplayError("outbound network is disabled during SIM replay")


def _is_loopback_address(address: Any) -> bool:
    host = address[0] if isinstance(address, tuple) and address else address
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
