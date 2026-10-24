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
from caller import relay  # noqa: E402

common.SEEDS.setdefault("caller", os.getenv("CALLER_AGENT_SEED") or "tech-bazaar-caller-dev")
NAME = "Bazaar Caller"


class CallRequest(Model):
    mandate_json: str
    reason_json: str = ""
    deal_json: str = ""


class CallResult(Model):
    approved: bool
    reason: str = ""
    call_id: str = ""
    voice_approval_id: str = ""


def screen_sink():
    """The code goes to the buyer's /buyer screen through the market (issue_approval_code), or nowhere."""
    token = os.getenv("SPACETIMEDB_REFEREE_TOKEN_FILE")
    if not token or not Path(token).exists():
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
    description="Places the one approval phone call for a Tech Bazaar purchase: the buyer says the code on their screen "
                "and approve. It approves and charges nothing itself."))
protocol = Protocol(name="tech-bazaar-approval-call", version="0.1.0")
SEEN: set = set()


@protocol.on_message(CallRequest, replies=CallResult)
async def on_call(ctx: Context, sender: str, msg: CallRequest):
    try:
        request = {"mandate": json.loads(msg.mandate_json), "reason": json.loads(msg.reason_json or "null"),
                   "deal": json.loads(msg.deal_json or "null")}
    except ValueError:
        await ctx.send(sender, CallResult(approved=False, reason="bad_request"))
        return
    from pay import voice_cartesia as vc
    env = vc.load_env(vc.DEFAULT_ENV_FILE)
    try:
        client, unconfigured = vc.CartesiaClient.from_env(env), None
    except vc.CartesiaError as e:
        client, unconfigured = None, str(e)
    sink = screen_sink()
    mandate_hash = request["mandate"].get("hash") if isinstance(request["mandate"], dict) else None
    show = (lambda code: sink(code, mandate_hash)) if sink else None
    out = await asyncio.to_thread(relay.handle, sender, request, buyer_address=common.address("buyer"), client=client,
                                  show_code=show, seen=SEEN, unconfigured=unconfigured, secret=env.get(vc.SECRET_ENV),
                                  buyer_name=env.get(vc.NAME_ENV) or vc.DEFAULT_BUYER_NAME)
    ctx.logger.info(f"approval call for {str(mandate_hash)[:12]}: {'approved' if out['approved'] else 'not approved'}")
    await ctx.send(sender, CallResult(approved=out["approved"], reason=out["reason"] or "", call_id=out["call_id"] or "",
                                      voice_approval_id=out["voice_approval_id"] or ""))


agent.include(protocol, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
