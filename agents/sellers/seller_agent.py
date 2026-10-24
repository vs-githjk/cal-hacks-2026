"""One seller uAgent. Run from agents/: python sellers/seller_agent.py seller_1
A custom seller from the Seller Kit runs from its config: python sellers/seller_agent.py --config sellers/custom/<id>.json"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for common
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for policy

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.payment import CommitPayment, CompletePayment, RejectPayment, payment_protocol_spec

import common
import payment
from factory import load_config, pick_port, seller_from_config
from policy import make_bid, seller as load_seller


def persona_line(s: dict, total: float) -> str:
    fallback = f"{s['name']} here: ${total:,.2f} all in" + (f", {s['claims'][0]}." if s["claims"] else ".")
    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback
    try:
        import anthropic
        msg = anthropic.Anthropic(timeout=5).messages.create(
            model="claude-haiku-5-5", max_tokens=40,
            messages=[{"role": "user", "content":
                       f"You are {s['name']}, a {s['archetype']}, bidding at a PC parts auction. "
                       f"Your bid total is ${total:,.2f}. Say one short in-character line. "
                       f"Do not state any price or number other than ${total:,.2f}."}])
        text = msg.content[0].text.strip().splitlines()[0]
        prices = re.findall(r"\$\s?([\d,]+(?:\.\d+)?)", text)
        if not text or any(abs(float(p.replace(",", "")) - total) > 0.005 for p in prices):
            return fallback
        return text
    except Exception:
        return fallback


def build(name: str, cfg: dict | None = None) -> Agent:
    """A catalog seller by name, or a custom seller from a validated SellerConfig `cfg` (name is then cfg["id"])."""
    if cfg is None:
        s = load_seller(name)
        port = common.SELLER_PORTS[name]
        profile = {"readme_path": str(Path(__file__).with_name(f"AGENTVERSE-{name}.md")),
                   "handle": f"techbazaar{name.replace('_', '')}"}
    else:
        s = seller_from_config(cfg)
        name = s["id"]
        common.register_custom_seller(name)
        port = pick_port(cfg)
        profile = {}  # a custom seller has no Agentverse profile page until its owner writes one
    labelled = "simulated (SIM)" if s["origin"] == "SIM" else "LIVE, owner supplied"
    agent = Agent(**common.agent_args(
        name, port, name=s['name'][:32], **profile,
        description=f"Seller agent ({s['archetype']}) that bids in Tech Bazaar's sealed rounds for computer gear. "
                    f"Prices come from policy code, never below its floor. Listings are {labelled}."))
    common.include_profile_chat(agent, f"I am {s['name']}, a Tech Bazaar {s['origin']} seller. I bid on structured sealed "
                                "rounds using policy prices. Send buying goals to @techbazaarbuyer; "
                                "this chat cannot place orders or approve purchases.")

    @agent.on_message(model=common.BidRequest)
    async def on_bid_request(ctx: Context, sender: str, msg: common.BidRequest):
        verdict = common.screen(f"bidreq-{name}-{ctx.session}", sender, msg.need_json,
                                common.shield_context(sender, payee_of_record=agent.address))
        if verdict["verdict"] != "allow":
            ctx.logger.warning(f"ignored BidRequest from {sender}: {verdict['reasons']}")
            return
        bid = make_bid(json.loads(msg.need_json), s)
        if bid is None:
            return
        common.validate("Bid", bid)
        await ctx.send(sender, common.BidReply(bid_json=json.dumps(bid),
                                               persona_line=persona_line(s, bid["total_landed_price"])))

    pay = Protocol(spec=payment_protocol_spec, role="seller")

    @agent.on_message(model=common.OrderPlaced)
    async def on_order(ctx: Context, sender: str, msg: common.OrderPlaced):
        verdict = common.screen(f"order-{name}-{ctx.session}", sender, msg.order_json + "\n" + msg.mandate_json,
                                common.shield_context(sender, payee_of_record=agent.address))
        if verdict["verdict"] != "allow":
            ctx.logger.warning(f"ignored OrderPlaced from {sender}: {verdict['reasons']}")
            return
        mandate = json.loads(msg.mandate_json)
        ctx.logger.info(f"order {mandate['deal_id']} placed; requesting ${mandate['amount']:.2f}")
        await ctx.send(sender, payment.payment_request(mandate, recipient=agent.address))

    @pay.on_message(CommitPayment)
    async def on_commit(ctx: Context, sender: str, msg: CommitPayment):
        verdict = common.screen(f"commit-{name}-{ctx.session}", sender, msg.model_dump_json(),
                                common.shield_context(sender, payee_of_record=agent.address))
        if verdict["verdict"] != "allow":
            ctx.logger.warning(f"ignored CommitPayment from {sender}: {verdict['reasons']}")
            return
        # TODO(Lane D): confirm the Stripe test charge for msg.transaction_id before shipping. No money moved yet.
        ctx.logger.info(f"payment committed: {msg.funds.amount} {msg.funds.currency}, ref {msg.reference}")
        await ctx.send(sender, CompletePayment(transaction_id=msg.transaction_id))

    @pay.on_message(RejectPayment)
    async def on_reject(ctx: Context, sender: str, msg: RejectPayment):
        ctx.logger.warning(f"buyer rejected payment: {msg.reason}")

    agent.include(pay, publish_manifest=True)
    return agent


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run one Tech Bazaar seller agent")
    ap.add_argument("name", nargs="?", default="seller_1", help="a catalog seller (seller_1 to seller_5)")
    ap.add_argument("--config", help="path to a SellerConfig JSON file (custom seller); overrides name")
    args = ap.parse_args()
    if args.config:
        try:
            cfg = load_config(args.config)
        except ValueError as e:
            sys.exit(f"Seller config refused: {e}")
        a, name = build(cfg["id"], cfg), cfg["id"]
    else:
        a, name = build(args.name), args.name
    print(f"{name} address:", a.address)
    a.run()
