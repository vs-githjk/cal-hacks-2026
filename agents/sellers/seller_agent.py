"""One seller uAgent. Run from agents/: python sellers/seller_agent.py seller_1
A custom seller from the Seller Kit runs from its config: python sellers/seller_agent.py --config sellers/custom/<id>.json"""
import argparse
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
import market_env_check
import payment
from factory import load_config, pick_port, seller_from_config
from market_bridge import MarketBridge
from agents.buyer import checkout, state
from agents.sellers import learning, mind_store, minds, mirror_live, seller_chat
from pay.mandate import mandate_hash
from pay.replay import NonceStore
from policy import make_bid, mirror_seller, seller as load_seller
from data.mirror import not_partners
from shield.receipt import parse_unique_json

_CHARGE_ID = re.compile(r"(?:pi|ch)_[A-Za-z0-9_]{1,128}\Z")
_MARKET_SELLER_SUBJECT = {"seller_1": "seller-a", "seller_2": "seller-b", "seller_3": "seller-c"}
# #342: built-in MIRROR sellers and the real store whose dated listings each one bids. Never a partner, never paid.
MIRROR_SOURCES = {"seller_6": "central_computers_sf"}
MIRROR_NAMES = {"seller_6": "Central Comp MIRROR"}  # display name under 20 characters (#259), never the bare store name


def _mirror_for(name: str, need: dict | None = None) -> dict | None:
    """The MIRROR seller dict for a built-in MIRROR agent, under its own agent id (the buyer checks the sender's id).
    The buyer's case clearance, when the need carries it, picks the card that fits; None when no card can be bid."""
    owned = (need or {}).get("owned") if isinstance(need, dict) else None
    clearance = ((owned or {}).get("case") or {}).get("max_gpu_length_mm") if isinstance(owned, dict) else None
    if isinstance(clearance, bool) or not isinstance(clearance, (int, float)):
        clearance = None
    s = mirror_seller(MIRROR_SOURCES[name], clearance)
    return None if s is None else {**s, "id": name, "orderable": False}


def _mirror_persona(s: dict, total: float, anchor: dict | None = None) -> str:
    """Fixed text for a MIRROR seller: never a model speaking in character as a real store."""
    return (f"{s['mirror_label']} Listed at ${total:,.2f}, shown for comparison."
            + (f" {anchor['label']}" if anchor else ""))


def _learned_price_step(name: str, db_path=None) -> float:
    seller_id = _MARKET_SELLER_SUBJECT.get(name)
    if seller_id is None:
        return 0.0  # sellers 4, 5 and Seller Kit sellers have no Market identity yet, so no loss reports to learn from
    token_file = os.environ.get(f"SPACETIMEDB_{seller_id.replace('-', '_').upper()}_TOKEN_FILE")
    try:
        market = MarketBridge("seller", token_file=token_file) if token_file else None
    except Exception:
        market = None

    db = learning.open_learning_state(db_path or state.DEFAULT_DB_PATH)
    try:
        mind = None
        if minds.is_stateful(name):  # Byte Bros learns its margin, Frankie learns which trick got caught
            mind_store.ensure(db)
            mind = minds.load(db, name)
        if market is not None:
            try:
                reports = market.my_loss_reports()
            except Exception:
                reports = []
            if isinstance(reports, list):
                for report in reports:
                    try:
                        applied = learning.apply_loss(db, report, seller_id)
                    except (TypeError, ValueError):
                        continue
                    if applied is not None and mind is not None:  # a new, valid loss report: the mind learns from it once
                        minds.observe_loss(name, mind, report, seller_id)
        if mind is not None:
            minds.save(db, name, mind)
            if name == "seller_1":
                return mind["cut"]  # the learner's own margin step replaces the one-way price_step ratchet
        return learning.load_strategy(db, seller_id)["price_step"]
    finally:
        db.close()


def _apply_mind(name: str, need: dict, bid: dict, s: dict, db_path=None) -> tuple[dict, str | None]:
    """The seller's mind applied to its built bid (strategy note, trick, tradeoff) and the floor line it says, or None for
    the default line. State is saved here; a state file that will not load fails the bid closed, like learning does."""
    if name not in minds.KINDS:
        return bid, None
    if not minds.is_stateful(name):
        return minds.apply_to_bid(name, need, bid, s, None)
    db = mind_store.open_store(db_path or state.DEFAULT_DB_PATH)
    try:
        mind = minds.load(db, name)
        out, line = minds.apply_to_bid(name, need, bid, s, mind)
        minds.save(db, name, mind)
        return out, line
    finally:
        db.close()


def _record_win(name: str, need_id, db_path=None) -> None:
    """A trusted order reached this agent: tell its mind it won that round. Best effort, never blocks the payment path."""
    if not minds.is_stateful(name) or not isinstance(need_id, str):
        return
    db = mind_store.open_store(db_path or state.DEFAULT_DB_PATH)
    try:
        mind = minds.load(db, name)
        minds.observe_order(name, mind, need_id)
        minds.save(db, name, mind)
    finally:
        db.close()


def _make_bid_with_learning(need: dict, seller: dict, name: str, db_path=None) -> dict | None:
    price_step = _learned_price_step(name, db_path)
    bid_seller = seller
    base_discount = seller.get("discount")
    if (need.get("source") not in ("live", "mirror") and isinstance(base_discount, (int, float))
            and not isinstance(base_discount, bool) and 0 <= base_discount < 1):
        bid_seller = dict(seller)
        bid_seller["discount"] = 1 - (1 - base_discount) * (1 - price_step)
    return make_bid(need, bid_seller)


def _market_bid(bid: dict, seller: dict) -> None:
    subject = _MARKET_SELLER_SUBJECT.get(bid["supplier_id"])
    if subject is None:
        return  # no Market identity for this seller (sellers 4, 5, Seller Kit): the bid goes to the buyer only
    token_var = f"SPACETIMEDB_{subject.replace('-', '_').upper()}_TOKEN_FILE"
    token_file = os.environ.get(token_var)
    if not token_file:
        raise ValueError(f"seller Market identity is not configured: set {token_var}")
    market = MarketBridge("seller", token_file=token_file)
    metadata = []
    for index, line in enumerate(bid["lines"]):
        origin = line.get("origin", bid["origin"])
        source = line.get("source", bid["source"])
        listing_id = line.get("listing_id") or line.get("listing_url")
        if not isinstance(listing_id, str) or not listing_id or not isinstance(source, str) or not source:
            raise ValueError("listing evidence is incomplete")
        listing_hash = hashlib.sha256(json.dumps(line, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        metadata.append({"lineIndex": index,
                         "shipping": line.get("shipping", seller["shipping"] if origin == "SIM" and index == 0 else 0.0),
                         "listingId": listing_id, "listingHash": listing_hash, "source": source,
                         "snapshotId": line.get("snapshot_id", bid.get("mirror_snapshot_id", "")),
                         "provenance": {"origin": origin, "source": source,
                                        **({"seller_of_record": line["seller_of_record"]}
                                           if isinstance(line.get("seller_of_record"), str) else {}),
                                        **({"listing_url": line["listing_url"]}
                                           if isinstance(line.get("listing_url"), str)
                                           and len(line["listing_url"]) <= 512 else {})},
                         "attrs": line.get("attrs", {})})
    market.publish_bid(bid_id=bid["id"], round_id=f"round-{bid['need_id']}", seller_id=subject,
                       persona=bid["persona"], lines=bid["lines"], line_metadata=metadata,
                       stated_total=bid["total_landed_price"], perks=bid["perks"], claims=bid["claims"],
                       origin=bid["origin"], source=bid["source"])


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
    fallback = f"{s['name']} here: ${total:,.2f} all in" + (f", {s['claims'][0]}." if s["claims"] else ".")
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


def build(name: str, cfg: dict | None = None) -> Agent:
    """A catalog seller by name, or a custom seller from a validated SellerConfig `cfg` (name is then cfg["id"])."""
    loud = market_env_check.seller_line(name, os.environ) if cfg is None else None  # Maincloud: a missing token file is loud
    if loud:
        print(loud, file=sys.stderr, flush=True)
    mirror = cfg is None and name in MIRROR_SOURCES
    if mirror:
        if name not in common.SEEDS:  # no default seed: a guessable key must never sign as this agent
            raise SystemExit(f"{name} is off: set {name.upper()}_AGENT_SEED in agents/.env to a private seed of "
                             f"{common.MIN_PRIVATE_SEED}+ characters (never committed).")
        s = _mirror_for(name)
        if s is None:
            raise SystemExit(f"{name} has no listing it may bid.")
        port = common.SELLER_PORTS[name]
        profile = {"readme_path": str(Path(__file__).with_name(f"AGENTVERSE-{name}.md")),
                   "handle": f"techbazaar{name.replace('_', '')}"}
    elif cfg is None:
        s = load_seller(name)
        port = common.SELLER_PORTS[name]
        profile = {"readme_path": str(Path(__file__).with_name(f"AGENTVERSE-{name}.md")),
                   "handle": f"techbazaar{name.replace('_', '')}"}
    else:
        s = seller_from_config(cfg)
        name = s["id"]
        common.register_custom_seller(name)
        port = pick_port(cfg)
        profile = {}  # a custom seller has no Agentverse profile page until its owner writes one
    origin = s.get("origin", "SIM")
    # a real store that never joined: no money path may treat this agent as a payee (#333, #342)
    not_orderable = not not_partners.orderable({"supplier_id": name, **({"orderable": False} if mirror else {})})
    if mirror:
        agent = Agent(**common.agent_args(
            name, port, name=MIRROR_NAMES[name], **profile,
            description=f"Fish Market MIRROR agent that bids {s['name']} public listings at their listed price. "
                        f"{s['mirror_label']} Shown for comparison, cannot be bought here."))
        common.include_profile_chat(agent, f"I am Fish Market's MIRROR agent for {s['name']} listings, not the store. "
                                    f"{s['mirror_label']} My bids are shown for comparison and cannot be bought "
                                    "here. Send buying goals to @techbazaarbuyer.",
                                    answer=seller_chat.responder(name, lambda: state.DEFAULT_DB_PATH))
    else:
        labelled = "simulated (SIM)" if origin == "SIM" else "LIVE, owner supplied"
        agent = Agent(**common.agent_args(
            name, port, name=s['name'][:32], **profile,
            description=f"Seller agent ({s['archetype']}) that bids in Fish Market's sealed rounds for computer gear. "
                        f"Prices come from policy code, never below its floor. Listings are {labelled}."))
        role_text = (f"I am {s['name']}, a Fish Market {origin} seller. I bid on structured "
                     "sealed rounds using policy prices. Send buying goals to @techbazaarbuyer; "
                     "this chat cannot place orders or approve purchases.")
        if cfg is None and name in minds.KINDS:  # the four named sellers answer in character; a custom seller keeps the fixed text
            common.include_profile_chat(agent, role_text, answer=seller_chat.responder(name, lambda: state.DEFAULT_DB_PATH))
        else:
            common.include_profile_chat(agent, role_text)

    @agent.on_message(model=common.BidRequest)
    async def on_bid_request(ctx: Context, sender: str, msg: common.BidRequest):
        verdict = common.screen(f"bidreq-{name}-{ctx.session}", sender, msg.need_json,
                                common.shield_context(sender, payee_of_record=agent.address))
        if verdict["verdict"] != "allow":
            ctx.logger.warning(f"ignored BidRequest from {sender}: {verdict['reasons']}")
            return
        need = json.loads(msg.need_json)
        mind_line = None
        try:
            if mirror:  # the real listing as a price anchor, re-checked now (Bright Data) or the dated snapshot
                s_bid = _mirror_for(name, need)
                if s_bid and any(str(i.get("sku_spec", "")).lower() == mirror_live.cc.SKU for i in need.get("items", [])):
                    s_bid, anchor = await mirror_live.refresh_async(s_bid)
                    bid = mirror_live.annotate(make_bid(need, s_bid), anchor) if s_bid else None
                    if bid is None:
                        ctx.logger.warning(f"MIRROR no bid: {anchor['label']}")
                else:
                    bid = make_bid(need, s_bid) if s_bid else None
            else:
                bid = _make_bid_with_learning(need, s, name)
                if bid is not None:
                    bid, mind_line = _apply_mind(name, need, bid, s)
        except Exception as exc:
            ctx.logger.warning(f"seller learning unavailable: {type(exc).__name__}")
            return
        if bid is None:
            return
        common.validate("Bid", bid)
        try:
            _market_bid(bid, s)
        except Exception as exc:
            ctx.logger.warning(f"Market bid publication failed: {type(exc).__name__}: {str(exc)[:200]}")
            return
        seller_chat.remember_bid(name, bid)  # the Advocate may ask about this bid's condition; answer from what was bid
        line = (_mirror_persona(s, bid["total_landed_price"], bid.get("price_anchor")) if mirror
                else mind_line or persona_line(s, bid["total_landed_price"]))
        await ctx.send(sender, common.BidReply(bid_json=json.dumps(bid), persona_line=line))

    pay = Protocol(spec=payment_protocol_spec, role="seller")

    @agent.on_message(model=common.OrderPlaced)
    async def on_order(ctx: Context, sender: str, msg: common.OrderPlaced):
        if not_orderable:
            ctx.logger.warning("ignored OrderPlaced: MIRROR seller for a store that never joined, never ordered")
            return
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
        try:
            _record_win(name, order.get("need_id"))  # this round was won: the mind learns it
        except Exception as exc:
            ctx.logger.warning(f"seller mind could not record the win: {type(exc).__name__}")
        await ctx.send(sender, request)

    @pay.on_message(CommitPayment)
    async def on_commit(ctx: Context, sender: str, msg: CommitPayment):
        if not_orderable:
            ctx.logger.warning("ignored CommitPayment: MIRROR seller for a store that never joined, never paid")
            return
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
    ap = argparse.ArgumentParser(description="Run one Fish Market seller agent")
    ap.add_argument("name", nargs="?", default="seller_1", help="a catalog seller (seller_1 to seller_5) or seller_6 (MIRROR)")
    ap.add_argument("--config", help="path to a SellerConfig JSON file (custom seller); overrides name")
    args = ap.parse_args()
    common.require_peer_seeds(args.name if not args.config else "seller")   # #449 RT-27: production mode needs the buyer's private seed
    if args.config:
        try:
            cfg = load_config(args.config)
        except ValueError as e:
            sys.exit(f"Seller config refused: {e}")
        a, name = build(cfg["id"], cfg), cfg["id"]
    else:
        a, name = build(args.name), args.name
    print(f"{name} address:", a.address)
    a.run()
