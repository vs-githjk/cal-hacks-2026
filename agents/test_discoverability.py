"""Offline checks that the caller and Market Pulse can be found on Agentverse and ASI:One (#383 item 7)."""
import asyncio
import importlib
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

from uagents import Protocol
from uagents_core.contrib.protocols.chat import chat_protocol_spec

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common


def test_caller_has_its_own_mailbox_flag(monkeypatch):
    monkeypatch.delenv('AGENTS_MAILBOX', raising=False)
    monkeypatch.delenv('SELLERS_MAILBOX', raising=False)
    monkeypatch.setenv('CALLER_MAILBOX', '1')
    assert common.mailbox_on('caller') is True
    monkeypatch.delenv('CALLER_MAILBOX')
    monkeypatch.setenv('SELLERS_MAILBOX', '1')
    assert common.mailbox_on('caller') is False  # the sellers' flag must not put the caller on Agentverse


def test_caller_has_readme_handle_and_a_profile_chat(monkeypatch):
    fake = Mock()
    fake.on_message.side_effect = lambda *a, **k: lambda fn: fn
    with patch('uagents.Agent', return_value=fake) as constructor, patch.object(common, 'include_profile_chat') as include_chat:
        importlib.reload(importlib.import_module('caller.caller_agent'))
    kwargs = constructor.call_args.kwargs
    assert kwargs['readme_path'].endswith('caller' + os.sep + 'AGENTVERSE.md')
    assert kwargs['handle'] == os.getenv('CALLER_AGENT_HANDLE', 'techbazaarcaller')
    assert include_chat.call_args.args[0] is fake
    text = include_chat.call_args.args[1]
    assert 'cannot' in text and 'approve' in text


def test_pulse_agent_has_handle_readme_and_chat(monkeypatch):
    for name in ('PULSE_MAILBOX', 'AGENTS_MAILBOX', 'PULSE_AGENT_HANDLE'):
        monkeypatch.delenv(name, raising=False)
    asyncio.set_event_loop(asyncio.new_event_loop())  # earlier tests close the main thread's loop
    orchestrator = importlib.import_module('pulse.orchestrator')
    agent = orchestrator.build_agent(Mock())
    assert Protocol(spec=chat_protocol_spec).digest in agent.protocols
    with patch('uagents.Agent') as constructor:
        orchestrator.build_agent(Mock())
    kwargs = constructor.call_args.kwargs
    assert kwargs['handle'] == 'techbazaarpulse'
    assert kwargs['readme_path'].endswith('pulse' + os.sep + 'AGENTVERSE.md')
    monkeypatch.setenv('PULSE_AGENT_HANDLE', 'mypulse')
    with patch('uagents.Agent') as constructor:
        orchestrator.build_agent(Mock())
    assert constructor.call_args.kwargs['handle'] == 'mypulse'


def test_every_discoverable_agent_has_a_readme_with_the_required_badges():
    root = Path(__file__).resolve().parent
    for rel in ('caller/AGENTVERSE.md', 'pulse/AGENTVERSE.md', 'sellers/AGENTVERSE-seller_4.md', 'sellers/AGENTVERSE-seller_5.md'):
        text = (root / rel).read_text(encoding='utf-8')
        assert 'tag:innovationlab' in text and 'tag:hackathon' in text, rel
        for heading in ('## Summary', '## What it accepts', '## Example ASI:One prompts', '## SIM, MIRROR and LIVE'):
            assert heading in text, f'{rel} lacks {heading}'
