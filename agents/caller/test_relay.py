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


def test_a_screen_that_refuses_the_code_is_not_approved_and_never_calls_twice():
    seen, m = set(), mandate()

    def refuse(code):
        raise RuntimeError("issue_approval_code refused")
    c = FakeCartesia(lambda code: f"{code} approve")
    out = relay.handle(BUYER, {"mandate": m}, buyer_address=BUYER, client=c, show_code=refuse, seen=seen, secret="s" * 32,
                       sleep=lambda x: None, poll=0)
    assert out["approved"] is False and out["reason"].startswith("call_error") and c.calls == []
    again, _ = call(seen=seen, m=m)
    assert again["reason"] == "already_called"


def test_the_caller_shows_no_code_while_the_market_has_typed_approval(tmp_path):
    module = tmp_path / "index.ts"
    module.write_text("export const approve_typed = 1")
    assert relay.market_has_typed_approval(module) is True
    module.write_text("export const record_approval = 1")
    assert relay.market_has_typed_approval(module) is False
    assert relay.market_has_typed_approval(tmp_path / "missing.ts") is True
    src = Path(__file__).with_name("caller_agent.py").read_text()
    assert "or market_has_typed_approval()" in src          # screen_sink returns None then: no code, no call


# ---------- #298 Lows: the sender before Shield, one call under threads, a byte cap ----------

def test_a_stranger_is_refused_before_any_shield_call():
    assert relay.precheck("agent1q" + "z" * 58, "hello", buyer_address=BUYER) == "not_the_buyer"
    assert relay.precheck(BUYER, "hello", buyer_address=BUYER) is None


@pytest.mark.parametrize("text", ["x" * 20001, "é" * 15000, "\U0001F600" * 6000])
def test_a_request_over_the_char_or_body_cap_is_too_large_not_shield_blocked(text):
    assert relay.precheck(BUYER, text, buyer_address=BUYER) == "too_large"


def test_two_threads_with_the_same_mandate_place_one_call():
    import threading

    clients = [FakeCartesia(lambda code: f"{code} approve") for _ in range(8)]
    barrier, inside = threading.Barrier(len(clients)), threading.Barrier(len(clients))

    class AllInsideSet(set):
        """The membership check waits until every thread is inside it. Without the lock all 8 then see "not called"
        together and dial; with it the first thread waits out the timeout alone and the rest are told already_called."""
        def __contains__(self, item):
            found = super().__contains__(item)   # read before the wait, as an unlocked check-then-add would
            try:
                inside.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass
            return found

    m, seen, results = mandate(), AllInsideSet(), []

    def go(c):
        barrier.wait()
        out = relay.handle(BUYER, {"mandate": m, "reason": None, "deal": None}, buyer_address=BUYER, client=c,
                           show_code=lambda code, c=c: c.shown.update(code=code), seen=seen, secret="s" * 32,
                           sleep=lambda x: None, poll=0)
        results.append(out["reason"])
    threads = [threading.Thread(target=go, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(len(c.calls) for c in clients) == 1 and results.count("already_called") == len(clients) - 1


# ---- #398 item 3: voice transport only ------------------------------------------------------------------------------
VARS = {"buyer_name": "Vidyut", "deal_script": "One RTX 5070 Ti for $1,299.99 from Byte Bros.", "why_answer": "It fits."}


class TransportClient:
    approval_call_to = "+14155550123"

    def __init__(self):
        self.calls = 0

    def create_call(self, _to, variables):
        self.calls += 1
        self.variables = variables
        return "call-t1"

    def get_call(self, call_id):
        return {"id": call_id, "status": "completed", "end_reason": "client_hangup",
                "transcript": [{"role": "user", "text": "lemon river approve", "start_timestamp": 1.0}]}


def transport(request=None, *, sender=BUYER, client=None, seen=None):
    client = client or TransportClient()
    req = request if request is not None else {"mandate_hash": "a" * 64, "variables": dict(VARS)}
    return relay.transport(sender, req, buyer_address=BUYER, client=client, seen=set() if seen is None else seen,
                           sleep=lambda s: None), client


def test_transport_returns_the_finished_call_and_its_transcript_and_judges_nothing():
    out, client = transport()
    assert out["error"] is None and out["call_id"] == "call-t1" and client.calls == 1
    assert out["call"]["transcript"][0]["text"] == "lemon river approve"
    assert "approved" not in out and "voice_approval_id" not in out   # no verdict, no record


@pytest.mark.parametrize("req,error", [({"mandate_hash": "x", "variables": VARS}, "bad_request"),
                                       ({"mandate_hash": "a" * 64, "variables": {**VARS, "code": "lemon river"}}, "bad_variables"),
                                       ({"mandate_hash": "a" * 64, "variables": {"buyer_name": "V"}}, "bad_variables"),
                                       ("junk", "bad_request")])
def test_transport_refuses_anything_but_the_three_script_variables(req, error):
    out, client = transport(req)
    assert out["error"] == error and client.calls == 0


def test_transport_only_for_the_buyer_and_one_call_per_mandate():
    out, client = transport(sender="agent1stranger")
    assert out["error"] == "not_the_buyer" and client.calls == 0
    seen = set()
    transport(seen=seen)
    again, client2 = transport(seen=seen)
    assert again["error"] == "already_called" and client2.calls == 0


def test_the_existing_call_request_path_is_unchanged():
    out, _ = call()
    assert out["approved"] is True and set(out) == {"approved", "reason", "call_id", "voice_approval_id"}


# ---- #449 PL-22: the Caller never trusts a public dev seed for the buyer address ----------------------------------------
@pytest.mark.parametrize("seed", [None, "", "   ", "tech-bazaar-buyer-dev", "my-own-private-thing-dev", "short"])
def test_a_missing_or_public_or_short_buyer_seed_is_a_problem(seed):
    problem = relay.buyer_seed_problem(seed)
    assert problem and "BUYER_AGENT_SEED" in problem


def test_a_private_buyer_seed_is_fine():
    assert relay.buyer_seed_problem("a-private-seed-of-24-chars!") is None


def _load_caller_agent(run_name):
    """Execute caller_agent.py with uagents.Agent faked (no event loop, no network, nothing can start): (globals, fake)."""
    import runpy
    from unittest.mock import patch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with patch("uagents.Agent") as fake_class:
        try:
            return runpy.run_module("caller.caller_agent", run_name=run_name), fake_class.return_value, None
        except SystemExit as e:
            return None, fake_class.return_value, e


def _run_as_main(monkeypatch, seed):
    monkeypatch.delenv("AGENTS_MAILBOX", raising=False)
    monkeypatch.delenv("CALLER_MAILBOX", raising=False)
    if seed is None:
        monkeypatch.delenv("BUYER_AGENT_SEED", raising=False)
    else:
        monkeypatch.setenv("BUYER_AGENT_SEED", seed)
    _, agent, exit_ = _load_caller_agent("__main__")
    return agent.run, exit_


@pytest.mark.parametrize("seed", [None, "tech-bazaar-buyer-dev"])
def test_the_caller_exits_at_start_without_a_private_buyer_seed(monkeypatch, seed):
    run, exit_ = _run_as_main(monkeypatch, seed)
    assert exit_ is not None and "BUYER_AGENT_SEED" in str(exit_.code)
    run.assert_not_called()


def test_the_caller_starts_with_a_private_buyer_seed(monkeypatch):
    run, exit_ = _run_as_main(monkeypatch, "a-private-seed-of-24-chars!")
    assert exit_ is None
    run.assert_called_once()
