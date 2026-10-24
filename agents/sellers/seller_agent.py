"""One seller uAgent. Run from agents/: python sellers/seller_agent.py seller_1"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for common
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for policy

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.payment import CommitPayment, CompletePayment, RejectPayment, payment_protocol_spec

import common
import payment
from agents.buyer import checkout, state
from pay.mandate import mandate_hash
from pay.replay import NonceStore
from policy import make_bid, seller as load_seller
from shield.receipt import parse_unique_json

PORTS = {"seller_1": 8011, "seller_2": 8012, "seller_3": 8013}
_CHARGE_ID = re.compile(r"(?:pi|ch)_[A-Za-z0-9_]{1,128}\Z")


def _read_transaction(db_path, deal_id: str, buyer_id: str) -> dict | None:
    db = state.open_state(db_path)
    try:
        return state.load_transaction(db, deal_id, buyer_id)
    finally:
        db.close()


def _read_attempt_and_transaction(db_path, mandate_hash_value: str):
    db = state.open_state(db_path)  # validate/protect the shared file before opening its D ledger
    try:
        store = NonceStore(str(db_path))
        try:
            attempt = store.get_payment_attempt(mandate_hash_value)
        finally:
            store._db.close()
        if not isinstance(attempt, dict):
            return None, None
        transaction = state.load_transaction(db, attempt.get("deal_id"), attempt.get("buyer_id"))
        return transaction, attempt
    finally:
        db.close()


def _valid_charge_binding(transaction, attempt, message, seller_address: str) -> bool:
    if not isinstance(transaction, dict) or not isinstance(attempt, dict):
        return False
    mandate = transaction.get("mandate")
    deal = transaction.get("deal")
    order = transaction.get("order")
    if (transaction.get("phase") not in ("submitted", "settled")
            or not isinstance(mandate, dict) or not isinstance(deal, dict) or not isinstance(order, dict)):
        return False
    try:
        valid_hash = mandate_hash(mandate) == mandate.get("hash")
    except (TypeError, ValueError, KeyError):
        valid_hash = False
    mandate_hash_value = mandate.get("hash")
    if (not valid_hash or not isinstance(mandate_hash_value, str)
            or mandate.get("status") != "approved" or not mandate.get("approval_id")
            or mandate.get("origin") != "SIM" or mandate.get("payee") != seller_address
            or transaction.get("deal_id") != mandate.get("deal_id")
            or transaction.get("buyer_id") != mandate.get("buyer_id")
            or transaction.get("goal_id") != mandate.get("goal_id")
            or deal.get("id") != transaction.get("deal_id")
            or deal.get("goal_id") != transaction.get("goal_id")
            or deal.get("need_id") != transaction.get("need_id")
            or deal.get("bid_id") != transaction.get("bid_id")
            or deal.get("payee") != seller_address
            or order.get("id") != deal.get("id") or order.get("need_id") != deal.get("need_id")
            or order.get("bid_id") != deal.get("bid_id")
            or payment._cents(deal.get("amount")) != payment._cents(mandate.get("amount"))
            or payment._cents(order.get("amount")) != payment._cents(mandate.get("amount"))):
        return False

    request = payment.payment_request(mandate, recipient=seller_address)
    body = request.model_dump_json().encode("utf-8")
    request_sha256 = hashlib.sha256(body).hexdigest()
    message_id = "req:" + hashlib.sha256(transaction["buyer_id"].encode("utf-8") + b"\n" + body).hexdigest()
    cents = payment._cents(mandate.get("amount"))
    charge_id = attempt.get("charge_id")
    if (attempt.get("phase") != "charged" or attempt.get("mandate_hash") != mandate_hash_value
            or attempt.get("buyer_id") != transaction.get("buyer_id")
            or attempt.get("deal_id") != transaction.get("deal_id")
            or attempt.get("request_sha256") != request_sha256 or attempt.get("message_id") != message_id
            or attempt.get("amount_cents") != cents or attempt.get("currency") != mandate.get("currency")
            or attempt.get("payee") != seller_address
            or attempt.get("idempotency_key") != "mandate:" + mandate_hash_value
            or not isinstance(attempt.get("receipt_keyid"), str)
            or not attempt["receipt_keyid"] or attempt["receipt_keyid"] == "not-submitted"
            or not isinstance(charge_id, str) or not _CHARGE_ID.fullmatch(charge_id)):
        return False

    settlement = transaction.get("settlement")
    result = transaction.get("settlement_result")
    if not isinstance(settlement, dict) or not isinstance(result, dict):
        return False
    exact_settlement = {"message_id": message_id, "request_sha256": request_sha256,
        "mandate_hash": mandate_hash_value, "deal_id": transaction["deal_id"],
        "buyer_id": transaction["buyer_id"], "amount_cents": cents,
        "currency": mandate["currency"], "payee": seller_address,
        "idempotency_key": "mandate:" + mandate_hash_value, "receipt_keyid": attempt["receipt_keyid"]}
    settlement_keys = set(exact_settlement)
    if set(settlement) == settlement_keys | {"mode"}:
        mode = settlement.get("mode")
        if mode not in ("SIM", "stripe_test") or mode != transaction.get("mode"):
            return False
        exact_settlement["mode"] = mode
    elif set(settlement) != settlement_keys:
        return False
    if any(settlement.get(key) != value for key, value in exact_settlement.items()):
        return False
    if (set(result) != {"status", "reason", "charge_id", "mandate_hash", "origin"}
            or result.get("status") != "charged" or result.get("origin") != "SIM"
            or result.get("mandate_hash") != mandate_hash_value or result.get("charge_id") != charge_id
            or transaction.get("payment_ref") != charge_id):
        return False

    funds = getattr(message, "funds", None)
    return (getattr(message, "transaction_id", None) == charge_id
            and getattr(message, "reference", None) == mandate_hash_value
            and getattr(message, "recipient", None) == seller_address
            and getattr(message, "description", None) == request.description
            and getattr(funds, "currency", None) == mandate.get("currency") == "USD"
            and getattr(funds, "payment_method", None) == "stripe"
            and payment._cents(getattr(funds, "amount", None)) == cents)


def persona_line(s: dict, total: float) -> str:
    fallback = f"{s['name']} here: ${total:,.2f} all in, {s['claims'][0]}."
    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback
    try:
        import anthropic
        msg = anthropic.Anthropic(timeout=5).messages.create(
            model="claude-haiku-5-5", max_tokens=40,
            messages=[{"role": "user", "content":
                       f"You are {s['name']}, a {s['archetype']}, bidding at a PC parts auction. "
                       f"Your bid total is ${total:,.2f}. Say one short in-character line. "
                       f"Do not state any price or number other than ${total:,.2f}."}])
        text = msg.content[0].text.strip().splitlines()[0]
        prices = re.findall(r"\$\s?([\d,]+(?:\.\d+)?)", text)
        if not text or any(abs(float(p.replace(",", "")) - total) > 0.005 for p in prices):
            return fallback
        return text
    except Exception:
        return fallback


def build(name: str) -> Agent:
    s = load_seller(name)
    port = PORTS[name]
    agent = Agent(**common.agent_args(
        name, port, name=s['name'][:32], handle=f"techbazaar{name.replace('_', '')}",
        readme_path=str(Path(__file__).with_name(f"AGENTVERSE-{name}.md")),
        description=f"Seller agent ({s['archetype']}) that bids in Tech Bazaar's sealed rounds for computer gear. "
                    "Prices come from policy code, never below its floor. Listings are simulated (SIM)."))
    common.include_profile_chat(agent, f"I am {s['name']}, a Tech Bazaar SIM seller. I bid on structured sealed "
                                "rounds using policy prices. Send buying goals to @techbazaarbuyer; "
                                "this chat cannot place orders or approve purchases.")

    @agent.on_message(model=common.BidRequest)
    async def on_bid_request(ctx: Context, sender: str, msg: common.BidRequest):
        verdict = common.screen(f"bidreq-{name}-{ctx.session}", sender, msg.need_json,
                                common.shield_context(sender, payee_of_record=agent.address))
        if verdict["verdict"] != "allow":
            ctx.logger.warning(f"ignored BidRequest from {sender}: {verdict['reasons']}")
            return
        bid = make_bid(json.loads(msg.need_json), s)
        if bid is None:
            return
        common.validate("Bid", bid)
        await ctx.send(sender, common.BidReply(bid_json=json.dumps(bid),
                                               persona_line=persona_line(s, bid["total_landed_price"])))

    pay = Protocol(spec=payment_protocol_spec, role="seller")

    @agent.on_message(model=common.OrderPlaced)
    async def on_order(ctx: Context, sender: str, msg: common.OrderPlaced):
        if sender != common.address("buyer"):
            ctx.logger.warning("ignored OrderPlaced from unregistered buyer")
            return
        verdict = common.screen(f"order-{name}-{ctx.session}", sender, msg.order_json + "\n" + msg.mandate_json,
                                common.shield_context(sender, payee_of_record=agent.address))
        if verdict["verdict"] != "allow":
            ctx.logger.warning("ignored OrderPlaced blocked by Shield")
            return
        try:
            order = common.validate("Order", parse_unique_json(msg.order_json))
            mandate = common.validate("Mandate", parse_unique_json(msg.mandate_json))
            if (mandate.get("origin") != "SIM" or mandate.get("payee") != agent.address
                    or mandate.get("deal_id") != order.get("id")):
                raise PermissionError
            stored = _read_transaction(state.DEFAULT_DB_PATH, mandate["deal_id"], mandate["buyer_id"])
            if stored is None:
                raise PermissionError
            tx, stored_mandate, deal = checkout._bound_transaction(stored, approval_phase=False)
            if (tx.get("phase") not in ("approved", "submitted") or tx.get("order") != order
                    or stored_mandate != mandate or deal.get("payee") != agent.address
                    or (isinstance(tx.get("settlement_result"), dict)
                        and tx["settlement_result"].get("status") == "charged")):
                raise PermissionError
            request = payment.payment_request(stored_mandate, recipient=agent.address)
        except Exception:
            ctx.logger.warning("ignored OrderPlaced without a matching fresh approved local transaction")
            return
        ctx.logger.info("trusted order received; sending its exact payment request")
        await ctx.send(sender, request)

    @pay.on_message(CommitPayment)
    async def on_commit(ctx: Context, sender: str, msg: CommitPayment):
        if sender != common.address("buyer"):
            ctx.logger.warning("ignored CommitPayment from unregistered buyer")
            return
        verdict = common.screen(f"commit-{name}-{ctx.session}", sender, msg.model_dump_json(),
                                common.shield_context(sender, payee_of_record=agent.address))
        if verdict["verdict"] != "allow":
            ctx.logger.warning("ignored CommitPayment blocked by Shield")
            return
        try:
            mandate_hash_value = msg.reference
            if not isinstance(mandate_hash_value, str) or not re.fullmatch(r"[0-9a-f]{64}", mandate_hash_value):
                raise PermissionError
            tx, attempt = _read_attempt_and_transaction(state.DEFAULT_DB_PATH, mandate_hash_value)
            if not _valid_charge_binding(tx, attempt, msg, agent.address):
                raise PermissionError
            transaction_id = attempt["charge_id"]
        except Exception:
            ctx.logger.warning("ignored CommitPayment without a matching local charged attempt")
            return
        ctx.logger.info("matching local SIM charge confirmed; sending completion")
        await ctx.send(sender, CompletePayment(transaction_id=transaction_id))

    @pay.on_message(RejectPayment)
    async def on_reject(ctx: Context, sender: str, msg: RejectPayment):
        if sender != common.address("buyer"):
            ctx.logger.warning("ignored RejectPayment from unregistered buyer")
            return
        verdict = common.screen(f"reject-{name}-{ctx.session}", sender, msg.model_dump_json(),
                                common.shield_context(sender, payee_of_record=agent.address))
        if verdict["verdict"] != "allow":
            ctx.logger.warning("ignored RejectPayment blocked by Shield")
            return
        ctx.logger.warning("buyer rejected payment; no completion sent")

    agent.include(pay, publish_manifest=True)
    return agent


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "seller_1"
    a = build(name)
    print(f"{name} address:", a.address)
    a.run()
