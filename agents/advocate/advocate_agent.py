"""Quality Advocate uAgent. Run from the agents folder: python -m advocate.advocate_agent
Every word on a card comes from checks.py code; no model rewrites it, so seller text cannot steer a warning."""
import json

from uagents import Agent, Context

import common
from advocate import checks, mock_data

agent = Agent(**common.agent_args(
    "advocate", 8003, name="Tech Bazaar Quality Advocate", handle="techbazaaradvocate",
    description="Argues for the buyer: checks every seller bid for fit (decided by code), condition claims against "
                "the listing page, price history, CPSC recalls and seller record; vetoes traps with a cited source."))


@agent.on_message(model=common.AdviceRequest, replies=common.AdviceReply)
async def on_advice(ctx: Context, sender: str, msg: common.AdviceRequest):
    verdict = common.screen(f"advice-{ctx.session}", sender, msg.need_json + msg.bids_json)
    if verdict["verdict"] != "allow":
        ctx.logger.warning(f"shield {verdict['verdict']} from {sender}: {verdict['reasons']}")
        return
    need, bids = json.loads(msg.need_json), json.loads(msg.bids_json)
    cards = checks.advise(need, bids, mock_data.BASELINE, mock_data.RECORDS, mock_data.RECALLS,
                          owned=need.get("owned", {}))
    for c in cards:
        common.validate("AdvocateCard", c)
    await ctx.send(sender, common.AdviceReply(cards_json=json.dumps(cards)))


if __name__ == "__main__":
    agent.run()
