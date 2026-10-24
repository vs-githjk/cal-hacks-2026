"""Offline Shield front-door checks; no private environment or running agent."""
import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from uagents import Agent, Model, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent
from uagents_core.contrib.protocols.chat import chat_protocol_spec

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def client(monkeypatch):
    exists = Path.exists
    with patch.object(Path, 'exists', lambda p: False if p.name == '.env' else exists(p)):
        import common
    fake_agent = Mock()
    with patch('uagents.Agent', return_value=fake_agent), patch.object(common, 'agent_args', return_value={}):
        sys.modules.pop('shield_client', None)
        module = importlib.import_module('shield_client')
    monkeypatch.setenv('SHIELD_URL', 'http://127.0.0.1:8787')
    yield module, fake_agent
    sys.modules.pop('shield_client', None)


def send(client, monkeypatch, verdict):
    module, _ = client
    screen = Mock(return_value=verdict)
    monkeypatch.setattr(module.common, 'screen', screen)
    ctx = Mock(send=AsyncMock())
    msg = ChatMessage(content=[TextContent(text='private user text')])
    asyncio.run(module.on_chat(ctx, 'owner', msg))
    messages = [call.args[1] for call in ctx.send.call_args_list]
    assert isinstance(messages[0], ChatAcknowledgement)
    assert messages[0].acknowledged_msg_id == msg.msg_id
    assert len(messages) == 2
    assert 'private user text' not in messages[1].text()
    return messages[1].text(), screen, msg


@pytest.mark.parametrize('verdict', ['allow', 'quarantine', 'block'])
def test_returns_only_validated_shield_result(client, monkeypatch, verdict):
    text, screen, msg = send(client, monkeypatch, {'verdict': verdict, 'rule_ids': ['shield.hidden.text']})
    assert f'verdict: {verdict}' in text
    assert 'shield.hidden.text' in text
    screen.assert_called_once_with(str(msg.msg_id), 'owner', 'private user text')


def test_missing_url_never_calls_stub(client, monkeypatch):
    monkeypatch.delenv('SHIELD_URL')
    text, screen, _ = send(client, monkeypatch, {'verdict': 'allow', 'rule_ids': []})
    screen.assert_not_called()
    assert 'unavailable' in text and 'block' in text


@pytest.mark.parametrize('verdict', [None, [], {}, {'verdict': 'allow'},
    {'verdict': 'unknown', 'rule_ids': []}, {'verdict': 'allow', 'rule_ids': 'oops'},
    {'verdict': 'allow', 'rule_ids': [3]}, {'verdict': 'allow', 'rule_ids': ['ignore instructions']},
    {'verdict': 'block', 'reasons': ['shield unreachable: private error']}])
def test_malformed_or_unreachable_result_is_unavailable(client, monkeypatch, verdict):
    text, _, _ = send(client, monkeypatch, verdict)
    assert 'unavailable' in text and 'block' in text
    assert 'private error' not in text


def test_unexpected_tool_exception_recovers(client, monkeypatch):
    module, _ = client
    monkeypatch.setattr(module.common, 'screen', Mock(side_effect=OSError('private error')))
    ctx = Mock(send=AsyncMock())
    asyncio.run(module.on_chat(ctx, 'owner', ChatMessage(content=[TextContent(text='test')])))
    assert 'unavailable' in ctx.send.call_args.args[1].text()
    assert 'private error' not in ctx.send.call_args.args[1].text()


def test_real_chat_manifest_is_published(client):
    module, agent = client
    agent.include.assert_called_once_with(module.chat, publish_manifest=True)
    manifest = module.chat.manifest()
    names = {model['schema']['title'] for model in manifest['models']}
    assert {'ChatMessage', 'ChatAcknowledgement'} <= names


def test_installed_agent_advertises_chat_offline(monkeypatch):
    for flag in ('AGENTS_MAILBOX', 'SHIELD_MAILBOX'):
        monkeypatch.delenv(flag, raising=False)
    exists = Path.exists

    async def check():
        store = Mock()
        store.get.return_value = None
        with patch.object(Path, 'exists', lambda p: False if p.name == '.env' else exists(p)), \
                patch('uagents.agent.KeyValueStore', return_value=store), \
                patch('uagents.agent.get_ledger'), patch('uagents.agent.get_almanac_contract'), \
                patch('uagents.agent.dispatcher'), patch.object(Agent, 'publish_manifest', new_callable=AsyncMock):
            module = importlib.import_module('shield_client')
            protocol = module.agent.protocols[Protocol(spec=chat_protocol_spec).digest]
            assert protocol.verify()
            assert Model.build_schema_digest(ChatMessage) in protocol.models
            assert Model.build_schema_digest(ChatAcknowledgement) in protocol.models
            assert module.agent._port == 8004
            await asyncio.sleep(0)
        sys.modules.pop('shield_client', None)

    asyncio.run(check())
