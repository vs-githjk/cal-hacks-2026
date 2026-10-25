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
try:  # the shared quarantine list screen() reads; a sibling of common.py
    import smell_memory
except ImportError:  # common.py loaded by file path (demo/bridge.py), so its folder is not on sys.path
    import importlib.util as _util
    _spec = _util.spec_from_file_location("smell_memory", Path(__file__).with_name("smell_memory.py"))
    smell_memory = _util.module_from_spec(_spec)
    sys.modules["smell_memory"] = smell_memory
    _spec.loader.exec_module(smell_memory)

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
            memory = smell_memory.default()  # the shared quarantine list: a trick caught once is flagged for every agent
            return memory.apply(text, result, context) if memory is not None else result
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


# #398 item 3: the buyer may delegate only the voice of the approval call to Bazaar Caller (BUYER_DELEGATE_CALL=1).
# The request carries the call script variables (no code, no secret); the result carries the spoken evidence only.
# The buyer issues the code, verifies the utterance and writes the record itself. Additive: CallRequest is unchanged.
class VoiceTransportRequest(Model):
    mandate_hash: str
    variables_json: str   # exactly buyer_name, deal_script, why_answer (pay.voice_cartesia.build_variables)


class VoiceTransportResult(Model):
    mandate_hash: str
    call_id: str = ""
    call_json: str = ""   # the ended call as Cartesia returned it, with its transcript; never a verdict
    error: str = ""


# Deterministic seeds so addresses are stable across restarts. Override in .env for the real deploy.
CATALOG_SELLERS = ["seller_1", "seller_2", "seller_3", "seller_4", "seller_5"]  # five named SIM seller agents
# #342: seller_6 bids Central Computers (SF) listings as MIRROR. That store never joined, so its bids are shown for
# comparison and never ordered or paid (data/mirror/not_partners.py). It has NO default seed: it runs only when
# SELLER_6_AGENT_SEED is set to a private seed (agents/.env, never committed); otherwise it stays off.
MIRROR_SELLERS = ("seller_6",)
MIN_PRIVATE_SEED = 16


def _private_seed(env: str) -> str | None:
    """The env seed when it is private enough to sign with: set, 16+ characters, not a public *-dev default."""
    value = (os.getenv(env) or "").strip()
    return value if len(value) >= MIN_PRIVATE_SEED and not value.endswith("-dev") else None


_MIRROR_SEEDS = {name: seed for name in MIRROR_SELLERS if (seed := _private_seed(f"{name.upper()}_AGENT_SEED"))}
SELLERS = [*CATALOG_SELLERS, *_MIRROR_SEEDS]  # each its own uAgent; seller_6 only when its private seed is set
# #398 roster: four sellers, four jobs. Byte Bros learns, Frankie lies (the Advocate catches it), ReNew bundles refurbished
# and open-box lines, seller_6 bids a real store's MIRROR listings. These two are not run (their code, data, web arena and
# tests stay): each only repeats a job above, which Fetch asked us not to show as separate agents.
RETIRED_SELLERS = {"seller_2": "not run (same job as ReNew Refurb, seller_5)",
                   "seller_4": "not run (same job as Byte Bros Outlet, seller_1)"}
SELLER_JOBS = {"seller_1": "learner: steps its margin across rounds from its own losses and wins, never below its floor, and "
                           "shows a strategy note",
               "seller_3": "adaptive trickster: rotates a condition lie, a hidden fee, a fake warranty and an injection line, "
                           "learns which got caught, and every trick stays catchable",
               "seller_5": "honest refurbisher: labelled refurbished and open-box lines, the tradeoff in plain words, truthful "
                           "answers to the Advocate",
               "seller_6": "live mirror: bids a real store's dated listing as a price anchor, re-checked each round when a Bright "
                           "Data key is set, and can never be ordered or paid"}


def live_sellers() -> list[str]:
    """The sellers that run: SELLERS without the retired ones (seller_6 only when its private seed is set)."""
    return [s for s in SELLERS if s not in RETIRED_SELLERS]


SELLER_PORTS = {"seller_1": 8011, "seller_2": 8012, "seller_3": 8013, "seller_4": 8014, "seller_5": 8015,
                "seller_6": 8016}
BUILT_IN_ROLES = ("buyer", "advocate", "shield", *CATALOG_SELLERS, *MIRROR_SELLERS)
SEEDS = {
    "buyer": os.getenv("BUYER_AGENT_SEED", "tech-bazaar-buyer-dev"),
    "advocate": os.getenv("ADVOCATE_AGENT_SEED") or os.getenv("ADVOCATE_SEED", "tech-bazaar-advocate-dev"),
    "shield": os.getenv("SHIELD_AGENT_SEED") or os.getenv("SHIELD_SEED", "tech-bazaar-shield-dev"),
    **{s: os.getenv(f"{s.upper()}_AGENT_SEED") or os.getenv(f"{s.upper()}_SEED", f"tech-bazaar-{s}-dev")
       for s in CATALOG_SELLERS},
    **_MIRROR_SEEDS,  # never a default: no private seed, no seller_6
}

SEEDS.setdefault("caller", os.getenv("CALLER_AGENT_SEED") or "tech-bazaar-caller-dev")  # same default as caller_agent.py


_CUSTOM_ENVS: dict[str, str] = {}  # env name -> the custom role that owns it


def register_custom_seller(role: str) -> None:
    """Give a custom seller (from the Seller Kit) a stable seed so its address survives restarts.
    Set <ROLE>_AGENT_SEED in agents/.env before putting it on Agentverse; the default is public."""
    if role in SEEDS:
        raise ValueError(f"{role!r} is already a Fish Market agent: a custom seller must not reuse its key")
    env = role.upper().replace("-", "_")
    # Both env names a role reads are checked against every name a built-in reads: 'seller-1' and 'seller_1_agent'
    # both land on SELLER_1_AGENT_SEED, 'buyer_agent' on BUYER_AGENT_SEED, so none may reuse a built-in's key.
    owned = {f"{built_in.upper()}{suffix}" for built_in in BUILT_IN_ROLES for suffix in ("_AGENT_SEED", "_SEED")}
    if {f"{env}_AGENT_SEED", f"{env}_SEED"} & owned:
        raise ValueError(f"{role!r} is already a Fish Market agent: its seed name {env}_AGENT_SEED belongs to a "
                         "built-in agent, a custom seller must not reuse its key")
    if _CUSTOM_ENVS.get(env, role) != role:
        raise ValueError(f"{role!r} and {_CUSTOM_ENVS[env]!r} map to the same seed name {env}_AGENT_SEED")
    _CUSTOM_ENVS[env] = role
    SEEDS[role] = os.getenv(f"{env}_AGENT_SEED", f"tech-bazaar-{role}-dev")


def public_seed(role: str) -> bool:
    """The dev defaults above are in the public repo, so anyone could sign as that agent.
    Never put an agent on Agentverse with one; set <ROLE>_AGENT_SEED in agents/.env first."""
    return SEEDS[role].endswith("-dev")


def mailbox_on(role: str) -> bool:
    """True when this role should go on Agentverse (AGENTS_MAILBOX, or its own flag; sellers share SELLERS_MAILBOX)."""
    mailbox_flag = f"{role.upper()}_MAILBOX" if role in ("buyer", "advocate", "shield", "caller") else "SELLERS_MAILBOX"
    return bool(os.getenv("AGENTS_MAILBOX") or os.getenv(mailbox_flag))


def mailbox_ready(role: str) -> bool:
    """False only when mailbox mode is on for this role and it still has the public dev seed (agent_args would exit).
    Multi-agent runners use it to skip that one agent instead of losing the whole process."""
    return not (mailbox_on(role) and public_seed(role))


AVATARS = Path(__file__).resolve().parent / "avatars"
AVATAR_BASE = "https://raw.githubusercontent.com/vs-githjk/cal-hacks-2026/main/agents/avatars"


def avatar_url(role: str) -> str | None:
    """Public URL of the role's avatar (agents/avatars/<role>.png, served from the public repo), or None when the
    role has no avatar file. AGENT_AVATAR_BASE overrides the host, e.g. to serve them from the web app."""
    if not (AVATARS / f"{role}.png").is_file():
        return None
    return f"{os.getenv('AGENT_AVATAR_BASE', AVATAR_BASE).rstrip('/')}/{role}.png"


def agent_args(role: str, port: int, **profile) -> dict:
    """Constructor args for an agent. AGENTS_MAILBOX=1 puts it on Agentverse (register once with
    `python connect.py <port>`); otherwise it listens on localhost. `profile`: name, description,
    readme_path, handle, avatar_url (defaults to the role's avatar), published to Agentverse on connect."""
    if "avatar_url" not in profile and (url := avatar_url(role)):
        profile["avatar_url"] = url
    args = dict(seed=SEEDS[role], port=port, publish_agent_details=True, **profile)
    if mailbox_on(role):
        if public_seed(role):
            sys.exit(f"Set {role.upper()}_AGENT_SEED in agents/.env before going on Agentverse: the default seed is public.")
        return {**args, "mailbox": True}
    return {**args, "endpoint": [f"http://localhost:{port}/submit"]}


def address(role: str) -> str:
    if role not in SEEDS and role in MIRROR_SELLERS:
        raise ValueError(f"{role} is off: set {role.upper()}_AGENT_SEED in agents/.env to a private seed of "
                         f"{MIN_PRIVATE_SEED}+ characters. It has no default seed.")
    return Identity.from_seed(SEEDS[role], 0).address


def include_profile_chat(agent, role_text: str, answer=None, intercept=None):
    """Discoverability chat explains the role; structured protocols do the work.
    answer(text) -> str|None: a reply to a screened message (None means send role_text).
    intercept(ctx, sender, text) -> bool: True when the message belongs to the agent's own conversation (for example a
    seller's answer to a question the agent asked); it is acknowledged and gets no profile reply."""
    chat = Protocol(spec=chat_protocol_spec)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx, sender: str, msg: ChatMessage):
        if intercept is not None and await intercept(ctx, sender, msg):
            await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
            return
        verdict = screen(str(msg.msg_id), sender, msg.text())
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        text = role_text if verdict.get("verdict") == "allow" else "Smell Test blocked this message. No action taken."
        if answer is not None and verdict.get("verdict") == "allow":
            try:
                text = await answer(msg.text()) or role_text
            except Exception:  # a failed answer falls back to the profile text, never a silent chat
                text = role_text
        await ctx.send(sender, ChatMessage(content=[TextContent(text=text)]))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx, sender: str, msg: ChatAcknowledgement):
        pass

    agent.include(chat, publish_manifest=True)
