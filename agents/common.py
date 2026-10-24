"""Shared bits for every Lane A agent: contract checks, Shield screening, wire messages, agent seeds."""
import json
import os
import time
import urllib.request
from pathlib import Path

from jsonschema import Draft202012Validator
from uagents import Model
from uagents.crypto import Identity

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"


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


# Deterministic seeds so addresses are stable across restarts. Override in .env for the real deploy.
SEEDS = {
    "buyer": os.getenv("BUYER_AGENT_SEED", "bidding-royale-buyer-dev"),
    "advocate": os.getenv("ADVOCATE_AGENT_SEED", "bidding-royale-advocate-dev"),
    "supplier": os.getenv("SUPPLIER_AGENT_SEED", "bidding-royale-supplier-dev"),
}


def address(role: str) -> str:
    return Identity.from_seed(SEEDS[role], 0).address
