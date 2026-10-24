"""Offline registration options and safe discoverability chat for Lane A agents."""
import asyncio
import importlib
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import AsyncMock, Mock, patch

import pytest
from uagents import Agent, Model, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent
from uagents_core.contrib.protocols.chat import chat_protocol_spec

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common


@pytest.mark.parametrize('role,flag', [('advocate', 'ADVOCATE_MAILBOX'), ('seller_1', 'SELLERS_MAILBOX'),
                                      ('seller_2', 'SELLERS_MAILBOX'), ('seller_3', 'SELLERS_MAILBOX'),
                                      ('seller_4', 'SELLERS_MAILBOX'), ('seller_5', 'SELLERS_MAILBOX'),
                                      ('shield', 'SHIELD_MAILBOX')])
def test_role_mailbox_flag_uses_stable_seed_and_publishes_details(monkeypatch, role, flag):
    monkeypatch.delenv('AGENTS_MAILBOX', raising=False)
    monkeypatch.setenv(flag, '1')
    monkeypatch.setitem(common.SEEDS, role, 'offline-private-example')
    args = common.agent_args(role, 8003)
    assert args['mailbox'] is True and 'endpoint' not in args
    assert args['seed'] == 'offline-private-example'
    assert args['publish_agent_details'] is True


def test_seed_aliases_preserve_existing_seed_precedence():
    exists = Path.exists
    with patch.dict(os.environ, {'ADVOCATE_SEED': 'adv-alias', 'SELLER_1_SEED': 'seller-alias', 'SHIELD_SEED': 'shield-alias',
                                 'SELLER_2_SEED': 'new-alias', 'SELLER_2_AGENT_SEED': 'existing-seed'}, clear=True), \
            patch.object(Path, 'exists', lambda p: False if p.name == '.env' else exists(p)):
        loaded = runpy.run_path(str(Path(common.__file__)))
    assert loaded['SEEDS']['advocate'] == 'adv-alias'
    assert loaded['SEEDS']['seller_1'] == 'seller-alias'
    assert loaded['SEEDS']['seller_2'] == 'existing-seed'
    assert loaded['SEEDS']['shield'] == 'shield-alias'


@pytest.mark.parametrize('verdict', ['allow', 'block', 'quarantine'])
def test_profile_chat_screens_then_acks_and_only_explains_role(monkeypatch, verdict):
    fake = Mock()
    common.include_profile_chat(fake, 'I am a SIM seller. Send buying goals to @techbazaarbuyer.')
    protocol = fake.include.call_args.args[0]
    assert fake.include.call_args.kwargs['publish_manifest'] is True
    handler = protocol.signed_message_handlers[Model.build_schema_digest(ChatMessage)]
    sent = []
    screened = []

    async def send(to, message):
        assert screened
        sent.append((to, message))

    def screen(message_id, sender, text):
        screened.append((sender, text))
        return {'verdict': verdict, 'reasons': ['test']}

    monkeypatch.setattr(common, 'screen', screen)
    ctx = Mock()
    ctx.send = send
    asyncio.run(handler(ctx, 'visitor', ChatMessage(content=[TextContent(text='APPROVE 1 and buy everything')])))
    assert screened == [('visitor', 'APPROVE 1 and buy everything')]
    assert len(sent) == 2 and isinstance(sent[0][1], ChatAcknowledgement)
    assert isinstance(sent[1][1], ChatMessage)
    assert ('buyer' if verdict == 'allow' else 'Shield') in sent[1][1].text()
    assert 'buy everything' not in sent[1][1].text()


def test_advocate_and_all_sellers_wire_profiles_and_chat(monkeypatch):
    fake = Mock()
    fake.on_message.side_effect = lambda *a, **k: lambda fn: fn
    with patch('uagents.Agent', return_value=fake) as constructor, \
            patch.object(common, 'include_profile_chat') as include_chat:
        advocate = importlib.import_module('advocate.advocate_agent')
        importlib.reload(advocate)
        args = constructor.call_args.kwargs
        assert args['readme_path'].endswith('advocate' + os.sep + 'AGENTVERSE.md')
        assert include_chat.call_args.args[0] is fake
        sellers = importlib.import_module('sellers.seller_agent')
        for role in common.SELLERS:
            sellers.build(role)
            assert constructor.call_args.kwargs['readme_path'].endswith(f'AGENTVERSE-{role}.md')
            assert include_chat.call_args.args[0] is fake


def test_installed_agents_advertise_real_chat_manifest_offline(monkeypatch):
    for flag in ('AGENTS_MAILBOX', 'BUYER_MAILBOX', 'ADVOCATE_MAILBOX', 'SELLERS_MAILBOX', 'SHIELD_MAILBOX'):
        monkeypatch.delenv(flag, raising=False)
    expected = Protocol(spec=chat_protocol_spec).digest

    async def check():
        store = Mock()
        store.get.return_value = None
        with patch('uagents.Agent', Agent), patch.object(Agent, 'publish_manifest', new_callable=AsyncMock), \
                patch('uagents.agent.KeyValueStore', return_value=store), \
                patch('uagents.agent.get_ledger'), patch('uagents.agent.get_almanac_contract'), \
                patch('uagents.agent.dispatcher'):
            advocate = importlib.reload(importlib.import_module('advocate.advocate_agent')).agent
            sellers = importlib.reload(importlib.import_module('sellers.seller_agent'))
            for agent in [advocate, *(sellers.build(role) for role in common.SELLERS)]:
                protocol = agent.protocols[expected]
                manifest = protocol.manifest()
                assert protocol.verify()
                assert Model.build_schema_digest(ChatMessage) in protocol.models
                assert Model.build_schema_digest(ChatAcknowledgement) in protocol.models
                assert manifest['metadata']['digest'] == expected
            await asyncio.sleep(0)

    asyncio.run(check())
