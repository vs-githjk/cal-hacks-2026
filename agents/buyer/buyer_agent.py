"""Tech Bazaar buyer agent: buyer's goal -> ownership memory -> sealed round with three sellers -> advocate cards
-> approval. Run from agents/:  .venv/Scripts/python.exe buyer/buyer_agent.py   (BUYER_MAILBOX=1 for Agentverse)"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
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
from advocate.mock_data import BASELINE
from chat_diagnostics import ChatDiagnostics
from goal import apply_owned, need_from_goal, owned_attrs, parse_goal, remember, skip_lines
from logic import decide, make_order, sealed

ADVICE_TIMEOUT_S = 15
ALLOWANCE = float(os.getenv("BUYER_ALLOWANCE", "0"))  # $0: every order needs the buyer's APPROVE
CRS_NOT_CONFIGURED_NOTICE = "CRS not configured; seller eligibility was not verified."
SELLER_ADDRS = {common.address(s): s for s in common.SELLERS}
WEB = "web"  # owner id for the local web chat (web_chat.py); its replies queue in WEB_OUTBOX

# Agentverse profile, published on connect (README, short description, handle) for ASI:One discovery.
agent = Agent(**common.agent_args(
    "buyer", 8001, name="Tech Bazaar Buyer",
    readme_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "AGENTVERSE.md"),
    description="Your buying agent for computer gear: give it a goal, it skips parts you own, makes seller agents "
                "bid in a sealed round, vetoes traps with a cited source, and pays only after you approve.",
    handle=os.getenv("BUYER_AGENT_HANDLE", "techbazaarbuyer")))
chat = Protocol(spec=chat_protocol_spec)
pay = Protocol(spec=payment_protocol_spec, role="buyer")

# One round at a time; plain dicts are enough for the demo (lost on restart).
# phase: bidding -> advice -> decided (or done). Goal state: ACTIVE -> HUNTING -> HOLD_FOR_CALL / DONE.
ROUND: dict = {}
WEB_OUTBOX: list[str] = []
# mandate hash -> approval row. STUB: the chat APPROVE stands in until Lane D's VoiceApproval writes these rows.
APPROVALS: dict = {}
USED: set = set()  # mandate hashes already committed (replay guard)
CHAT_DIAG = ChatDiagnostics(print)


class WebIn(Model):
    text: str


class WebOut(Model):
    replies: list[str]


async def tell(ctx: Context, to: str, text: str):
    if to == WEB:
        WEB_OUTBOX.append(text)
    else:
        msg = ChatMessage(content=[TextContent(text=text)])
        CHAT_DIAG.send_started(msg.msg_id, to, ctx.session, ROUND.get("need", {}).get("id", ""))
        ctx.logger.info("AGENT_MSG name=buyer to=owner text=reply to owner")
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
    now = time.time()
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


async def handle_text(ctx: Context, sender: str, text: str):
    # Single buyer deployment: no sender other than the owner of the active round sees its state.
    if ROUND.get("owner") and sender != ROUND["owner"]:
        await tell(ctx, sender, "A buyer session is active. Try again later.")
        return
    cmd = hunt.command(text)
    if cmd and cmd[0] == "approve" and ROUND.get("owner") == sender:
        await approve(ctx, cmd[1])
        return
    if cmd and cmd[0] == "cancel" and ROUND.get("owner") == sender:
        ROUND.clear()
        await tell(ctx, sender, "Cancelled. Nothing ordered. Send a new goal when you are ready.")
        return
    if ROUND.get("phase") == "decided" and not ROUND.get("order"):
        # A deal waits for the owner. ASI:One's own assistant also messages us (recaps of our replies);
        # never let that text start a new round or approve anything.
        if not ROUND.get("told_waiting"):
            ROUND["told_waiting"] = True
            await tell(ctx, sender, "A deal is waiting for your decision. Reply APPROVE followed by the bid number, "
                                    "or CANCEL to drop it and start a new goal.")
        return
    if ROUND.get("order"):
        # Same reason: after an order, a recap of it ("$581.99 for the GPU") would read as a new goal.
        m = re.match(r"(?is)^(?:@\S+\s+)*new\b[:\s]*(.+)", text.strip())
        if not m:
            if not ROUND.get("told_ordered"):
                ROUND["told_ordered"] = True
                await tell(ctx, sender, "That order is placed. To start another goal, begin with NEW, "
                                        "e.g. 'NEW a 850 W PSU under $150'.")
            return
        text = m.group(1)
    if ROUND.get("phase") in ("checking", "bidding", "advice", "requote"):
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
    owned = remember(buyer_id, told)
    goal = apply_owned(goal, owned)
    need = need_from_goal(goal)
    ROUND.clear()
    # Async seller/advocate callbacks must reply on the owner's Chat Protocol session.
    ROUND.update(owner=sender, owner_context=ctx if sender != WEB else None,
                 goal=goal, owned=owned, need=need, bids=[], personas={}, cards={},
                 attempts=0, last_sent={})
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
    sellers/run_all.py, so it is neither asked for a bid nor counted in what the owner is told."""
    return [s for s in common.SELLERS if common.mailbox_ready(s)]


async def start_round(ctx: Context, need: dict | None = None):
    """Open a sealed round. A retry gets a fresh Need id so stale bids from the last round cannot count."""
    need = need or need_from_goal(ROUND["goal"])
    token = uuid4().hex
    ROUND.update(need=need, bids=[], personas={}, cards={}, seller_checks={},
                 reviewed=False, order=None, mandate=None, phase="checking", deadline=0, round_token=token)
    set_state("HUNTING")
    try:
        checks = await crs.check_sellers(datetime.now(timezone.utc))
    except Exception:
        ctx.logger.warning("CRS checks failed; business sellers will be ineligible for this round.")
        checks = {}
    if ROUND.get("round_token") != token or ROUND.get("phase") != "checking" or ROUND.get("need") is not need:
        return False
    ROUND.update(seller_checks=checks, phase="bidding", deadline=time.time() + need["auction_window_s"])
    for s in live_sellers():
        if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need["id"]:
            return False
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
    ROUND.update(phase="waiting", next_round_at=time.time() + hunt.RETRY_S)
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
    verdict = common.screen_bid(str(uuid4()), sender, msg.bid_json, msg.persona_line, BASELINE)
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    reasons = None if verdict.get("verdict") == "allow" else "; ".join(verdict.get("reasons", [])) or verdict.get("verdict")
    if reasons:
        await tell_owner(ctx, f"Shield blocked a bid from {SELLER_ADDRS[sender]}: {reasons}")
        return
    if ROUND.get("phase") not in ("bidding", "requote") or time.time() > ROUND["deadline"]:
        ctx.logger.info("late or stray bid ignored")
        return
    try:
        bid = common.validate("Bid", json.loads(msg.bid_json))
    except Exception as exc:
        ctx.logger.warning(f"invalid bid dropped: {type(exc).__name__}")
        return
    if bid["need_id"] != ROUND["need"]["id"]:
        return
    if bid.get("supplier_id") != SELLER_ADDRS[sender]:
        ctx.logger.info("bid supplier does not match its registered sender; ignored")
        return
    if ROUND["phase"] == "requote":
        await on_requote(ctx, bid)
        return
    ROUND["bids"].append(bid)
    ROUND["personas"][bid["id"]] = msg.persona_line
    await emit(ctx, "bid in", f"Bid in: {bid['persona']} at ${bid['total_landed_price']:.2f} (sealed round still open).")


@agent.on_message(common.AdviceReply)
async def on_advice(ctx: Context, sender: str, msg: common.AdviceReply):
    token, need_id = ROUND.get("round_token"), ROUND.get("need", {}).get("id")
    if sender != common.address("advocate") or ROUND.get("phase") != "advice":
        return
    reasons = blocked_reasons(sender, msg.cards_json, common.shield_context(sender))
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    if reasons:
        await fail_round(ctx, f"Shield blocked the advocate's reply: {reasons}. Nothing ordered.", always_notify=True)
        return
    try:
        raw = json.loads(msg.cards_json)
        if not isinstance(raw, list):
            raise ValueError("expected a list of review cards")
        cards = [common.validate("AdvocateCard", c) for c in raw]
        if (not cards or len(cards) != len(ROUND["bids"])
                or {c["bid_id"] for c in cards} != {b["id"] for b in ROUND["bids"]}
                or any(c["need_id"] != ROUND["need"]["id"]
                       or c["recommendation"] not in ("buy", "caution", "veto") for c in cards)):
            raise ValueError("expected one current review per bid, with buy, caution or veto")
    except Exception as exc:
        ctx.logger.warning(f"invalid advocate reply: {type(exc).__name__}")
        await fail_round(ctx, "The advocate's review was invalid or incomplete. Nothing ordered.", always_notify=True)
        return
    ROUND["cards"] = {c["bid_id"]: c for c in cards}
    await conclude(ctx, reviewed=True)


@agent.on_interval(period=1.0)
async def tick(ctx: Context):
    CHAT_DIAG.expire()
    now = time.time()
    if ROUND.get("goal") and hunt.expired(ROUND["goal"]):
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
    elif ROUND.get("phase") == "bidding" and now > ROUND["deadline"]:
        if not ROUND["bids"]:
            why = "No seller bid this round."
            if hunt.BUY_PUBLIC_IF_NO_BID:
                why = hunt.public_hint(ROUND["need"], BASELINE)
            await fail_round(ctx, why)
            return
        ROUND["bids"].sort(key=lambda b: b["total_landed_price"])
        ROUND["quoted_at"] = now
        ROUND["phase"] = "advice"
        ROUND["deadline"] = now + ADVICE_TIMEOUT_S
        # The advocate sees the owned parts for fit checks, but not the cap.
        advice_need = dict(sealed(ROUND["need"]), owned=owned_attrs(ROUND["owned"]))
        token, need_id = ROUND.get("round_token"), ROUND.get("need", {}).get("id")
        try:
            await ctx.send(common.address("advocate"), common.AdviceRequest(
                need_json=json.dumps(advice_need), bids_json=json.dumps(ROUND["bids"])))
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
    now_utc = datetime.now(timezone.utc)
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
        if ROUND["personas"].get(b["id"]):
            out.append(f'   "{ROUND["personas"][b["id"]]}"')
        out.append(f"   Advocate: {rec}")
        for w in card.get("warnings", [])[:3]:
            out.append(f"   ! {w['text']} (source: {w['source_url']})")
    best = hunt.pick_best(bids, cards, eligible_suppliers)
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
               else "Every eligible bid was vetoed by the advocate.")
        await fail_round(ctx, why)
        return
    verdict = decide(need, bids[best - 1], ALLOWANCE)
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
    if verdict == "auto_order" and reviewed:  # only under the allowance, and never without a review
        out.append(await place_order(ctx, best, approved_by="auto", approval_id=f"auto-{need['id']}"))
    else:
        set_state("HOLD_FOR_CALL")
        out.append(f"Your allowance is ${ALLOWANCE:.0f}, so this needs your call. Reply APPROVE {best} to order bid #{best} "
                   f"(quote good for {hunt.QUOTE_TTL_S // 60} minutes).")
    if ROUND.get("round_token") != token or ROUND.get("need", {}).get("id") != need_id:
        return
    await tell_owner(ctx, "\n".join(out))

async def approve(ctx: Context, n: int):
    bids = ROUND.get("bids", [])
    if ROUND.get("order"):
        await tell_owner(ctx, f"Already ordered: {ROUND['order']['id']}.")
    elif ROUND.get("phase") != "decided" or not 1 <= n <= len(bids):
        await tell_owner(ctx, f"No bid #{n} is waiting for approval.")
    elif not eligible_for_order(n):
        await tell_owner(ctx, f"Bid #{n} is unreviewed, vetoed, or CRS-ineligible; not ordering it. Cancel or wait for a reviewed round.")
    elif bids[n - 1]["total_landed_price"] > ROUND["need"]["spend_limit"]:
        await tell_owner(ctx, f"Bid #{n} is over your cap; not ordering it.")
    elif time.time() - ROUND["quoted_at"] > hunt.QUOTE_TTL_S:
        await restart_card(ctx, f"Bid #{n}'s quote is older than {hunt.QUOTE_TTL_S // 60} minutes.")
    else:
        # Re-read the price just before committing: ask the winning seller to quote the same Need again.
        ROUND.update(phase="requote", pick=n, deadline=time.time() + ADVICE_TIMEOUT_S)
        await ctx.send(common.address(bids[n - 1]["supplier_id"]),
                       common.BidRequest(need_json=json.dumps(sealed(ROUND["need"]))))


async def on_requote(ctx: Context, fresh: dict):
    n = ROUND["pick"]
    old = ROUND["bids"][n - 1]
    if fresh["supplier_id"] != old["supplier_id"]:
        return
    if not hunt.quote_still_good(old["total_landed_price"], fresh["total_landed_price"], ROUND["quoted_at"], time.time()):
        await restart_card(ctx, f"Bid #{n}'s price moved from ${old['total_landed_price']:.2f} to "
                                f"${fresh['total_landed_price']:.2f} (or its quote expired).")
        return
    ROUND["phase"] = "decided"
    await tell_owner(ctx, await place_order(ctx, n, approved_by="owner", approval_id=f"chat-{uuid4().hex[:8]}"))


def eligible_for_order(n: int) -> bool:
    if not 1 <= n <= len(ROUND.get("bids", [])):
        return False
    bid = ROUND["bids"][n - 1]
    card = ROUND.get("cards", {}).get(ROUND["bids"][n - 1]["id"], {})
    return (ROUND.get("reviewed", False) and card.get("need_id") == ROUND["need"]["id"]
            and card.get("recommendation") in ("buy", "caution")
            and crs.eligible(bid["supplier_id"], ROUND.get("seller_checks", {}).get(bid["supplier_id"]),
                             datetime.now(timezone.utc)))


async def place_order(ctx: Context, n: int, approved_by: str, approval_id: str) -> str:
    if not eligible_for_order(n):
        return f"Bid #{n} is unreviewed, vetoed, or CRS-ineligible; not ordering it."
    bid = ROUND["bids"][n - 1]
    order = common.validate("Order", make_order(ROUND["need"], bid, approved_by, approval_id))
    seller = common.address(bid["supplier_id"])
    m = payment.make_mandate(deal_id=order["id"], amount=order["amount"], payee=seller, buyer_id=ROUND["need"]["buyer_id"],
                             within_allowance=approved_by == "auto", goal_id=ROUND["goal"]["id"])
    # STUB approval row: the chat APPROVE (or the allowance) stands in until Lane D's VoiceApproval writes it.
    source = "auto under allowance" if approved_by == "auto" else "chat stub until Lane D VoiceApproval"
    APPROVALS[m["hash"]] = {"answer": "approve", "source": source}
    ROUND.update(order=order, mandate=m)
    ROUND["goal"].update(state="DONE", po_number=order["id"])
    ctx.logger.info("order prepared")
    ctx.logger.info("mandate prepared")
    await ctx.send(seller, common.OrderPlaced(order_json=json.dumps(order), mandate_json=json.dumps(m)))
    who = "Auto-ordered" if approved_by == "auto" else "Approved and ordered"
    return (f"{who} #{n}: {order['id']}, ${order['amount']:.2f} from {bid['persona']}. "
            f"Asked the seller to request payment (mandate cap ${m['amount']:.2f}, expires {m['expires_at']}). "
            f"No money has moved.")


@pay.on_message(RequestPayment)
async def on_request_payment(ctx: Context, sender: str, req: RequestPayment):
    if sender not in SELLER_ADDRS:
        ctx.logger.info("payment request from unregistered sender ignored")
        return
    reasons = blocked_reasons(sender, req.model_dump_json(), common.shield_context(sender, payee_of_record=sender))
    if reasons:
        await ctx.send(sender, RejectPayment(reason=f"blocked by Shield: {reasons}"))
        await tell_owner(ctx, f"Shield blocked a payment request from {SELLER_ADDRS[sender]}: {reasons}")
        return
    m = ROUND.get("mandate")
    if m and sender != m["payee"]:
        m = None  # only the mandate's payee may ask for its payment
    out = hunt.settle(req, m, APPROVALS, USED)
    await ctx.send(sender, out)
    if isinstance(out, RejectPayment):
        await tell_owner(ctx, f"Payment request from {SELLER_ADDRS[sender]} rejected: {out.reason}. No money moved.")
        return
    # TODO(Lane D): run the Stripe test charge for this mandate here and put its id in order.payment_ref.
    await tell_owner(ctx, f"Payment committed for {ROUND['order']['id']}, ${float(out.funds.amount):.2f} "
                          f"(Stripe test charge pending Lane D). No money has moved yet.")


@pay.on_message(CompletePayment)
async def on_complete(ctx: Context, sender: str, msg: CompletePayment):
    ctx.logger.info("seller completion acknowledgement received")


@pay.on_message(CancelPayment)
async def on_cancel(ctx: Context, sender: str, msg: CancelPayment):
    await tell_owner(ctx, f"Seller cancelled the payment: {msg.reason or 'no reason given'}.")


agent.include(chat, publish_manifest=True)
agent.include(pay, publish_manifest=True)

if __name__ == "__main__":
    print(f"buyer address: {agent.address}")
    agent.run()
