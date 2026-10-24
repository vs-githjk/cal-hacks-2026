"""Quality Advocate uAgent. Run from the agents folder: python -m advocate.advocate_agent"""
import json
import os

from uagents import Agent, Context

import common
from advocate import checks, mock_data

agent = Agent(name="quality_advocate", seed=common.SEEDS["advocate"], port=8003,
              endpoint=["http://localhost:8003/submit"])


def plainer(cards: list[dict]) -> list[dict]:
    """Optional: Claude rewrites warning text only. Any failure keeps the original text."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return cards
    try:
        import anthropic
        texts = [w["text"] for c in cards for w in c["warnings"]]
        if not texts:
            return cards
        msg = anthropic.Anthropic().messages.create(
            model="claude-haiku-5-5", max_tokens=1024,
            messages=[{"role": "user", "content":
                       "Rewrite each warning for a busy restaurant owner: plainer, one sentence, keep every "
                       "number exactly. Return ONLY a JSON array of strings, same length and order.\n"
                       + json.dumps(texts)}])
        new = json.loads(msg.content[0].text)
        if not (isinstance(new, list) and len(new) == len(texts) and all(isinstance(t, str) and t for t in new)):
            return cards
        it = iter(new)
        for c in cards:
            for w in c["warnings"]:
                w["text"] = next(it)
    except Exception:
        pass
    return cards


@agent.on_message(model=common.AdviceRequest, replies=common.AdviceReply)
async def on_advice(ctx: Context, sender: str, msg: common.AdviceRequest):
    verdict = common.screen(f"advice-{ctx.session}", sender, msg.need_json + msg.bids_json)
    if verdict["verdict"] != "allow":
        ctx.logger.warning(f"shield {verdict['verdict']} from {sender}: {verdict['reasons']}")
        return
    need, bids = json.loads(msg.need_json), json.loads(msg.bids_json)
    cards = checks.advise(need, bids, mock_data.BASELINE, mock_data.SIGNALS, mock_data.RECALLS)
    original = json.loads(json.dumps(cards))
    cards = plainer(cards)
    try:
        for c in cards:
            common.validate("AdvocateCard", c)
    except Exception:
        cards = original
    await ctx.send(sender, common.AdviceReply(cards_json=json.dumps(cards)))


if __name__ == "__main__":
    agent.run()
