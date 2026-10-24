import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from common import validate
from logic import advice_need_for, decide, make_order, mandate, sealed

NEED = {"id": "need-x", "buyer_id": "b", "items": [], "delivery_window": "by Friday", "spend_limit": 900.0,
        "consent": True, "auction_window_s": 12, "source": "live"}


def bid(total, bid_id="bid-1"):
    return {"id": bid_id, "need_id": "need-x", "supplier_id": "sup-1", "persona": "p", "lines": [],
            "total_landed_price": total, "perks": [], "claims": [], "floor_check_passed": True,
            "mirror_snapshot_id": "m", "decision_trace": "", "expires_at": "2026-10-24T00:00:00Z",
            "source": "simulated"}


def test_sealed_drops_spend_limit():
    need = dict(NEED)
    s = sealed(need)
    assert "spend_limit" not in s and "spend_limit" in need
    assert s["items"] == need["items"]


@pytest.mark.parametrize("total,expected", [(500, "auto_order"), (600, "auto_order"), (601, "needs_approval"),
                                            (900, "needs_approval"), (900.01, "over_limit")])
def test_decide_thresholds(total, expected):
    need = dict(NEED)
    assert decide(need, bid(total), 600.0) == expected


def test_decide_auto_limit_above_spend_limit_still_capped():
    need = dict(dict(NEED), spend_limit=100)
    assert decide(need, bid(150), auto_limit=1000) == "over_limit"


def test_order_and_mandate():
    need = dict(NEED)
    a = validate("Order", make_order(need, bid(512.5), "owner", "approve-1"))
    b = validate("Order", make_order(need, bid(512.5), "owner", "approve-1"))
    assert a["idempotency_key"] != b["idempotency_key"]
    assert a["limit_checked"] and a["status"] == "approved" and a["payment_ref"] == ""
    m = mandate(a, "sup-1")
    assert m["amount_cap"] == 512.5 and m["payee"] == "sup-1" and m["single_use"]
    assert m["idempotency_key"] == a["idempotency_key"]


def test_missing_spend_limit_fails_closed():
    need = {k: v for k, v in NEED.items() if k != "spend_limit"}
    assert advice_need_for(need, {}, [bid(100)])["in_cap_bid_ids"] == []
    assert decide(need, bid(100), auto_limit=500) == "over_limit"
    assert decide({**NEED, "spend_limit": None}, bid(100), auto_limit=500) == "over_limit"
