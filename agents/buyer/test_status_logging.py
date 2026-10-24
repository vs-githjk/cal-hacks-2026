"""Offline coverage for the buyer's fixed-label activity feed."""
import asyncio
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import status

ADDRESS = 'agent1qwxhy93uzmw5prlqldm8a2mz9gsmc2563um6th2l6z0pudw63juej97nmj8'


@pytest.fixture
def buyer(monkeypatch):
    monkeypatch.delenv('AGENTS_MAILBOX', raising=False)
    monkeypatch.delenv('BUYER_MAILBOX', raising=False)
    fake_agent = Mock()
    fake_agent.address = ADDRESS
    for decorator in ('on_message', 'on_interval', 'on_rest_post', 'on_rest_get', 'on_event'):
        getattr(fake_agent, decorator).side_effect = lambda *args, **kwargs: lambda fn: fn
    exists = Path.exists
    with patch('uagents.Agent', return_value=fake_agent), patch.object(
            Path, 'exists', lambda path: False if path.name == '.env' else exists(path)):
        module = importlib.import_module('buyer_agent')
    module.ROUND.clear()
    module.STATE_DB = None
    yield module
    module.ROUND.clear()


class Context:
    def __init__(self, fail_to=None):
        self.logger = Mock()
        self.sent = []
        self.session = uuid4()
        self.fail_to = fail_to

    async def send(self, recipient, message):
        if recipient == self.fail_to:
            raise OSError('send failed')
        self.sent.append((recipient, message))


def status_logs(ctx, prefix='AGENT_MSG'):
    return [call.args[0] for call in ctx.logger.info.call_args_list
            if call.args and isinstance(call.args[0], str) and call.args[0].startswith(prefix)]


def test_startup_status_is_emitted_only_after_successful_recovery(buyer, monkeypatch):
    monkeypatch.setattr(buyer, 'recover_buyer_state', lambda: 0)
    for args, mailbox in (({'endpoint': ['http://localhost:8001/submit']}, False),
                          ({'mailbox': True}, True)):
        buyer._AGENT_ARGS = args
        ctx = Context()
        asyncio.run(buyer.buyer_startup(ctx))
        assert status_logs(ctx, 'AGENT_STATUS') == [
            status.status_line('buyer', 'buyer', ADDRESS, mailbox=mailbox)]

    buyer._AGENT_ARGS = {'endpoint': ['http://localhost:8001/submit']}
    monkeypatch.setattr(buyer, 'recover_buyer_state', lambda: (_ for _ in ()).throw(ValueError('private')))
    failed = Context()
    with pytest.raises(ValueError):
        asyncio.run(buyer.buyer_startup(failed))
    assert status_logs(failed, 'AGENT_STATUS') == []


def test_failed_owner_reply_does_not_emit_message_status(buyer):
    ctx = Context(fail_to='owner')

    with pytest.raises(OSError):
        asyncio.run(buyer.tell(ctx, 'owner', 'private reply body'))

    assert status_logs(ctx) == []


def test_accepted_goal_and_successful_bid_requests_use_fixed_labels(buyer, monkeypatch):
    monkeypatch.setattr(buyer.buyer_state, 'remember_owned', lambda *_args: None)
    monkeypatch.setattr(buyer.buyer_state, 'load_owned_parts', lambda *_args: [])
    monkeypatch.setattr(buyer.buyer_state, 'save_goal', lambda *_args: None)
    monkeypatch.setattr(buyer, 'state_db', lambda: object())
    actual_start_round = buyer.start_round
    monkeypatch.setattr(buyer, 'start_round', AsyncMock(return_value=True))
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'owner-private-id', 'a new GPU under $800 by Friday'))
    assert status.msg_line('buyer', 'owner', 'goal') in status_logs(ctx)
    assert all('owner-private-id' not in line and '$800' not in line for line in status_logs(ctx))

    buyer.ROUND.update(goal={'id': 'goal-1', 'cap': 800}, owner='owner')
    monkeypatch.setattr(buyer, 'start_round', actual_start_round)
    market, referee = Mock(), Mock()
    referee.round_status.return_value = {'state': 'open'}
    monkeypatch.setattr(buyer, 'market_clients', lambda: (market, referee))
    async def sellers(_now):
        return {}
    monkeypatch.setattr(buyer.crs, 'check_sellers', sellers)
    need = {'id': 'need-1', 'buyer_id': 'buyer-1', 'auction_window_s': 10, 'items': []}
    asyncio.run(buyer.start_round(ctx, need))
    assert [line for line in status_logs(ctx) if 'sealed request for bids' in line] == [
        status.msg_line('buyer', seller, 'bid_request') for seller in buyer.common.SELLERS], (
            buyer.ROUND, ctx.logger.warning.call_args_list)


def test_accepted_bid_logs_a_fixed_seller_label_without_bid_text(buyer, monkeypatch):
    buyer.ROUND.update(phase='bidding', deadline=10**12, round_token='round-token', need={'id': 'need-1'},
                       retired_need_ids=[], bids=[], received_bids={}, personas={}, screened_bids={})
    bid = {'id': 'bid-1', 'need_id': 'need-1', 'supplier_id': 'seller_1', 'persona': 'private persona',
           'total_landed_price': 582, 'source': 'SIM', 'origin': 'SIM'}
    monkeypatch.setattr(buyer.common, 'screen_bid', lambda *_args: {'verdict': 'allow'})
    monkeypatch.setattr(buyer.common, 'validate', lambda *_args: bid)
    ctx = Context()
    asyncio.run(buyer.on_bid(ctx, buyer.common.address('seller_1'),
                             buyer.common.BidReply(bid_json=json.dumps(bid), persona_line='private persona')))
    assert status_logs(ctx) == [status.msg_line('buyer', 'seller_1', 'bid')]


def test_order_log_is_after_successful_order_send(buyer, monkeypatch):
    chat_approval = ModuleType('buyer.chat_approval')
    chat_approval.approve_in_chat = AsyncMock(return_value=SimpleNamespace(
        approved=True, record={'result': 'approved', 'mandate_hash': 'h' * 64, 'mandate_id': 'mandate-1',
                              'id': 'approval-1', 'channel': 'typed'}))
    monkeypatch.setitem(sys.modules, 'buyer.chat_approval', chat_approval)

    ctx = Context()
    sender = 'owner'
    bid = {'id': 'bid-1', 'supplier_id': 'seller_1', 'total_landed_price': 582, 'origin': 'SIM'}
    transaction = {
        'phase': 'pending_approval', 'deal_id': 'deal-1', 'need_id': 'need-1', 'bid_id': 'bid-1',
        'deal': {'owner_sender': sender, 'amount': 582}, 'mandate': {'id': 'mandate-1', 'hash': 'h' * 64},
    }
    buyer.ROUND.update(owner=sender, owner_context=ctx, owner_session=ctx.session, phase='pending_approval',
                       transaction=transaction, bids=[bid], need={'id': 'need-1'}, goal={'id': 'goal-1'})
    monkeypatch.setattr(buyer, 'eligible_for_order', lambda _n: True)
    monkeypatch.setattr(buyer, '_configured_market_owner_matches', lambda _owner: True)
    monkeypatch.setattr(buyer, '_approval_service', lambda: object())
    monkeypatch.setattr(buyer, 'make_order', lambda *_args: {'amount': 582})
    monkeypatch.setattr(buyer.common, 'validate', lambda _contract, value: value)
    monkeypatch.setattr(buyer.buyer_state, 'save_transaction', lambda *_args: None)
    monkeypatch.setattr(buyer, 'state_db', lambda: object())
    market = Mock()
    market.record_approval.return_value = {'approval_method': 'typed_code', 'approved_at': 'now'}
    monkeypatch.setattr(buyer, 'market_clients', lambda: (market, Mock()))

    asyncio.run(buyer.approve(ctx, 1, sender=sender))

    assert any(isinstance(message, buyer.common.OrderPlaced) for _, message in ctx.sent), (
        ctx.logger.warning.call_args_list, buyer.ROUND, ctx.sent)
    assert status.msg_line('buyer', 'seller_1', 'order') in status_logs(ctx)


def test_bound_payment_request_and_successful_rejection_use_fixed_labels(buyer, monkeypatch):
    sender = buyer.common.address('seller_1')
    buyer.ROUND['transaction'] = {
        'phase': 'approved', 'mode': 'SIM', 'mandate': {'payee': sender},
        'deal': {'payee': sender, 'owner_sender': 'not-configured'},
    }
    monkeypatch.setattr(buyer, '_configured_market_owner_matches', lambda _owner: False)
    ctx = Context()
    request = buyer.RequestPayment(accepted_funds=[], recipient=sender, deadline_seconds=60)

    asyncio.run(buyer.on_request_payment(ctx, sender, request))

    assert any(isinstance(message, buyer.RejectPayment) for _, message in ctx.sent)
    assert status.msg_line('buyer', 'seller_1', 'payment_request') in status_logs(ctx)
    assert status.msg_line('buyer', 'seller_1', 'payment_reject') in status_logs(ctx)


def test_payment_commit_is_logged_after_successful_commit_send(buyer, monkeypatch):
    class FakePrivateKey:
        pass

    crypto = ModuleType('cryptography')
    hazmat = ModuleType('cryptography.hazmat')
    primitives = ModuleType('cryptography.hazmat.primitives')
    asymmetric = ModuleType('cryptography.hazmat.primitives.asymmetric')
    ed25519 = ModuleType('cryptography.hazmat.primitives.asymmetric.ed25519')
    ed25519.Ed25519PrivateKey = FakePrivateKey
    for name, module in (('cryptography', crypto), ('cryptography.hazmat', hazmat),
                         ('cryptography.hazmat.primitives', primitives),
                         ('cryptography.hazmat.primitives.asymmetric', asymmetric),
                         ('cryptography.hazmat.primitives.asymmetric.ed25519', ed25519)):
        monkeypatch.setitem(sys.modules, name, module)
    checkout = ModuleType('buyer.checkout')
    sender = buyer.common.address('seller_1')
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    mandate = {'id': 'mandate-1', 'hash': 'h' * 64, 'payee': sender, 'amount': 582,
               'expires_at': expires, 'nonce': 'nonce-1'}
    checkout.settle_offer = lambda *_args, **_kwargs: {
        'settlement': {'mode': 'SIM'}, 'settlement_result': {'status': 'charged', 'charge_id': 'charge-1'},
        'mandate': mandate,
    }
    monkeypatch.setitem(sys.modules, 'buyer.checkout', checkout)
    receipt_module = ModuleType('shield.receipt')
    receipt_module.verify_allow_receipt = lambda *_args, **_kwargs: True
    monkeypatch.setitem(sys.modules, 'shield', ModuleType('shield'))
    monkeypatch.setitem(sys.modules, 'shield.receipt', receipt_module)
    from uagents_core.contrib.protocols.payment import CommitPayment, Funds

    buyer.NONCE_STORE = object()
    buyer.MERCHANT_SIM = SimpleNamespace(store=buyer.NONCE_STORE, keys={'tap': 'key'}, receipt_keys={'receipt': 'key'})
    buyer.TAP_PRIVATE_KEY = FakePrivateKey()
    buyer.SHIELD_RECEIPT_KEYS = {'receipt': 'key'}
    buyer.ROUND['transaction'] = {
        'phase': 'approved', 'mode': 'SIM', 'buyer_id': 'owner', 'deal_id': 'deal-1', 'goal_id': 'goal-1',
        'mandate': mandate, 'deal': {'payee': sender, 'owner_sender': 'owner', 'id': 'deal-1'},
        'order': {'id': 'deal-1', 'status': 'ordered'},
    }
    buyer.STATE_DB = object()
    monkeypatch.setattr(buyer, '_configured_market_owner_matches', lambda _owner: True)
    market = Mock()
    market.purchase_status.return_value = {
        'approval_method': 'typed_code', 'retired': False, 'reservation_matches': True,
        'payment_ref': None, 'expiry': expires,
    }
    monkeypatch.setattr(buyer, 'market_clients', lambda: (market, Mock()))
    monkeypatch.setattr(buyer, '_request_payment_message_id', lambda *_args: ('message-1', '{}'))
    monkeypatch.setattr(buyer, '_shield_payment_receipt', lambda *_args: {'ok': True})
    monkeypatch.setattr(buyer, '_merchant_sim_for', lambda _tx: object())
    monkeypatch.setattr(buyer.buyer_state, 'save_transaction', lambda *_args: None)
    monkeypatch.setattr(buyer.hunt, 'settle', lambda *_args, **_kwargs: CommitPayment(
        funds=Funds(amount='582', currency='USD'), recipient=sender, transaction_id='charge-1'))
    ctx = Context()
    request = buyer.RequestPayment(accepted_funds=[], recipient=sender, deadline_seconds=60)

    asyncio.run(buyer.on_request_payment(ctx, sender, request))

    assert status.msg_line('buyer', 'seller_1', 'payment_commit') in status_logs(ctx)
    assert any(isinstance(message, CommitPayment) for _, message in ctx.sent)


def test_verified_payment_complete_logs_after_market_settlement_and_state_write(buyer, monkeypatch):
    sender = buyer.common.address('seller_1')
    now = datetime.now(timezone.utc)
    mandate = buyer.payment.make_mandate(deal_id='deal-1', amount=582, payee=sender, buyer_id='buyer-1',
                                         within_allowance=False, goal_id='goal-1', now=now)
    mandate.update(status='approved', approval_id='approval-1')
    deal = {'id': 'deal-1', 'goal_id': 'goal-1', 'need_id': 'need-1', 'bid_id': 'bid-1',
            'amount': 582, 'payee': sender, 'owner_sender': 'owner'}
    order = {'id': 'deal-1', 'need_id': 'need-1', 'bid_id': 'bid-1', 'amount': 582}
    request = buyer.payment.payment_request(mandate, recipient=sender)
    body_hash = buyer.hashlib.sha256(request.model_dump_json().encode('utf-8')).hexdigest()
    message_id = 'req:' + buyer.hashlib.sha256(b'buyer-1\n' + request.model_dump_json().encode('utf-8')).hexdigest()
    attempt = {'phase': 'charged', 'charge_id': 'charge-1', 'mandate_hash': mandate['hash'],
               'buyer_id': 'buyer-1', 'deal_id': 'deal-1', 'request_sha256': body_hash,
               'amount_cents': 58200, 'currency': 'USD', 'payee': sender,
               'idempotency_key': 'mandate:' + mandate['hash'], 'message_id': message_id,
               'receipt_keyid': 'receipt-1'}
    settlement = {key: attempt[key] for key in ('message_id', 'request_sha256', 'mandate_hash', 'deal_id',
                 'buyer_id', 'amount_cents', 'currency', 'payee', 'idempotency_key', 'receipt_keyid')}
    settlement['mode'] = 'SIM'
    transaction = {
        'phase': 'submitted', 'buyer_id': 'buyer-1', 'deal_id': 'deal-1', 'goal_id': 'goal-1',
        'need_id': 'need-1', 'bid_id': 'bid-1', 'mandate': mandate, 'deal': deal, 'order': order,
        'voice_approval': {'result': 'approved', 'mandate_hash': mandate['hash'], 'mandate_id': mandate['id']},
        'settlement': settlement,
        'settlement_result': {'status': 'charged', 'charge_id': 'charge-1', 'mandate_hash': mandate['hash'], 'origin': 'SIM'},
        'payment_ref': 'charge-1', 'mode': 'SIM',
    }
    buyer.ROUND['transaction'] = transaction
    buyer.STATE_DB = object()
    monkeypatch.setattr(buyer, '_configured_market_owner_matches', lambda _owner: True)
    monkeypatch.setattr(buyer, 'nonce_store', lambda: SimpleNamespace(get_payment_attempt=lambda _hash: attempt))
    monkeypatch.setattr(buyer.buyer_state, 'load_transaction', lambda *_args: transaction)
    buyer_market, referee_market = Mock(), Mock()
    buyer_market.purchase_status.return_value = {'payment_ref': 'charge-1', 'payment_mode': 'sim', 'payment_amount': 582}
    buyer_market.settle_goal.return_value = {'settled': True}
    monkeypatch.setattr(buyer, 'market_clients', lambda: (buyer_market, referee_market))
    monkeypatch.setattr(buyer.buyer_state, 'load_goal', lambda *_args: {'id': 'goal-1', 'state': 'HOLD_FOR_CALL'})
    monkeypatch.setattr(buyer.buyer_state, 'save_goal', lambda *_args: None)
    monkeypatch.setattr(buyer.buyer_state, 'save_transaction', lambda *_args: None)
    ctx = Context()

    asyncio.run(buyer.on_complete(ctx, sender, buyer.CompletePayment(transaction_id='charge-1')))

    assert buyer.ROUND['transaction']['phase'] == 'settled', (
        ctx.logger.warning.call_args_list, buyer_market.mock_calls, referee_market.mock_calls)
    assert status.msg_line('buyer', 'seller_1', 'payment_complete') in status_logs(ctx)
