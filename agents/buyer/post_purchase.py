"""After a purchase (#261): the owner's order confirmation, shipped and tracking messages, and the same facts as an
email to the owner's own address.

Pure functions on the order facts the buyer agent already has. The carrier, tracking number and delivery estimate are
SIM (no real shipment exists), and every line that shows them says SIM. Payment wording follows the payment mode:
"SIM payment, no money moved" or "Stripe test mode, no real money"; never a live charge. The email goes only to the
owner's own address, and `deliver` says plainly when it was not sent, while the chat lines still go out.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

SIM_CARRIER = "SIM Carrier"
SIM_TRANSIT_DAYS = 3
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+")
PAY_NOTE = {"sim": "SIM payment, no money moved", "stripe_test": "Stripe test mode, no real money"}


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _pay_note(mode: Any) -> str:
    return PAY_NOTE.get(mode, PAY_NOTE["sim"])   # anything unknown reads as SIM, never as a real charge


def sim_shipment(facts: dict, now: Optional[datetime] = None) -> dict:
    """A SIM shipment for the order: SIM carrier, a SIM tracking number from the mandate hash, an estimate 3 days out."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    code = re.sub(r"[^0-9a-f]", "", str(facts.get("mandate_hash") or "").lower())[:10].upper() or "0000000000"
    return {"carrier": SIM_CARRIER, "tracking": f"SIM{code}", "shipped_at": now.isoformat(),
            "eta": (now + timedelta(days=SIM_TRANSIT_DAYS)).date().isoformat(), "origin": "SIM"}


def confirmation(facts: dict) -> str:
    return (f"Order confirmed: {facts['item']} from {facts['seller']}, {_money(facts['amount'])} before tax "
            f"({_pay_note(facts.get('payment_mode'))}). Order {facts['order_id']}. I will message you when it ships.")


def shipped(facts: dict, shipment: dict) -> str:
    return (f"Shipped: {facts['item']} from {facts['seller']} is on its way with {shipment['carrier']}, tracking "
            f"{shipment['tracking']}, expected {shipment['eta']} (SIM carrier data, no real shipment).")


def tracking(facts: dict, shipment: dict, status: str) -> str:
    return f"Tracking {shipment['tracking']}: {status} (SIM carrier data). Expected {shipment['eta']}."


def messages(facts: dict, shipment: dict) -> list[str]:
    """The three owner chat lines, in order."""
    return [confirmation(facts), shipped(facts, shipment), tracking(facts, shipment, "in transit")]


def email(facts: dict, shipment: dict, owner_email: Any) -> Optional[dict]:
    """{to, subject, body} for the owner's own address, or None when there is no plain address to send to."""
    if not isinstance(owner_email, str) or not _EMAIL.fullmatch(owner_email.strip()):
        return None
    body = "\n".join([
        f"What you ordered: {facts['item']} from {facts['seller']}",
        f"Total paid: {_money(facts['amount'])} before tax ({_pay_note(facts.get('payment_mode'))})",
        f"Order: {facts['order_id']}",
        f"Expected delivery: {shipment['eta']} (SIM estimate)",
        f"Tracking: {shipment['carrier']} {shipment['tracking']} (SIM carrier data, no real shipment)",
        "",
        "Sent by your Tech Bazaar buyer agent to your own address. Nothing in this email asks you for a code or a card.",
    ])
    return {"to": owner_email.strip(), "subject": f"Tech Bazaar order {facts['order_id']}: {facts['item']}", "body": body}


def deliver(facts: dict, shipment: dict, *, tell_owner: Callable[[str], Any], owner_email: Any = None,
            send_email: Optional[Callable[[dict], Any]] = None) -> dict:
    """Send the three chat lines, then try the email. The chat always goes out; a missing address, no sender or a
    failing sender gives one more chat line saying the email was not sent and why. {sent: [...], email: state}."""
    sent = []
    for line in messages(facts, shipment):
        tell_owner(line)
        sent.append(line)
    mail = email(facts, shipment, owner_email)
    if mail is None:
        state = "not_sent: no owner email address set"
    elif send_email is None:
        state = "not_sent: no email sender configured"
    else:
        try:
            ok = send_email(mail)
            state = "sent" if ok is True else f"not_sent: {ok or 'the sender refused'}"
        except Exception as e:  # noqa: BLE001  (a connector down or a timeout: the chat lines already went out)
            state = f"not_sent: {type(e).__name__}"
    if state != "sent":
        note = f"The order email was not sent ({state.split(': ', 1)[1]}). These chat messages are your record."
        tell_owner(note)
        sent.append(note)
    return {"sent": sent, "email": state}


if __name__ == "__main__":   # a local look at the three lines and the email for a SIM order (no network, no email sent)
    demo = {"order_id": "ord-sim-1", "item": "RTX 5070 Ti", "seller": "Best Buy", "amount": 1299.99, "payment_mode": "sim",
            "mandate_hash": "7fe6783ca5c94c92"}
    ship = sim_shipment(demo)
    deliver(demo, ship, tell_owner=print, owner_email="owner@example.test")
