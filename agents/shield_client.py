"""ASI:One front door for the existing Shield HTTP API. Run from agents/."""
import os
import re
from pathlib import Path

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

import common

agent = Agent(**common.agent_args(
    'shield', 8004, name='Tech Bazaar Shield Client', handle='techbazaarshield',
    readme_path=str(Path(__file__).with_name('SHIELD_AGENTVERSE.md')),
    description='Screens a message through Bazaar Shield and returns its verdict and rule IDs. '
                'A client of the existing Shield API; no purchases or payments.'))
chat = Protocol(spec=chat_protocol_spec)
UNAVAILABLE = 'Shield unavailable. Verdict: block. No action taken.'


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    text = UNAVAILABLE
    if os.getenv('SHIELD_URL', '').strip():
        try:
            result = common.screen(str(msg.msg_id), sender, msg.text())
            if (isinstance(result, dict) and result.get('verdict') in ('allow', 'quarantine', 'block')
                    and isinstance(result.get('rule_ids'), list)
                    and all(isinstance(rule, str) and re.fullmatch(r'[a-z][a-z0-9_.-]{0,95}', rule)
                            for rule in result['rule_ids'])):
                rules = ', '.join(result['rule_ids']) or 'none'
                text = f"Shield verdict: {result['verdict']}. Rules: {rules}. No action taken."
        except Exception:
            pass  # Transport or malformed tool failure must still return a safe chat reply.
    await ctx.send(sender, ChatMessage(content=[TextContent(text=text)]))


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat, publish_manifest=True)

if __name__ == '__main__':
    agent.run()
