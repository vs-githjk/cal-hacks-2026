"""Offline buyer handler checks: failed review must never authorize a purchase."""
import asyncio
import importlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import crs

REAL_CHECK_SELLERS = crs.check_sellers
REAL_ELIGIBLE = crs.eligible


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
    async def checks(now):
        return {'seller_1': {'eligible': True, 'signal': {'supplier_id': 'seller_1', 'stability': 'verified_stable',
                                        'checked_at': '2026-10-24T08:00:00Z', 'source': 'sandbox'},
                            'reason': 'Synthetic representative identity verified by CRS sandbox.'}}
    monkeypatch.setattr(crs, 'check_sellers', checks)
    monkeypatch.setattr(crs, 'eligible', lambda supplier_id, check, now: bool(check and check.get('eligible')))
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
    module.ROUND['seller_checks'] = {'seller_1': {'eligible': True, 'signal': {
        'supplier_id': 'seller_1', 'stability': 'verified_stable', 'checked_at': '2026-10-24T08:00:00Z',
        'source': 'sandbox'}, 'reason': 'Synthetic representative identity verified by CRS sandbox.'}}
    yield module
    module.ROUND.clear()
    module.APPROVALS.clear()


class Context:
    def __init__(self, fail_to=None):
        self.logger = Mock()
        self.sent = []
        self.fail_to = fail_to
        self.session = uuid4()

    async def send(self, to, message):
        if to == self.fail_to:
            raise OSError('tool unavailable')
        self.sent.append((to, message))

    def owner_text(self):
        return '\n'.join(message.text() for to, message in self.sent if to == 'owner')


def run_bounded(coro):
    asyncio.run(asyncio.wait_for(coro, timeout=5))


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


def test_crs_ineligible_cheapest_bid_stays_displayed_but_cannot_order(buyer, monkeypatch):
    buyer.ROUND.update(phase='advice', bids=[
        {'id': 'bad', 'supplier_id': 'seller_2', 'total_landed_price': 100, 'persona': 'Cheap Seller', 'source': 'SIM'},
        dict(buyer.ROUND['bids'][0], id='good', total_landed_price=200, persona='Verified Seller')],
        seller_checks={'seller_1': buyer.ROUND['seller_checks']['seller_1'],
                       'seller_2': {'signal': None, 'reason': 'Seller consent is missing or withdrawn.'}})
    cards = [card(need_id='need-1', bid_id='bad'), card(need_id='need-1', bid_id='good')]
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=json.dumps(cards))))
    assert len(buyer.ROUND['bids']) == 2
    assert buyer.ROUND['order']['bid_id'] == 'good'
    assert not any(isinstance(msg, buyer.common.OrderPlaced) and to == buyer.common.address('seller_2')
                   for to, msg in ctx.sent)
    assert 'Cheap Seller' in ctx.owner_text() and 'consent is missing' in ctx.owner_text()


def test_crs_failure_reason_uses_received_bids_only(buyer):
    buyer.ROUND.update(phase='advice', bids=[
        {'id': 'bad', 'supplier_id': 'seller_2', 'total_landed_price': 100, 'persona': 'Cheap Seller', 'source': 'SIM'}],
        seller_checks={'seller_1': buyer.ROUND['seller_checks']['seller_1'],
                       'seller_2': {'signal': None, 'reason': 'Seller consent is missing or withdrawn.'}})
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
        cards_json=json.dumps([card(need_id='need-1', bid_id='bad')]))))
    assert not buyer.ROUND.get('order') and not buyer.APPROVALS
    assert 'No seller passed the CRS eligibility check' in ctx.owner_text()


def test_crs_ineligible_rejects_approve_auto_order_and_requote(buyer):
    buyer.ROUND.update(phase='decided', reviewed=True, seller_checks={'seller_1': {'signal': None, 'reason': 'unavailable'}},
                       cards={'bid-1': card()}, quoted_at=time.time())
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'owner', 'APPROVE 1'))
    result = asyncio.run(buyer.place_order(ctx, 1, approved_by='auto', approval_id='auto-1'))
    assert not buyer.ROUND.get('order') and not buyer.APPROVALS
    assert not any(isinstance(msg, buyer.common.OrderPlaced) for _, msg in ctx.sent)
    assert not any(isinstance(msg, buyer.common.BidRequest) for _, msg in ctx.sent)
    assert 'CRS' in result or 'CRS' in ctx.owner_text()
    buyer.ROUND.update(phase='requote', pick=1)
    asyncio.run(buyer.on_requote(ctx, dict(buyer.ROUND['bids'][0])))
    assert not buyer.ROUND.get('order') and not buyer.APPROVALS
    assert not any(isinstance(msg, buyer.common.OrderPlaced) for _, msg in ctx.sent)


def test_bid_sender_cannot_claim_another_supplier(buyer):
    buyer.ROUND.update(phase='bidding', deadline=time.time() + 60)
    bid = {'id': 'borrowed', 'need_id': 'need-1', 'persona': 'Seller', 'lines': [],
           'total_landed_price': 50, 'perks': [], 'claims': [], 'floor_check_passed': True,
           'mirror_snapshot_id': '', 'decision_trace': '', 'expires_at': '', 'source': 'SIM',
           'origin': 'SIM', 'supplier_id': 'seller_2'}
    ctx = Context()
    asyncio.run(buyer.on_bid(ctx, buyer.common.address('seller_1'),
                             buyer.common.BidReply(bid_json=json.dumps(bid), persona_line='Seller')))
    assert all(item['id'] != 'borrowed' for item in buyer.ROUND['bids'])
    assert not buyer.ROUND.get('seller_checks', {}).get('seller_2')


def test_round_waits_for_crs_and_discards_result_after_cancel(buyer, monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_checks(now):
            started.set()
            await release.wait()
            return {'seller_1': buyer.ROUND['seller_checks']['seller_1']}
        monkeypatch.setattr(crs, 'check_sellers', slow_checks)
        need = dict(buyer.ROUND['need'])
        task = asyncio.create_task(buyer.start_round(Context(), need))
        await started.wait()
        assert buyer.ROUND['phase'] == 'checking' and buyer.ROUND['deadline'] == 0
        buyer.ROUND.clear()
        release.set()
        assert await task is False
        assert not buyer.ROUND
    run_bounded(run())


def test_round_deadline_starts_only_after_crs_returns(buyer, monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_checks(now):
            started.set()
            await release.wait()
            return buyer.ROUND['seller_checks']
        monkeypatch.setattr(crs, 'check_sellers', slow_checks)
        need = dict(buyer.ROUND['need'])
        task = asyncio.create_task(buyer.start_round(Context(), need))
        await started.wait()
        assert buyer.ROUND['phase'] == 'checking' and buyer.ROUND['deadline'] == 0
        release.set()
        assert await task is True
        assert buyer.ROUND['phase'] == 'bidding' and buyer.ROUND['deadline'] > time.time()
    run_bounded(run())


def test_expired_round_ignores_late_crs_result(buyer, monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_checks(now):
            started.set()
            await release.wait()
            return buyer.ROUND['seller_checks']
        monkeypatch.setattr(crs, 'check_sellers', slow_checks)
        need = dict(buyer.ROUND['need'])
        ctx = Context()
        task = asyncio.create_task(buyer.start_round(ctx, need))
        await started.wait()
        buyer.ROUND['goal']['deadline'] = '2000-01-01T00:00:00Z'
        await buyer.tick(ctx)
        release.set()
        assert await task is False
        assert buyer.ROUND['phase'] == 'done'
        assert not any(isinstance(msg, buyer.common.BidRequest) for _, msg in ctx.sent)
    run_bounded(run())


def test_superseded_round_ignores_its_late_crs_result(buyer, monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def checks(now):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
            return buyer.ROUND['seller_checks']
        monkeypatch.setattr(crs, 'check_sellers', checks)
        need = dict(buyer.ROUND['need'])
        ctx = Context()
        old = asyncio.create_task(buyer.start_round(ctx, need))
        await started.wait()
        assert await buyer.start_round(ctx, need) is True
        release.set()
        assert await old is False
        assert buyer.ROUND['phase'] == 'bidding'
        assert len([msg for _, msg in ctx.sent if isinstance(msg, buyer.common.BidRequest)]) == len(buyer.common.SELLERS)
    run_bounded(run())


def test_buyer_output_shows_cached_crs_time_without_forwarding_profile(buyer, monkeypatch):
    check = {'eligible': True, 'signal': {'supplier_id': 'seller_1', 'stability': 'verified_stable',
             'checked_at': '2026-10-24T08:00:00-07:00', 'source': 'recorded'},
             'reason': 'Synthetic representative identity verified by CRS sandbox.'}
    bid = dict(buyer.ROUND['bids'][0])
    seller_ctx = Context()
    asyncio.run(buyer.start_round(seller_ctx, dict(buyer.ROUND['need'])))
    seller_requests = [msg for _, msg in seller_ctx.sent if isinstance(msg, buyer.common.BidRequest)]
    assert len(seller_requests) == len(buyer.common.SELLERS)
    buyer.ROUND.update(phase='bidding', seller_checks={'seller_1': check}, deadline=time.time() - 1,
                       bids=[bid])
    ctx = Context()
    asyncio.run(buyer.tick(ctx))
    request = next(msg for _, msg in ctx.sent if isinstance(msg, buyer.common.AdviceRequest))
    assert all('CRS' not in msg.need_json and 'persona_ref' not in msg.need_json for msg in seller_requests)
    assert 'CRS' not in request.need_json and 'persona_ref' not in request.need_json
    assert 'CRS' not in request.bids_json and 'persona_ref' not in request.bids_json
    buyer.ROUND['phase'] = 'advice'
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
        cards_json=json.dumps([card()]))))
    text = ctx.owner_text()
    assert 'CRS: verified_stable' in text and 'cached from CRS 2026-10-24T08:00:00-07:00' in text


def test_trusted_individual_output_uses_exemption_reason(buyer):
    buyer.ROUND.update(phase='advice', seller_checks={'seller_1': {
        'eligible': True, 'signal': None, 'reason': crs.REASON_PROFILE}}, cards={})
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
        cards_json=json.dumps([card()]))))
    assert 'CRS: exempt - Trusted individual seller; CRS check exempt.' in ctx.owner_text()
    assert 'Approved synthetic representative profile is unavailable' not in ctx.owner_text()


def _approved_profile_without_auth(monkeypatch):
    body = {"firstName": "Synthetic"}
    monkeypatch.setattr(crs, "APPROVED_PERSONAS", {"official-a": crs._canonical_hash(body)})
    monkeypatch.setattr(crs, "_profiles", lambda: {"seller_1": {
        "seller_type": "business", "consent": True, "persona_ref": "official-a", "request": body}})
    monkeypatch.setattr(crs, "_paths", lambda: (None, Path(__file__).with_name("missing-crs-cache-test.json")))


def test_no_crs_config_winner_notifies_once_and_stays_unchecked(buyer, monkeypatch):
    monkeypatch.delenv('CRS_API_KEY', raising=False)
    monkeypatch.delenv('CRS_USERNAME', raising=False)
    monkeypatch.delenv('CRS_PASSWORD', raising=False)
    monkeypatch.setattr(crs, 'check_sellers', REAL_CHECK_SELLERS)
    monkeypatch.setattr(crs, 'eligible', REAL_ELIGIBLE)
    _approved_profile_without_auth(monkeypatch)
    requests = []

    def no_network(*args, **kwargs):
        requests.append((args, kwargs))
        raise AssertionError('CRS must not call the provider without configuration')

    monkeypatch.setattr(crs, '_open_request', no_network)
    checks = asyncio.run(crs.check_sellers(datetime.now(timezone.utc)))
    assert checks['seller_1']['reason'] == crs.REASON_NOT_CONFIGURED
    assert requests == []

    buyer.ALLOWANCE = 0
    buyer.ROUND.update(phase='advice', seller_checks=checks,
                       cards={'bid-1': card()},
                       bids=[dict(buyer.ROUND['bids'][0], supplier_id='seller_1')])
    ctx = Context()
    asyncio.run(buyer.conclude(ctx, reviewed=True))
    asyncio.run(buyer.conclude(ctx, reviewed=True))
    text = ctx.owner_text()
    assert text.count('CRS not configured') == 1
    assert 'CRS: not configured' in text
    assert 'CRS: exempt' not in text
    assert 'Reply APPROVE 1' in text
    assert not buyer.ROUND.get('order')


def test_not_configured_row_does_not_relabel_configured_adverse_row(buyer, monkeypatch):
    monkeypatch.delenv('CRS_API_KEY', raising=False)
    monkeypatch.delenv('CRS_USERNAME', raising=False)
    monkeypatch.delenv('CRS_PASSWORD', raising=False)
    monkeypatch.setattr(crs, 'eligible', REAL_ELIGIBLE)
    _approved_profile_without_auth(monkeypatch)
    checks = {
        'seller_1': {'signal': None, 'reason': crs.REASON_NOT_CONFIGURED},
        'seller_2': {'signal': {'supplier_id': 'seller_2', 'stability': 'not_verified',
                                'checked_at': '2026-10-24T08:00:00Z', 'source': 'sandbox'},
                     'reason': crs.REASON_NOT_VERIFIED},
    }
    buyer.ROUND.update(phase='advice', seller_checks=checks,
                       bids=[dict(buyer.ROUND['bids'][0], supplier_id='seller_1'),
                             dict(buyer.ROUND['bids'][0], id='bid-2', supplier_id='seller_2', persona='Adverse')],
                       cards={'bid-1': card(), 'bid-2': card(bid_id='bid-2')})
    ctx = Context()
    asyncio.run(buyer.conclude(ctx, reviewed=True))
    text = ctx.owner_text()
    assert 'CRS: not configured - Seller eligibility was not verified.' in text
    assert f'CRS: not_verified - {crs.REASON_NOT_VERIFIED}' in text
    assert 'Deal found: Adverse' not in text
    assert text.count('CRS not configured') == 1


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

    run_bounded(run())


def test_web_followup_stays_in_web_queue(buyer):
    buyer.ROUND.update(owner=buyer.WEB, owner_context=None, events=['Bid in'])
    buyer.WEB_OUTBOX.clear()
    ctx = Context()
    asyncio.run(buyer.tell_owner(ctx, 'Review ready'))
    assert buyer.web_drain().replies == ['Bid in\nReview ready']
    assert not ctx.sent


def test_foreign_sender_gets_generic_busy_reply_without_pending_deal_details(buyer):
    ctx = Context()
    buyer.ROUND.update(owner='authenticated-owner', phase='decided', bids=[
        {'id': 'secret-bid', 'persona': 'Private Seller Name', 'total_landed_price': 582}],
        order={'id': 'private-order'})
    owner_context = Context()
    buyer.ROUND['owner_context'] = owner_context
    before = dict(buyer.ROUND)
    for command in ('hello', 'APPROVE 1', 'CANCEL'):
        asyncio.run(buyer.handle_text(ctx, 'other-sender', command))
    replies = [message.text() for to, message in ctx.sent if to == 'other-sender']
    assert replies == ['A buyer session is active. Try again later.']
    assert all('Private Seller Name' not in text and 'private-order' not in text and 'APPROVE' not in text for text in replies)
    asyncio.run(buyer.handle_text(ctx, 'authenticated-owner', 'APPROVE 1'))
    assert any(to == 'authenticated-owner' and 'private-order' in message.text()
               for to, message in owner_context.sent)
    assert buyer.ROUND == before | {'told_foreign_busy': True}
    assert buyer.ROUND['owner_context'] is owner_context


@pytest.mark.parametrize(('phase', 'state'), [('done', 'ACTIVE'), ('decided', 'DONE')])
def test_terminal_owner_can_be_replaced_by_a_valid_new_sender_goal(buyer, phase, state):
    ctx = Context()
    buyer.ROUND.update(owner='alice', owner_context=object(), phase=phase,
                       goal={'id': 'old-goal', 'state': state}, order=None)
    asyncio.run(buyer.handle_text(ctx, 'bob', 'GPU under $800'))
    assert buyer.ROUND['owner'] == 'bob'
    assert buyer.ROUND['goal']['buyer_id'] == 'bob'
    assert buyer.ROUND['goal']['id'] != 'old-goal'
    assert buyer.ROUND['phase'] == 'bidding'


def test_malformed_new_sender_goal_preserves_terminal_owner(buyer):
    ctx = Context()
    old_context = object()
    buyer.ROUND.update(owner='alice', owner_context=old_context, phase='done',
                       goal={'id': 'old-goal', 'state': 'EXPIRED'}, order=None)
    before = dict(buyer.ROUND)
    asyncio.run(buyer.handle_text(ctx, 'bob', 'GPU under'))
    assert buyer.ROUND == before
    assert buyer.ROUND['owner_context'] is old_context
    assert buyer.ROUND['owner'] == 'alice'


def test_late_bid_from_old_need_cannot_enter_replacement_goal(buyer, monkeypatch):
    buyer.ROUND.update(owner='alice', owner_context=object(), phase='done',
                       goal={'id': 'old-goal', 'state': 'EXPIRED'}, order=None)
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'bob', 'GPU under $800'))
    current_need = buyer.ROUND['need']['id']
    monkeypatch.setattr(buyer.common, 'screen_bid', lambda *args: {'verdict': 'allow'})
    monkeypatch.setattr(buyer.common, 'validate', lambda contract, payload: payload)
    old_bid = {'id': 'old-bid', 'need_id': 'old-need', 'supplier_id': 'seller_1', 'persona': 'Seller',
               'total_landed_price': 500, 'source': 'SIM'}
    asyncio.run(buyer.on_bid(ctx, buyer.common.address('seller_1'),
                             buyer.common.BidReply(bid_json=json.dumps(old_bid), persona_line='Seller')))
    assert buyer.ROUND['owner'] == 'bob' and buyer.ROUND['need']['id'] == current_need
    assert buyer.ROUND['phase'] == 'bidding'
    assert all(bid['id'] != 'old-bid' for bid in buyer.ROUND['bids'])


def test_ordered_round_cannot_be_cleared_by_cancel_or_new_goal(buyer):
    ctx = Context()
    buyer.ROUND.update(owner='alice', phase='decided', goal={'id': 'goal-1', 'state': 'DONE'},
                       order={'id': 'order-1', 'payment_ref': 'payment-1'},
                       mandate={'hash': 'mandate-1'})
    before = dict(buyer.ROUND)
    asyncio.run(buyer.handle_text(ctx, 'alice', 'CANCEL'))
    asyncio.run(buyer.handle_text(ctx, 'bob', 'PSU under $150'))
    assert buyer.ROUND == before | {'told_foreign_busy': True}
    replies = '\n'.join(message.text() for _, message in ctx.sent)
    assert 'Cancelled. Nothing ordered.' not in replies
    assert 'Nothing was canceled.' in replies
    assert buyer.ROUND['order']['payment_ref'] == 'payment-1'


def test_pending_prompt_uses_plain_approval_instructions_and_keeps_cancel(buyer):
    ctx = Context()
    buyer.ROUND.update(owner='owner', phase='decided', bids=[{'id': 'bid-1'}], order=None)
    asyncio.run(buyer.handle_text(ctx, 'owner', 'hello'))
    text = ctx.owner_text()
    assert '<number>' not in text and '<n>' not in text
    assert 'APPROVE followed by the bid number' in text and 'CANCEL' in text


def test_plain_owner_text_does_not_replace_saved_chat_context(buyer):
    old_context = object()
    buyer.ROUND.update(owner='owner', owner_context=old_context, phase='decided', told_waiting=True)
    ctx = Context()
    asyncio.run(buyer.on_chat(ctx, 'owner', buyer.ChatMessage(content=[buyer.TextContent(text='hello')])))
    assert buyer.ROUND['owner_context'] is old_context


def test_tell_logs_no_private_reply_body(buyer):
    ctx = Context()
    private_body = 'approval code 482913 under $800 seller payload private'
    asyncio.run(buyer.tell(ctx, 'owner', private_body))
    logged = '\n'.join(str(call) for call in ctx.logger.method_calls)
    assert private_body not in logged
    assert '482913' not in logged and '$800' not in logged and 'seller payload' not in logged


def test_start_round_stops_before_old_summary_after_final_send_is_superseded(buyer, monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def checks(now):
            return buyer.ROUND['seller_checks']
        monkeypatch.setattr(crs, 'check_sellers', checks)

        class PausedLastSeller(Context):
            async def send(self, to, message):
                if (isinstance(message, buyer.common.BidRequest)
                        and to == buyer.common.address(buyer.common.SELLERS[-1])):
                    started.set()
                    await release.wait()
                await super().send(to, message)

        ctx = PausedLastSeller()
        buyer.ROUND.clear()
        task = asyncio.create_task(buyer.handle_text(ctx, 'old-owner', 'GPU under $800'))
        await started.wait()
        buyer.ROUND.clear()
        buyer.ROUND.update(owner='new-owner', owner_context=ctx, round_token='replacement',
                           need={'id': 'new-need'}, phase='bidding')
        release.set()
        await task
        assert not any(to == 'new-owner' and isinstance(msg, buyer.ChatMessage) for to, msg in ctx.sent)
    run_bounded(run())


def test_tick_failed_advice_send_does_not_fail_replacement_round(buyer):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        class PausedFailure(Context):
            async def send(self, to, message):
                if isinstance(message, buyer.common.AdviceRequest):
                    started.set()
                    await release.wait()
                    raise OSError('private endpoint detail')
                await super().send(to, message)

        ctx = PausedFailure()
        buyer.ROUND.update(phase='bidding', deadline=time.time() - 1, round_token='old-token',
                           bids=[dict(buyer.ROUND['bids'][0])], owned=[])
        task = asyncio.create_task(buyer.tick(ctx))
        await started.wait()
        buyer.ROUND.clear()
        buyer.ROUND.update(owner='owner', phase='bidding', round_token='new-token', need={'id': 'new-need'},
                           attempts=0, goal={'id': 'new-goal', 'state': 'HUNTING'})
        release.set()
        await task
        assert buyer.ROUND['round_token'] == 'new-token'
        assert buyer.ROUND['attempts'] == 0 and buyer.ROUND['phase'] == 'bidding'
        assert 'private endpoint detail' not in '\n'.join(str(c) for c in ctx.logger.method_calls)
    run_bounded(run())


def test_restart_card_does_not_start_new_round_after_cancel_during_reply(buyer, monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def paused_reply(ctx, text):
            started.set()
            await release.wait()
        started_rounds = []
        async def start_round(ctx):
            started_rounds.append(True)
        monkeypatch.setattr(buyer, 'tell_owner', paused_reply)
        monkeypatch.setattr(buyer, 'start_round', start_round)
        buyer.ROUND.update(round_token='old-token', need={'id': 'old-need'})
        task = asyncio.create_task(buyer.restart_card(Context(), 'stale quote'))
        await started.wait()
        buyer.ROUND.clear()
        buyer.ROUND.update(round_token='new-token', need={'id': 'new-need'})
        release.set()
        await task
        assert not started_rounds
    run_bounded(run())


def test_advice_send_failure_after_review_does_not_overwrite_decision(buyer, monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        class PausedFailure(Context):
            async def send(self, to, message):
                if isinstance(message, buyer.common.AdviceRequest):
                    started.set()
                    await release.wait()
                    raise OSError('private endpoint detail')
                await super().send(to, message)

        async def conclude(ctx, reviewed):
            buyer.ROUND['phase'] = 'decided'
        monkeypatch.setattr(buyer, 'conclude', conclude)
        ctx = PausedFailure()
        buyer.ROUND.update(phase='bidding', deadline=time.time() - 1, round_token='same-token',
                           bids=[dict(buyer.ROUND['bids'][0])], owned=[], attempts=0)
        task = asyncio.create_task(buyer.tick(ctx))
        await started.wait()
        await buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
            cards_json=json.dumps([card()])))
        assert buyer.ROUND['phase'] == 'decided'
        release.set()
        await task
        assert buyer.ROUND['phase'] == 'decided' and buyer.ROUND['attempts'] == 0
        assert 'private endpoint detail' not in '\n'.join(str(c) for c in ctx.logger.method_calls)
    run_bounded(run())


def test_conclude_does_not_fail_expired_round_after_owner_send_await(buyer):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        class PauseFirstReply(Context):
            async def send(self, to, message):
                if isinstance(message, buyer.ChatMessage) and not started.is_set():
                    started.set()
                    await release.wait()
                await super().send(to, message)

        ctx = PauseFirstReply()
        bid = dict(buyer.ROUND['bids'][0])
        buyer.ROUND.update(round_token='expiring-token', phase='advice', bids=[bid],
                           cards={bid['id']: card(recommendation='veto')}, attempts=0)
        task = asyncio.create_task(buyer.conclude(ctx, reviewed=True))
        await started.wait()
        buyer.ROUND['goal']['deadline'] = '2000-01-01T00:00:00Z'
        await buyer.tick(ctx)
        assert buyer.ROUND['phase'] == 'done' and buyer.ROUND['goal']['state'] == 'EXPIRED'
        release.set()
        await task
        assert buyer.ROUND['phase'] == 'done' and buyer.ROUND['attempts'] == 0
    run_bounded(run())


def test_conclude_stops_after_crs_notice_if_owner_cancels_and_starts_new_goal(buyer, monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        class PauseNotice(Context):
            async def send(self, to, message):
                if (isinstance(message, buyer.ChatMessage) and message.content
                        and message.content[0].text == buyer.CRS_NOT_CONFIGURED_NOTICE):
                    started.set()
                    await release.wait()
                await super().send(to, message)

        monkeypatch.setattr(crs, 'to_crs_check', lambda *a: {'origin': 'NOT_CONFIGURED'})
        picked = []
        monkeypatch.setattr(buyer.hunt, 'pick_best', lambda *a: picked.append(True))
        buyer.ROUND.update(round_token='old-token', phase='advice', need={'id': 'old-need', 'spend_limit': 800},
                           bids=[dict(buyer.ROUND['bids'][0])], seller_checks={})
        ctx = PauseNotice()
        task = asyncio.create_task(buyer.conclude(ctx, reviewed=True))
        await asyncio.wait_for(started.wait(), timeout=5)
        # Same state transition as CANCEL followed immediately by a replacement goal.
        buyer.ROUND.clear()
        buyer.ROUND.update(round_token='new-token', phase='bidding', need={'id': 'new-need'},
                           goal={'id': 'new-goal', 'state': 'HUNTING'}, bids=[], attempts=0)
        release.set()
        await asyncio.wait_for(task, timeout=5)
        assert not picked
        assert buyer.ROUND['round_token'] == 'new-token'
        assert buyer.ROUND['need']['id'] == 'new-need'
        assert buyer.ROUND['phase'] == 'bidding'

    run_bounded(run())
