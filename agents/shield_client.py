"""ASI:One front door for the existing Shield HTTP API. Run from agents/.
Paste a listing and ask "is this fishy?": the reply gives the verdict, the matched phrase, the rule id, a plain reason and a
rewrite that Smell Test passed again (smell.py). "What is on the quarantine list?" gets counts from the shared list that every
agent's common.screen reads (smell_memory.py). The verdict is Shield's; a model may only reword the reason sentence."""
import asyncio
import os
import re
from pathlib import Path

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

import common
import phrasing
import smell
import smell_memory

agent = Agent(**common.agent_args(
    'shield', 8004, name='Fish Market Smell Test', handle='techbazaarshield',
    readme_path=str(Path(__file__).with_name('SHIELD_AGENTVERSE.md')),
    description='Screens a message through Smell Test (nothing fishy gets through) and returns its verdict, rule IDs, the '
                'phrase that smelled, why, and a rewrite that passes again. Paste a listing and ask "is this fishy?". '
                'A client of the existing Shield API; no purchases or payments.'))
chat = Protocol(spec=chat_protocol_spec)
UNAVAILABLE = 'Smell Test unavailable. Verdict: block. No action taken.'


def _valid(result) -> bool:
    return (isinstance(result, dict) and result.get('verdict') in ('allow', 'quarantine', 'block')
            and isinstance(result.get('rule_ids'), list)
            and all(isinstance(rule, str) and re.fullmatch(r'[a-z][a-z0-9_.-]{0,95}', rule) for rule in result['rule_ids']))


async def _reasons_reworded(explained: dict) -> dict:
    """The model may reword each reason sentence (guarded in phrasing.py); a failure leaves the code's own sentence."""
    unique = list(dict.fromkeys(f['reason'] for f in explained['findings']))
    return dict(zip(unique, await asyncio.gather(*(asyncio.to_thread(phrasing.phrase, r) for r in unique)))) if unique else {}


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    text = UNAVAILABLE
    body = msg.text()
    if smell.is_memory_query(body):
        memory = smell_memory.default()
        text = smell.render_memory(memory.summary() if memory is not None else None)
    elif os.getenv('SHIELD_URL', '').strip():
        try:
            result = common.screen(str(msg.msg_id), sender, body)
            if _valid(result):
                explained = smell.explain(body, result, screen=lambda rewrite: common.screen(f'{msg.msg_id}-rewrite', sender, rewrite))
                words = await _reasons_reworded(explained)
                text = smell.render(explained, phrase=lambda reason: words.get(reason, reason))
        except Exception:
            pass  # Transport or malformed tool failure must still return a safe chat reply.
    await ctx.send(sender, ChatMessage(content=[TextContent(text=text)]))


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat, publish_manifest=True)

if __name__ == '__main__':
    agent.run()
