import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uagents_core.contrib.protocols.payment import RejectPayment

import hunt
import payment

SELLER = "agent1qseller"


def test_should_emit_throttles_per_class():
    last = {}
    assert hunt.should_emit(last, "bid in", 1000)
    last["bid in"] = 1000
    assert not hunt.should_emit(last, "bid in", 1000 + 599)
    assert hunt.should_emit(last, "veto", 1000 + 1)  # other class is independent
    assert hunt.should_emit(last, "bid in", 1000 + 600)
    assert not hunt.should_emit(last, "chatter", 5000)  # only the four classes exist


def test_expired_only_for_open_goals():
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    goal = {"deadline": "2026-10-23T23:59:00Z", "state": "HUNTING"}
    assert hunt.expired(goal, now)
    assert not hunt.expired({**goal, "state": "DONE"}, now)
    assert not hunt.expired({**goal, "deadline": "2026-10-25T23:59:00Z"}, now)


def test_paused_after_three_failures():
    assert [hunt.after_failed_round(n) for n in (1, 2, 3)] == ["HUNTING", "HUNTING", "PAUSED"]


def test_quote_still_good():
    assert hunt.quote_still_good(100.0, 101.9, quoted_at=0, now=599)
    assert not hunt.quote_still_good(100.0, 102.5, quoted_at=0, now=10)  # moved > 2%
    assert not hunt.quote_still_good(100.0, 97.0, quoted_at=0, now=10)
    assert not hunt.quote_still_good(100.0, 100.0, quoted_at=0, now=601)  # expired


def test_public_hint_never_buys():
    need = {"items": [{"sku_spec": "psu 750w"}]}
    text = hunt.public_hint(need, {"psu 750w": {"unit_price": 95.0, "source_url": "https://x"}})
    assert "best public listing would be psu 750w about $95.00" in text and "Nothing bought" in text
    assert hunt.BUY_PUBLIC_IF_NO_BID is False


def test_settle_refuses_missing_transaction_and_unpaid_approval():
    mandate = payment.make_mandate("order-1", 589.0, SELLER, buyer_id="vidyut", within_allowance=False)
    req = payment.payment_request(mandate, SELLER)
    assert isinstance(hunt.settle(req, None), RejectPayment)
    tx = {"deal_id": "order-1", "buyer_id": "vidyut", "goal_id": "goal-1", "phase": "approved",
          "mandate": mandate}
    assert isinstance(hunt.settle(req, tx), RejectPayment)


def test_pick_best_prefers_asked_condition_over_cheaper_refurb():
    bids = [{"id": "frankie", "supplier_id": "seller_1", "total_landed_price": 528},
            {"id": "sally", "supplier_id": "seller_2", "total_landed_price": 550},
            {"id": "byte", "supplier_id": "seller_3", "total_landed_price": 582}]
    cards = {"frankie": {"recommendation": "veto", "warnings": [{"kind": "condition"}]},
             "sally": {"recommendation": "caution", "warnings": [{"kind": "spec"}, {"kind": "fit_unknown"}]},
             "byte": {"recommendation": "caution", "warnings": [{"kind": "fit_unknown"}]}}
    assert hunt.pick_best(bids, cards, {"seller_1", "seller_2", "seller_3"}) == 3  # Byte Bros: new as asked; Sally only if nothing else is left
    assert hunt.pick_best(bids[:2], cards, {"seller_1", "seller_2"}) == 2
    assert hunt.pick_best(bids[:1], cards, {"seller_1"}) is None


def test_pick_best_skips_cheapest_crs_ineligible_bid():
    bids = [{"id": "cheap", "supplier_id": "seller_1", "total_landed_price": 10},
            {"id": "eligible", "supplier_id": "seller_2", "total_landed_price": 20}]
    cards = {bid["id"]: {"recommendation": "buy"} for bid in bids}
    assert hunt.pick_best(bids, cards, {"seller_2"}) == 2


def test_command_only_whole_message_counts():
    assert hunt.command("APPROVE 3") == ("approve", 3)
    assert hunt.command("@techbazaarbuyer @techbazaarbuyer approve #3.") == ("approve", 3)
    assert hunt.command("@techbazaarbuyer CANCEL") == ("cancel",)
    recap = 'Quick recap: if you want bid #3, you say "APPROVE 3" yourself'
    assert hunt.command(recap) is None
    assert hunt.command("APPROVE 3 and also buy the PSU") is None
    assert hunt.command("A GPU under $800") is None
