"""Quality Advocate uAgent. Run from the agents folder: python -m advocate.advocate_agent
Every word on a card comes from checks.py code; no model rewrites it, so seller text cannot steer a warning.
Depth (Lane D): cards also carry a total-cost ranking (tco.py, advisory), a one-sentence explanation (explain.py), and, when a
listing page leaves a condition open, the seller's answer to ONE chat question (clarify.py). In ASI:One chat the Advocate
answers "is this card worth it" and "will it fit" with the same checks (qa.py)."""
import asyncio
import json
import os
from pathlib import Path

from uagents import Agent, Context
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

import common
import status
from advocate import checks, clarify, explain, qa, real_data, tco

agent = Agent(**common.agent_args(
    "advocate", 8003, name="Fish Market Quality Advocate", handle="techbazaaradvocate",
    readme_path=str(Path(__file__).with_name("AGENTVERSE.md")),
    description="Argues for the buyer: checks fit with code and condition claims, price history, recalls and "
                "seller records using SIM fixtures; vetoes traps with cited warnings. Weighs total cost, asks a seller "
                "before it vetoes, and answers worth-it and fit questions in chat."))

_CTX: dict = {}  # the context of the advice request in flight, so the clarifier can send a chat message to a seller


async def _send_chat(address: str, text: str):
    await _CTX["ctx"].send(address, ChatMessage(content=[TextContent(text=text)]))


clarifier = clarify.Clarifier(_send_chat, common.address)


async def seller_reply(ctx: Context, sender: str, msg: ChatMessage) -> bool:
    """A chat message from a seller we just asked is its answer. It is screened first; a blocked reply is not read."""
    if not clarifier.is_waiting(sender):
        return False
    verdict = await asyncio.to_thread(common.screen, str(msg.msg_id), sender, msg.text(), common.shield_context(sender))
    clarifier.offer(sender, msg.text(), allowed=verdict.get("verdict") == "allow")
    return True


common.include_profile_chat(agent, "I am the Fish Market Quality Advocate, Fish Market's quality advocate. I review structured seller bids for fit "
                            "and claims with cited warnings, weigh total cost, and answer 'is this card worth it' and 'will it fit my case' "
                            "questions: tell me the card, price, condition, and your case clearance and PSU watts. "
                            "Current checks use SIM fixtures. "
                            "Send buying goals to @techbazaarbuyer; this chat cannot approve purchases.",
                            answer=qa.answer, intercept=seller_reply)


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
    _CTX["ctx"] = ctx

    async def lookups():
        # dated baseline, CPSC; unverified lookups become notes. In a thread: the CPSC lookups take up to 10 s (#330)
        return await asyncio.to_thread(real_data.advice_inputs, need, bids)

    async def questions():
        try:  # ask-before-veto runs beside the lookups, so it adds no wait; any failure means no question was asked
            return await clarifier.ask_all(need, bids)
        except Exception:
            return {}

    (baseline, records, recalls, notes), answers = await asyncio.gather(lookups(), questions())
    cards = checks.advise(need, bids, baseline, records, recalls, owned=need.get("owned", {}), clarifications=answers,
                          track=tco.load_track(os.environ.get("ADVOCATE_TRACK_FILE")))
    cards = [explain.attach(c) for c in real_data.with_notes(cards, notes)]  # notes are info warnings: the sentence is rebuilt
    for c in cards:
        common.validate("AdvocateCard", c)
    ctx.logger.info(status.msg_line("advocate", "buyer", "advice"))
    await ctx.send(sender, common.AdviceReply(cards_json=json.dumps(cards)))


if __name__ == "__main__":
    common.require_peer_seeds("advocate")   # #449 RT-27: production mode needs the buyer's private seed
    agent.run()
