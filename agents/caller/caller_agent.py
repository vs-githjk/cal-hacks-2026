"""Bazaar Caller: the 7th agent (#259). It makes the approval workflow visible on Agentverse: buyer -> advocate ->
caller -> pay. On a CallRequest from the buyer agent it places ONE approval phone call through pay/ (caller/relay.py)
and answers with a CallResult. It never approves or charges anything itself.

Run (from agents/): python caller/caller_agent.py. Config: CARTESIA_* names (pay/voice_cartesia.py), and
SPACETIMEDB_REFEREE_TOKEN_FILE so the code can go to the buyer's own /buyer screen; without it no call is placed.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from uagents import Agent, Context, Model, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))         # agents/, for common
sys.path.insert(1, str(Path(__file__).resolve().parents[2]))         # the repo root, for pay/
import common  # noqa: E402
from caller import explain, relay  # noqa: E402
from caller.relay import market_has_typed_approval  # noqa: E402

common.SEEDS.setdefault("caller", os.getenv("CALLER_AGENT_SEED") or "tech-bazaar-caller-dev")
NAME = "Fish Market Caller"


class CallRequest(Model):
    mandate_json: str
    reason_json: str = ""
    deal_json: str = ""
    expires_at: str = ""   # RT-24: ISO 8601 with a zone, at most 10 minutes ahead; a stale or missing one is refused


class CallResult(Model):
    approved: bool
    reason: str = ""
    call_id: str = ""
    voice_approval_id: str = ""


def screen_sink():
    """The code goes to the buyer's /buyer screen through the market (issue_approval_code), or nowhere. Nowhere while
    the market still has typed approval, or without the referee token."""
    token = os.getenv("SPACETIMEDB_REFEREE_TOKEN_FILE")
    if not token or not Path(token).exists() or market_has_typed_approval():
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "market" / "scripts"))
    from stdb import Market
    referee = Market(token_file=token)

    def show(code: str, mandate_hash: str) -> None:
        referee.call("issue_approval_code", mandate_hash=mandate_hash, code=code)
    return show


agent = Agent(**common.agent_args(
    "caller", 8006, name=NAME, handle=os.getenv("CALLER_AGENT_HANDLE", "techbazaarcaller"),
    readme_path=str(Path(__file__).with_name("AGENTVERSE.md")),
    description="The second-factor agent: the buyer agent cannot approve its own spend, so I place the one approval phone call. "
                "You say the code from your own screen, for that exact amount and seller. I approve and charge nothing myself."))
protocol = Protocol(name="tech-bazaar-approval-call", version="0.1.0")
SEEN: set = set()


@protocol.on_message(CallRequest, replies=CallResult)
async def on_call(ctx: Context, sender: str, msg: CallRequest):
    # Only the buyer agent may ask, checked before Shield so a stranger costs no Shield call (#298). Then invariant 3:
    # every agent message goes through Shield first (fails closed when Shield is down), whole or not at all.
    text = " ".join((msg.mandate_json, msg.reason_json, msg.deal_json))
    refused = relay.precheck(sender, text, buyer_address=common.address("buyer"), expires_at=msg.expires_at)
    if refused:
        await ctx.send(sender, CallResult(approved=False, reason=refused))
        return
    verdict = await asyncio.to_thread(common.screen, f"call-{abs(hash(msg.mandate_json)) % 10**12}", sender, text)
    if verdict.get("verdict") != "allow":
        await ctx.send(sender, CallResult(approved=False, reason="shield_blocked"))
        return
    try:
        request = {"mandate": json.loads(msg.mandate_json), "reason": json.loads(msg.reason_json or "null"),
                   "deal": json.loads(msg.deal_json or "null")}
    except Exception:  # noqa: BLE001  (bad JSON, deep nesting)
        await ctx.send(sender, CallResult(approved=False, reason="bad_request"))
        return
    from pay import voice_cartesia as vc
    env = vc.load_env(vc.DEFAULT_ENV_FILE)
    try:
        client, unconfigured = vc.CartesiaClient.from_env(env), None
    except vc.CartesiaError as e:
        client, unconfigured = None, str(e)
    try:
        sink = screen_sink()
    except Exception:  # noqa: BLE001  (an unreadable token file: no screen, so no call)
        sink = None
    mandate_hash = request["mandate"].get("hash") if isinstance(request["mandate"], dict) else None
    show = (lambda code: sink(code, mandate_hash)) if sink else None
    out = await asyncio.to_thread(relay.handle, sender, request, buyer_address=common.address("buyer"), client=client,
                                  show_code=show, seen=SEEN, unconfigured=unconfigured, secret=env.get(vc.SECRET_ENV),
                                  buyer_name=env.get(vc.NAME_ENV) or "there", expires_at=msg.expires_at)
    ctx.logger.info(f"approval call for {str(mandate_hash)[:12]}: {'approved' if out['approved'] else 'not approved'}")
    await ctx.send(sender, CallResult(approved=out["approved"], reason=out["reason"] or "", call_id=out["call_id"] or "",
                                      voice_approval_id=out["voice_approval_id"] or ""))


async def voice_transport(ctx: Context, sender: str, mandate_hash: str, variables_json: str, expires_at):
    """The delegated voice call for both request messages. `expires_at` None means the request carries no deadline (the old
    VoiceTransportRequest): accepted unless the operator set CALLER_REQUIRE_EXPIRES=1. A string is always checked, and a blank one
    is refused as missing."""
    require = relay.expiry_required_for_transport()
    if expires_at is None and require:
        expires_at = ""
    text = " ".join((mandate_hash, variables_json))
    refused = relay.precheck(sender, text, buyer_address=common.address("buyer"), expires_at=expires_at, require_expiry=True)
    if refused:
        await ctx.send(sender, common.VoiceTransportResult(mandate_hash=mandate_hash, error=refused))
        return
    verdict = await asyncio.to_thread(common.screen, f"voice-{abs(hash(mandate_hash)) % 10**12}", sender, text)
    if verdict.get("verdict") != "allow":
        await ctx.send(sender, common.VoiceTransportResult(mandate_hash=mandate_hash, error="shield_blocked"))
        return
    try:
        variables = json.loads(variables_json)
    except Exception:  # noqa: BLE001
        await ctx.send(sender, common.VoiceTransportResult(mandate_hash=mandate_hash, error="bad_request"))
        return
    from pay import voice_cartesia as vc
    try:
        client, unconfigured = vc.CartesiaClient.from_env(vc.load_env(vc.DEFAULT_ENV_FILE)), None
    except vc.CartesiaError as e:
        client, unconfigured = None, str(e)
    out = await asyncio.to_thread(relay.transport, sender, {"mandate_hash": mandate_hash, "variables": variables},
                                  buyer_address=common.address("buyer"), client=client, seen=SEEN, unconfigured=unconfigured,
                                  expires_at=expires_at, require_expiry=True)
    await ctx.send(sender, common.VoiceTransportResult(mandate_hash=mandate_hash, call_id=out["call_id"] or "",
                                                       call_json=json.dumps(out["call"]) if out["call"] else "",
                                                       error=out["error"] or ""))


@protocol.on_message(common.VoiceTransportRequest, replies=common.VoiceTransportResult)
async def on_transport(ctx: Context, sender: str, msg: common.VoiceTransportRequest):
    """#398 item 3: voice only. The buyer owns the code, the nonce and the record; this places the call and returns
    what was said. Same gates as on_call: only the buyer, Shield first, one call per mandate. This message is UNCHANGED (a buyer on
    older code keeps working) and has no deadline, so it is refused only when CALLER_REQUIRE_EXPIRES=1."""
    await voice_transport(ctx, sender, msg.mandate_hash, msg.variables_json, None)


@protocol.on_message(common.ExpiringVoiceTransportRequest, replies=common.VoiceTransportResult)
async def on_expiring_transport(ctx: Context, sender: str, msg: common.ExpiringVoiceTransportRequest):
    """RT-24: the same request with `expires_at`, always checked: stale, missing, malformed or far-future is refused before Shield."""
    await voice_transport(ctx, sender, msg.mandate_hash, msg.variables_json, msg.expires_at)


agent.include(protocol, publish_manifest=True)
common.include_profile_chat(agent, explain.SECOND_FACTOR_TEXT)

def require_private_buyer_seed(seed: str | None = None) -> None:
    """#449 PL-22: exit with a clear message unless BUYER_AGENT_SEED is set and private. The Caller obeys only the address
    that seed derives; common.SEEDS falls back to a public *-dev default, which anyone could sign as."""
    problem = relay.buyer_seed_problem(os.getenv("BUYER_AGENT_SEED") if seed is None else seed)
    if problem:
        sys.exit(problem)


if __name__ == "__main__":
    require_private_buyer_seed()
    agent.run()
