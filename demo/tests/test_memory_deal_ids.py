"""#447: the purchase memory finds the winning bid from a deal id exactly as the market's bidIdOfDeal does
(market/spacetimedb/src/market.ts): strip "deal-", then take what follows the last ':'."""
import pytest

from demo import memory


@pytest.mark.parametrize("deal,bid", [
    ("deal-round-need-1:bid-1", "bid-1"),     # the buyer agent's web deal id
    ("round-w1:bid-w1", "bid-w1"),            # the market tests' shape
    ("deal-bid-7", "bid-7"),                  # an older deal id with no round
    ("bid-9", "bid-9"),
])
def test_a_deal_id_names_the_same_bid_as_the_market(deal, bid):
    assert memory.bid_id_of_deal(deal) == bid
