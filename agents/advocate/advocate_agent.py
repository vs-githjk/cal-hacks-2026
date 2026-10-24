"""Quality Advocate uAgent. Run from the agents folder: python -m advocate.advocate_agent"""
import json
import os

from uagents import Agent, Context

import common
from advocate import checks, mock_data

agent = Agent(name="quality_advocate", seed=common.SEEDS["advocate"], port=8003,
              endpoint=["http://localhost:8003/submit"])

# Closed schema: Claude may only return the same number of rephrased strings.
REPHRASE_TOOL = {"name": "rephrase", "description": "Return the warnings rephrased, same count and order.",
                 "input_schema": {"type": "object", "required": ["texts"], "additionalProperties": False,
                                  "properties": {"texts": {"type": "array", "items": {"type": "string"}}}}}


def plainer(cards: list[dict]) -> list[dict]:
    """Optional: Claude rephrases warning text only. kind, numbers, source and recommendation stay code's.
    Any failure keeps the code's text."""
    texts = [w["text"] for c in cards for w in c["warnings"]]
    if not os.getenv("ANTHROPIC_API_KEY") or not texts:
        return cards
    try:
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model="claude-haiku-5-5", max_tokens=1024, tools=[REPHRASE_TOOL],
            tool_choice={"type": "tool", "name": "rephrase"},
            messages=[{"role": "user", "content":
                       "Rephrase each PC part warning for a buyer: plain, one sentence, keep every number and "
                       "name exactly, neutral tone (say a claim 'did not match', never 'wrong' or 'liar'), "
                       "no dashes.\n" + json.dumps(texts)}])
        new = next(b.input["texts"] for b in msg.content if b.type == "tool_use")
        if len(new) != len(texts) or not all(isinstance(t, str) and t.strip() for t in new) \
                or any("—" in t or "–" in t for t in new):
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
    cards = checks.advise(need, bids, mock_data.BASELINE, mock_data.RECORDS, mock_data.RECALLS,
                          owned=need.get("owned", {}))
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
