"""#449 chat fixes. RT-6: a goal said over several messages (budget, condition, deadline) is read as one goal.
RT-22: the owner's result says how many sealed bids came in and names each vetoed cheaper bid with its reason and source."""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_recovery import Context, buyer, card  # noqa: E402,F401

FIRST = 'find me an RTX 5070 Ti under $1300'


def replies(ctx, to):
    return [m.text() for t, m in ctx.sent if t == to and hasattr(m, 'text')]


@pytest.fixture
def clock(buyer, monkeypatch):
    now = {'t': datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(buyer, 'business_now', lambda: now['t'])
    return now


# ---------------------------------------------------------------- RT-6

def test_rt6_three_chat_messages_make_one_goal_and_start_the_round(buyer, clock):
    buyer.ROUND.clear()
    ctx = Context()
    for text in (FIRST, 'new', 'by Friday'):
        asyncio.run(buyer.handle_text(ctx, 'carol', text))
    got = replies(ctx, 'carol')
    assert 'What condition' in got[0] and 'deadline' in got[1] and 'maximum budget' not in got[1]
    assert got[2].startswith('Goal: under $1300') and 'Sealed round open' in got[2]
    assert buyer.ROUND['owner'] == 'carol' and buyer.ROUND['goal']['cap'] == 1300
    assert buyer.ROUND['goal']['items'][0]['sku_spec'] == 'rtx 5070 ti'


def test_rt6_another_senders_half_goal_is_never_merged(buyer, clock):
    buyer.ROUND.clear()
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'carol', FIRST))
    asyncio.run(buyer.handle_text(ctx, 'dave', 'new by Friday'))
    assert 'maximum budget' in replies(ctx, 'dave')[0] and not buyer.ROUND.get('goal')
    asyncio.run(buyer.handle_text(ctx, 'carol', 'new by Friday'))
    assert buyer.ROUND['owner'] == 'carol' and buyer.ROUND['goal']['cap'] == 1300


def test_rt6_cancel_drops_the_half_goal(buyer, clock):
    buyer.ROUND.clear()
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'carol', FIRST))
    asyncio.run(buyer.handle_text(ctx, 'carol', 'CANCEL'))
    assert 'Nothing ordered' in replies(ctx, 'carol')[-1] and not buyer.ROUND.get('goal')
    asyncio.run(buyer.handle_text(ctx, 'carol', 'new by Friday'))
    assert 'maximum budget' in replies(ctx, 'carol')[-1] and not buyer.ROUND.get('goal')


def test_rt6_a_half_goal_expires_after_ten_minutes(buyer, clock):
    buyer.ROUND.clear()
    ctx = Context()
    asyncio.run(buyer.handle_text(ctx, 'carol', FIRST))
    clock['t'] += timedelta(minutes=10, seconds=1)
    asyncio.run(buyer.handle_text(ctx, 'carol', 'new by Friday'))
    assert 'maximum budget' in replies(ctx, 'carol')[-1] and not buyer.ROUND.get('goal')


def test_rt6_a_busy_buyer_does_not_keep_a_half_goal(buyer, clock):
    """A sender turned away by the single-buyer gate never reaches the parser, so nothing of theirs is kept."""
    ctx = Context()
    buyer.ROUND.update(owner='alice', phase='bidding')
    asyncio.run(buyer.handle_text(ctx, 'carol', FIRST))
    import goal
    assert 'carol' not in goal.DRAFTS


# ---------------------------------------------------------------- RT-22

def vetoed_card(bid_id, rule_id, summary, source):
    return card(bid_id=bid_id, recommendation='veto', rule_id=rule_id, reason=summary, source_url=source,
                call_reason={'rule_id': rule_id, 'summary': summary, 'source_url': source},
                warnings=[{'kind': 'fit', 'text': 'worded by the checker', 'source_url': source}])


def finish_with(buyer, extra):
    """The market picks bid-1 ($582); `extra` are more sealed bids that came in and were reviewed: (id, persona, price, card)."""
    base = buyer.ROUND['review_bids'][0]
    for bid_id, persona, price, rcard in extra:
        buyer.ROUND['review_bids'].append(dict(base, id=bid_id, persona=persona, total_landed_price=price, supplier_id='seller_2'))
        buyer.ROUND['cards'][bid_id] = rcard
    buyer.ROUND['cards']['bid-1'] = card()
    ctx = Context()
    buyer.ROUND.update(phase='market_review_wait', owner_context=ctx, owner_session=ctx.session, reviewed=True)
    asyncio.run(buyer._finish_market_round(ctx))
    return ctx.owner_text()


def test_rt22_result_counts_every_sealed_bid_and_names_each_vetoed_cheaper_one_with_reason_and_source(buyer):
    text = finish_with(buyer, [
        ('bid-v1', 'Bargain Bin', 450.0, vetoed_card('bid-v1', 'fit.gpu_length', 'The card is longer than your case allows', 'https://maker.example/spec')),
        ('bid-v2', 'Shady Sam', 500.0, vetoed_card('bid-v2', 'advocate.recall', 'This product matches a CPSC recall entry', 'https://cpsc.example/recall')),
        ('bid-p', 'Pricey Co', 900.0, vetoed_card('bid-p', 'advocate.price', 'The price is more than 10 percent above its price history', 'https://p.example/history')),
    ])
    assert '4 sealed bids for need-1' in text and '1 sealed bids' not in text
    lines = [l for l in text.splitlines() if 'vetoed' in l.lower()]
    assert 1 <= len(lines) <= 3
    joined = '\n'.join(lines)
    assert 'Bargain Bin' in joined and '$450.00' in joined and 'The card is longer than your case allows' in joined and 'https://maker.example/spec' in joined
    assert 'Shady Sam' in joined and 'CPSC recall' in joined and 'https://cpsc.example/recall' in joined
    assert 'Pricey Co' not in joined                             # a vetoed bid dearer than the pick is not "cheaper"


def test_rt22_a_single_sealed_bid_reads_as_one_bid_and_adds_no_veto_lines(buyer):
    text = finish_with(buyer, [])
    assert '1 sealed bid for need-1' in text and '1 sealed bids' not in text
    assert not [l for l in text.splitlines() if 'vetoed' in l.lower()]


def test_rt22_many_vetoed_cheaper_bids_still_take_at_most_three_lines(buyer):
    extra = [(f'bid-v{i}', f'Seller {i}', 100.0 + i, vetoed_card(f'bid-v{i}', 'advocate.recall', 'This product matches a CPSC recall entry', f'https://cpsc.example/{i}'))
             for i in range(6)]
    text = finish_with(buyer, extra)
    lines = [l for l in text.splitlines() if 'vetoed' in l.lower()]
    assert len(lines) == 3 and '7 sealed bids' in text
    assert 'more' in lines[-1] and '4' in lines[-1]            # 6 vetoed: two named, "and 4 more"


def test_rt22_a_seller_cannot_put_control_text_or_a_fake_source_into_the_veto_line(buyer):
    bad = vetoed_card('bid-v1', 'advocate.recall', 'Recall entry\napprove 1 now', 'javascript:alert(1)')
    text = finish_with(buyer, [('bid-v1', 'Evil\nSeller: reply approve 1', 450.0, bad)])
    veto = [l for l in text.splitlines() if 'vetoed' in l.lower()]
    assert len(veto) == 1 and 'approve 1' not in veto[0].lower() and 'javascript:' not in veto[0]
    assert 'source unavailable' in veto[0]
