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
from advocate.checks import CALL_SUMMARIES
from buyer import state as buyer_state

REAL_CHECK_SELLERS = crs.check_sellers
REAL_ELIGIBLE = crs.eligible


def market_candidate(bid, round_id='round-need-1'):
    import hashlib
    lines, metadata = [], []
    for index, raw in enumerate(bid['lines']):
        line_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'),
                                              ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        lines.append({'line_index': index, 'sku_spec': raw['sku_spec'],
                      'unit_price': raw['unit_price'], 'quantity': raw['quantity'],
                      'shipping': raw['shipping']})
        metadata.append({'lineIndex': index, 'listingId': raw['listing_id'], 'listingHash': line_hash,
                         'source': raw['source'], 'snapshotId': '', 'provenance': {}, 'attrs': raw['attrs']})
    return {'round_id': round_id, 'need_id': bid['need_id'], 'bid_id': bid['id'],
            'seller_id': {'seller_1': 'seller-a', 'seller_2': 'seller-b', 'seller_3': 'seller-c'}[bid['supplier_id']],
            'origin': bid['origin'], 'lines': lines, 'line_metadata': metadata,
            'binding_hash': 'c' * 64}


def projected_market_bid(bid, candidate):
    selected = []
    for index, (row, meta) in enumerate(zip(candidate['lines'], candidate['line_metadata'])):
        selected.append({**bid['lines'][index], 'line_index': row['line_index'],
                         'listing_id': meta['listingId'], 'listing_hash': meta['listingHash']})
    return {**bid, 'lines': selected, 'candidate_binding_hash': candidate['binding_hash']}


@pytest.fixture
def multi_sender(buyer, monkeypatch):
    """#449 item 2: only the pinned owner reaches a round, so the second-sender gates below (told_foreign, release,
    takeover) are defence in depth. Open the chat-sender check to reach them; approval still uses the real owner pin."""
    monkeypatch.setattr(buyer, '_chat_sender_allowed', lambda _sender: True)
    return buyer


@pytest.fixture
def buyer(monkeypatch, tmp_path):
    # Agent construction writes local identity storage; handlers need no running agent.
    fake_agent = Mock()
    fake_agent.on_message.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_interval.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_rest_post.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_rest_get.side_effect = lambda *a, **k: lambda fn: fn
    fake_agent.on_event.side_effect = lambda *a, **k: lambda fn: fn
    exists = Path.exists
    with patch('uagents.Agent', return_value=fake_agent), patch.object(
            Path, 'exists', lambda p: False if p.name == '.env' else exists(p)):
        module = importlib.import_module('buyer_agent')
    fake_agent.address = module.common.address('buyer')
    monkeypatch.setattr(module, 'ALLOWANCE', 1000)
    monkeypatch.setattr(module, 'MARKET_BUYER_ID', 'vidyut')
    monkeypatch.setenv('MARKET_BUYER_OWNER_SENDER', 'owner')  # #449 item 2: only the pinned owner reaches a round
    module.STRANGER_TOLD.clear()
    class FakeMarket:
        def __init__(self, identity):
            self.identity = identity
            self.state = 'open'   # #447: the published module reviews while the round is open, then closes it
            self.candidates = []

        def post_goal(self, *args, **kwargs): pass
        def post_need(self, *args, **kwargs): pass
        def open_round(self, *args, **kwargs): self.state = 'open'
        def close_round(self, *args, **kwargs): self.state = 'closed'
        def round_status(self, *args, **kwargs):
            return {'state': self.state, 'deadline': datetime.now(timezone.utc).isoformat()}
        def attach_verdict(self, *args, **kwargs): pass
        def attach_claim_check(self, *args, **kwargs): pass
        def attach_advocate_card(self, *args, **kwargs): pass
        def authoritative_winner(self, round_id, need_items):
            # #447: the published module's winner row: no line index, listing or binding hash
            candidate = (self.candidates or module.ROUND.get('review_bids', []))[0]
            return {'bid_id': candidate['bid_id'], 'seller_id': candidate['seller_id'],
                    'landed': module.ROUND['bids'][0]['total_landed_price'],
                    'lines': [{'sku_spec': line['sku_spec'], 'unit_price': line['unit_price'], 'quantity': line['quantity'],
                               'qty_available': line['quantity'], 'offered_condition': '', 'offered_spec': ''}
                              for line in candidate['lines']]}

    monkeypatch.setattr(module, 'MARKET_BUYER', FakeMarket('buyer-test'))
    referee = FakeMarket('referee-test')
    monkeypatch.setattr(module, 'MARKET_REFEREE', referee)
    market = module.MARKET_BUYER
    db = buyer_state.open_state(tmp_path / '.state' / 'state.sqlite3')
    monkeypatch.setattr(module, 'STATE_DB', db)
    async def checks(now):
        return {'seller_1': {'eligible': True, 'signal': {'supplier_id': 'seller_1', 'stability': 'verified_stable',
                                        'checked_at': '2026-10-24T08:00:00Z', 'source': 'sandbox'},
                            'reason': 'Synthetic representative identity verified by CRS sandbox.'}}
    monkeypatch.setattr(crs, 'check_sellers', checks)
    monkeypatch.setattr(crs, 'eligible', lambda supplier_id, check, now: bool(check and check.get('eligible')))
    monkeypatch.setattr(module, 'blocked_reasons', lambda *a: None)
    monkeypatch.setattr(module, '_approval_call', lambda: (module.APPROVAL_CALL_CLIENT, 'not_configured'))  # never dial
    module.ROUND.clear()
    raw_line = {'sku_spec': 'gpu', 'unit_price': 582.0, 'quantity': 1, 'shipping': 0.0,
                'offered_condition': 'new', 'variant': 'retail', 'listing_id': 'SIM:seller_1:gpu',
                'listing_url': 'https://seller.example/gpu', 'page_condition': 'new', 'attrs': {'chipset': 'gpu'},
                'origin': 'SIM', 'source': 'simulated'}
    raw_bid = {'id': 'bid-1', 'need_id': 'need-1', 'supplier_id': 'seller_1', 'seller_id': 'seller_1',
               'persona': 'Seller', 'lines': [raw_line], 'total_landed_price': 582, 'perks': [], 'claims': [],
               'floor_check_passed': True, 'mirror_snapshot_id': 'sim', 'decision_trace': 'SIM',
               'expires_at': '2099-01-01T00:00:00Z', 'origin': 'SIM', 'source': 'simulated'}
    candidate = market_candidate(raw_bid)
    projected_bid = projected_market_bid(raw_bid, candidate)
    module.ROUND.update(
        owner='owner', phase='advice', deadline=time.time() - 1, quoted_at=time.time(),
        need={'id': 'need-1', 'buyer_id': 'owner', 'spend_limit': 800, 'items': [], 'auction_window_s': 12},
        goal={'id': 'goal-1', 'deadline': '2099-01-01T00:00:00Z', 'state': 'HUNTING'},
        bids=[raw_bid], received_bids={'bid-1': raw_bid}, review_bids=[projected_bid],
        candidate_hashes={'bid-1': candidate['binding_hash']}, market_round_id='round-need-1',
        cards={}, personas={}, owned=[], attempts=0, last_sent={})
    module.ROUND['seller_checks'] = {'seller_1': {'eligible': True, 'signal': {
        'supplier_id': 'seller_1', 'stability': 'verified_stable', 'checked_at': '2026-10-24T08:00:00Z',
        'source': 'sandbox'}, 'reason': 'Synthetic representative identity verified by CRS sandbox.'}}
    referee.candidates = [candidate]
    market.candidates = [candidate]
    yield module
    module.ROUND.clear()
    db.close()


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
    reason = CALL_SUMMARIES['advocate.ok']
    source = 'https://example.test/advocate'
    return dict(need_id='need-1', bid_id='bid-1', warnings=[], claim_checks=[], recommendation='buy',
                wait_until='', call_reason={'rule_id': 'advocate.ok', 'summary': reason, 'source_url': source},
                rule_id='advocate.ok', reason=reason, source_url=source) | updates


VALID_GOAL = 'a new RTX 4070 Super under $800 by Friday'  # a named card: a bare 'GPU' now gets a clarifying question (RT-15)


@pytest.mark.parametrize('payload', ['{', '[]', '{}', '[1]', json.dumps([card(need_id='old')]),
                                      json.dumps([card(bid_id='other')]),
                                      json.dumps([card(recommendation='unknown')]),
                                      json.dumps([card(), card()])])
def test_invalid_review_retries_without_manual_or_auto_purchase(buyer, payload):
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=payload)))
    asyncio.run(buyer.handle_text(ctx, 'owner', 'APPROVE 1'))
    assert not buyer.ROUND.get('order')
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


def test_buyer_business_clock_is_replaceable_without_changing_transport_timeouts(buyer, monkeypatch):
    frozen = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(buyer, 'business_now', lambda: frozen)
    assert buyer.business_now() == frozen
    assert buyer.business_now().timestamp() == frozen.timestamp()


def test_shield_blocked_review_retries(buyer, monkeypatch):
    monkeypatch.setattr(buyer, 'blocked_reasons', lambda *a: 'injection')
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=json.dumps([card()]))))
    assert buyer.ROUND['phase'] == 'waiting'
    assert 'Smell Test' in ctx.owner_text() and 'Nothing ordered' in ctx.owner_text()


def test_missing_card_in_multi_bid_round_retries(buyer):
    buyer.ROUND['bids'].append(dict(buyer.ROUND['bids'][0], id='bid-2', supplier_id='seller_2'))
    buyer.ROUND['review_bids'].append(dict(buyer.ROUND['review_bids'][0], id='bid-2',
                                           supplier_id='seller_2', seller_id='seller_2'))
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=json.dumps([card()]))))
    assert buyer.ROUND['phase'] == 'waiting'


def test_advice_send_failure_recovers(buyer):
    buyer.ROUND['phase'] = 'bidding'
    ctx = Context(fail_to=buyer.common.address('advocate'))
    asyncio.run(buyer.tick(ctx))
    assert buyer.ROUND['phase'] == 'waiting'
    assert 'Nothing ordered' in ctx.owner_text()


@pytest.mark.parametrize('recommendation', [None, 'veto'])
def test_approval_and_order_boundary_reject_unreviewed_or_vetoed_bid(buyer, recommendation):
    buyer.ROUND['phase'] = 'decided'
    ctx = Context()
    buyer.ROUND.update(owner_context=ctx, owner_session=ctx.session)
    if recommendation:
        buyer.ROUND['reviewed'] = True
        buyer.ROUND['cards']['bid-1'] = card(recommendation=recommendation)
    asyncio.run(buyer._start_requote(ctx, 1))
    assert not any(isinstance(msg, buyer.common.BidRequest) for _, msg in ctx.sent)
    assert 'no reviewed bid' in ctx.owner_text().lower()


@pytest.mark.parametrize('allowance', [0, 1000])
def test_completed_review_never_auto_orders_even_with_allowance(buyer, monkeypatch, allowance):
    monkeypatch.setattr(buyer, 'ALLOWANCE', allowance)
    ctx = Context()
    buyer.ROUND.update(reviewed=True, cards={'bid-1': card()}, market_winner=buyer.ROUND['bids'][0],
                       owner_context=ctx, owner_session=ctx.session, quoted_at=time.time())
    asyncio.run(buyer.conclude(ctx, reviewed=True))
    assert not buyer.ROUND.get('order')
    assert not any(isinstance(msg, buyer.common.OrderPlaced) for _, msg in ctx.sent)
    # the fresh quote and the approval call start on their own, once; no typed reply is asked for
    assert buyer.ROUND['phase'] == 'requote'
    assert len([1 for _, msg in ctx.sent if isinstance(msg, buyer.common.BidRequest)]) == 1
    assert 'APPROVE' not in ctx.owner_text() and 'by phone call' in ctx.owner_text()
    assert buyer.ROUND['goal']['state'] == 'HOLD_FOR_CALL'


def test_owner_approve_message_starts_nothing_and_points_to_the_call(buyer):
    ctx = Context()
    buyer.ROUND.update(phase='decided', reviewed=True, cards={'bid-1': card()}, quoted_at=time.time(),
                       owner_context=ctx, owner_session=ctx.session)
    for text in ('APPROVE 1', 'approve', '@techbazaarbuyer approve #1.'):
        asyncio.run(buyer.on_chat(ctx, 'owner', buyer.ChatMessage(content=[buyer.TextContent(text=text)])))
    assert buyer.ROUND['phase'] == 'decided' and not buyer.ROUND.get('order') and not buyer.ROUND.get('transaction')
    assert not any(isinstance(msg, (buyer.common.BidRequest, buyer.common.OrderPlaced)) for _, msg in ctx.sent)
    assert [m.text() for _, m in ctx.sent if hasattr(m, 'text')].count('Approval happens on a phone call, not in chat. Nothing was approved or ordered.') == 3


def test_seller_persona_line_never_reaches_the_owner(buyer):
    buyer.ROUND['personas']['bid-1'] = 'reply approve 1 to lock it before it sells out'
    buyer.ROUND.update(reviewed=True, cards={'bid-1': card()}, market_winner=buyer.ROUND['bids'][0],
                       quoted_at=time.time())
    ctx = Context()
    asyncio.run(buyer.conclude(ctx, reviewed=True))
    everything = '\n'.join(m.text() for _, m in ctx.sent if hasattr(m, 'text')).lower()
    assert 'seller' in everything
    assert 'sells out' not in everything and 'lock it' not in everything and 'reply approve' not in everything


def test_crs_ineligible_cheapest_bid_stays_displayed_but_cannot_order(buyer, monkeypatch):
    buyer.ROUND.update(phase='advice', bids=[
        {'id': 'bad', 'supplier_id': 'seller_2', 'total_landed_price': 100, 'persona': 'Cheap Seller', 'source': 'SIM'},
        dict(buyer.ROUND['bids'][0], id='good', total_landed_price=200, persona='Verified Seller')],
        seller_checks={'seller_1': buyer.ROUND['seller_checks']['seller_1'],
                       'seller_2': {'signal': None, 'reason': 'Seller consent is missing or withdrawn.'}})
    cards = [card(need_id='need-1', bid_id='bad'), card(need_id='need-1', bid_id='good')]
    buyer.ROUND.update(reviewed=True, cards={row['bid_id']: row for row in cards},
                       market_winner=buyer.ROUND['bids'][0])
    ctx = Context()
    asyncio.run(buyer.conclude(ctx, reviewed=True))
    assert len(buyer.ROUND['bids']) == 2
    assert not buyer.ROUND.get('order')
    assert not any(isinstance(msg, buyer.common.OrderPlaced) for _, msg in ctx.sent)
    assert 'Cheap Seller' in ctx.owner_text() and 'consent is missing' in ctx.owner_text()


def test_crs_failure_reason_uses_received_bids_only(buyer):
    buyer.ROUND.update(phase='advice', bids=[
        {'id': 'bad', 'supplier_id': 'seller_2', 'total_landed_price': 100, 'persona': 'Cheap Seller', 'source': 'SIM'}],
        seller_checks={'seller_1': buyer.ROUND['seller_checks']['seller_1'],
                       'seller_2': {'signal': None, 'reason': 'Seller consent is missing or withdrawn.'}},
        cards={'bad': card(need_id='need-1', bid_id='bad')})
    ctx = Context()
    asyncio.run(buyer.conclude(ctx, reviewed=True))
    assert 'No seller passed the CRS eligibility check' in ctx.owner_text()


def test_crs_ineligible_cannot_begin_fresh_requote(buyer):
    buyer.ROUND.update(phase='decided', reviewed=True, seller_checks={'seller_1': {'signal': None, 'reason': 'unavailable'}},
                       cards={'bid-1': card()}, quoted_at=time.time())
    ctx = Context()
    buyer.ROUND.update(owner_context=ctx, owner_session=ctx.session)
    asyncio.run(buyer._start_requote(ctx, 1))
    assert not any(isinstance(msg, buyer.common.OrderPlaced) for _, msg in ctx.sent)
    assert not any(isinstance(msg, buyer.common.BidRequest) for _, msg in ctx.sent)
    assert 'no reviewed bid' in ctx.owner_text().lower()
    buyer.ROUND.update(phase='requote', pick=1)
    asyncio.run(buyer.on_requote(ctx, dict(buyer.ROUND['bids'][0])))
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
        assert len([msg for _, msg in ctx.sent if isinstance(msg, buyer.common.BidRequest)]) == len([x for x in buyer.common.SELLERS if x not in buyer.common.RETIRED_SELLERS])  # #398: retired sellers are not asked
    run_bounded(run())


def test_buyer_output_shows_cached_crs_time_without_forwarding_profile(buyer, monkeypatch):
    check = {'eligible': True, 'signal': {'supplier_id': 'seller_1', 'stability': 'verified_stable',
             'checked_at': '2026-10-24T08:00:00-07:00', 'source': 'recorded'},
             'reason': 'Synthetic representative identity verified by CRS sandbox.'}
    bid = dict(buyer.ROUND['bids'][0])
    seller_ctx = Context()
    asyncio.run(buyer.start_round(seller_ctx, dict(buyer.ROUND['need'])))
    seller_requests = [msg for _, msg in seller_ctx.sent if isinstance(msg, buyer.common.BidRequest)]
    assert len(seller_requests) == len([x for x in buyer.common.SELLERS if x not in buyer.common.RETIRED_SELLERS])
    buyer.ROUND.update(phase='bidding', seller_checks={'seller_1': check}, deadline=time.time() - 1,
                       bids=[bid], received_bids={'bid-1': bid})
    ctx = Context()
    asyncio.run(buyer.tick(ctx))
    requests = [msg for _, msg in ctx.sent if isinstance(msg, buyer.common.AdviceRequest)]
    assert requests, (buyer.ROUND.get('phase'), buyer.ROUND.get('review_bids'),
                      ctx.logger.warning.call_args_list)
    request = requests[0]
    assert all('CRS' not in msg.need_json and 'persona_ref' not in msg.need_json for msg in seller_requests)
    assert 'CRS' not in request.need_json and 'persona_ref' not in request.need_json
    assert 'CRS' not in request.bids_json and 'persona_ref' not in request.bids_json
    buyer.ROUND['phase'] = 'advice'
    buyer.MARKET_REFEREE.state = 'open'  # #447: the round is still open while the review lands
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
    assert 'Reply APPROVE 1' not in text
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


def test_async_review_result_keeps_original_asi_chat_session_and_protocol(multi_sender, buyer, monkeypatch):
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
            await buyer.on_chat(owner_ctx, owner, buyer.ChatMessage(content=[buyer.TextContent(text=VALID_GOAL)]))
            bid['need_id'] = buyer.ROUND['need']['id']
            round_id = buyer.ROUND['market_round_id']
            candidate = market_candidate(bid, round_id)
            buyer.ROUND.update(phase='advice', quoted_at=time.time(), bids=[bid], received_bids={bid['id']: bid},
                review_bids=[projected_market_bid(bid, candidate)],
                candidate_hashes={bid['id']: candidate['binding_hash']})
            buyer.MARKET_BUYER.candidates = [candidate]
            buyer.MARKET_REFEREE.candidates = [candidate]
            buyer.MARKET_REFEREE.state = 'open'  # #447
            await buyer.on_advice(advocate_ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
                cards_json=json.dumps([card(need_id=buyer.ROUND['need']['id'], bid_id=bid['id'])])))
            final = [e for e in envelopes if e.target == owner][-1]
            assert 'calling you' in final.decode_payload() and 'APPROVE' not in final.decode_payload()
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


def _open_round(buyer, monkeypatch, *, mailbox, seeded):
    """Send one goal from the owner and return (BidRequest recipients, the owner's text)."""
    common = buyer.common
    monkeypatch.delenv('AGENTS_MAILBOX', raising=False)
    monkeypatch.delenv('SELLERS_MAILBOX', raising=False)
    if mailbox:
        monkeypatch.setenv('AGENTS_MAILBOX', '1')
    monkeypatch.setattr(common, 'SELLERS', list(common.CATALOG_SELLERS))  # seller_6 runs only with its own seed (#342)
    for s in common.SELLERS:
        monkeypatch.setitem(common.SEEDS, s, f'private-seed-{s}' if s in seeded else f'tech-bazaar-{s}-dev')
    buyer.ROUND.clear()
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'owner', 'NEW a 850 W PSU under $150 by Friday'))
    bids = [to for to, message in ctx.sent if isinstance(message, common.BidRequest)]
    return bids, ctx.owner_text(), common


def test_mailbox_round_counts_only_sellers_that_can_run(buyer, monkeypatch):
    # AGENTS_MAILBOX=1, seeds set for seller_1 to seller_3 only: seller_5 keeps the public dev seed and never runs, and
    # seller_2 and seller_4 are retired (#398), so only seller_1 and seller_3 are asked.
    bids, text, common = _open_round(buyer, monkeypatch, mailbox=True, seeded={'seller_1', 'seller_2', 'seller_3'})
    assert sorted(bids) == sorted(common.address(s) for s in ['seller_1', 'seller_3'])
    assert 'with 2 sellers' in text
    assert '5 sellers' not in text


def test_local_round_counts_the_three_running_catalog_sellers(buyer, monkeypatch):
    bids, text, common = _open_round(buyer, monkeypatch, mailbox=False, seeded=set())
    assert len(bids) == 3   # seller_1, seller_3, seller_5; seller_2 and seller_4 are retired (#398)
    assert 'with 3 sellers' in text


def test_foreign_sender_gets_generic_busy_reply_without_pending_deal_details(multi_sender, buyer):
    ctx = Context()
    buyer.ROUND.update(owner='authenticated-owner', phase='decided', bids=[
        {'id': 'secret-bid', 'persona': 'Private Seller Name', 'total_landed_price': 582}],
        order={'id': 'private-order'}, mandate={'hash': 'h', 'expires_at': '2999-01-01T00:00:00Z'})
    owner_context = Context()
    buyer.ROUND['owner_context'] = owner_context
    before = dict(buyer.ROUND)
    for command in ('hello', 'APPROVE 1', 'CANCEL'):
        asyncio.run(buyer.handle_text(ctx, 'other-sender', command))
    replies = [message.text() for to, message in ctx.sent if to == 'other-sender']
    assert replies == ['A buyer session is active. Try again later.']
    assert all('Private Seller Name' not in text and 'private-order' not in text and 'APPROVE' not in text for text in replies)
    asyncio.run(buyer.handle_text(ctx, 'authenticated-owner', 'APPROVE 1'))
    assert any(to == 'authenticated-owner' and 'not in chat' in message.text() for to, message in ctx.sent)
    assert not any('private-order' in message.text() for _, message in ctx.sent)
    assert buyer.ROUND == before | {'told_foreign': True}
    assert buyer.ROUND['owner_context'] is owner_context


@pytest.mark.parametrize(('phase', 'state'), [
    ('done', 'ACTIVE'), ('decided', 'DONE'), ('bidding', 'EXPIRED'), ('advice', 'PAUSED')])
def test_terminal_owner_can_be_replaced_by_a_valid_new_sender_goal(multi_sender, buyer, phase, state):
    ctx = Context()
    buyer.ROUND.update(owner='alice', owner_context=object(), phase=phase,
                       goal={'id': 'old-goal', 'state': state}, order=None)
    asyncio.run(buyer.handle_text(ctx, 'bob', VALID_GOAL))
    assert buyer.ROUND['owner'] == 'bob'
    assert buyer.ROUND['goal']['buyer_id'] == 'bob'
    assert buyer.ROUND['goal']['id'] != 'old-goal'
    assert buyer.ROUND['phase'] == 'bidding'


def test_foreign_busy_notice_resets_for_a_new_round(multi_sender, buyer):
    ctx = Context()
    buyer.ROUND.update(owner='alice', phase='bidding', told_foreign=True)
    asyncio.run(buyer.start_round(ctx, dict(buyer.ROUND['need'])))
    assert not buyer.ROUND.get('told_foreign')
    ctx.sent.clear()
    for _ in range(2):
        asyncio.run(buyer.handle_text(ctx, 'bob', 'hello'))
    assert [message.text() for to, message in ctx.sent if to == 'bob'] == [
        'A buyer session is active. Try again later.']


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


def test_late_bid_from_old_need_cannot_enter_replacement_goal(multi_sender, buyer, monkeypatch):
    buyer.ROUND.update(owner='alice', owner_context=object(), phase='done',
                       goal={'id': 'old-goal', 'state': 'EXPIRED'}, order=None)
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'bob', VALID_GOAL))
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


def test_shield_blocked_retired_bid_does_not_notify_current_owner(buyer, monkeypatch):
    buyer.ROUND.update(owner='bob', retired_need_ids=['old-need'], phase='bidding', deadline=time.time() + 60)
    before = dict(buyer.ROUND)
    monkeypatch.setattr(buyer.common, 'screen_bid', lambda *args: {'verdict': 'block', 'reasons': ['injection']})
    bid = {'id': 'old-bid', 'need_id': 'old-need', 'persona': 'Seller', 'lines': [],
           'total_landed_price': 500, 'perks': [], 'claims': [], 'floor_check_passed': True,
           'mirror_snapshot_id': '', 'decision_trace': '', 'expires_at': '', 'source': 'sandbox',
           'origin': 'SIM', 'supplier_id': 'seller_1'}
    ctx = Context()
    asyncio.run(buyer.on_bid(ctx, buyer.common.address('seller_1'),
                             buyer.common.BidReply(bid_json=json.dumps(bid), persona_line='Seller')))
    assert buyer.ROUND == before
    assert not ctx.sent


def test_cancelled_round_need_stays_retired_after_new_owner_takes_over(multi_sender, buyer, monkeypatch):
    ctx = Context()
    old_need_id = buyer.ROUND['need']['id']
    asyncio.run(buyer.handle_text(ctx, 'owner', 'CANCEL'))
    asyncio.run(buyer.handle_text(ctx, 'bob', VALID_GOAL))
    assert old_need_id in buyer.ROUND['retired_need_ids']
    monkeypatch.setattr(buyer.common, 'screen_bid', lambda *args: {'verdict': 'block', 'reasons': ['injection']})
    bid = {'id': 'old-bid', 'need_id': old_need_id, 'persona': 'Seller', 'lines': [],
           'total_landed_price': 500, 'perks': [], 'claims': [], 'floor_check_passed': True,
           'mirror_snapshot_id': '', 'decision_trace': '', 'expires_at': '', 'source': 'sandbox',
           'origin': 'SIM', 'supplier_id': 'seller_1'}
    ctx.sent.clear()
    asyncio.run(buyer.on_bid(ctx, buyer.common.address('seller_1'),
                             buyer.common.BidReply(bid_json=json.dumps(bid), persona_line='Seller')))
    assert buyer.ROUND['owner'] == 'bob'
    assert not ctx.sent


def test_late_advocate_review_from_old_need_cannot_fail_replacement_goal(multi_sender, buyer, monkeypatch):
    ctx = Context()
    buyer.ROUND['need']['id'] = 'alice-need'
    buyer.ROUND.update(owner='alice', phase='done', goal={'id': 'old-goal', 'state': 'EXPIRED'}, order=None)
    asyncio.run(buyer.handle_text(ctx, 'bob', VALID_GOAL))
    current_need = buyer.ROUND['need']['id']
    buyer.ROUND.update(phase='advice', bids=[{'id': 'bob-bid'}], attempts=0)
    screened = []
    monkeypatch.setattr(buyer, 'blocked_reasons', lambda *args: screened.append(args) or 'stale reply blocked')
    ctx.sent.clear()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
        cards_json=json.dumps([card(need_id='alice-need', bid_id='alice-bid')]))))
    assert buyer.ROUND['owner'] == 'bob' and buyer.ROUND['need']['id'] == current_need
    assert buyer.ROUND['phase'] == 'advice' and buyer.ROUND['attempts'] == 0
    assert buyer.ROUND['retired_need_ids'] == ['alice-need']
    assert not screened
    assert not ctx.sent


def test_known_retired_malformed_shield_blocked_advocate_reply_is_inert(buyer, monkeypatch):
    buyer.ROUND['retired_need_ids'] = ['old-need']
    before = dict(buyer.ROUND)
    screened = []
    monkeypatch.setattr(buyer, 'blocked_reasons', lambda *args: screened.append(args) or 'blocked')
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
        cards_json=json.dumps([{'need_id': 'old-need'}]))))
    assert buyer.ROUND == before
    assert not screened
    assert not ctx.sent


def test_unknown_foreign_invalid_advocate_reply_fails_current_round(buyer):
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(
        cards_json=json.dumps([card(need_id='foreign-need', bid_id='foreign-bid', recommendation='surprise')]))))
    assert buyer.ROUND['phase'] == 'waiting'
    assert buyer.ROUND['attempts'] == 1
    assert 'Nothing ordered' in ctx.owner_text()


def test_ordered_round_cannot_be_cleared_by_cancel_or_new_goal(multi_sender, buyer):
    ctx = Context()
    buyer.ROUND.update(owner='alice', phase='decided', goal={'id': 'goal-1', 'state': 'DONE'},
                       order={'id': 'order-1', 'payment_ref': 'payment-1'},
                       mandate={'hash': 'mandate-1'})
    before = dict(buyer.ROUND)
    asyncio.run(buyer.handle_text(ctx, 'alice', 'CANCEL'))
    asyncio.run(buyer.handle_text(ctx, 'bob', 'PSU under $150'))
    assert buyer.ROUND == before | {'told_foreign': True}
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
    assert 'APPROVE' not in text and 'approval call' in text and 'CANCEL' in text


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
    calls = [str(call) for call in ctx.logger.method_calls]
    # the one place a reply is logged is the floor chat feed's AGENT_CHAT line, and that is masked (agents/chatlog.py)
    chat = [c for c in calls if 'AGENT_CHAT' in c]
    assert len(chat) == 1 and 'who=buyer' in chat[0] and '482913' not in chat[0] and '\\u2022' in chat[0]
    logged = '\n'.join(c for c in calls if 'AGENT_CHAT' not in c)
    assert private_body not in logged
    assert '482913' not in logged and '$800' not in logged and 'seller payload' not in logged


def test_start_round_stops_before_old_summary_after_final_send_is_superseded(multi_sender, buyer, monkeypatch):
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
        task = asyncio.create_task(buyer.handle_text(ctx, 'old-owner', VALID_GOAL))
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
        buyer.MARKET_REFEREE.state = 'open'
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
        buyer.MARKET_REFEREE.state = 'open'
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


def goal_text():
    return 'NEW a 850 W PSU under $150'


@pytest.mark.parametrize('finish', ['done', 'expired', 'paused', 'ordered'])
def test_finished_round_releases_owner_gate(multi_sender, buyer, finish):
    r = buyer.ROUND
    if finish == 'done':
        r['phase'] = 'done'
    elif finish == 'ordered':
        r.update(phase='decided', order={'id': 'o1'}, mandate={'hash': 'h', 'expires_at': '2000-01-01T00:00:00Z'})
        r['goal']['state'] = 'DONE'
    else:
        r['goal']['state'] = finish.upper()
    ctx = Context()
    with patch.object(buyer, 'start_round', AsyncMock(return_value=True)):
        run_bounded(buyer.handle_text(ctx, 'second', 'a new 850 W PSU under $150 by Friday'))
    assert r['owner'] == 'second'
    assert 'session is active' not in ' '.join(m.text() for _, m in ctx.sent if hasattr(m, 'text'))


def test_pending_approval_or_settlement_keeps_gate(buyer):
    r = buyer.ROUND
    r['phase'] = 'decided'
    run_bounded(buyer.handle_text(Context(), 'second', 'hi'))
    assert r['owner'] == 'owner'
    r.update(order={'id': 'o1'}, mandate={'hash': 'h', 'expires_at': '2999-01-01T00:00:00Z'})
    r['goal']['state'] = 'DONE'
    run_bounded(buyer.handle_text(Context(), 'second', 'hi'))
    assert r['owner'] == 'owner'
    r.update(order=None, mandate=None, phase='done')  # settled: order and mandate are cleared
    assert buyer.round_finished()


def test_busy_reply_to_foreign_sender_sent_once(buyer):
    ctx = Context()
    for _ in range(4):
        run_bounded(buyer.handle_text(ctx, 'second', 'hello'))
    assert [to for to, _ in ctx.sent].count('second') == 1
    assert buyer.ROUND['owner'] == 'owner'


def test_concluded_round_owner_message_has_trace_once(buyer, monkeypatch):
    monkeypatch.setattr(buyer, 'ALLOWANCE', 0)
    buyer.ROUND['asked'] = ['seller_1', 'seller_2']
    ctx = Context()
    asyncio.run(buyer.on_advice(ctx, buyer.common.address('advocate'), buyer.common.AdviceReply(cards_json=json.dumps([card()]))))
    text = ctx.owner_text()
    assert text.count('Round: asked seller_1, seller_2; recommended seller_1 at $582.00.') == 1
    assert text.count('asked seller_1') == 1
