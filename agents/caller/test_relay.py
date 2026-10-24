"""#259: the caller relays to pay/'s existing approval call and nothing else. Fake Cartesia, no network."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from caller import relay  # noqa: E402
from pay.mandate import new_mandate  # noqa: E402

BUYER = "agent1q" + "b" * 58


class FakeCartesia:
    approval_call_to = "+15555550100"

    def __init__(self, says):
        self.says, self.calls, self.shown = says, [], {}

    def create_call(self, to_number, variables):
        self.calls.append(dict(variables))
        return "call_1"

    def get_call(self, call_id):
        said = self.says(self.shown.get("code"))
        entries = [{"role": "assistant", "text": "Hello.", "start_timestamp": 0.0}]
        if said:
            entries.append({"role": "user", "text": said, "start_timestamp": 6.0})
        return {"status": "completed", "end_reason": "client_hangup", "transcript": entries}


def mandate():
    return new_mandate(deal_id="deal-bid-1", buyer_id="vidyut", amount=1299.99, payee="best-buy", origin="MIRROR")


def call(says="{code} approve", *, sender=BUYER, client="fake", show=True, seen=None, m=None):
    c = FakeCartesia(lambda code: says.format(code=code)) if client == "fake" else client
    show_code = (lambda code: c.shown.update(code=code)) if show and c is not None else None
    out = relay.handle(sender, {"mandate": m or mandate(), "reason": None, "deal": {"item": "RTX 5070 Ti", "seller": "Best Buy"}},
                       buyer_address=BUYER, client=c, show_code=show_code, seen=set() if seen is None else seen,
                       secret="s" * 32, sleep=lambda x: None, poll=0)
    return out, c


def test_an_approved_call_returns_the_voice_approval_id():
    out, c = call()
    assert out["approved"] is True and out["voice_approval_id"].startswith("apr_") and len(c.calls) == 1


@pytest.mark.parametrize("says,reason", [("{code}", "no_code"), ("hello there", None), ("", None),
                                         ("{code} approve nine hundred", "no_code")])
def test_anything_but_the_code_and_approve_denies(says, reason):
    out, _ = call(says)
    assert out["approved"] is False and out["voice_approval_id"] is None
    if reason:
        assert out["reason"] == reason


def test_only_the_buyer_agent_can_ask_and_nothing_is_dialled_otherwise():
    out, c = call(sender="agent1q" + "x" * 58)
    assert out == {"approved": False, "reason": "not_the_buyer", "call_id": None, "voice_approval_id": None} and c.calls == []


def test_one_call_per_mandate():
    seen, m = set(), mandate()
    first, _ = call(seen=seen, m=m)
    again, c = call(seen=seen, m=m)
    assert first["approved"] and again["reason"] == "already_called" and c.calls == []


def test_a_tampered_mandate_places_no_call():
    m = mandate()
    m["amount"] = 1.0
    out, c = call(m=m)
    assert out["reason"].startswith("bad_mandate") and c.calls == []


def test_no_cartesia_or_no_screen_places_no_call():
    out, _ = call(client=None)
    assert out["reason"].startswith("not_configured")
    out, c = call(show=False)
    assert out["reason"].startswith("no_screen") and c.calls == []
