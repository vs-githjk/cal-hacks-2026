"""One uAgent that bids for the whole simulated supplier fleet. Run from agents/: python supplier/supplier_agent.py"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for common
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for policy

from uagents import Agent, Context

import common
from policy import load, make_bid

CATALOG = load()
agent = Agent(name="supplier_gateway", seed=common.SEEDS["supplier"], port=8002,
              endpoint=["http://localhost:8002/submit"])


def persona_line(supplier: dict, total: float) -> str:
    fallback = f"{supplier['name']} here: ${total:,.2f} landed, {supplier['claims'][0]}."
    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback
    try:
        import anthropic
        msg = anthropic.Anthropic(timeout=5).messages.create(
            model="claude-haiku-5-5", max_tokens=40,
            messages=[{"role": "user", "content":
                       f"You are {supplier['name']}, a {supplier['archetype']} at a restaurant ingredient auction. "
                       f"Your bid is ${total:,.2f}. Say one short in-character line. Do not state any other price."}])
        text = msg.content[0].text.strip().splitlines()[0]
        return text or fallback
    except Exception:
        return fallback


@agent.on_message(model=common.BidRequest)
async def on_bid_request(ctx: Context, sender: str, msg: common.BidRequest):
    verdict = common.screen(f"bidreq-{ctx.session}", sender, msg.need_json)
    if verdict["verdict"] != "allow":
        ctx.logger.warning(f"ignored BidRequest from {sender}: {verdict['reasons']}")
        return
    need = json.loads(msg.need_json)
    for supplier in CATALOG["suppliers"]:
        bid = make_bid(need, supplier, CATALOG)
        if bid is None:
            continue
        common.validate("Bid", bid)
        await ctx.send(sender, common.BidReply(bid_json=json.dumps(bid),
                                               persona_line=persona_line(supplier, bid["total_landed_price"])))


if __name__ == "__main__":
    print("supplier_gateway address:", agent.address)
    agent.run()
