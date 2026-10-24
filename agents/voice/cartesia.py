"""Cartesia transport for the approval call: place an outbound call (REST) and drive it as a Line agent.
Needs CARTESIA_API_KEY, CARTESIA_AGENT_ID, CARTESIA_PHONE_NUMBER_ID in agents/.env, and the `cartesia-line`
package for the Line agent (not installed yet: needs Vidyut's OK). The in-browser call stays the fallback.

Flow: place_call(call, buyer_id) dials only the buyer's registered number and remembers the Call under the
returned agent_call_id; Cartesia then runs ApprovalCallAgent for that call, which speaks only script lines."""
import json
import os
import urllib.request

import common  # noqa: F401  (loads agents/.env)
from voice.call import Call, number_for

API = "https://api.cartesia.ai/agents/calls"
VERSION = "2026-03-01"
CALLS: dict[str, Call] = {}  # agent_call_id -> Call; ponytail: in-memory, the Line app must run in this process


def place_call(call: Call, buyer_id: str) -> str:
    """Dial the buyer's registered number. Returns the agent_call_id; raises if Cartesia rejects the call."""
    body = {"from_number_id": os.environ["CARTESIA_PHONE_NUMBER_ID"], "agent_id": os.environ["CARTESIA_AGENT_ID"],
            "outbound_calls": [{"to_number": number_for(buyer_id),
                                "metadata": {"mandate_hash": call.mandate["hash"]}}],
            "ringing_timeout_seconds": 30, "max_call_duration_minutes": 3}
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {os.environ['CARTESIA_API_KEY']}", "Cartesia-Version": VERSION,
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        result = json.loads(r.read())["calls"][0]
    if "agent_call_id" not in result:
        raise RuntimeError(f"Cartesia did not place the call: {result.get('error')}")
    CALLS[result["agent_call_id"]] = call
    return result["agent_call_id"]


def _say(text: str):
    from line.events import AgentSendText  # cartesia-line
    return AgentSendText(text=text, interruptible=False)


class ApprovalCallAgent:
    """Line agent for one call. Events are matched by class name so this module imports without cartesia-line.
    Line gives no STT confidence, so none is passed (pay.approval then judges the words alone)."""

    def __init__(self, call: Call):
        self.call = call

    async def process(self, env, event):
        kind = type(event).__name__
        if kind == "CallStarted":
            yield _say(self.call.start())
        elif kind == "UserTurnEnded" and not self.call.done:
            text = " ".join(c.content for c in event.content if getattr(c, "content", None))
            line = self.call.heard(text)
            if line:
                yield _say(line)
        elif kind == "CallEnded" and not self.call.done:
            self.call.silence()  # hung up or never answered: deny, fresh code for the review card


async def get_agent(env, call_request):
    """VoiceAgentApp hook. Unknown calls get no agent logic that could approve anything."""
    call = CALLS.get(getattr(call_request, "agent_call_id", None))
    if call is None:
        raise PermissionError("no approval call is pending for this call id")
    return ApprovalCallAgent(call)


def app():
    from line.voice_agent_app import VoiceAgentApp  # cartesia-line
    return VoiceAgentApp(get_agent=get_agent)
