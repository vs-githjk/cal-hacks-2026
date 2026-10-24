"""Offline buyer handler checks: failed review must never authorize a purchase."""
import asyncio
import importlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def buyer(monkeypatch):
    # Agent construction writes local identity storage; handlers need no running agent.
    fake_agent = Mock()
    fake_agent.on_message.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_interval.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_rest_post.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_rest_get.side_effect = lambda *a, **k: lambda fn: fn
    exists = Path.exists
    with patch('uagents.Agent', return_value=fake_agent), patch.object(
            Path, 'exists', lambda p: False if p.name == '.env' else exists(p)):
        module = importlib.import_module('buyer_agent')
    monkeypatch.setattr(module, 'ALLOWANCE', 1000)
    monkeypatch.setattr(module, 'blocked_reasons', lambda *a: None)
    module.ROUND.clear()
    module.APPROVALS.clear()
    module.ROUND.update(
        owner='owner', phase='advice', deadline=time.time() - 1, quoted_at=time.time(),
        need={'id': 'need-1', 'buyer_id': 'owner', 'spend_limit': 800, 'items': [], 'auction_window_s': 12},
        goal={'id': 'goal-1', 'deadline': '2099-01-01T00:00:00Z', 'state': 'HUNTING'},
        bids=[{'id': 'bid-1', 'supplier_id': 'seller_1', 'total_landed_price': 582,
               'persona': 'Seller', 'source': 'SIM'}],
        cards={}, personas={}, owned=[], attempts=0, last_sent={})
    yield module
    module.ROUND.clear()
    module.APPROVALS.clear()


class Context:
    def __init__(self, fail_to=None):
        self.logger = Mock()
        self.sent = []
        self.fail_to = fail_to

    async def send(self, to, message):
        if to == self.fail_to:
            raise OSError('tool unavailable')
        self.sent.append((to, message))

    def owner_text(self):
        return '\n'.join(message.text() for to, message in self.sent if to == 'owner')


def card(**updates):
    return dict(need_id='need-1', bid_id='bid-1', warnings=[], recommendation='buy', wait_until='') | updates


@pytest.mark.parametrize('payload', ['{', '[]', '{}', '[1]', json.dumps([card(need_id='old')]),
                                      json.dumps([card(bid_id='other')]),
                                      json.dumps([card(recommendation='unknown')]),
                                      json.dumps([card(), card()])])
def test_invalid_review_retries_without_manual_or_auto_purchase(buyer, payload):
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=payload)))
    asyncio.run(buyer.handle_text(ctx, 'owner', 'APPROVE 1'))
    assert not buyer.ROUND.get('order')
    assert not buyer.APPROVALS
    assert buyer.ROUND['phase'] == 'waiting'
    assert 'Nothing ordered' in ctx.owner_text()
    assert 'next round' in ctx.owner_text()


def test_advice_timeout_retries_then_pauses(buyer):
    ctx = Context()
    for _ in range(3):
        buyer.ROUND.update(phase='advice', deadline=time.time() - 1)
        asyncio.run(buyer.tick(ctx))
        asyncio.run(buyer.handle_text(ctx, 'owner', 'APPROVE 1'))
        assert not buyer.ROUND.get('order')
    assert buyer.ROUND['goal']['state'] == 'PAUSED'
    assert 'paused' in ctx.owner_text()


def test_recovery_notice_is_not_suppressed_by_progress_throttle(buyer):
    buyer.ROUND['last_sent']['progress to goal'] = time.time()
    ctx = Context()
    asyncio.run(buyer.tick(ctx))
    assert 'Nothing ordered' in ctx.owner_text()
    assert 'next round' in ctx.owner_text()


def test_shield_blocked_review_retries(buyer, monkeypatch):
    monkeypatch.setattr(buyer, 'blocked_reasons', lambda *a: 'injection')
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=json.dumps([card()]))))
    assert buyer.ROUND['phase'] == 'waiting'
    assert 'Shield' in ctx.owner_text() and 'Nothing ordered' in ctx.owner_text()


def test_missing_card_in_multi_bid_round_retries(buyer):
    buyer.ROUND['bids'].append(dict(buyer.ROUND['bids'][0], id='bid-2', supplier_id='seller_2'))
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=json.dumps([card()]))))
    assert buyer.ROUND['phase'] == 'waiting'
    assert not buyer.ROUND.get('order') and not buyer.APPROVALS


def test_advice_send_failure_recovers(buyer):
    buyer.ROUND['phase'] = 'bidding'
    ctx = Context(fail_to=buyer.common.address('advocate'))
    asyncio.run(buyer.tick(ctx))
    assert buyer.ROUND['phase'] == 'waiting'
    assert 'Nothing ordered' in ctx.owner_text()


@pytest.mark.parametrize('recommendation', [None, 'veto'])
def test_approval_and_order_boundary_reject_unreviewed_or_vetoed_bid(buyer, recommendation):
    buyer.ROUND['phase'] = 'decided'
    if recommendation:
        buyer.ROUND['reviewed'] = True
        buyer.ROUND['cards']['bid-1'] = card(recommendation=recommendation)
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'owner', 'APPROVE 1'))
    result = asyncio.run(buyer.place_order(ctx, 1, approved_by='auto', approval_id='auto-1'))
    assert not buyer.ROUND.get('order') and not buyer.APPROVALS
    assert not any(isinstance(msg, buyer.common.BidRequest) for _, msg in ctx.sent)
    assert 'not ordering' in result.lower()


@pytest.mark.parametrize('allowance', [0, 1000])
def test_complete_review_preserves_manual_requote_and_auto_order(buyer, monkeypatch, allowance):
    monkeypatch.setattr(buyer, 'ALLOWANCE', allowance)
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=json.dumps([card()]))))
    if allowance == 0:
        asyncio.run(buyer.handle_text(ctx, 'owner', 'APPROVE 1'))
        assert buyer.ROUND['phase'] == 'requote' and not buyer.ROUND.get('order')
        asyncio.run(buyer.on_requote(ctx, dict(buyer.ROUND['bids'][0])))
    assert buyer.ROUND['order']['amount'] == 582
    assert buyer.ROUND['goal']['state'] == 'DONE'


def test_async_review_result_keeps_original_asi_chat_session_and_protocol(buyer, monkeypatch):
    from uagents.context import ExternalContext
    from uagents.crypto import Identity
    from uagents.types import MsgInfo
    from uagents_core.types import DeliveryStatus, MsgStatus

    monkeypatch.setattr(buyer, 'ALLOWANCE', 0)
    envelopes = []
    identity = Identity.from_seed('offline-buyer-route-test', 0)
    owner = Identity.from_seed('offline-owner-route-test', 0).address
    incoming_session = uuid4()

    def queued(envelope, endpoints, future, sync):
        envelopes.append(envelope)
        future.set_result(MsgStatus(status=DeliveryStatus.DELIVERED, detail='offline',
                                    destination=envelope.target, endpoint='offline', session=envelope.session))

    def context(session, protocol):
        return ExternalContext(
            agent=SimpleNamespace(identity=identity, address=identity.address), storage=Mock(), ledger=Mock(),
            resolver=SimpleNamespace(resolve=AsyncMock(side_effect=lambda destination: (destination, ['offline']))),
            dispenser=SimpleNamespace(add_envelope=queued), session=session, logger=Mock(),
            message_received=MsgInfo(message='', sender=owner, schema_digest='offline'), protocol=protocol)

    async def run():
        owner_ctx = context(incoming_session, (buyer.chat.digest, buyer.chat))
        advocate_ctx = context(uuid4(), ('structured-advice-protocol', None))
        tick_ctx = context(uuid4(), ('', None))
        bid = dict(buyer.ROUND['bids'][0])
        buyer.ROUND.clear()
        with patch('uagents.context.dispatcher.contains', return_value=False):
            await buyer.on_chat(owner_ctx, owner, buyer.ChatMessage(content=[buyer.TextContent(text='GPU under $800')]))
            buyer.ROUND.update(phase='advice', bids=[bid])
            await buyer.on_advice(advocate_ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
                cards_json=json.dumps([card(need_id=buyer.ROUND['need']['id'])])))
            final = envelopes[-1]
            assert 'APPROVE 1' in final.decode_payload()
            assert final.target == owner
            assert final.session == incoming_session
            assert final.protocol_digest == buyer.chat.digest

            buyer.ROUND['goal'].update(deadline='2000-01-01T00:00:00Z', state='HUNTING')
            await buyer.tick(tick_ctx)
            assert 'EXPIRED' in envelopes[-1].decode_payload()
            assert envelopes[-1].session == incoming_session
            assert envelopes[-1].protocol_digest == buyer.chat.digest

            updated_session = uuid4()
            updated_ctx = context(updated_session, (buyer.chat.digest, buyer.chat))
            await buyer.on_chat(updated_ctx, owner, buyer.ChatMessage(content=[buyer.TextContent(text='APPROVE 1')]))
            await buyer.tell_owner(advocate_ctx, 'Followup on latest owner command')
            assert envelopes[-1].session == updated_session
            assert envelopes[-1].protocol_digest == buyer.chat.digest

    asyncio.run(run())


def test_web_followup_stays_in_web_queue(buyer):
    buyer.ROUND.update(owner=buyer.WEB, owner_context=None, events=['Bid in'])
    buyer.WEB_OUTBOX.clear()
    ctx = Context()
    asyncio.run(buyer.tell_owner(ctx, 'Review ready'))
    assert buyer.web_drain().replies == ['Bid in\nReview ready']
    assert not ctx.sent


def _open_round(buyer, monkeypatch, *, mailbox, seeded):
    """Send one goal from the owner and return (BidRequest recipients, the owner's text)."""
    common = buyer.common
    monkeypatch.delenv('AGENTS_MAILBOX', raising=False)
    monkeypatch.delenv('SELLERS_MAILBOX', raising=False)
    if mailbox:
        monkeypatch.setenv('AGENTS_MAILBOX', '1')
    for s in common.SELLERS:
        monkeypatch.setitem(common.SEEDS, s, f'private-seed-{s}' if s in seeded else f'tech-bazaar-{s}-dev')
    buyer.ROUND.clear()
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'owner', 'NEW a 850 W PSU under $150'))
    bids = [to for to, message in ctx.sent if isinstance(message, common.BidRequest)]
    return bids, ctx.owner_text(), common


def test_mailbox_round_counts_only_sellers_that_can_run(buyer, monkeypatch):
    # AGENTS_MAILBOX=1, seeds set for seller_1 to seller_3 only: seller_4 and seller_5 keep the public dev seed and never run.
    bids, text, common = _open_round(buyer, monkeypatch, mailbox=True, seeded={'seller_1', 'seller_2', 'seller_3'})
    assert sorted(bids) == sorted(common.address(s) for s in ['seller_1', 'seller_2', 'seller_3'])
    assert 'with 3 sellers' in text
    assert '5 sellers' not in text


def test_local_round_still_counts_all_five_sellers(buyer, monkeypatch):
    bids, text, common = _open_round(buyer, monkeypatch, mailbox=False, seeded=set())
    assert len(bids) == 5
    assert 'with 5 sellers' in text
