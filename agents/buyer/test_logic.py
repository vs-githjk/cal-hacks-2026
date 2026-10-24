import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from common import validate
from logic import decide, make_order, mandate, need_from_forecast, sealed
from mock_forecast import FORECASTS, ON_HAND, OWNER


def bid(total, bid_id="bid-1"):
    return {"id": bid_id, "need_id": "need-x", "supplier_id": "sup-1", "persona": "p", "lines": [],
            "total_landed_price": total, "perks": [], "claims": [], "floor_check_passed": True,
            "mirror_snapshot_id": "m", "decision_trace": "", "expires_at": "2026-10-24T00:00:00Z",
            "source": "simulated"}


def test_need_rounds_up_to_whole_packs_and_validates():
    need = validate("Need", need_from_forecast(FORECASTS, ON_HAND, OWNER))
    qty = {i["sku_spec"]: i["quantity"] for i in need["items"]}
    assert qty["yellow onions"] == 3  # 150 lb short / 50 -> 3
    assert qty["roma tomatoes"] == 4  # 80 / 25 = 3.2 -> 4
    assert qty["chicken thighs"] == 4  # 130 / 40 = 3.25 -> 4
    assert need["source"] == "simulated"


def test_need_skips_items_fully_in_stock():
    f = [dict(FORECASTS[0], predicted_quantity=20)]
    assert need_from_forecast(f, {"yellow onions": 30}, OWNER)["items"] == []


def test_sealed_drops_spend_limit():
    need = need_from_forecast(FORECASTS, ON_HAND, OWNER)
    s = sealed(need)
    assert "spend_limit" not in s and "spend_limit" in need
    assert s["items"] == need["items"]


@pytest.mark.parametrize("total,expected", [(500, "auto_order"), (600, "auto_order"), (601, "needs_approval"),
                                            (900, "needs_approval"), (900.01, "over_limit")])
def test_decide_thresholds(total, expected):
    need = need_from_forecast(FORECASTS, ON_HAND, OWNER)
    assert decide(need, bid(total), OWNER["auto_limit"]) == expected


def test_decide_auto_limit_above_spend_limit_still_capped():
    need = dict(need_from_forecast(FORECASTS, ON_HAND, OWNER), spend_limit=100)
    assert decide(need, bid(150), auto_limit=1000) == "over_limit"


def test_order_and_mandate():
    need = need_from_forecast(FORECASTS, ON_HAND, OWNER)
    a = validate("Order", make_order(need, bid(512.5), "owner", "approve-1"))
    b = validate("Order", make_order(need, bid(512.5), "owner", "approve-1"))
    assert a["idempotency_key"] != b["idempotency_key"]
    assert a["limit_checked"] and a["status"] == "approved" and a["payment_ref"] == ""
    m = mandate(a, "sup-1")
    assert m["amount_cap"] == 512.5 and m["payee"] == "sup-1" and m["single_use"]
    assert m["idempotency_key"] == a["idempotency_key"]
