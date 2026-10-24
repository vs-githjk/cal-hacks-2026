"""Quality Advocate uAgent. Run from the agents folder: python -m advocate.advocate_agent
Every word on a card comes from checks.py code; no model rewrites it, so seller text cannot steer a warning."""
import json
from pathlib import Path

from uagents import Agent, Context

import common
import status
from advocate import checks, mock_data

agent = Agent(**common.agent_args(
    "advocate", 8003, name="Tech Bazaar Quality Advocate", handle="techbazaaradvocate",
    readme_path=str(Path(__file__).with_name("AGENTVERSE.md")),
    description="Argues for the buyer: checks fit with code and condition claims, price history, recalls and "
                "seller records using SIM fixtures; vetoes traps with cited warnings."))

common.include_profile_chat(agent, "I am Tech Bazaar's Quality Advocate. I review structured seller bids for fit "
                            "and claims with cited warnings. Current checks use SIM fixtures. "
                            "Send buying goals to @techbazaarbuyer; this chat cannot approve purchases.")


@agent.on_event("startup")
async def announce(ctx: Context):
    ctx.logger.info(status.status_line("advocate", "advocate", agent.address, mailbox=common.mailbox_on("advocate")))


@agent.on_message(model=common.AdviceRequest, replies=common.AdviceReply)
async def on_advice(ctx: Context, sender: str, msg: common.AdviceRequest):
    ctx.logger.info(status.msg_line("buyer", "advocate", "advice_request"))
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
    ctx.logger.info(status.msg_line("advocate", "buyer", "advice"))
    await ctx.send(sender, common.AdviceReply(cards_json=json.dumps(cards)))


if __name__ == "__main__":
    agent.run()
