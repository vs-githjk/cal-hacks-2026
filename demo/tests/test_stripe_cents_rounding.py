"""Dollars to integer cents at the Stripe edge (demo/approval_flow.py, the SIM stub and the test-mode call).

`int(x * 100)` truncates a float that lands just under the cent (0.29 * 100 is 28.999999999999996), so a
charge would be a cent short. The guard is `int(round(x * 100))`; these cases fail if it is deleted.
"""
import io
import json
import urllib.parse

import pytest

from demo.approval_flow import stripe_charge_sim, stripe_charge_test
from pay.mandate import new_mandate

# (dollars, cents). The first four are floats whose product with 100 truncates one cent low.
CASES = [(0.29, 29), (1.15, 115), (19.99, 1999), (4.35, 435), (1299.99, 129999), (773.22, 77322), (0.1 + 0.2, 30), (0.01, 1), (2499.98, 249998)]


def _mandate(amount):
    return new_mandate(deal_id="deal-cents", buyer_id="vidyut", amount=amount, payee="honest-hal@pay.example.test")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("dollars,cents", CASES)
def test_sim_charge_is_the_exact_integer_cent_amount(dollars, cents):
    out = stripe_charge_sim(_mandate(dollars))
    assert out["amount_cents"] == cents and isinstance(out["amount_cents"], int)


@pytest.mark.parametrize("dollars,cents", CASES)
def test_stripe_test_mode_request_sends_the_exact_integer_cent_amount(dollars, cents):
    seen = {}

    def fake_urlopen(req, timeout=None, context=None):
        seen["form"] = urllib.parse.parse_qs(req.data.decode())
        return _Resp(json.dumps({"id": "pi_1", "object": "payment_intent", "amount": cents, "currency": "usd", "status": "succeeded"}).encode())
    stripe_charge_test(_mandate(dollars), "sk_test_FAKEKEY1234567890", urlopen=fake_urlopen)
    assert seen["form"]["amount"] == [str(cents)]
