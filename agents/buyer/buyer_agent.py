"""Restaurant buyer agent: forecast -> sealed auction -> Quality Advocate review -> order within owner limits.
Run from agents/:  .venv/Scripts/python.exe buyer/buyer_agent.py   (BUYER_MAILBOX=1 to use Agentverse mailbox)"""
import json
import os
import re
import sys
import time
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

import common
from logic import decide, make_order, mandate, need_from_forecast, sealed
from mock_forecast import FORECASTS, ON_HAND, OWNER

ADVICE_TIMEOUT_S = 15

if os.getenv("BUYER_MAILBOX"):
    agent = Agent(name="restaurant_buyer", seed=common.SEEDS["buyer"], port=8001, mailbox=True)
else:
    agent = Agent(name="restaurant_buyer", seed=common.SEEDS["buyer"], port=8001,
                  endpoint=["http://localhost:8001/submit"])
chat = Protocol(spec=chat_protocol_spec)

# One auction round at a time; a plain dict is enough for the demo (lost on restart).
# phase: bidding -> advice -> decided (or done)
ROUND: dict = {}


async def tell_owner(ctx: Context, text: str):
    if ROUND.get("owner"):
        await ctx.send(ROUND["owner"], ChatMessage(content=[TextContent(text=text)]))
    ctx.logger.info(f"to owner: {text}")


def blocked_reasons(sender: str, text: str) -> str | None:
    verdict = common.screen(str(uuid4()), sender, text)
    if verdict.get("verdict") == "allow":
        return None
    return "; ".join(verdict.get("reasons", [])) or verdict.get("verdict", "blocked")  # quarantine counts as blocked


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    text = msg.text().strip()
    m = re.match(r"(?i)approve\s+#?(\d+)", text)
    if m and ROUND.get("owner") == sender:
        await approve(ctx, int(m.group(1)))
        return
    if ROUND.get("phase") in ("bidding", "advice"):
        await ctx.send(sender, ChatMessage(content=[TextContent(text="An auction is already running; results soon.")]))
        return
    need = common.validate("Need", need_from_forecast(FORECASTS, ON_HAND, OWNER))
    ROUND.clear()
    ROUND.update(owner=sender, need=need, bids=[], personas={}, cards={}, phase="bidding",
                 deadline=time.time() + need["auction_window_s"])
    await ctx.send(common.address("supplier"), common.BidRequest(need_json=json.dumps(sealed(need))))
    lines = "\n".join(f"- {i['quantity']} x {i['pack_size']} {i['sku_spec']} ({i['grade']})" for i in need["items"])
    await tell_owner(ctx, f"SIMULATED forecast. Sealed auction open for {need['auction_window_s']}s:\n{lines}")


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@agent.on_message(common.BidReply)
async def on_bid(ctx: Context, sender: str, msg: common.BidReply):
    reasons = blocked_reasons(sender, msg.bid_json + "\n" + msg.persona_line)
    if reasons:
        await tell_owner(ctx, f"Shield blocked a bid from {sender[:16]}...: {reasons}")
        return
    if ROUND.get("phase") != "bidding" or time.time() > ROUND["deadline"]:
        ctx.logger.info("late or stray bid ignored")
        return
    try:
        bid = common.validate("Bid", json.loads(msg.bid_json))
    except Exception as e:
        ctx.logger.warning(f"invalid bid dropped: {e}")
        return
    if bid["need_id"] == ROUND["need"]["id"]:
        ROUND["bids"].append(bid)
        ROUND["personas"][bid["id"]] = msg.persona_line


@agent.on_message(common.AdviceReply)
async def on_advice(ctx: Context, sender: str, msg: common.AdviceReply):
    reasons = blocked_reasons(sender, msg.cards_json)
    if reasons:
        await tell_owner(ctx, f"Shield blocked the Quality Advocate's reply: {reasons}")
        return
    if ROUND.get("phase") != "advice":
        return
    try:
        cards = [common.validate("AdvocateCard", c) for c in json.loads(msg.cards_json)]
    except Exception as e:
        await tell_owner(ctx, f"Advocate reply was malformed ({e}); showing bids without review.")
        await conclude(ctx, reviewed=False)
        return
    ROUND["cards"] = {c["bid_id"]: c for c in cards}
    await conclude(ctx, reviewed=True)


@agent.on_interval(period=1.0)
async def tick(ctx: Context):
    now = time.time()
    if ROUND.get("phase") == "bidding" and now > ROUND["deadline"]:
        if not ROUND["bids"]:
            ROUND["phase"] = "done"
            await tell_owner(ctx, "No supplier bids arrived in time. Nothing ordered; send any message to retry.")
            return
        ROUND["bids"].sort(key=lambda b: b["total_landed_price"])
        ROUND["phase"] = "advice"
        ROUND["deadline"] = now + ADVICE_TIMEOUT_S
        await ctx.send(common.address("advocate"), common.AdviceRequest(
            need_json=json.dumps(sealed(ROUND["need"])), bids_json=json.dumps(ROUND["bids"])))
    elif ROUND.get("phase") == "advice" and now > ROUND["deadline"]:
        await tell_owner(ctx, "Quality Advocate did not reply in time; bids below are NOT reviewed.")
        await conclude(ctx, reviewed=False)


async def conclude(ctx: Context, reviewed: bool):
    need, bids, cards = ROUND["need"], ROUND["bids"], ROUND["cards"]
    ROUND["phase"] = "decided"
    out = [f"{len(bids)} sealed bids for {need['id']} (limit ${need['spend_limit']:.2f}):"]
    best = None  # bids are sorted cheapest first, so the first non-vetoed one wins
    for n, b in enumerate(bids, 1):
        card = cards.get(b["id"], {})
        rec = card.get("recommendation", "not reviewed")
        out.append(f"{n}. {b['persona']}: ${b['total_landed_price']:.2f} [{b['source']}]")
        if ROUND["personas"].get(b["id"]):
            out.append(f'   "{ROUND["personas"][b["id"]]}"')
        out.append(f"   Advocate: {rec}")
        for w in card.get("warnings", [])[:3]:
            out.append(f"   ! {w['text']} (source: {w['source_url']})")
        if best is None and rec != "veto":
            best = n
    if best is None:
        out.append("Every bid was vetoed by the Quality Advocate. Nothing ordered.")
    else:
        verdict = decide(need, bids[best - 1], OWNER["auto_limit"])
        if verdict == "auto_order" and reviewed:  # never auto-order without a quality review
            out.append(place_order(ctx, best, approved_by="auto", approval_id=f"auto-{need['id']}"))
        elif verdict == "over_limit":
            out.append(f"Best eligible bid #{best} is over your ${need['spend_limit']:.2f} limit. Nothing ordered.")
        else:
            out.append(f"Reply APPROVE {best} to order bid #{best}.")
    await tell_owner(ctx, "\n".join(out))


async def approve(ctx: Context, n: int):
    bids = ROUND.get("bids", [])
    if ROUND.get("order"):
        await tell_owner(ctx, f"Already ordered: {ROUND['order']['id']}.")
    elif ROUND.get("phase") != "decided" or not 1 <= n <= len(bids):
        await tell_owner(ctx, f"No bid #{n} is waiting for approval.")
    elif bids[n - 1]["total_landed_price"] > ROUND["need"]["spend_limit"]:
        await tell_owner(ctx, f"Bid #{n} is over your spend limit; not ordering it.")
    else:
        await tell_owner(ctx, place_order(ctx, n, approved_by="owner", approval_id=f"chat-{uuid4().hex[:8]}"))


def place_order(ctx: Context, n: int, approved_by: str, approval_id: str) -> str:
    bid = ROUND["bids"][n - 1]
    order = common.validate("Order", make_order(ROUND["need"], bid, approved_by, approval_id))
    ROUND["order"] = order
    ROUND["mandate"] = mandate(order, bid["supplier_id"])
    ctx.logger.info(f"ORDER {json.dumps(order)}")
    ctx.logger.info(f"MANDATE {json.dumps(ROUND['mandate'])}")
    # TODO(Lane D): hand ROUND["mandate"] to the Stripe charge and set order.payment_ref from its result.
    # No CommitPayment is sent: it needs a real transaction_id, and inventing one would fake a payment.
    who = "Auto-ordered" if approved_by == "auto" else "Approved and ordered"
    return (f"{who} #{n} within your limit: {order['id']}, ${order['amount']:.2f} from {bid['persona']}. "
            f"Payment NOT charged yet (mandate cap ${order['amount']:.2f}, expires {ROUND['mandate']['expires_at'][:16]}Z).")


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    print(f"buyer address: {agent.address}")
    agent.run()
