"""Quality Advocate uAgent. Run from the agents folder: python -m advocate.advocate_agent
Every word on a card comes from checks.py code; no model rewrites it, so seller text cannot steer a warning."""
import json

from uagents import Agent, Context

import common
from advocate import checks, mock_data

agent = Agent(name="quality_advocate", seed=common.SEEDS["advocate"], port=8003,
              endpoint=["http://localhost:8003/submit"])


@agent.on_message(model=common.AdviceRequest, replies=common.AdviceReply)
async def on_advice(ctx: Context, sender: str, msg: common.AdviceRequest):
    verdict = common.screen(f"advice-{ctx.session}", sender, msg.need_json + msg.bids_json,
                            common.shield_context(sender))
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
