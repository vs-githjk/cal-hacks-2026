"""#449 RT-22: the owner's result counts the sealed bids that were reviewed, not the one bid left after the market picked a winner.
(The vetoes are named by explain.round_summary, with their sources; chat memory is #456's.)"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_recovery import Context, buyer, card  # noqa: E402,F401


def finish_with(buyer, extra):
    """The market picks bid-1 and ROUND["bids"] is cut to it; `extra` more sealed bids came in and were reviewed: (id, price)."""
    base = buyer.ROUND['review_bids'][0]
    for bid_id, price in extra:
        buyer.ROUND['review_bids'].append(dict(base, id=bid_id, persona=f'Seller {bid_id}', total_landed_price=price, supplier_id='seller_2'))
        buyer.ROUND['cards'][bid_id] = card()
    buyer.ROUND['cards']['bid-1'] = card()
    ctx = Context()
    buyer.ROUND.update(phase='market_review_wait', owner_context=ctx, owner_session=ctx.session, reviewed=True)
    asyncio.run(buyer._finish_market_round(ctx))
    return ctx.owner_text()


def test_rt22_the_result_counts_every_reviewed_bid_and_pluralizes(buyer):
    text = finish_with(buyer, [('bid-a', 700.0), ('bid-b', 900.0)])
    assert '3 sealed bids for need-1' in text and '1 sealed bids' not in text


def test_rt22_a_single_reviewed_bid_reads_as_one_bid(buyer):
    text = finish_with(buyer, [])
    assert '1 sealed bid for need-1' in text and 'sealed bids for need-1' not in text
