"""Shared bits for every Lane A agent: contract checks, Shield screening, wire messages, agent seeds."""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from jsonschema import Draft202012Validator
from uagents import Model, Protocol
from uagents.crypto import Identity
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
sys.path.insert(0, str(ROOT))  # so agents can import other lanes' code, e.g. `from data.fit_checker import check_fit`

# Load agents/.env (gitignored) without overriding real environment variables. Empty values are skipped.
_ENV = Path(__file__).resolve().parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _k, _, _v = _line.partition("=")
        if _k.strip() and not _k.lstrip().startswith("#") and _v.strip():
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


def validate(contract: str, obj: dict) -> dict:
    """Raise if obj breaks contracts/<contract>.schema.json; return obj."""
    schema = json.loads((CONTRACTS / f"{contract}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(obj)
    return obj


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_shield(req, timeout: float):
    return urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout)


def shield_context(sender: str, payee_of_record: str | None = None, price_history=None) -> dict:
    """Build Shield context from known agent identities and trusted local reference data."""
    roles = {address("buyer"): "buyer", address("advocate"): "advocate",
             **{address(name): "seller" for name in SELLERS}}
    role = roles.get(sender, "unknown")
    return {"payee_of_record": payee_of_record or (sender if role == "seller" else None),
            "price_history": list(price_history or []),
            "sender_role": role}


def screen(message_id: str, sender: str, text: str, context: dict | None = None) -> dict:
    """Invariant 3: every agent-to-agent message goes through Shield before we act on it.
    Calls Lane D at SHIELD_URL and fails closed when Shield is unavailable."""
    context = context or shield_context(sender)
    if not isinstance(context, dict) or not {"payee_of_record", "price_history", "sender_role"} <= context.keys():
        context = shield_context(sender)
    url = os.getenv("SHIELD_URL")
    if not url:
        return {"message_id": message_id, "sender_agent": sender, "verdict": "block",
                "reasons": ["shield.unavailable"], "attack_type": "unknown", "latency_ms": 0}
    start = time.monotonic()
    req = urllib.request.Request(f"{url.rstrip('/')}/screen", method="POST",
                                 data=json.dumps({"message_id": message_id, "sender_agent": sender, "text": text,
                                                  "context": context}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with _open_shield(req, timeout=1.5) as r:
            if r.status != 200:
                raise ValueError("non-200 Shield response")
            result = json.loads(r.read())
            if not isinstance(result, dict) or result.get("verdict") not in {"allow", "quarantine", "block"}:
                raise ValueError("invalid Shield verdict")
            rules = result.get("rule_ids", [])
            if not isinstance(rules, list) or any(not isinstance(rule, str) for rule in rules):
                raise ValueError("invalid Shield rule ids")
            reasons = result.get("reasons", rules)
            if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
                raise ValueError("invalid Shield reasons")
            result["reasons"] = reasons
            result["rule_ids"] = rules or reasons
            result.setdefault("message_id", message_id)
            result.setdefault("sender_agent", sender)
            result.setdefault("attack_type", "unknown")
            result.setdefault("latency_ms", (time.monotonic() - start) * 1000)
            record = str(context.get("payee_of_record") or "").strip().lower()
            if record and result["verdict"] == "allow" and _structured_payee_mismatch(text, record):
                result.update(verdict="quarantine", reasons=["shield.payee.swap"],
                              rule_ids=["shield.payee.swap"], attack_type="payee_swap")
            return result
    except Exception:  # fail closed without echoing response bodies or transport details
        return {"message_id": message_id, "sender_agent": sender, "verdict": "block",
                "reasons": ["shield.unavailable"], "attack_type": "unknown",
                "latency_ms": (time.monotonic() - start) * 1000}


def _structured_payee_mismatch(text: str, record: str) -> bool:
    decoder = json.JSONDecoder()
    pos = 0
    while (start := text.find("{", pos)) >= 0:
        try:
            obj, end = decoder.raw_decode(text[start:])
        except ValueError:
            pos = start + 1
            continue
        pos = start + end
        objects = [obj]
        if isinstance(obj, dict) and isinstance(obj.get("mandate"), dict):
            objects.append(obj["mandate"])
        for item in objects:
            if not isinstance(item, dict):
                continue
            for key in ("payee", "recipient"):
                value = item.get(key)
                if isinstance(value, str) and value.strip().lower() != record:
                    return True
    return False


def screen_bid(message_id: str, sender: str, bid_json: str, persona_line: str, references: dict) -> dict:
    """Screen a seller bid as a whole, then check each SKU against only its own trusted SIM baseline."""
    try:
        payload = json.loads(bid_json)
        lines = payload["lines"]
        if not isinstance(lines, list) or any(not isinstance(line, dict) for line in lines):
            raise ValueError
    except (TypeError, ValueError, KeyError):
        return {"message_id": message_id, "sender_agent": sender, "verdict": "block",
                "reasons": ["shield.invalid_message"], "rule_ids": ["shield.invalid_message"],
                "attack_type": "unknown", "latency_ms": 0}
    context = shield_context(sender)
    skus = {str(line.get("sku_spec", "")).strip().lower() for line in lines}
    if len(skus) == 1:
        reference = references.get(next(iter(skus)))
        if reference:
            context["price_history"] = [reference["unit_price"]]
    result = screen(message_id, sender, bid_json + "\n" + persona_line, context)
    if result.get("verdict") != "allow":
        return result
    if len(skus) <= 1:
        return result
    shared = {key: value for key, value in payload.items() if key != "lines"}
    for sku in sorted(skus):
        reference = references.get(sku)
        line_context = dict(context, price_history=[reference["unit_price"]] if reference else [])
        related = dict(shared, lines=[line for line in lines if str(line.get("sku_spec", "")).strip().lower() == sku])
        result = screen(message_id, sender, json.dumps(related) + "\n" + persona_line, line_context)
        if result.get("verdict") != "allow":
            return result
    return result


# Wire messages between our agents. Payloads are contract objects serialized as JSON strings.
class BidRequest(Model):
    need_json: str  # Need, with spend_limit removed (sealed: suppliers never see it)


class BidReply(Model):
    bid_json: str  # Bid
    persona_line: str  # one line the persona says on the floor


class AdviceRequest(Model):
    need_json: str
    bids_json: str  # list of Bid


class AdviceReply(Model):
    cards_json: str  # list of AdvocateCard


class OrderPlaced(Model):
    """Buyer -> winning seller: the order is approved; ask for payment against this mandate (Payment Protocol)."""
    order_json: str  # Order
    mandate_json: str  # payment.make_mandate(...) dict


# Deterministic seeds so addresses are stable across restarts. Override in .env for the real deploy.
SELLERS = ["seller_1", "seller_2", "seller_3"]  # three named seller agents, each its own uAgent
SEEDS = {
    "buyer": os.getenv("BUYER_AGENT_SEED", "tech-bazaar-buyer-dev"),
    "advocate": os.getenv("ADVOCATE_AGENT_SEED") or os.getenv("ADVOCATE_SEED", "tech-bazaar-advocate-dev"),
    "shield": os.getenv("SHIELD_AGENT_SEED") or os.getenv("SHIELD_SEED", "tech-bazaar-shield-dev"),
    **{s: os.getenv(f"{s.upper()}_AGENT_SEED") or os.getenv(f"{s.upper()}_SEED", f"tech-bazaar-{s}-dev")
       for s in SELLERS},
}


def public_seed(role: str) -> bool:
    """The dev defaults above are in the public repo, so anyone could sign as that agent.
    Never put an agent on Agentverse with one; set <ROLE>_AGENT_SEED in agents/.env first."""
    return SEEDS[role].endswith("-dev")


def agent_args(role: str, port: int, **profile) -> dict:
    """Constructor args for an agent. AGENTS_MAILBOX=1 puts it on Agentverse (register once with
    `python connect.py <port>`); otherwise it listens on localhost. `profile`: name, description,
    readme_path, handle, published to Agentverse on connect."""
    args = dict(seed=SEEDS[role], port=port, publish_agent_details=True, **profile)
    mailbox_flag = "SELLERS_MAILBOX" if role in SELLERS else f"{role.upper()}_MAILBOX"
    if os.getenv("AGENTS_MAILBOX") or os.getenv(mailbox_flag):
        if public_seed(role):
            sys.exit(f"Set {role.upper()}_AGENT_SEED in agents/.env before going on Agentverse: the default seed is public.")
        return {**args, "mailbox": True}
    return {**args, "endpoint": [f"http://localhost:{port}/submit"]}


def address(role: str) -> str:
    return Identity.from_seed(SEEDS[role], 0).address


def include_profile_chat(agent, role_text: str):
    """Discoverability chat explains the role; structured protocols do the work."""
    chat = Protocol(spec=chat_protocol_spec)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx, sender: str, msg: ChatMessage):
        verdict = screen(str(msg.msg_id), sender, msg.text())
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        text = role_text if verdict.get("verdict") == "allow" else "Shield blocked this message. No action taken."
        await ctx.send(sender, ChatMessage(content=[TextContent(text=text)]))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(chat, publish_manifest=True)
