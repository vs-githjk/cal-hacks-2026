import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uagents_core.contrib.protocols.payment import CommitPayment, RejectPayment

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


def _deal():
    m = payment.make_mandate("order-1", 589.0, SELLER, buyer_id="joe", within_allowance=False)
    return m, {m["hash"]: {"answer": "approve", "source": "chat stub"}}, set()


def test_settle_commits_then_rejects_reuse():
    m, approvals, used = _deal()
    req = payment.payment_request(m, SELLER)
    assert isinstance(hunt.settle(req, m, approvals, used), CommitPayment)
    again = hunt.settle(req, m, approvals, used)
    assert isinstance(again, RejectPayment) and "replay" in again.reason


def test_settle_rejects_other_payee_and_no_mandate():
    m, approvals, used = _deal()
    out = hunt.settle(payment.payment_request(m, "agent1qattacker"), m, approvals, used)
    assert isinstance(out, RejectPayment) and "payee" in out.reason
    assert not used
    assert isinstance(hunt.settle(payment.payment_request(m, SELLER), None, approvals, used), RejectPayment)


def test_settle_rejects_expired_mandate():
    m, approvals, used = _deal()
    m_old = payment.make_mandate("order-2", 10.0, SELLER, buyer_id="joe", within_allowance=False,
                                  now=datetime.now(timezone.utc) - timedelta(minutes=20))
    out = hunt.settle(payment.payment_request(m_old, SELLER), m_old, {m_old["hash"]: {"answer": "approve"}}, used)
    assert isinstance(out, RejectPayment) and "expired" in out.reason


def test_pick_best_prefers_asked_condition_over_cheaper_refurb():
    bids = [{"id": "frankie", "total_landed_price": 528}, {"id": "sally", "total_landed_price": 550},
            {"id": "byte", "total_landed_price": 582}]
    cards = {"frankie": {"recommendation": "veto", "warnings": [{"kind": "condition"}]},
             "sally": {"recommendation": "caution", "warnings": [{"kind": "spec"}, {"kind": "fit_unknown"}]},
             "byte": {"recommendation": "caution", "warnings": [{"kind": "fit_unknown"}]}}
    assert hunt.pick_best(bids, cards) == 3  # Byte Bros: new as asked; Sally only if nothing else is left
    assert hunt.pick_best(bids[:2], cards) == 2
    assert hunt.pick_best(bids[:1], cards) is None
