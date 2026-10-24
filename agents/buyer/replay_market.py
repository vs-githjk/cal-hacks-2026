"""SIM adapter that drives the buyer's real handlers on the replay clock.

This starts a fresh volatile ROUND from an open persisted goal. Full production
ROUND restoration still depends on the Market startup hook.
"""
from __future__ import annotations

import copy
import importlib
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

    def __init__(self, *, clock: Any, checker: Any, provider: Any, transport: SimTransport,
                 market_clients: tuple[Any, Any] | None = None):
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
        if hasattr(self.buyer, "MARKET_BUYER"):
            if (not isinstance(market_clients, tuple) or len(market_clients) != 2
                    or market_clients[0] is market_clients[1]
                    or getattr(market_clients[0], "role", None) != "buyer"
                    or getattr(market_clients[1], "role", None) != "referee"
                    or not getattr(market_clients[0], "identity", None)
                    or not getattr(market_clients[1], "identity", None)
                    or market_clients[0].identity == market_clients[1].identity):
                raise ReplayError("current buyer runtime requires distinct injected SIM buyer/referee clients")
        self.clock, self.checker, self.provider, self.transport = clock, checker, provider, transport
        self.market_clients = market_clients
        self.ctx = _Context(transport)
        self._started = False
        self._entered = False

    def __enter__(self):
        if self._entered:
            raise ReplayError("replay adapter is already active")
        if self.buyer.ROUND:
            raise ReplayError("SIM replay requires an empty volatile buyer ROUND")
        try:
            self._runtime_snapshot = {}
            for name in ("ROUND", "APPROVALS", "USED", "WEB_OUTBOX", "APPROVAL_WAITERS"):
                if hasattr(self.buyer, name):
                    self._runtime_snapshot[name] = copy.deepcopy(getattr(self.buyer, name))
            self._runtime_snapshot["CHAT_DIAG"] = copy.deepcopy(self.buyer.CHAT_DIAG.__dict__)
            self._global_snapshot = {name: getattr(self.buyer, name) for name in (
                "STATE_DB", "NONCE_STORE", "MARKET_BUYER", "MARKET_REFEREE", "APPROVAL_SERVICE",
                "APPROVAL_CALL_CLIENT", "MERCHANT_SIM", "TAP_PRIVATE_KEY", "SHIELD_RECEIPT_KEYS",
                "SHIELD_PAYMENT_SCREEN") if hasattr(self.buyer, name)}
            self._buyer_state_path = (getattr(self.buyer.buyer_state, "DEFAULT_DB_PATH", None)
                                      if hasattr(self.buyer, "buyer_state") else None)
        except Exception as exc:
            raise ReplayError(f"buyer runtime globals cannot be isolated: {type(exc).__name__}") from None
        self._originals = (self.buyer.business_now, self.buyer.crs.check_sellers,
                           self.buyer.common.screen, self.buyer.common.screen_bid)
        self._socket_originals = (socket.socket.connect, socket.socket.connect_ex,
                                  socket.create_connection, socket.getaddrinfo,
                                  socket.socket.sendto, getattr(socket.socket, "sendmsg", None))
        original_sendmsg = self._socket_originals[-1]
        self.buyer.business_now = self.clock.now
        self.buyer.crs.check_sellers = self.checker.check_sellers
        self.buyer.common.screen = self.checker.screen
        self.buyer.common.screen_bid = self.checker.screen_bid
        if self.market_clients is not None and hasattr(self.buyer, "MARKET_BUYER"):
            self.buyer.MARKET_BUYER, self.buyer.MARKET_REFEREE = self.market_clients
        socket.socket.connect = _deny_network
        socket.socket.connect_ex = _deny_network
        socket.create_connection = _deny_network
        socket.getaddrinfo = _deny_network
        socket.socket.sendto = _deny_network
        if original_sendmsg is not None:
            socket.socket.sendmsg = _deny_network
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
            for name, snapshot in self._runtime_snapshot.items():
                if name == "CHAT_DIAG":
                    self.buyer.CHAT_DIAG.__dict__.clear()
                    self.buyer.CHAT_DIAG.__dict__.update(snapshot)
                    continue
                target = getattr(self.buyer, name)
                target.clear()
                if isinstance(target, dict):
                    target.update(snapshot)
                elif isinstance(target, set):
                    target.update(snapshot)
                else:
                    target.extend(snapshot)
            for name, value in self._global_snapshot.items():
                setattr(self.buyer, name, value)
            if self._buyer_state_path is not None:
                self.buyer.buyer_state.DEFAULT_DB_PATH = self._buyer_state_path
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
            self._inject_scratch_services(db)
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
            if before_phase in {"bidding", "advice", "requote", "market_review_wait"}:
                events.append("deadline")
            if round_state.get("round_token") != before_round_token:
                events.append("round_started")
            if round_state.get("phase") == "waiting":
                events.append("retry")
            if round_state.get("phase") == "decided" and before_phase in {"advice", "market_review_wait"}:
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
        elif phase in {"bidding", "advice", "requote", "market_review_wait"}:
            candidates.append(datetime.fromtimestamp(round_state["deadline"], timezone.utc)
                              + timedelta(microseconds=1))
        return min((when for when in candidates if when > self.clock.now()), default=None)

    def _inject_scratch_services(self, db):
        if not hasattr(self.buyer, "STATE_DB"):
            return
        raw_path = db.execute("PRAGMA database_list").fetchone()[2]
        if not raw_path:
            raise ReplayError("SIM buyer state database must be a file-backed replay database")
        replay_path = Path(raw_path)
        if replay_path.resolve() == state.DEFAULT_DB_PATH.resolve():
            raise ReplayError("SIM buyer state cannot use the live default database")
        self.buyer.STATE_DB = db
        self.buyer.buyer_state.DEFAULT_DB_PATH = replay_path
        from pay.replay import NonceStore

        self.buyer.NONCE_STORE = NonceStore()


def _deny_network(*args, **kwargs):
    raise ReplayError("outbound network is disabled during SIM replay")
