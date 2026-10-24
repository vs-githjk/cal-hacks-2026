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


def screen(message_id: str, sender: str, text: str) -> dict:
    """Invariant 3: every agent-to-agent message goes through Shield before we act on it.
    Calls Lane D at SHIELD_URL. With no SHIELD_URL set, returns an allow verdict labelled as a stub."""
    url = os.getenv("SHIELD_URL")
    if not url:
        # ponytail: stub until Lane D's /screen is up; set SHIELD_URL to go live
        return {"message_id": message_id, "sender_agent": sender, "verdict": "allow",
                "reasons": ["shield stub: SHIELD_URL not set"], "attack_type": "none", "latency_ms": 0}
    start = time.monotonic()
    req = urllib.request.Request(f"{url.rstrip('/')}/screen", method="POST",
                                 data=json.dumps({"message_id": message_id, "sender_agent": sender, "text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1.5) as r:
            return json.loads(r.read())
    except Exception as e:  # fail closed: if Shield is down we do not act on the message
        return {"message_id": message_id, "sender_agent": sender, "verdict": "block",
                "reasons": [f"shield unreachable: {e}"], "attack_type": "unknown",
                "latency_ms": (time.monotonic() - start) * 1000}


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
