"""#261: the owner's order, shipped and tracking messages and the order email. Pure, no network."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import post_purchase as P  # noqa: E402

FACTS = {"order_id": "ord-1", "item": "RTX 5070 Ti", "seller": "Best Buy", "amount": 1299.99, "payment_mode": "sim",
         "mandate_hash": "7fe6783ca5c94c92aa"}
NOW = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)


def test_three_messages_in_order_with_honest_labels():
    ship = P.sim_shipment(FACTS, NOW)
    lines = P.messages(FACTS, ship)
    assert [l.split(":")[0] for l in lines] == ["Order confirmed", "Shipped", f"Tracking {ship['tracking']}"]
    assert "$1,299.99 before tax (SIM payment, no money moved)" in lines[0]
    assert all("SIM carrier data" in l for l in lines[1:])
    assert ship == {"carrier": "SIM Carrier", "tracking": "SIM7FE6783CA5", "shipped_at": "2026-10-24T22:00:00+00:00",
                    "eta": "2026-10-27", "origin": "SIM"}


@pytest.mark.parametrize("mode, note", [("stripe_test", "Stripe test mode, no real money"), ("live", "SIM payment, no money moved"),
                                        (None, "SIM payment, no money moved")])
def test_payment_wording_never_claims_a_real_charge(mode, note):
    assert note in P.confirmation({**FACTS, "payment_mode": mode})


def test_the_email_goes_only_to_a_plain_owner_address_and_labels_sim():
    ship = P.sim_shipment(FACTS, NOW)
    mail = P.email(FACTS, ship, " vidyut@example.test ")
    assert mail["to"] == "vidyut@example.test" and "ord-1" in mail["subject"]
    for want in ("What you ordered: RTX 5070 Ti from Best Buy", "Total paid: $1,299.99", "Expected delivery: 2026-10-27 (SIM estimate)",
                 "SIM carrier data", "Nothing in this email asks you for a code or a card"):
        assert want in mail["body"]
    for bad in (None, "", "not an address", "a@b", "x@example.test, y@evil.test", "x@example.test\nBcc: y@evil.test"):
        assert P.email(FACTS, ship, bad) is None, bad


def test_deliver_sends_the_chat_lines_and_the_email():
    said, mails = [], []
    out = P.deliver(FACTS, P.sim_shipment(FACTS, NOW), tell_owner=said.append, owner_email="v@example.test",
                    send_email=lambda m: mails.append(m) or True)
    assert out["email"] == "sent" and len(said) == 3 and len(mails) == 1


@pytest.mark.parametrize("email, sender, why", [
    (None, lambda m: True, "no owner email address set"),
    ("v@example.test", None, "no email sender configured"),
    ("v@example.test", lambda m: (_ for _ in ()).throw(TimeoutError()), "TimeoutError"),
    ("v@example.test", lambda m: "connector not authorized", "connector not authorized"),
    ("v@example.test", lambda m: False, "the sender refused"),
])
def test_when_the_email_fails_the_chat_still_goes_out_and_says_so(email, sender, why):
    said = []
    out = P.deliver(FACTS, P.sim_shipment(FACTS, NOW), tell_owner=said.append, owner_email=email, send_email=sender)
    assert out["email"].startswith("not_sent") and len(said) == 4
    assert said[-1] == f"The order email was not sent ({why}). These chat messages are your record."
