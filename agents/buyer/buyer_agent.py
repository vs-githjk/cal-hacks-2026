"""Tech Bazaar buyer agent: buyer's goal -> ownership memory -> sealed round with the seller agents -> advocate cards
-> approval. Run from agents/:  .venv/Scripts/python.exe buyer/buyer_agent.py   (BUYER_MAILBOX=1 for Agentverse)"""
import json
import hashlib
import os
import re
import sys
import time
import asyncio
import copy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uagents import Agent, Context, Model, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec
from uagents_core.contrib.protocols.payment import (CancelPayment, CompletePayment, RejectPayment, RequestPayment,
                                                    payment_protocol_spec)

import common
import crs
import hunt
import payment
import status
import state as buyer_state
from market_bridge import MarketBridge, MarketBridgeError
from advocate.real_data import cached_shield_baseline
from chat_diagnostics import ChatDiagnostics
from chat_trace import round_trace
from goal import apply_owned, need_from_goal, owned_attrs, parse_goal, remember, skip_lines
from logic import advice_need_for, decide, make_order, sealed
from data.mirror import not_partners  # common put the repo root on sys.path

ADVICE_TIMEOUT_S = 15
RETIRED_NEED_HISTORY = 8
ALLOWANCE = float(os.getenv("BUYER_ALLOWANCE", "0"))  # $0: every order needs a phone-call approval
CRS_NOT_CONFIGURED_NOTICE = "CRS not configured; seller eligibility was not verified."
SELLER_ADDRS = {common.address(s): s for s in common.SELLERS}
WEB = "web"  # owner id for the local web chat (web_chat.py); its replies queue in WEB_OUTBOX

# Agentverse profile, published on connect (README, short description, handle) for ASI:One discovery.
agent = Agent(**common.agent_args(
    "buyer", 8001, name="Fish Market Buyer",
    readme_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "AGENTVERSE.md"),
    description="Your buying agent for computer gear: give it a goal, it skips parts you own, makes seller agents "
                "bid in a sealed round, vetoes traps with a cited source, and pays only after you approve.",
    handle=os.getenv("BUYER_AGENT_HANDLE", "techbazaarbuyer")))
chat = Protocol(spec=chat_protocol_spec)
pay = Protocol(spec=payment_protocol_spec, role="buyer")

# One live protocol round at a time; protected purchase state is durable across restarts.
# phase: bidding -> advice -> decided (or done). Goal state: ACTIVE -> HUNTING -> HOLD_FOR_CALL / DONE.
ROUND: dict = {}
WEB_OUTBOX: list[str] = []
CHAT_DIAG = ChatDiagnostics(print)
MARKET_BUYER = None  # injectable for offline tests; production uses the explicit buyer token file
MARKET_REFEREE = None  # separate role identity, never substituted with the buyer
STATE_DB = None
NONCE_STORE = None
APPROVAL_SERVICE = None
APPROVAL_CALL_CLIENT = None
MERCHANT_SIM = None
TAP_PRIVATE_KEY = None
SHIELD_RECEIPT_KEYS = None
SHIELD_PAYMENT_SCREEN = None
MARKET_BUYER_ID = os.environ.get("MARKET_BUYER_ID", "")
MARKET_SELLER_IDS = {"seller-a": "seller_1", "seller-b": "seller_2", "seller-c": "seller_3"}


def business_now() -> datetime:
    """Injectable UTC business clock; transport and diagnostic timeouts stay real-time."""
    return datetime.now(timezone.utc)


def _configured_market_owner_matches(sender: Any) -> bool:
    """Require an operator-pinned authenticated owner for purchase and payment actions."""
    configured = os.environ.get("MARKET_BUYER_OWNER_SENDER")
    return isinstance(configured, str) and bool(configured.strip()) and sender == configured


def market_clients():
    """Return explicit role clients; missing or shared identities disable Market-backed orders."""
    global MARKET_BUYER, MARKET_REFEREE
    if MARKET_BUYER is None or MARKET_REFEREE is None:
        buyer_path = os.environ.get("SPACETIMEDB_BUYER_TOKEN_FILE")
        referee_path = os.environ.get("SPACETIMEDB_REFEREE_TOKEN_FILE")
        if not buyer_path or not referee_path or os.path.normcase(os.path.abspath(buyer_path)) == os.path.normcase(os.path.abspath(referee_path)):
            raise MarketBridgeError("market_role_identity_unavailable")
        buyer = MarketBridge("buyer", token_file=buyer_path)
        referee = MarketBridge("referee", token_file=referee_path)
        if not buyer.identity or not referee.identity or buyer.identity == referee.identity:
            raise MarketBridgeError("market_role_identity_mismatch")
        MARKET_BUYER, MARKET_REFEREE = buyer, referee
    if (MARKET_BUYER is MARKET_REFEREE
            or (getattr(MARKET_BUYER, "identity", None) is not None
                and getattr(MARKET_BUYER, "identity", None) == getattr(MARKET_REFEREE, "identity", None))):
        raise MarketBridgeError("market_role_identity_mismatch")
    return MARKET_BUYER, MARKET_REFEREE


def state_db():
    global STATE_DB
    if STATE_DB is None:
        STATE_DB = buyer_state.open_state(buyer_state.DEFAULT_DB_PATH)
    return STATE_DB


def _market_timestamp(value) -> float:
    if isinstance(value, datetime):
        current = value
    elif isinstance(value, str):
        current = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Market deadline is unavailable")
    if current.tzinfo is None:
        raise ValueError("Market deadline has no timezone")
    return current.astimezone(timezone.utc).timestamp()


def _review_candidates(referee_market, round_id: str) -> list[dict]:
    candidates = referee_market.review_candidates(round_id)
    originals = {bid["id"]: bid for bid in ROUND.get("received_bids", {}).values()}
    selected = []
    hashes = {}
    for candidate in candidates:
        bid = originals.get(candidate.get("bid_id"))
        if (bid is None or candidate.get("round_id") != round_id
                or candidate.get("need_id") != ROUND["need"]["id"]
                or candidate.get("seller_id") != {"seller_1": "seller-a", "seller_2": "seller-b",
                                                   "seller_3": "seller-c"}.get(bid["supplier_id"])
                or candidate.get("origin") != bid.get("origin")):
            raise MarketBridgeError("candidate_bid_binding_mismatch")
        lines = candidate.get("lines")
        metadata = candidate.get("line_metadata")
        if not isinstance(lines, list) or not lines or not isinstance(metadata, list) or len(lines) != len(metadata):
            raise MarketBridgeError("candidate_lines_invalid")
        projected = dict(bid, lines=[])
        for row, meta in zip(lines, metadata):
            index = row.get("line_index") if isinstance(row, dict) else None
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(bid["lines"]):
                raise MarketBridgeError("candidate_line_index_invalid")
            original = bid["lines"][index]
            line_hash = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"),
                                               ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            if (meta.get("lineIndex") != index or meta.get("listingHash") != line_hash
                    or meta.get("listingId") != (original.get("listing_id") or original.get("listing_url"))
                    or row.get("sku_spec") != original.get("sku_spec")
                    or row.get("unit_price") != original.get("unit_price")
                    or row.get("quantity") != original.get("quantity")):
                raise MarketBridgeError("candidate_line_binding_mismatch")
            projected["lines"].append({**original, "line_index": index, "listing_id": meta["listingId"],
                                       "listing_hash": meta["listingHash"]})
        projected["candidate_binding_hash"] = candidate["binding_hash"]
        selected.append(projected)
        hashes[bid["id"]] = candidate["binding_hash"]
    ROUND["candidate_hashes"] = hashes
    return selected


def _ensure_market_round_state(referee_market, round_id: str, *, expected: str, transition_from: str) -> dict:
    status = referee_market.round_status(round_id)
    if status.get("state") == expected:
        return status
    if status.get("state") != transition_from:
        raise MarketBridgeError("market_round_transition_invalid")
    try:
        referee_market.close_round(round_id)
    except MarketBridgeError:
        # The scheduler may have completed this exact transition after our read.
        status = referee_market.round_status(round_id)
        if status.get("state") != expected:
            raise
    else:
        status = referee_market.round_status(round_id)
    if status.get("state") != expected:
        raise MarketBridgeError("market_round_transition_unconfirmed")
    return status


def _begin_market_review() -> list[dict]:
    _buyer_market, referee_market = market_clients()
    round_id = ROUND["market_round_id"]
    _ensure_market_round_state(referee_market, round_id, expected="review", transition_from="open")
    for bid_id, check in ROUND.get("screened_bids", {}).items():
        referee_market.attach_verdict(bid_id=bid_id, verdict=check["verdict"],
                                      rule_ids=check["rule_ids"], origin=check["origin"])
    return _review_candidates(referee_market, round_id)


def _record_market_reviews(cards: list[dict]) -> None:
    _buyer_market, referee_market = market_clients()
    bids = {bid["id"]: bid for bid in ROUND.get("review_bids", [])}
    cards_by_bid = {card["bid_id"]: card for card in cards}
    if set(cards_by_bid) != set(bids):
        raise MarketBridgeError("advocate_review_coverage_invalid")
    for bid_id, bid in bids.items():
        card = cards_by_bid[bid_id]
        binding_hash = bid["candidate_binding_hash"]
        origin = bid["origin"]
        selected = {line["line_index"]: line for line in bid["lines"]}
        checked = set()
        for evidence in card.get("claim_checks", []):
            index = evidence.get("line_index")
            line = selected.get(index)
            if (evidence.get("bid_id") != bid_id or line is None
                    or evidence.get("listing_id") != line["listing_id"]
                    or evidence.get("result") not in {"verified", "unverified", "false"}):
                raise MarketBridgeError("claim_check_binding_mismatch")
            checked.add(index)
            referee_market.attach_claim_check(
                bid_id=bid_id, claim=f"condition:{evidence['value']}", check=evidence["result"],
                evidence_url=evidence.get("evidence_url") or line["listing_url"], origin=origin,
                binding_hash=binding_hash, line_index=index, listing_id=line["listing_id"],
                listing_hash=line["listing_hash"])
        for index, line in selected.items():
            if index not in checked:
                referee_market.attach_claim_check(
                    bid_id=bid_id, claim=f"condition:{line['offered_condition']}", check="unverified",
                    evidence_url=line["listing_url"], origin=origin, binding_hash=binding_hash,
                    line_index=index, listing_id=line["listing_id"], listing_hash=line["listing_hash"])
            for claim in bid.get("claims", []):
                referee_market.attach_claim_check(
                    bid_id=bid_id, claim=claim, check="unverified", evidence_url=line["listing_url"],
                    origin=origin, binding_hash=binding_hash, line_index=index,
                    listing_id=line["listing_id"], listing_hash=line["listing_hash"])
        reason = card["call_reason"]
        referee_market.attach_advocate_card(
            bid_id=bid_id, recommendation=card["recommendation"], rule_id=reason["rule_id"],
            text=reason["summary"], source_url=reason["source_url"], origin=origin,
            binding_hash=binding_hash)


async def _finish_market_round(ctx: Context):
    token, need_id = ROUND.get("round_token"), ROUND.get("need", {}).get("id")
    try:
        reviewed_cards = ROUND.get("cards", {})
        buyer_market, referee_market = market_clients()
        round_id = ROUND["market_round_id"]
        _ensure_market_round_state(referee_market, round_id, expected="closed", transition_from="review")
        winner = buyer_market.authoritative_winner(round_id, ROUND["need"]["items"])
        if winner is None:
            ROUND["market_winner"] = None
        else:
            local = next((bid for bid in ROUND.get("review_bids", []) if bid["id"] == winner.get("bid_id")), None)
            supplier = MARKET_SELLER_IDS.get(winner.get("seller_id"))
            if (local is None or supplier != local.get("supplier_id")
                    or winner.get("binding_hash") != ROUND.get("candidate_hashes", {}).get(local["id"])):
                raise MarketBridgeError("market_winner_binding_mismatch")
            raw_offer = next((bid for bid in ROUND.get("received_bids", {}).values()
                              if bid.get("id") == local["id"]), None)
            if not isinstance(raw_offer, dict):
                raise MarketBridgeError("original_offer_readback_missing")
            by_index = {line["line_index"]: line for line in local["lines"]}
            selected = []
            for result_line in winner["lines"]:
                line = by_index.get(result_line.get("original_line_index"))
                if (line is None or line.get("sku_spec") != result_line.get("sku_spec")
                        or line.get("unit_price") != result_line.get("unit_price")
                        or result_line.get("listing_id") != line.get("listing_id")
                        or result_line.get("listing_hash") != line.get("listing_hash")):
                    raise MarketBridgeError("market_winner_line_mismatch")
                selected.append({**line, "quantity": result_line["quantity"],
                                 "shipping": result_line["shipping"]})
            ROUND["market_winner"] = dict(local, lines=selected, total_landed_price=winner["landed"],
                                           market_binding_hash=winner["binding_hash"])
            ROUND["original_offer"] = copy.deepcopy(raw_offer)
            ROUND["bids"] = [ROUND["market_winner"]]
        if not ROUND.get("trace_written"):
            ctx.logger.info(round_trace(common.SELLERS, ROUND.get("review_bids", []), reviewed_cards,
                                        ROUND.get("market_winner")))
            ROUND["trace_written"] = True
        if ROUND.get("market_winner"):
            ROUND["cards"] = {ROUND["market_winner"]["id"]: reviewed_cards[ROUND["market_winner"]["id"]]}
    except Exception as exc:
        ctx.logger.warning(f"Authoritative Market result unavailable: {type(exc).__name__}")
        await fail_round(ctx, "Market could not verify the round result. Nothing ordered.", always_notify=True)
        return
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    if ROUND.get("market_winner") is None:
        await fail_round(ctx, "No reviewed Market bid passed the authoritative ranking. Nothing ordered.",
                         always_notify=True)
        return
    await conclude(ctx, reviewed=True)


def nonce_store():
    global NONCE_STORE
    if NONCE_STORE is None:
        from pay.replay import NonceStore
        nonce_path = buyer_state.DEFAULT_DB_PATH
        if state_db().execute("PRAGMA database_list").fetchone()[2] != str(nonce_path):
            raise ValueError("buyer state and nonce store must share one database")
        NONCE_STORE = NonceStore(str(nonce_path))
    return NONCE_STORE


def recover_buyer_state() -> int:
    """Run owner-thread recovery once at startup; interrupted submissions stay uncertain."""
    db = state_db()
    buyer_state.recover_on_start(db)
    recovered = nonce_store().recover_submitted_attempts()
    unresolved = db.execute("SELECT deal_id, buyer_id FROM transactions "
                            "WHERE phase IN ('paused', 'approved', 'submitted', 'uncertain') ORDER BY rowid").fetchall()
    # Web (b_) buyers have no owner chat and their purchases end in a SIM/test-mode charge, no payment request: never hold the agent for them.
    unresolved = [(d, b) for d, b in unresolved if not str(b).startswith("b_")]
    held = None
    for deal_id, buyer_id in unresolved:
        transaction = buyer_state.load_transaction(db, deal_id, buyer_id)
        owner = (transaction.get("deal", {}).get("owner_sender")
                 if isinstance(transaction.get("deal"), dict) else None)
        if owner:
            held = (transaction, owner)
            break
    if held:
        transaction, owner = held
        goal = buyer_state.load_goal(db, transaction["goal_id"], owner) if isinstance(owner, str) and owner else None
        ROUND.clear()
        ROUND.update(owner=owner, owner_context=None, goal=goal, phase="uncertain", order=transaction.get("order"),
                     mandate=transaction.get("mandate"), pending_hold=True, transaction=transaction)
    return recovered


@agent.on_event("startup")
async def buyer_startup(ctx: Context):
    try:
        recover_buyer_state()
    except Exception as exc:
        ctx.logger.error(f"Buyer private state recovery failed: {type(exc).__name__}")
        raise


class WebIn(Model):
    text: str


class WebOut(Model):
    replies: list[str]


def log_msg(ctx: Context, frm: str, to: str, kind: str):
    ctx.logger.info(status.msg_line(frm, to, kind))


@agent.on_event("startup")
async def announce(ctx: Context):
    ctx.logger.info(status.status_line("buyer", "buyer", agent.address, mailbox=common.mailbox_on("buyer")))


async def tell(ctx: Context, to: str, text: str):
    if to == WEB:
        WEB_OUTBOX.append(text)
    else:
        msg = ChatMessage(content=[TextContent(text=text)])
        CHAT_DIAG.send_started(msg.msg_id, to, ctx.session, ROUND.get("need", {}).get("id", ""))
        log_msg(ctx, "buyer", "owner", "reply")
        try:
            result = await ctx.send(to, msg)
        except Exception as exc:
            CHAT_DIAG.send_exception(msg.msg_id, exc)
            raise
        CHAT_DIAG.send_result(msg.msg_id, result)


async def tell_owner(ctx: Context, text: str):
    """Step events wait here and ride along at the top of the next owner message, so a round sends
    two chat messages (ack and result) instead of five: ASI:One rate-limits bursts (HTTP 429)."""
    if ROUND.get("owner"):
        pending = ROUND.pop("events", [])
        await tell(ROUND.get("owner_context") or ctx, ROUND["owner"], "\n".join(pending + [text]))


def blocked_reasons(sender: str, text: str, context: dict | None = None) -> str | None:
    verdict = common.screen(str(uuid4()), sender, text, context)
    if verdict.get("verdict") == "allow":
        return None
    return "; ".join(verdict.get("reasons", [])) or verdict.get("verdict", "blocked")  # quarantine counts as blocked


async def emit(ctx: Context, cls: str, text: str):
    """Step event: at most one per class per goal per 10 minutes reaches the owner; the rest are only logged."""
    now = business_now().timestamp()
    if hunt.should_emit(ROUND.setdefault("last_sent", {}), cls, now):
        ROUND["last_sent"][cls] = now
        if cls == "progress to goal":  # between rounds, nothing else is coming soon: send it now
            await tell_owner(ctx, text)
        else:
            ROUND.setdefault("events", []).append(text)
            ctx.logger.info(f"step event ({cls}, sent with the next message)")
    else:
        ctx.logger.info(f"step event ({cls}, throttled)")


def set_state(state: str):
    if ROUND.get("goal"):
        ROUND["goal"]["state"] = state


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    CHAT_DIAG.inbound(msg.msg_id, sender, ctx.session, ROUND.get("need", {}).get("id", ""))
    ack = ChatAcknowledgement(acknowledged_msg_id=msg.msg_id)
    try:
        result = await ctx.send(sender, ack)
    except Exception as exc:
        CHAT_DIAG.ack_send_result(msg.msg_id, sender, ctx.session, error=exc)
        raise
    CHAT_DIAG.ack_send_result(msg.msg_id, sender, ctx.session, result=result)
    command = hunt.command(msg.text().strip())
    if ROUND.get("owner") == sender and command:
        ROUND["owner_context"] = ctx
        ROUND["owner_session"] = ctx.session
    await handle_text(ctx, sender, msg.text().strip())


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    CHAT_DIAG.acknowledged(msg.acknowledged_msg_id, sender)


@agent.on_rest_post("/chat", WebIn, WebOut)
async def web_post(ctx: Context, req: WebIn) -> WebOut:
    await handle_text(ctx, WEB, req.text.strip())
    return web_drain()


@agent.on_rest_get("/chat", WebOut)
async def web_get(ctx: Context) -> WebOut:
    return web_drain()


def web_drain() -> WebOut:
    out = WEB_OUTBOX[:]
    WEB_OUTBOX.clear()
    return WebOut(replies=out)


def round_finished() -> bool:
    """True once the round is done, expired or paused and nothing is awaiting approval or settlement."""
    tx = ROUND.get("transaction")
    if ROUND.get("pending_hold") or (isinstance(tx, dict) and tx.get("phase") in HELD_PHASES):
        return False  # an approved, submitted or unresolved purchase keeps the owner gate
    if ROUND.get("order"):
        m = ROUND.get("mandate") or {}
        try:
            if datetime.fromisoformat(m["expires_at"].replace("Z", "+00:00")) >= datetime.now(timezone.utc):
                return False  # payment still to be requested and committed
        except (KeyError, ValueError, TypeError):
            return False
    state = (ROUND.get("goal") or {}).get("state")
    return ROUND.get("phase") == "done" or state in ("DONE", "EXPIRED", "PAUSED")


HELD_PHASES = {"pending_approval", "paused", "approved", "submitted", "uncertain"}


async def handle_text(ctx: Context, sender: str, text: str):
    if sender == ROUND.get("owner") and (hunt.command(text) or ("",))[0] == "approve":
        await tell(ctx, sender, "Approval happens on a phone call, not in chat. Nothing was approved or ordered.")
        return
    if ROUND.get("pending_hold"):
        if sender == ROUND.get("owner"):
            await tell(ctx, sender, "A previous approved or submitted purchase is unresolved. I cannot start another goal yet.")
        else:
            await tell(ctx, sender, "A buyer session is active. Try again later.")
        return
    tx = ROUND.get("transaction")
    if isinstance(tx, dict) and tx.get("phase") in {"pending_approval", "paused", "approved", "submitted", "uncertain"}:
        if sender == ROUND.get("owner"):
            await tell(ctx, sender, "A purchase is pending approval or settlement. It remains held; no new goal can start.")
        else:
            await tell(ctx, sender, "A buyer session is active. Try again later.")
        return
    web_round = (str(ROUND.get("goal", {}).get("market_buyer_id", "")).startswith("b_") and ROUND.get("owner") is None
                 and ROUND.get("phase") not in (None, "done"))
    if web_round:  # an adopted web hunt belongs to no chat sender: never let a chat goal wipe it
        if not ROUND.get("told_busy"):
            ROUND["told_busy"] = True
            await tell(ctx, sender, "A sealed round is already running; results soon.")
        return
    released = False
    # Single buyer deployment: no sender other than the owner of the active round sees its state.
    if ROUND.get("owner") and sender != ROUND["owner"]:
        if round_finished():
            released = True  # release the gate: this sender may start a fresh round below
        else:
            if not ROUND.get("told_foreign"):  # once per round
                ROUND["told_foreign"] = True
                await tell(ctx, sender, "A buyer session is active. Try again later.")
            return
    state = ROUND.get("goal", {}).get("state")
    terminal = (ROUND.get("phase") in ("done", "expired", "paused")
                or state in ("DONE", "EXPIRED", "PAUSED"))
    cmd = hunt.command(text)
    if cmd and cmd[0] == "cancel" and ROUND.get("owner") == sender:
        if ROUND.get("order"):
            await tell_owner(ctx, "An order has already been placed; CANCEL cannot reverse it. Nothing was canceled.")
            return
        retired_need_ids = list(ROUND.get("retired_need_ids", []))
        need_id = ROUND.get("need", {}).get("id")
        if need_id and need_id not in retired_need_ids:
            retired_need_ids = (retired_need_ids + [need_id])[-RETIRED_NEED_HISTORY:]
        ROUND.clear()
        ROUND["retired_need_ids"] = retired_need_ids
        await tell(ctx, sender, "Cancelled. Nothing ordered. Send a new goal when you are ready.")
        return
    if ROUND.get("phase") == "decided" and not ROUND.get("order") and not terminal and not released:
        # A deal waits for the owner. ASI:One's own assistant also messages us (recaps of our replies);
        # never let that text start a new round or approve anything.
        if not ROUND.get("told_waiting"):
            ROUND["told_waiting"] = True
            await tell(ctx, sender, "A deal is waiting for your approval call. "
                                    "Reply CANCEL to drop it and start a new goal.")
        return
    if ROUND.get("order") and not released:
        # Keep the uncertain payment and its ids bound until a completion signal exists.
        if not ROUND.get("told_ordered"):
            ROUND["told_ordered"] = True
            await tell(ctx, sender, "An order is already placed; its payment status is unresolved. "
                                    "A new goal cannot replace it yet.")
        return
    if not terminal and not released and ROUND.get("phase") in ("checking", "bidding", "advice", "requote"):
        if not ROUND.get("told_busy"):  # once per round: ASI:One rate-limits bursts of replies
            ROUND["told_busy"] = True
            await tell(ctx, sender, "A sealed round is already running; results soon.")
        return
    buyer_id = sender  # one ownership memory per chat identity
    try:
        goal, told = parse_goal(text, buyer_id)
    except ValueError as e:
        await tell(ctx, sender, f"I could not read a goal from that. {e}")
        return
    try:
        db = state_db()
        buyer_state.remember_owned(db, buyer_id, told)
        owned = buyer_state.load_owned_parts(db, buyer_id)
        goal = apply_owned(goal, owned)
        buyer_state.save_goal(db, goal)
    except Exception as exc:
        ctx.logger.warning(f"Private buyer state unavailable: {type(exc).__name__}")
        await tell(ctx, sender, "Private buyer state is unavailable. Nothing was ordered.")
        return
    need = need_from_goal(goal)
    retired_need_ids = list(ROUND.get("retired_need_ids", []))
    old_need_id = ROUND.get("need", {}).get("id")
    if old_need_id and old_need_id != need["id"]:
        retired_need_ids = (retired_need_ids + [old_need_id])[-RETIRED_NEED_HISTORY:]
    ROUND.clear()
    # Async seller/advocate callbacks must reply on the owner's Chat Protocol session.
    ROUND.update(owner=sender, owner_context=ctx if sender != WEB else None,
                 goal=goal, owned=owned, need=need, bids=[], personas={}, cards={},
                 attempts=0, last_sent={}, retired_need_ids=retired_need_ids, market_goal_posted=False,
                 received_bids={})
    log_msg(ctx, "owner", "buyer", "goal")
    out = skip_lines(goal, owned)
    if not need["items"]:
        set_state("DONE")
        ROUND["phase"] = "done"
        await tell_owner(ctx, "\n".join(out + ["You already own everything on that list. Nothing to buy."]))
        return
    if not await start_round(ctx, need):
        return
    n_sellers = len(live_sellers())
    lines = "\n".join(f"- {i['quantity']} x {i['sku_spec']} ({i['condition']}, {i['variant']})" for i in need["items"])
    out.append(f"Goal: under ${goal['cap']:.0f} by {goal['deadline'][:10]}. Sealed round open for "
               f"{need['auction_window_s']}s with {n_sellers} seller{'s' if n_sellers != 1 else ''} (they never see your cap):\n{lines}")
    await tell_owner(ctx, "\n".join(out))


def live_sellers() -> list[str]:
    """The sellers that can run in this mode. On Agentverse a seller still on its public dev seed is skipped by
    sellers/run_all.py, so it is neither asked for a bid nor counted in what the owner is told. A retired seller
    (common.RETIRED_SELLERS, #398) is not run, so it is not asked either."""
    return [s for s in common.SELLERS if common.mailbox_ready(s) and s not in common.RETIRED_SELLERS]


GOAL_POLL_S = 8.0
LAST_GOAL_POLL = float("-inf")
GOAL_ATTEMPTS: dict[str, int] = {}  # ponytail: in memory, resets on restart, which is fine
GOAL_MAX_ATTEMPTS = 3


def _web_goal(row: dict) -> dict:
    """An open market goal row in the dict shape need_from_goal expects."""
    from market_bridge import _timestamp_iso
    items = [{"part": "", "sku_spec": i.get("sku_spec"), "condition": i.get("condition") or "new",
              "variant": i.get("variant") or "retail", "quantity": i.get("quantity"),
              **({"skipped_owned_part_id": i["skipped_owned_part_id"]} if i.get("skipped_owned_part_id") else {})}
             for i in row.get("items", [])]
    return {"id": row["id"], "buyer_id": row["buyer_id"], "type": row.get("type"), "items": items,
            "cap": float(row["cap"]), "deadline": _timestamp_iso(row["deadline"]), "state": "ACTIVE",
            "market_buyer_id": row["buyer_id"]}


async def adopt_open_goal(ctx: Context) -> bool:
    """Pick up a web buyer's ACTIVE market goal and hunt it. # ponytail: one round at a time; the rest wait their turn."""
    if ROUND.get("pending_hold") or ROUND.get("phase") not in (None, "done"):
        return False
    global LAST_GOAL_POLL
    if time.monotonic() - LAST_GOAL_POLL < GOAL_POLL_S:
        return False
    LAST_GOAL_POLL = time.monotonic()
    try:
        goals = await asyncio.to_thread(market_clients()[1].open_goals)
    except Exception:
        return False
    db, now = state_db(), business_now()

    def _skip(g: dict) -> bool:
        gid = str(g.get("id", ""))
        try:
            return (not gid or buyer_state.goal_handled(db, gid) or buyer_state.goal_has_transaction(db, gid)
                    or datetime.fromisoformat(_web_goal(g)["deadline"].replace("Z", "+00:00")) <= now)
        except Exception:
            return True  # fail closed

    row = next((g for g in goals if str(g.get("buyer_id", "")).startswith("b_") and not _skip(g)), None)
    if row is None:
        return False
    def _give_up(ctx_, why: str) -> None:
        try:
            buyer_state.mark_goal_handled(db, row["id"], row["buyer_id"])
        except Exception:
            ctx_.logger.warning(f"Open goal {row.get('id')} {why} but could not be recorded as handled")

    def _failed() -> None:  # one always-failing goal must not block the goals behind it
        n = GOAL_ATTEMPTS[row["id"]] = GOAL_ATTEMPTS.get(row["id"], 0) + 1
        if n >= GOAL_MAX_ATTEMPTS:
            ctx.logger.warning(f"Open goal {row.get('id')} given up after {n} attempts")
            _give_up(ctx, "given up")

    try:
        goal = _web_goal(row)
        need = need_from_goal(goal)
    except Exception as exc:
        ctx.logger.warning(f"Open goal {row.get('id')} skipped: {type(exc).__name__}")
        _failed()
        return False
    if not need["items"]:
        ctx.logger.warning(f"Open goal {row.get('id')} has nothing left to buy; marked handled")
        _give_up(ctx, "has nothing to buy")
        return False
    ROUND.clear()
    ROUND.update(owner=None, owner_context=None, goal=goal, owned=[], need=need, bids=[], personas={}, cards={},
                 attempts=0, last_sent={}, retired_need_ids=[], market_goal_posted=True, received_bids={})
    started = bool(await start_round(ctx, need))
    if started:
        GOAL_ATTEMPTS.pop(row["id"], None)
        _give_up(ctx, "hunted")
    else:
        _failed()
    return started


async def start_round(ctx: Context, need: dict | None = None):
    """Open a sealed round. A retry gets a fresh Need id so stale bids from the last round cannot count."""
    need = need or need_from_goal(ROUND["goal"])
    retired_need_ids = list(ROUND.get("retired_need_ids", []))
    old_need_id = ROUND.get("need", {}).get("id")
    if old_need_id and old_need_id != need["id"]:
        retired_need_ids = (retired_need_ids + [old_need_id])[-RETIRED_NEED_HISTORY:]
    token = uuid4().hex
    ROUND.update(need=need, retired_need_ids=retired_need_ids, bids=[], personas={}, cards={}, seller_checks={},
                 received_bids={}, screened_bids={},
                 reviewed=False, order=None, mandate=None, told_foreign=False,
                 phase="checking", deadline=0, round_token=token)
    set_state("HUNTING")
    try:
        buyer_market, referee_market = market_clients()
        market_buyer_id = ROUND["goal"].get("market_buyer_id") or MARKET_BUYER_ID
        # A web buyer's goal is already in the market; the referee posts its need against that goal id.
        need_poster = buyer_market if ROUND.get("owner") else referee_market
        if not market_buyer_id:
            raise MarketBridgeError("market_buyer_id_missing")
        ROUND["market_buyer_id"] = market_buyer_id
        goal = dict(ROUND["goal"], buyer_id=market_buyer_id)
        if not ROUND.get("market_goal_posted"):
            buyer_market.post_goal(goal, buyer_id=market_buyer_id)
            ROUND["market_goal_posted"] = True
        market_need = dict(need, buyer_id=market_buyer_id)
        need_poster.post_need(market_need, buyer_id=market_buyer_id, goal_id=goal["id"])
        round_id = f"round-{need['id']}"
        referee_market.open_round(round_id, need["id"], need["auction_window_s"])
        if referee_market.round_status(round_id).get("state") != "open":
            raise MarketBridgeError("round_open_readback_invalid")
        ROUND.update(market_round_id=round_id)
    except Exception as exc:
        ctx.logger.warning(f"Market round setup failed: {type(exc).__name__}")
        ROUND.update(phase="done", round_token=uuid4().hex)
        await tell_owner(ctx, "Market setup could not be verified. Nothing ordered.")
        return False
    try:
        checks = await crs.check_sellers(business_now())
    except Exception:
        ctx.logger.warning("CRS checks failed; business sellers will be ineligible for this round.")
        checks = {}
    if ROUND.get("round_token") != token or ROUND.get("phase") != "checking" or ROUND.get("need") is not need:
        return False
    asked = live_sellers()
    ROUND.update(seller_checks=checks, asked=asked, phase="bidding", deadline=business_now().timestamp() + need["auction_window_s"])
    for s in asked:
        if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need["id"]:
            return False
        log_msg(ctx, "buyer", s, "bid_request")
        await ctx.send(common.address(s), common.BidRequest(need_json=json.dumps(sealed(need))))
        if (ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need["id"]
                or ROUND.get("phase") != "bidding"):
            return False
    return True


async def fail_round(ctx: Context, why: str, *, always_notify: bool = False):
    """No eligible bid this round: retry every RETRY_S until the deadline, PAUSED after MAX_ATTEMPTS."""
    ROUND["reviewed"] = False
    ROUND["attempts"] = ROUND.get("attempts", 0) + 1
    state = hunt.after_failed_round(ROUND["attempts"])
    set_state(state)
    if state == "PAUSED":
        ROUND["phase"] = "done"
        await tell_owner(ctx, f"{why} That was {ROUND['attempts']} rounds without a deal, so I paused this goal. "
                              f"Send your goal again to restart.")
        return
    ROUND.update(phase="waiting", next_round_at=business_now().timestamp() + hunt.RETRY_S)
    text = (f"{why} Still hunting: next round in {hunt.RETRY_S}s "
            f"(attempt {ROUND['attempts']} of {hunt.MAX_ATTEMPTS}).")
    if always_notify:
        await tell_owner(ctx, text)
    else:
        await emit(ctx, "progress to goal", text)


async def restart_card(ctx: Context, why: str):
    token, need_id = ROUND.get("round_token"), ROUND.get("need", {}).get("id")
    await tell_owner(ctx, f"{why} Nothing ordered; restarting the hunt with a fresh round.")
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    await start_round(ctx)


@agent.on_message(common.BidReply)
async def on_bid(ctx: Context, sender: str, msg: common.BidReply):
    token, need_id = ROUND.get("round_token"), ROUND.get("need", {}).get("id")
    if sender not in SELLER_ADDRS:
        ctx.logger.info("bid from unregistered sender ignored")
        return
    bid = None
    try:
        bid = common.validate("Bid", json.loads(msg.bid_json))
    except Exception:
        pass
    if (bid and bid["need_id"] in ROUND.get("retired_need_ids", [])
            and bid.get("supplier_id") == SELLER_ADDRS[sender]):
        ctx.logger.info("stale bid ignored")
        return
    references = cached_shield_baseline(i.get("sku_spec") for i in ROUND.get("need", {}).get("items", []) if isinstance(i, dict))
    verdict = common.screen_bid(str(uuid4()), sender, msg.bid_json, msg.persona_line, references)  # real dated prices, re-read past the TTL
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    reasons = None if verdict.get("verdict") == "allow" else "; ".join(verdict.get("reasons", [])) or verdict.get("verdict")
    if ROUND.get("phase") not in ("bidding", "requote") or business_now().timestamp() > ROUND["deadline"]:
        ctx.logger.info("late or stray bid ignored")
        return
    try:
        bid = bid or common.validate("Bid", json.loads(msg.bid_json))
    except Exception as exc:
        ctx.logger.warning(f"invalid bid dropped: {type(exc).__name__}")
        if reasons:  # Shield's verdict still reaches the owner even when the payload is not a valid Bid
            await tell_owner(ctx, f"Smell Test blocked a bid from {SELLER_ADDRS[sender]}: {reasons}")
        return
    if bid["need_id"] != ROUND["need"]["id"]:
        return
    if bid.get("supplier_id") != SELLER_ADDRS[sender]:
        ctx.logger.info("bid supplier does not match its registered sender; ignored")
        return
    if bid["origin"] not in {"LIVE", "MIRROR", "SIM"}:
        ctx.logger.info("bid has an invalid origin; ignored")
        return
    ROUND.setdefault("received_bids", {})[bid["id"]] = bid
    ROUND.setdefault("personas", {})[bid["id"]] = msg.persona_line
    ROUND.setdefault("screened_bids", {})[bid["id"]] = {
        "verdict": verdict["verdict"],
        "rule_ids": verdict.get("rule_ids", verdict.get("reasons", [])),
        "origin": bid["origin"],
    }
    if reasons:
        await tell_owner(ctx, f"Smell Test blocked a bid from {SELLER_ADDRS[sender]}: {reasons}")
        return
    if ROUND["phase"] == "requote":
        await on_requote(ctx, bid)
        return
    ROUND["bids"].append(bid)
    log_msg(ctx, SELLER_ADDRS[sender], "buyer", "bid")
    ROUND["personas"][bid["id"]] = msg.persona_line
    await emit(ctx, "bid in", f"Bid in: {bid['persona']} at ${bid['total_landed_price']:.2f} (sealed round still open).")


@agent.on_message(common.AdviceReply)
async def on_advice(ctx: Context, sender: str, msg: common.AdviceReply):
    token, need_id = ROUND.get("round_token"), ROUND.get("need", {}).get("id")
    if sender != common.address("advocate") or ROUND.get("phase") != "advice":
        return
    raw = None
    try:
        raw = json.loads(msg.cards_json)
    except Exception:
        pass
    raw_need_ids = ([c.get("need_id") for c in raw]
                    if isinstance(raw, list) and raw and all(isinstance(c, dict) for c in raw) else [])
    if (raw_need_ids and all(isinstance(value, str) and value for value in raw_need_ids)
            and len(set(raw_need_ids)) == 1
            and raw_need_ids[0] in ROUND.get("retired_need_ids", [])):
        ctx.logger.info("stale advocate reply ignored")
        return
    reasons = blocked_reasons(sender, msg.cards_json, common.shield_context(sender))
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    cards = None
    if isinstance(raw, list) and raw:
        try:
            cards = [common.validate("AdvocateCard", c) for c in raw]
        except Exception:
            cards = None
    if reasons:
        await fail_round(ctx, f"Smell Test blocked the advocate's reply: {reasons}. Nothing ordered.", always_notify=True)
        return
    try:
        if not isinstance(raw, list):
            raise ValueError("expected a list of review cards")
        cards = cards or [common.validate("AdvocateCard", c) for c in raw]
        review_bids = ROUND.get("review_bids", [])
        if (not cards or len(cards) != len(review_bids)
                or {c["bid_id"] for c in cards} != {b["id"] for b in review_bids}
                or any(c["need_id"] != ROUND["need"]["id"]
                       or c["recommendation"] not in ("buy", "caution", "veto") for c in cards)):
            raise ValueError("expected one current review per bid, with buy, caution or veto")
    except Exception as exc:
        ctx.logger.warning(f"invalid advocate reply: {type(exc).__name__}")
        await fail_round(ctx, "The advocate's review was invalid or incomplete. Nothing ordered.", always_notify=True)
        return
    ROUND["cards"] = {c["bid_id"]: c for c in cards}
    try:
        _record_market_reviews(cards)
        _, referee_market = market_clients()
        status = referee_market.round_status(ROUND["market_round_id"])
        if status.get("state") != "review":
            raise MarketBridgeError("market_review_closed")
        ROUND["deadline"] = _market_timestamp(status.get("review_deadline"))
    except Exception as exc:
        ctx.logger.warning(f"Market review write failed: {type(exc).__name__}")
        await fail_round(ctx, "Market could not record the independent review. Nothing ordered.", always_notify=True)
        return
    ROUND["phase"] = "market_review_wait"
    if business_now().timestamp() >= ROUND["deadline"]:
        await _finish_market_round(ctx)


@agent.on_interval(period=1.0)
async def tick(ctx: Context):
    CHAT_DIAG.expire()
    await adopt_open_goal(ctx)
    now = business_now().timestamp()
    goal = ROUND.get("goal")
    transaction = ROUND.get("transaction")
    tx_phase = transaction.get("phase") if isinstance(transaction, dict) else None
    goal_state = goal.get("state") if isinstance(goal, dict) else None
    if (goal_state in {"DONE", "EXPIRED", "PAUSED"} or ROUND.get("pending_hold")
            or tx_phase in {"pending_approval", "paused", "approved", "submitted", "uncertain"}):
        # A purchase hold is governed by its durable transaction and exact seller ACK,
        # not the original hunt deadline. Terminal goals are never re-expired or restarted.
        return
    if ROUND.get("goal") and hunt.expired(ROUND["goal"], now=business_now()):
        set_state("EXPIRED")
        ROUND["phase"] = "done"
        ROUND["round_token"] = uuid4().hex
        await tell_owner(ctx, f"Your deadline ({ROUND['goal']['deadline'][:10]}) passed before a deal closed. "
                              f"Goal EXPIRED; nothing ordered. Send it again with a new date to keep hunting.")
        return
    if ROUND.get("phase") == "waiting" and now >= ROUND["next_round_at"]:
        await start_round(ctx)
    elif ROUND.get("phase") == "requote" and now > ROUND["deadline"]:
        await restart_card(ctx, f"Bid #{ROUND['pick']}'s seller did not reconfirm its price.")
    elif ROUND.get("phase") == "market_review_wait" and now >= ROUND["deadline"]:
        await _finish_market_round(ctx)
    elif ROUND.get("phase") == "bidding" and now > ROUND["deadline"]:
        try:
            review_bids = _begin_market_review()
            _, referee_market = market_clients()
            review_deadline = _market_timestamp(referee_market.round_status(ROUND["market_round_id"])
                                                 .get("review_deadline"))
        except Exception as exc:
            ctx.logger.warning(f"Market review could not be opened: {type(exc).__name__}")
            await fail_round(ctx, "Market could not verify the sealed round cutoff. Nothing ordered.", always_notify=True)
            return
        ROUND["quoted_at"] = now
        ROUND["review_bids"] = review_bids
        ROUND["phase"] = "market_review_wait" if not review_bids else "advice"
        ROUND["deadline"] = review_deadline if not review_bids else min(review_deadline, now + ADVICE_TIMEOUT_S)
        if not review_bids:
            return
        # The advocate sees the owned parts for fit checks, but not the cap.
        advice_need = advice_need_for(ROUND["need"], owned_attrs(ROUND["owned"]), ROUND["bids"])
        token, need_id = ROUND.get("round_token"), ROUND.get("need", {}).get("id")
        log_msg(ctx, "buyer", "advocate", "advice_request")
        try:
            await ctx.send(common.address("advocate"), common.AdviceRequest(
                need_json=json.dumps(advice_need), bids_json=json.dumps(review_bids)))
        except Exception as exc:
            if (ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id
                    or ROUND.get("phase") != "advice"):
                return
            ctx.logger.warning(f"advocate request failed: {type(exc).__name__}")
            await fail_round(ctx, "I could not reach the advocate for a review. Nothing ordered.", always_notify=True)
        if (ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id
                or ROUND.get("phase") != "advice"):
            return
    elif ROUND.get("phase") == "advice" and now > ROUND["deadline"]:
        await fail_round(ctx, "The advocate did not reply in time. Nothing ordered.", always_notify=True)


async def conclude(ctx: Context, reviewed: bool):
    token, need_id = ROUND.get("round_token"), ROUND.get("need", {}).get("id")
    if not reviewed:
        await fail_round(ctx, "The advocate has not completed its review. Nothing ordered.", always_notify=True)
        return
    ROUND["reviewed"] = True
    need, bids, cards = ROUND["need"], ROUND["bids"], ROUND["cards"]
    ROUND["phase"] = "decided"
    out = [f"{len(bids)} sealed bids for {need['id']} (your cap ${need['spend_limit']:.2f}):"]
    now_utc = business_now()
    seller_checks = ROUND.get("seller_checks", {})
    not_configured_suppliers = {
        b["supplier_id"] for b in bids
        if crs.to_crs_check(b["supplier_id"], seller_checks.get(b["supplier_id"])).get("origin") == "NOT_CONFIGURED"
    }
    if not_configured_suppliers and not ROUND.get("crs_notice_sent"):
        ROUND["crs_notice_sent"] = True
        await tell_owner(ctx, CRS_NOT_CONFIGURED_NOTICE)
        if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
            return
    eligible_suppliers = {b["supplier_id"] for b in bids
                          if crs.eligible(b["supplier_id"], seller_checks.get(b["supplier_id"]), now_utc)}
    for n, b in enumerate(bids, 1):
        card = cards.get(b["id"], {})
        rec = card.get("recommendation", "not reviewed")
        out.append(f"{n}. {b['persona']}: ${b['total_landed_price']:.2f} [{b['source']}]")
        if not not_partners.orderable(b):  # #333: code-owned label, never the bid's own text
            out.append(f"   {not_partners.label(b) or 'MIRROR listing.'} {not_partners.NOT_ORDERABLE}")
        check = ROUND.get("seller_checks", {}).get(b["supplier_id"], {})
        signal = check.get("signal")
        supplier_not_configured = b["supplier_id"] in not_configured_suppliers
        reason = ("Seller eligibility was not verified."
                  if supplier_not_configured
                  else "Trusted individual seller; CRS check exempt."
                  if b["supplier_id"] in eligible_suppliers and not signal
                  else check.get("reason") or crs.REASON_UNAVAILABLE)
        if signal:
            status = f"CRS: {signal['stability']} - {reason}"
            if signal["source"] == "recorded":
                status += f" (cached from CRS {signal['checked_at']})"
        elif supplier_not_configured:
            status = f"CRS: not configured - {reason}"
        else:
            status = f"CRS: {'exempt' if b['supplier_id'] in eligible_suppliers else 'ineligible'} - {reason}"
        out.append(f"   {status}")
        out.append(f"   Advocate: {rec}")
        for w in card.get("warnings", [])[:3]:
            out.append(f"   ! {w['text']} (source: {w['source_url']})")
    winner = ROUND.get("market_winner")
    best = (1 if winner and bids and winner.get("id") == bids[0].get("id")
            and crs.eligible(winner["supplier_id"], seller_checks.get(winner["supplier_id"]), now_utc)
            and not_partners.orderable(winner) and not_partners.orderable(bids[0]) else None)
    asked = ROUND.get("asked") or [b["supplier_id"] for b in bids]
    out.append(round_trace(asked, bids, cards, bids[best - 1] if best else None))
    vetoed = [b["persona"] for b in bids if cards.get(b["id"], {}).get("recommendation") == "veto"]
    if vetoed:
        await emit(ctx, "veto", f"Advocate vetoed {len(vetoed)} bid(s): {', '.join(vetoed)}.")
        if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
            return
    if best is None:
        if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
            return
        await tell_owner(ctx, "\n".join(out))
        if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
            return
        why = ("No seller passed the CRS eligibility check. Nothing ordered." if not eligible_suppliers
               else f"The best bid is a MIRROR listing from a store that never joined. {not_partners.NOT_ORDERABLE} "
                    "Nothing ordered." if winner and not not_partners.orderable(winner)
               else "Every eligible bid was vetoed by the advocate.")
        await fail_round(ctx, why)
        return
    # Every order uses the current private owner approval service; no old price threshold is an approval.
    verdict = decide(need, bids[best - 1], 0)
    if verdict == "over_limit":
        if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
            return
        await tell_owner(ctx, "\n".join(out))
        if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
            return
        await fail_round(ctx, f"Best eligible bid #{best} is over your ${need['spend_limit']:.2f} cap.")
        return
    b = bids[best - 1]
    await emit(ctx, "deal found", f"Deal found: {b['persona']} at ${b['total_landed_price']:.2f}, "
                                  f"${need['spend_limit'] - b['total_landed_price']:.2f} under your cap.")
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    set_state("HOLD_FOR_CALL")
    if not ROUND.get("owner"):  # adopted web goal: no owner chat
        ROUND.update(pick=best, quoted_at=business_now().timestamp())
        await _auto_web_approval(ctx, best)
        return
    ready = eligible_for_order(best)
    out.append(f"This purchase needs your approval by phone call. Getting a fresh quote for bid #{best} "
               f"(good for {hunt.QUOTE_TTL_S // 60} minutes), then calling you." if ready
               else f"Bid #{best} is unreviewed or vetoed, so I will not order it. Nothing ordered.")
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    await tell_owner(ctx, "\n".join(out))
    if ready and ROUND.get("round_token") == token and ROUND.get("need", {}).get("id") == need_id:
        await _start_requote(ctx, best)

async def _start_requote(ctx: Context, n: int):
    """Ask the seller to reconfirm bid n; on_requote then saves the deal and starts the approval call."""
    bids = ROUND.get("bids", [])
    if ROUND.get("phase") != "decided" or ROUND.get("transaction") is not None or not eligible_for_order(n):
        await tell_owner(ctx, f"No reviewed bid #{n} is ready for approval.")
        return
    if business_now().timestamp() - ROUND.get("quoted_at", 0) > hunt.QUOTE_TTL_S:
        await restart_card(ctx, f"Bid #{n}'s quote expired; the round needs a fresh review.")
        return
    ROUND.update(phase="requote", pick=n, deadline=business_now().timestamp() + ADVICE_TIMEOUT_S)
    log_msg(ctx, "buyer", bids[n - 1]["supplier_id"], "bid_request")
    await ctx.send(common.address(bids[n - 1]["supplier_id"]),
                   common.BidRequest(need_json=json.dumps(sealed(ROUND["need"]))))


def _approval_service():
    global APPROVAL_SERVICE
    from pay.approval import ApprovalService
    if APPROVAL_SERVICE is None:
        from pay.voice_cartesia import CALL_CODE_TTL_S
        APPROVAL_SERVICE = ApprovalService(store=nonce_store(), code_ttl_seconds=CALL_CODE_TTL_S)
    if getattr(APPROVAL_SERVICE, "store", None) is not nonce_store():
        raise RuntimeError("approval service must use the protected shared nonce store")
    return APPROVAL_SERVICE


def _approval_call(buyer_id: str = ""):
    """(client, reason, buyer_name) for the approval phone call. Approval is only ever the spoken code on that call,
    so with no client configured the buyer fails closed: no approval, no payment. The number is the buyer's own
    profile phone; only the env-default buyer may fall back to APPROVAL_CALL_TO."""
    from pay.voice_cartesia import CartesiaClient, CartesiaError, TO_ENV, load_env
    try:
        profile = market_clients()[1].buyer_contact(buyer_id) if buyer_id else None
    except Exception:
        profile = None
    profile = profile if isinstance(profile, dict) else {}
    env = load_env()
    # one rule with the CLI path: the buyer's own plain display_name, else "there"; APPROVAL_BUYER_NAME is only the default buyer's
    from pay.voice_cartesia import greeting_name
    name = greeting_name(buyer_id, env, lambda _b: profile.get("display_name"))
    if APPROVAL_CALL_CLIENT is not None:
        return APPROVAL_CALL_CLIENT, "", name
    phone = profile.get("phone")
    if not phone and not (buyer_id and buyer_id == MARKET_BUYER_ID):
        import logging
        logging.getLogger("buyer_agent").warning(f"approval call refused for buyer {buyer_id}: no phone on file")
        return None, "not_configured", name
    try:
        return CartesiaClient.from_env({**env, TO_ENV: phone} if phone else env), "", name
    except CartesiaError:
        return None, "not_configured", name


def _is_web_buyer(buyer_id, owner) -> bool:
    """Web buyers (market id "b_...", or no chat owner) have no ASI:One chat to receive the approval code."""
    return str(buyer_id or "").startswith("b_") or not owner


async def _phone_approval(transaction: dict, send_private, client, service, buyer_name: str = "there"):
    """The only approval: the owner speaks a one-time code on a phone call (buyer.checkout.approve_offer).
    The private chat shows the code and the outcome; no chat text or typed code is ever accepted as approval."""
    from buyer import checkout
    from pay.voice_cartesia import VoiceResult
    loop = asyncio.get_running_loop()
    deal_id = transaction.get("deal_id", "this deal")
    buyer_id = transaction.get("buyer_id", "")
    web = _is_web_buyer(buyer_id, (transaction.get("deal") or {}).get("owner_sender"))

    def on_code(code: str) -> None:
        try:  # every buyer: the market shows the code on /buyer. Never log the code.
            market_clients()[1].issue_approval_code(transaction["mandate"]["hash"], code)
        except Exception:
            if web:
                raise PermissionError("approval code could not be shown") from None
            import logging
            logging.getLogger("buyer_agent").warning(f"approval code not shown on /buyer for buyer {buyer_id}")
        if web:  # no chat: the market's own approval view shows the code on /buyer; never send it elsewhere
            import logging
            logging.getLogger("buyer_agent").info(f"web buyer {buyer_id}: code shown on /buyer")
            return
        text = f"One-time approval code: {code}. Calling your phone now: say the code, then say approve."
        try:
            future = asyncio.run_coroutine_threadsafe(send_private(text), loop)
            delivered = future.result(timeout=10.0)
        except Exception:
            raise PermissionError("private approval delivery failed") from None
        if delivered is False:
            raise PermissionError("private approval delivery failed")

    try:
        result = await asyncio.to_thread(checkout.approve_offer, dict(transaction), client, service,
                                         on_code=on_code, buyer_name=buyer_name, now=business_now)
    except Exception:
        result = VoiceResult(False, "private_approval_unavailable")
    try:
        if web:
            pass  # the web shows the outcome from the market rows
        elif result.approved:
            await send_private(f"Approval confirmed for deal {deal_id}. Payment is not confirmed by this approval.")
        else:
            await send_private(f"Approval not granted for deal {deal_id}.")
    except Exception:
        pass
    return result


# ---- #398 item 3: Bazaar Caller carries the voice only (off unless BUYER_DELEGATE_CALL=1) ----------------------------
PENDING_TRANSPORT: dict = {}   # mandate hash -> concurrent.futures.Future waiting for the Caller's VoiceTransportResult
USED_CALL_IDS: set = set()     # a call id the Caller already reported is never accepted again (replay)


def delegate_call_enabled() -> bool:
    return os.getenv("BUYER_DELEGATE_CALL") == "1"


def delegation_allowed(transaction: dict) -> bool:
    """Delegate the voice only when it is switched on and the buyer is not a web sign-up (a `b_` id from the market's
    sign_up reducer): a web buyer always gets the buyer's own direct call (#405 review)."""
    buyer_id = str(transaction.get("buyer_id") or "")
    return delegate_call_enabled() and bool(buyer_id) and not buyer_id.startswith("b_")


def market_approval_matches(status, mandate: dict) -> bool:
    """The market's own record of this purchase, re-read after record_approval: a voice approval for exactly the
    mandate the buyer issued (hash, amount, payee), not retired. Any mismatch means no payment."""
    from decimal import Decimal, InvalidOperation
    try:
        same_amount = Decimal(str(status.get("amount"))).quantize(Decimal("0.01")) == \
            Decimal(str(mandate.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError, TypeError, ValueError):
        return False
    return (isinstance(status, dict) and status.get("approval_method") == "voice_code" and bool(status.get("approved_at"))
            and status.get("mandate_hash") == mandate.get("hash") and status.get("payee") == mandate.get("payee")
            and same_amount and not status.get("retired"))


def _transport_request(ctx: Context, loop):
    """request(mandate_hash, variables) for DelegatedVoiceClient: send one VoiceTransportRequest to the Caller and wait
    for its VoiceTransportResult (runs in the approval worker thread)."""
    import concurrent.futures
    from buyer.delegate import DELEGATE_TIMEOUT_S

    def request(mandate_hash: str, variables: dict) -> dict:
        future = concurrent.futures.Future()
        PENDING_TRANSPORT[mandate_hash] = future
        try:
            asyncio.run_coroutine_threadsafe(ctx.send(common.address("caller"), common.VoiceTransportRequest(
                mandate_hash=mandate_hash, variables_json=json.dumps(variables))), loop).result(timeout=10.0)
            return future.result(timeout=DELEGATE_TIMEOUT_S)
        finally:
            PENDING_TRANSPORT.pop(mandate_hash, None)
    return request


@agent.on_message(common.VoiceTransportResult)
async def on_voice_transport(ctx: Context, sender: str, msg: common.VoiceTransportResult):
    if sender != common.address("caller"):
        return   # only Bazaar Caller can answer a delegated call
    future = PENDING_TRANSPORT.get(msg.mandate_hash)
    if future is None or future.done():
        return
    try:
        call = json.loads(msg.call_json) if msg.call_json else None
    except Exception:  # noqa: BLE001
        call = None
    future.set_result({"mandate_hash": msg.mandate_hash, "call_id": msg.call_id, "call": call, "error": msg.error})


async def _delegated_approval(ctx: Context, transaction: dict, send_private, direct_client, service, buyer_name: str = "there"):
    """The same approval as _phone_approval, with the voice carried by Bazaar Caller. Only a call that never reached the
    owner falls back to the buyer's own direct call, once: the Caller timed out or failed (transport_failed), or its reply
    failed the buyer's checks (refused). A finished call the buyer judged that is not an approval (a no, a wrong code, the
    code without approve) is final: the owner answered, so the phone never rings again. Nothing is retried through the Caller."""
    from buyer.delegate import DelegatedVoiceClient
    delegated = DelegatedVoiceClient(transaction["mandate"]["hash"], _transport_request(ctx, asyncio.get_running_loop()),
                                     USED_CALL_IDS)
    result = await _phone_approval(transaction, send_private, delegated, service, buyer_name)
    if result.approved or not (delegated.transport_failed or delegated.refused):
        return result
    ctx.logger.warning("Fish Market Caller did not deliver a usable call; placing the approval call directly")
    return await _phone_approval(transaction, send_private, direct_client, service, buyer_name)


async def _pay_web_purchase(ctx: Context, transaction: dict, mandate: dict, order: dict, bid: dict) -> None:
    """A web buyer's phone-approved purchase: one sandbox charge, idempotent on the mandate, then OrderPlaced.
    # ponytail: the owner RequestPayment path needs buyer-role reads a web buyer's agent cannot make, so charge directly."""
    import logging
    from pay import mandate as pay_mandate, merchant_sim
    cents = payment._cents(mandate["amount"])
    if cents is None:
        raise ValueError("web purchase amount is not whole cents")
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    stripe_test = key.startswith("sk_test_")  # a live or restricted key is never used, only a labelled stub
    if stripe_test:
        meta = {"deal_id": mandate["deal_id"], "mandate_hash": mandate["hash"], "origin": "SIM"}
        pi = await asyncio.to_thread(merchant_sim.StripeTestCharger(key).charge, amount_cents=cents, currency="USD",
                                     idempotency_key=pay_mandate.idempotency_key(mandate), metadata=meta)
        pi = pi if isinstance(pi, dict) else {}
        charge_id = pi.get("id")
        if pi.get("status") != "succeeded" or not isinstance(charge_id, str) or not charge_id.startswith(("pi_", "ch_")):
            raise RuntimeError("stripe_test_charge_not_succeeded")
    else:
        charge_id = "ch_sim_" + mandate["hash"][:12]
    mode = "stripe_test" if stripe_test else "sim"
    transaction["payment_ref"] = order["payment_ref"] = charge_id
    transaction["settlement_result"] = {"status": "charged", "charge_id": charge_id, "mandate_hash": mandate["hash"],
                                        "origin": "SIM", "mode": mode}
    order["status"], transaction["phase"] = "charged", "settled"
    buyer_state.save_transaction(state_db(), transaction)
    log = logging.getLogger("buyer_agent")
    try:
        market_clients()[1].record_payment(mandate_hash=mandate["hash"], payment_ref=charge_id,
                                           amount=mandate["amount"], mode=mode)
    except Exception as exc:  # the charge already happened: do not undo it or hold back the order
        log.warning(f"web buyer {transaction['buyer_id']}: payment recorded locally but the market row failed ({type(exc).__name__})")
    await ctx.send(common.address(bid["supplier_id"]), common.OrderPlaced(
        order_json=json.dumps(order), mandate_json=json.dumps(mandate)))
    log.info(f"web buyer {transaction['buyer_id']}: paid deal {transaction['deal_id']}, receipt {charge_id} "
             f"({'Stripe test mode' if stripe_test else 'SIM stub, no money moved'})")
    ROUND.update(transaction=transaction, mandate=mandate, order=order, pending_hold=False, phase="done")


async def _run_owner_approval(ctx: Context, n: int, sender: str, transaction: dict, *, web: bool = False) -> None:
    owner = ROUND.get("owner")
    # web: a market web buyer has no owner chat; the referee client records the approval after the phone call.
    if not web and (not _configured_market_owner_matches(owner)
                    or transaction.get("deal", {}).get("owner_sender") != owner):
        await tell_owner(ctx, "Private purchase approval is not configured for this owner. Nothing was ordered.")
        return
    key = (owner, transaction["deal_id"], transaction["mandate"]["hash"])
    if ROUND.get("approval_wait_key") == key:
        return  # this exact approval call is already in progress
    # Install before the call starts so this deal can never start a second call.
    ROUND["approval_wait_key"] = key

    async def send_private(text: str):
        if web:
            return True
        return await ctx.send(owner, ChatMessage(content=[TextContent(text=text)]))

    try:
        ROUND["phase"] = "approval"
        client, unavailable, buyer_name = await asyncio.to_thread(_approval_call, transaction["buyer_id"])
        if client is None:
            # Fail closed: no approval without the phone call. The transaction is left as it was.
            ROUND["phase"] = "pending_approval"
            if web:  # no phone: terminal, so nothing stays held and chat buyers are not blocked
                transaction["phase"] = "expired"
                buyer_state.save_transaction(state_db(), transaction)
                ROUND["transaction"] = None
            await send_private("Phone approval is not set up, so I could not place the call. "
                               "Nothing was approved, nothing was ordered and nothing was paid.")
            return
        if delegation_allowed(transaction) and not web:
            result = await _delegated_approval(ctx, transaction, send_private, client, _approval_service(), buyer_name)
        else:
            result = await _phone_approval(transaction, send_private, client, _approval_service(), buyer_name)
        if not result.approved or not isinstance(result.record, dict) or result.record.get("channel") != "phone":
            transaction["phase"] = "denied" if result.record and result.record.get("result") == "denied" else "paused"
            if web and transaction["phase"] == "paused":
                transaction["phase"] = "expired"  # terminal: recovery ignores it, so a restart cannot wedge the agent
            buyer_state.save_transaction(state_db(), transaction)
            ROUND["phase"] = "pending_approval"
            await tell_owner(ctx, "The approval call failed or was not approved. Nothing was paid and no order was placed; "
                                  "the deal remains held until it expires.")
            return
        record = result.record
        mandate = dict(transaction["mandate"])
        if (record.get("result") != "approved" or record.get("mandate_hash") != mandate.get("hash")
                or record.get("mandate_id") != mandate.get("id")):
            raise ValueError("approval record does not match the pending mandate")
        mandate.update(status="approved", approval_id=record["id"])
        transaction["mandate"] = mandate
        transaction["voice_approval"] = record
        transaction["phase"] = "approved"
        bid = ROUND["bids"][n - 1]
        order = common.validate("Order", make_order(ROUND["need"], bid, "owner", record["id"]))
        order["id"] = transaction["deal_id"]
        transaction["order"] = order
        buyer_state.save_transaction(state_db(), transaction)
        buyer_market = market_clients()[1 if web else 0]
        method = "voice_code"
        market_status = buyer_market.record_approval(mandate_hash=mandate["hash"], method=method,
                                                       approved_by=transaction["buyer_id"],
                                                       voice_approval_id=record["id"])
        if (not isinstance(market_status, dict) or market_status.get("approval_method") != method
                or (not web and not market_status.get("approved_at"))):  # the referee cannot read the buyer view back
            raise MarketBridgeError("market_approval_readback_mismatch")
        if delegation_allowed(transaction) and not web and not market_approval_matches(buyer_market.purchase_status(mandate["hash"]), mandate):
            raise MarketBridgeError("market_approval_readback_mismatch")  # #398: re-read before anything can be paid
        if web:
            await _pay_web_purchase(ctx, transaction, mandate, order, bid)
            return
        ROUND.update(transaction=transaction, mandate=mandate, order=order,
                     pending_hold=True, phase="approved")
        await ctx.send(common.address(bid["supplier_id"]), common.OrderPlaced(
            order_json=json.dumps(order), mandate_json=json.dumps(mandate)))
        await tell_owner(ctx, f"Approval recorded for deal {transaction['deal_id']}. The seller was asked to request payment; no charge is confirmed yet.")
    except Exception as exc:
        if web:  # web path: terminal "expired" (recovery ignores it); never leave the buyer agent held
            transaction["phase"] = "expired"
            try:
                buyer_state.save_transaction(state_db(), transaction)
            except Exception:
                pass
            ROUND.update(pending_hold=False, phase="done", transaction=None)
            import logging
            logging.getLogger("buyer_agent").warning(
                f"web buyer {transaction.get('buyer_id')}: approval failed ({type(exc).__name__}); round released")
            return
        if transaction.get("phase") == "approved":
            transaction["phase"] = "uncertain"
        try:
            buyer_state.save_transaction(state_db(), transaction)
        except Exception:
            pass
        ROUND.update(transaction=transaction, pending_hold=True, phase="uncertain")
        ctx.logger.warning(f"Private approval or Market readback failed: {type(exc).__name__}")
        await tell_owner(ctx, "The approval result could not be confirmed safely. This deal remains held; no new purchase will start.")
    finally:
        if ROUND.get("approval_wait_key") == key:
            ROUND.pop("approval_wait_key", None)


async def on_requote(ctx: Context, fresh: dict):
    n = ROUND["pick"]
    old = ROUND["bids"][n - 1]
    original = ROUND.get("original_offer")
    if (not isinstance(fresh, dict) or not isinstance(original, dict)
            or fresh.get("supplier_id") != old.get("supplier_id")):
        return
    if not (not_partners.orderable(old) and not_partners.orderable(fresh)
            and not_partners.orderable(ROUND.get("original_offer"))):
        ROUND["phase"] = "decided"  # #333: no mandate, no payee, no order for a store that never joined
        await tell_owner(ctx, f"Bid #{n} is a MIRROR listing from a store that never joined. "
                              f"{not_partners.NOT_ORDERABLE} Nothing was reserved or ordered.")
        return
    # Compare seller payload to the frozen pre-projection Bid, not Market's augmented winner lines.
    now = business_now()
    try:
        fresh_terms = {key: value for key, value in fresh.items() if key != "expires_at"}
        original_terms = {key: value for key, value in original.items() if key != "expires_at"}
        same_offer = (fresh_terms == original_terms and fresh.get("id") == old.get("id")
                      and fresh.get("need_id") == ROUND.get("need", {}).get("id")
                      and old.get("market_binding_hash") == ROUND.get("candidate_hashes", {}).get(old.get("id"))
                      and old.get("total_landed_price") == ROUND.get("market_winner", {}).get("total_landed_price"))
        expires_at = datetime.fromisoformat(str(fresh.get("expires_at", "")).replace("Z", "+00:00"))
        fresh_ttl = (expires_at - now).total_seconds() if expires_at.tzinfo else -1
    except (TypeError, ValueError, OverflowError):
        same_offer, fresh_ttl = False, -1
    if (not same_offer or fresh_ttl <= 0 or fresh_ttl > hunt.QUOTE_TTL_S
            or now.timestamp() - ROUND["quoted_at"] > hunt.QUOTE_TTL_S):
        await restart_card(ctx, f"Bid #{n}'s reviewed terms changed or its fresh quote is invalid; it needs a new review.")
        return
    if ROUND.get("transaction"):
        await tell_owner(ctx, "This exact offer already has a pending approval record.")
        return
    if not _configured_market_owner_matches(ROUND.get("owner")):
        ROUND["phase"] = "decided"
        await tell_owner(ctx, "Private purchase approval is not configured for this owner. Nothing was reserved.")
        return
    try:
        transaction = _create_pending_transaction(n)
        bid = ROUND["bids"][n - 1]
        await tell_owner(ctx, f"Fresh quote saved for deal {transaction['deal_id']}. Calling you now to approve bid #{n}: "
                              f"{bid['persona']} at ${bid['total_landed_price']:.2f}.")
    except Exception as exc:
        ctx.logger.warning(f"Purchase approval could not be prepared: {type(exc).__name__}")
        await tell_owner(ctx, "Private purchase state is unavailable. Nothing was ordered.")
    else:
        await _run_owner_approval(ctx, n, ROUND["owner"], transaction)


def _create_pending_transaction(n: int, *, web: bool = False) -> dict:
    """Mandate + stored pending transaction for bid #n (shared by the chat requote and the web auto-approval)."""
    transaction, create = _build_pending_transaction(n, web=web)
    return _finish_pending_transaction(transaction, create(), web=web)


def _build_pending_transaction(n: int, *, web: bool = False):
    """(transaction, blocking market create_mandate call): the call may run in a worker thread, the rest must not."""
    bid = ROUND["bids"][n - 1]
    card = ROUND["cards"][bid["id"]]
    deal_id = f"deal-{uuid4().hex}"
    amount = bid["total_landed_price"]
    seller = common.address(bid["supplier_id"])
    mandate = payment.make_mandate(deal_id=deal_id, amount=amount, payee=seller,
        buyer_id=ROUND["market_buyer_id"], within_allowance=False, goal_id=ROUND["goal"]["id"],
        now=business_now(), origin=bid.get("origin", "SIM"))
    deal = {"id": deal_id, "goal_id": ROUND["goal"]["id"], "need_id": ROUND["need"]["id"],
        "bid_id": bid["id"], "amount": amount, "payee": seller, "owner_sender": ROUND["owner"],
        "market_round_id": ROUND["market_round_id"],
        "candidate_binding_hash": bid.get("candidate_binding_hash")}
    transaction = {"deal_id": deal_id, "buyer_id": ROUND["market_buyer_id"], "goal_id": ROUND["goal"]["id"],
        "need_id": ROUND["need"]["id"], "bid_id": bid["id"], "phase": "pending_approval",
        "deal": deal, "order": None, "advocate_card": card, "mandate": mandate,
        "voice_approval": None, "allowance_authorization": None, "settlement": None,
        "settlement_result": None, "payment_ref": None, "mode": bid.get("origin", "SIM")}
    buyer_market, referee_market = market_clients()
    need_id, market_buyer_id, now = ROUND["need"]["id"], ROUND["market_buyer_id"], business_now()
    return transaction, lambda: (referee_market if web else buyer_market).create_mandate(
        mandate, need_id=need_id, buyer_id=market_buyer_id, now=now)


def _finish_pending_transaction(transaction: dict, status, *, web: bool = False) -> dict:
    mandate = transaction["mandate"]
    if (not isinstance(status, dict) or status.get("mandate_hash") != mandate["hash"]
            or (not web and (status.get("reservation_matches") is not True
                             or status.get("within_allowance") is not False
                             or status.get("retired") is not False))):
        raise MarketBridgeError("market_mandate_readback_mismatch")
    buyer_state.save_transaction(state_db(), transaction)
    ROUND["transaction"] = transaction
    ROUND["phase"] = "pending_approval"
    return transaction


async def _auto_web_approval(ctx: Context, n: int) -> None:
    """A web buyer's locked winner goes straight to mandate -> phone call -> approval; no owner chat, no owner check."""
    try:
        transaction, create = _build_pending_transaction(n, web=True)
        transaction = _finish_pending_transaction(transaction, await asyncio.to_thread(create), web=True)
    except Exception as exc:
        ctx.logger.warning(f"Web purchase approval could not be prepared: {type(exc).__name__}")
        ROUND["phase"] = "done"
        return
    await _run_owner_approval(ctx, n, "", transaction, web=True)
    if ROUND.get("phase") == "pending_approval":  # not approved (no phone, denied, no answer): free the hunt for the next web goal
        ROUND["phase"] = "done"
        ROUND["transaction"] = None


def eligible_for_order(n: int) -> bool:
    if not 1 <= n <= len(ROUND.get("bids", [])):
        return False
    bid = ROUND["bids"][n - 1]
    card = ROUND.get("cards", {}).get(ROUND["bids"][n - 1]["id"], {})
    return (ROUND.get("reviewed", False) and card.get("need_id") == ROUND["need"]["id"]
            and not_partners.orderable(bid)  # #333: a store that never joined is shown for comparison only
            and card.get("recommendation") in ("buy", "caution")
            and crs.eligible(bid["supplier_id"], ROUND.get("seller_checks", {}).get(bid["supplier_id"]),
                             business_now()))


def _request_payment_message_id(buyer_id: str, req: RequestPayment) -> tuple[str, str]:
    body = req.model_dump_json()
    raw = body.encode("utf-8")
    return "req:" + hashlib.sha256(buyer_id.encode("utf-8") + b"\n" + raw).hexdigest(), body


def _shield_payment_receipt(message_id: str, sender: str, request_json: str,
                            expected: dict[str, Any]) -> dict[str, Any]:
    # A trusted payment-screen transport must be explicitly injected by the runtime owner.
    if not callable(SHIELD_PAYMENT_SCREEN):
        raise RuntimeError("shield_payment_screen_unavailable")
    response = SHIELD_PAYMENT_SCREEN(message_id, sender, request_json, expected)
    if (not isinstance(response, dict) or response.get("verdict") != "allow"
            or response.get("message_id") != message_id or not isinstance(response.get("receipt"), dict)):
        raise PermissionError("shield_payment_blocked")
    return response["receipt"]


def _merchant_sim_for(transaction: dict):
    if MERCHANT_SIM is None or getattr(MERCHANT_SIM, "store", None) is not nonce_store():
        raise RuntimeError("merchant_sim_or_nonce_store_unavailable")
    from pay.merchant_sim import MerchantSim
    snapshot = dict(transaction)
    buyer_id, deal_id = transaction["buyer_id"], transaction["deal_id"]
    mandate_hash = transaction["mandate"]["hash"]
    return MerchantSim(keys=MERCHANT_SIM.keys, receipt_keys=MERCHANT_SIM.receipt_keys,
        store=nonce_store(), approvals=lambda got_deal, got_buyer: snapshot
            if (got_deal == deal_id and got_buyer == buyer_id
                and snapshot.get("deal_id") == deal_id
                and snapshot.get("mandate", {}).get("hash") == mandate_hash) else None,
        charger=MERCHANT_SIM.charger)


@pay.on_message(RequestPayment)
async def on_request_payment(ctx: Context, sender: str, req: RequestPayment):
    tx = ROUND.get("transaction")
    if (sender not in SELLER_ADDRS or not isinstance(tx, dict) or tx.get("phase") != "approved"
            or tx.get("mandate", {}).get("payee") != sender or tx.get("deal", {}).get("payee") != sender):
        ctx.logger.info("payment request did not match the approved seller and deal")
        return
    log_msg(ctx, SELLER_ADDRS[sender], "buyer", "payment_request")
    if not _configured_market_owner_matches(tx.get("deal", {}).get("owner_sender")):
        await ctx.send(sender, RejectPayment(reason="buyer owner is not configured"))
        return
    mandate = tx["mandate"]
    if tx.get("mode") != "SIM":
        await ctx.send(sender, RejectPayment(reason="unsupported payment origin"))
        return
    durable_charge_saved = False
    try:
        buyer_market, _referee_market = market_clients()
        market_status = buyer_market.purchase_status(mandate["hash"])
        now_ts = business_now().timestamp()
        market_expiry = _market_timestamp(market_status.get("expiry"))
        local_expiry = _market_timestamp(mandate.get("expires_at"))
        if (market_status.get("approval_method") not in {"voice_code", "allowance"}
                or market_status.get("retired") is not False
                or market_status.get("reservation_matches") is not True
                or market_status.get("payment_ref") is not None
                or now_ts >= market_expiry or now_ts >= local_expiry or market_expiry > local_expiry):
            raise PermissionError("market_purchase_not_approved")
        message_id, request_json = _request_payment_message_id(tx["buyer_id"], req)
        cents = payment._cents(mandate.get("amount"))
        if cents is None:
            raise PermissionError("mandate_amount_invalid")
        expected = {"deal_id": tx["deal_id"], "mandate_hash": mandate["hash"],
                    "amount_cents": cents, "currency": "USD", "payee": sender}
        receipt = _shield_payment_receipt(message_id, sender, request_json, expected)
        if not isinstance(SHIELD_RECEIPT_KEYS, dict) or not SHIELD_RECEIPT_KEYS:
            raise RuntimeError("shield_receipt_keys_unavailable")
        from shield.receipt import verify_allow_receipt
        verified = verify_allow_receipt(receipt, SHIELD_RECEIPT_KEYS, message_id=message_id,
            request_json=request_json, deal_id=tx["deal_id"], mandate_hash=mandate["hash"],
            amount_cents=cents, currency="USD", payee=sender, now=business_now())
        if not verified:
            raise PermissionError("shield_receipt_invalid")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        if (not isinstance(TAP_PRIVATE_KEY, Ed25519PrivateKey) or MERCHANT_SIM is None
                or getattr(MERCHANT_SIM, "store", None) is not nonce_store()
                or not isinstance(getattr(MERCHANT_SIM, "keys", None), dict)
                or not isinstance(getattr(MERCHANT_SIM, "receipt_keys", None), dict)
                or not getattr(MERCHANT_SIM, "receipt_keys", None)):
            raise RuntimeError("checkout_keys_or_nonce_store_unavailable")
        now_ts = business_now().timestamp()
        if now_ts >= market_expiry or now_ts >= local_expiry or market_expiry > local_expiry:
            raise PermissionError("mandate_expired")
        # Persist the submitted boundary before MerchantSim can consume the nonce or charge.
        tx["phase"] = "submitted"
        buyer_state.save_transaction(state_db(), tx)
        from buyer.checkout import settle_offer
        envelope = await asyncio.to_thread(settle_offer, dict(tx), req, _merchant_sim_for(tx),
            receipt=receipt, message_id=message_id, tap_private_key=TAP_PRIVATE_KEY,
            now=business_now())
        if (not isinstance(envelope, dict) or not isinstance(envelope.get("settlement"), dict)
                or not isinstance(envelope.get("settlement_result"), dict)
                or not isinstance(envelope.get("mandate"), dict)):
            raise RuntimeError("merchant_result_unavailable")
        tx["mandate"] = envelope["mandate"]  # the TAP-signed mandate returned by checkout.settle_offer
        tx["settlement"], tx["settlement_result"] = envelope["settlement"], envelope["settlement_result"]
        result = tx["settlement_result"]
        if result.get("status") != "charged":
            tx["phase"] = "uncertain"
            buyer_state.save_transaction(state_db(), tx)
            ROUND.update(transaction=tx, pending_hold=True, phase="uncertain")
            await ctx.send(sender, RejectPayment(reason="payment result is not confirmed"))
            await tell_owner(ctx, "The payment result is uncertain. This purchase remains held; no automatic retry will occur.")
            return
        tx["phase"] = "submitted"
        tx["payment_ref"] = result.get("charge_id")
        tx["order"]["payment_ref"] = result.get("charge_id")
        tx["order"]["status"] = "charged"
        buyer_state.save_transaction(state_db(), tx)
        durable_charge_saved = True
        out = hunt.settle(req, tx, now=business_now())
        if isinstance(out, RejectPayment):
            ROUND.update(transaction=tx, pending_hold=True, phase="uncertain")
            await tell_owner(ctx, "The charge was confirmed, but the payment message could not be validated. This purchase remains held.")
            return
        ROUND.update(transaction=tx, payment_commit=out, pending_hold=True, phase="submitted")
        await ctx.send(sender, out)
        from buyer.checkout import format_settlement_result
        await tell_owner(ctx, f"A confirmed charge was submitted for {tx['deal_id']}: {format_settlement_result(envelope)} "
                              "Waiting for the seller acknowledgement.")
    except Exception as exc:
        if durable_charge_saved:
            # The charge is known and durable; delivery/notification errors cannot turn it
            # into a rejection or trigger a provider retry. Keep the exact ACK path open.
            ROUND.update(transaction=tx, pending_hold=True, phase="submitted")
            ctx.logger.warning(f"Confirmed charge delivery failed: {type(exc).__name__}")
            return
        if tx.get("phase") in {"submitted", "uncertain"}:
            tx["phase"] = "uncertain"
            try:
                buyer_state.save_transaction(state_db(), tx)
            except Exception:
                pass
            ROUND.update(transaction=tx, pending_hold=True, phase="uncertain")
        ctx.logger.warning(f"Payment verification failed: {type(exc).__name__}")
        await ctx.send(sender, RejectPayment(reason="payment verification unavailable"))
        await tell_owner(ctx, "Payment verification did not complete. The transaction remains held.")


@pay.on_message(CompletePayment)
async def on_complete(ctx: Context, sender: str, msg: CompletePayment):
    log_msg(ctx, SELLER_ADDRS.get(sender, "seller"), "buyer", "payment_complete")
    tx = ROUND.get("transaction")
    if not isinstance(tx, dict) or tx.get("phase") not in {"submitted", "uncertain"}:
        return
    mandate, deal, result = tx.get("mandate"), tx.get("deal"), tx.get("settlement_result")
    if (not isinstance(mandate, dict) or not isinstance(deal, dict) or not isinstance(result, dict)
            or sender != mandate.get("payee") or sender not in SELLER_ADDRS
            or msg.transaction_id != tx.get("payment_ref") or msg.transaction_id != result.get("charge_id")
            or result.get("status") != "charged" or deal.get("payee") != sender
            or tx.get("order", {}).get("id") != deal.get("id")
            or not _configured_market_owner_matches(deal.get("owner_sender"))):
        ctx.logger.info("seller completion acknowledgement did not match the held purchase")
        return
    try:
        persisted = buyer_state.load_transaction(state_db(), tx["deal_id"], tx["buyer_id"])
        if (not isinstance(persisted, dict) or persisted.get("phase") not in {"submitted", "uncertain"}
                or persisted.get("payment_ref") != msg.transaction_id):
            raise ValueError("durable charged purchase is unavailable")
        tx = persisted
        mandate, deal, result = tx["mandate"], tx["deal"], tx["settlement_result"]
        settlement = tx.get("settlement")
        order = tx.get("order")
        if (not isinstance(order, dict) or mandate.get("status") != "approved"
                or payment.mandate_hash(mandate) != mandate.get("hash")
                or mandate.get("deal_id") != tx.get("deal_id")
                or mandate.get("buyer_id") != tx.get("buyer_id")
                or mandate.get("goal_id") != tx.get("goal_id")
                or mandate.get("payee") != deal.get("payee") or deal.get("payee") != sender
                or deal.get("id") != tx.get("deal_id") or deal.get("goal_id") != tx.get("goal_id")
                or deal.get("need_id") != tx.get("need_id") or deal.get("bid_id") != tx.get("bid_id")
                or not _configured_market_owner_matches(deal.get("owner_sender"))
                or order.get("id") != deal.get("id")
                or order.get("need_id") != tx.get("need_id") or order.get("bid_id") != tx.get("bid_id")
                or payment._cents(order.get("amount")) != payment._cents(mandate.get("amount"))
                or not mandate.get("approval_id")
                or not isinstance(tx.get("voice_approval"), dict)
                or tx["voice_approval"].get("result") != "approved"
                or tx["voice_approval"].get("mandate_hash") != mandate.get("hash")
                or tx["voice_approval"].get("mandate_id") != mandate.get("id")
                or tx["voice_approval"].get("id") != mandate.get("approval_id")
                or order.get("approval_id") != mandate.get("approval_id")
                or order.get("status") != "charged" or order.get("payment_ref") != msg.transaction_id
                or payment._cents(deal.get("amount")) != payment._cents(mandate.get("amount"))
                or result.get("status") != "charged"
                or tx.get("mode") != (settlement or {}).get("mode")):
            raise ValueError("durable purchase does not match the exact charged deal")
        attempt = nonce_store().get_payment_attempt(mandate["hash"])
        request = payment.payment_request(mandate, recipient=sender)
        body = request.model_dump_json().encode("utf-8")
        expected_message_id = "req:" + hashlib.sha256(tx["buyer_id"].encode("utf-8") + b"\n" + body).hexdigest()
        cents = payment._cents(mandate.get("amount"))
        if (not isinstance(settlement, dict) or not isinstance(attempt, dict) or cents is None
                or attempt.get("phase") != "charged" or attempt.get("charge_id") != msg.transaction_id
                or attempt.get("mandate_hash") != mandate.get("hash")
                or attempt.get("buyer_id") != tx.get("buyer_id") or attempt.get("deal_id") != tx.get("deal_id")
                or attempt.get("request_sha256") != hashlib.sha256(body).hexdigest()
                or attempt.get("amount_cents") != cents or attempt.get("currency") != "USD"
                or attempt.get("payee") != sender
                or attempt.get("idempotency_key") != "mandate:" + mandate["hash"]
                or attempt.get("message_id") != expected_message_id
                or not isinstance(attempt.get("receipt_keyid"), str)
                or not attempt["receipt_keyid"] or attempt["receipt_keyid"] == "not-submitted"
                or settlement.get("message_id") != expected_message_id
                or settlement.get("request_sha256") != hashlib.sha256(body).hexdigest()
                or settlement.get("mandate_hash") != mandate["hash"]
                or settlement.get("deal_id") != tx["deal_id"] or settlement.get("buyer_id") != tx["buyer_id"]
                or settlement.get("amount_cents") != cents or settlement.get("currency") != "USD"
                or settlement.get("payee") != sender
                or settlement.get("idempotency_key") != "mandate:" + mandate["hash"]
                or settlement.get("receipt_keyid") != attempt.get("receipt_keyid")
                or settlement.get("mode") not in {"SIM", "stripe_test"}
                or result.get("charge_id") != msg.transaction_id or result.get("mandate_hash") != mandate["hash"]
                or result.get("origin") != "SIM"):
            raise ValueError("durable charge attempt does not match the seller acknowledgement")
        buyer_market, referee_market = market_clients()
        mode = {"SIM": "sim", "stripe_test": "stripe_test"}.get(settlement.get("mode"))
        if mode is None:
            raise MarketBridgeError("settlement_mode_invalid")
        payment_status = buyer_market.purchase_status(mandate["hash"])
        expected_cents = payment._cents(mandate["amount"])
        if payment_status.get("payment_ref") is None:
            if (payment_status.get("payment_mode") is not None
                    or payment_status.get("payment_amount") is not None
                    or payment_status.get("settled") is True):
                raise MarketBridgeError("market_payment_readback_mismatch")
            referee_market.record_payment(mandate_hash=mandate["hash"],
                payment_ref=msg.transaction_id, amount=mandate["amount"], mode=mode)
            payment_status = buyer_market.purchase_status(mandate["hash"])
        elif (payment_status.get("payment_ref") != msg.transaction_id
                or payment_status.get("payment_mode") != mode
                or payment._cents(payment_status.get("payment_amount")) != expected_cents):
            raise MarketBridgeError("market_payment_readback_mismatch")
        if (payment_status.get("payment_ref") != msg.transaction_id
                or payment_status.get("payment_mode") != mode
                or payment._cents(payment_status.get("payment_amount")) != expected_cents):
            raise MarketBridgeError("market_payment_readback_mismatch")
        settled = buyer_market.settle_goal(goal_id=tx["goal_id"], deal_id=tx["deal_id"],
            mandate_hash=mandate["hash"], payment_ref=msg.transaction_id)
        if not isinstance(settled, dict) or settled.get("settled") is not True:
            raise MarketBridgeError("market_settlement_readback_mismatch")
        owner = deal.get("owner_sender")
        if not isinstance(owner, str) or not owner:
            raise ValueError("private goal owner is unavailable")
        goal = buyer_state.load_goal(state_db(), tx["goal_id"], owner)
        if not isinstance(goal, dict):
            raise ValueError("private goal state is unavailable")
        tx["phase"], tx["order"]["status"] = "settled", "paid"
        goal.update(state="DONE", po_number=tx["deal_id"], reserved_amount=0)
        buyer_state.save_goal(state_db(), goal)
        buyer_state.save_transaction(state_db(), tx)
        ROUND.update(transaction=tx, goal=goal, pending_hold=False, phase="done", order=None, mandate=None,
                     payment_commit=None)
    except Exception as exc:
        ctx.logger.warning(f"Settlement readback failed: {type(exc).__name__}")
        ROUND.update(pending_hold=True, phase="uncertain")
        await tell_owner(ctx, "The seller acknowledgement arrived, but Market could not confirm settlement. This purchase remains held.")
        return
    try:
        from buyer.checkout import format_settlement_result
        await tell(ctx, owner, f"Done: purchase {tx['deal_id']} settled and recorded after seller acknowledgement. "
                               f"Receipt: {format_settlement_result(tx)}")
    except Exception as exc:
        # The settled state is already durable. A failed owner notice must not relock it.
        ctx.logger.warning(f"Settlement notice failed after durable completion: {type(exc).__name__}")


@pay.on_message(CancelPayment)
async def on_cancel(ctx: Context, sender: str, msg: CancelPayment):
    await tell_owner(ctx, f"Seller cancelled the payment: {msg.reason or 'no reason given'}.")


agent.include(chat, publish_manifest=True)
agent.include(pay, publish_manifest=True)

if __name__ == "__main__":
    print(f"buyer address: {agent.address}")
    agent.run()
