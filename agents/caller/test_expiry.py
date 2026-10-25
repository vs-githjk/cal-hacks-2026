"""RT-24: a call request carries expires_at, and a stale, missing (when required), malformed or far-future one is refused
before Shield and before any call. A refused stale request burns nothing: a fresh request for the same mandate still works.
Fake Cartesia, no network, no key."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from caller import relay  # noqa: E402
from caller.test_relay import BUYER, VARS, FakeCartesia, TransportClient, mandate  # noqa: E402

NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds, fmt="%Y-%m-%dT%H:%M:%SZ"):
    return (NOW + timedelta(seconds=seconds)).strftime(fmt)


def now():
    return NOW


# ---- the rule ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [at(1), at(120), at(relay.MAX_REQUEST_TTL_S), "2026-10-25T12:02:00+00:00", "2026-10-25T05:02:00-07:00",
                                   "2026-10-25T12:02:00.250Z"])
def test_a_fresh_expiry_inside_the_window_is_accepted(value):
    assert relay.check_expiry(value, now=now) is None


@pytest.mark.parametrize("value", [at(0), at(-1), at(-3600), "2020-01-01T00:00:00Z"])
def test_a_stale_request_is_refused(value):
    assert relay.check_expiry(value, now=now) == "request_expired"


def test_an_expiry_beyond_the_window_is_refused_because_it_is_no_expiry():
    assert relay.check_expiry(at(relay.MAX_REQUEST_TTL_S + 1), now=now) == "expires_too_far"
    assert relay.check_expiry("2099-01-01T00:00:00Z", now=now) == "expires_too_far"


@pytest.mark.parametrize("value", ["garbage", "2026-10-25T12:02:00", "2026-10-25", "1793000000", "nan", "12:02", "\u0000", "x" * 500])
def test_a_malformed_or_zone_less_expiry_is_refused(value):
    assert relay.check_expiry(value, now=now) == "bad_expires_at"


def test_an_expiry_that_is_not_text_is_refused():
    for value in (123, 1.5, ["2026"], {"a": 1}, True):
        assert relay.check_expiry(value, now=now) == "bad_expires_at"


def test_a_missing_expiry_is_refused_when_required_and_allowed_when_not():
    assert relay.check_expiry("", now=now) == "missing_expires_at"
    assert relay.check_expiry(None, now=now) == "missing_expires_at"
    assert relay.check_expiry("", now=now, required=False) is None
    assert relay.check_expiry("garbage", now=now, required=False) == "bad_expires_at"   # a bad value is never waved through


def test_the_precheck_checks_the_sender_first_then_the_expiry_then_the_size():
    stranger = "agent1q" + "z" * 58
    assert relay.precheck(stranger, "hi", buyer_address=BUYER, expires_at=at(-5), now=now) == "not_the_buyer"
    assert relay.precheck(BUYER, "x" * 20001, buyer_address=BUYER, expires_at=at(-5), now=now) == "request_expired"
    assert relay.precheck(BUYER, "x" * 20001, buyer_address=BUYER, expires_at=at(60), now=now) == "too_large"
    assert relay.precheck(BUYER, "hi", buyer_address=BUYER, expires_at=at(60), now=now) is None
    assert relay.precheck(BUYER, "hi", buyer_address=BUYER) is None                      # not asked to check: unchanged


# ---- the relay re-checks right before it dials -------------------------------------------------------------------------

def call(expires_at, *, seen=None, m=None, required=True):
    c = FakeCartesia(lambda code: f"{code} approve")
    out = relay.handle(BUYER, {"mandate": m or mandate(), "reason": None, "deal": None}, buyer_address=BUYER, client=c,
                       show_code=lambda code: c.shown.update(code=code), seen=set() if seen is None else seen, secret="s" * 32,
                       sleep=lambda x: None, poll=0, expires_at=expires_at, now=now, require_expiry=required)
    return out, c


def test_a_stale_request_dials_nothing_and_a_fresh_one_for_the_same_mandate_still_works():
    seen, m = set(), mandate()
    out, c = call(at(-1), seen=seen, m=m)
    assert out == {"approved": False, "reason": "request_expired", "call_id": None, "voice_approval_id": None} and c.calls == []
    assert seen == set()                                            # nothing was burned: no call was placed
    fresh, c2 = call(at(90), seen=seen, m=m)
    assert fresh["approved"] is True and len(c2.calls) == 1


def test_a_request_that_expired_while_it_waited_for_shield_is_caught_at_the_dial():
    out, c = call(at(-30))
    assert out["reason"] == "request_expired" and c.calls == []


def test_the_request_path_with_no_expiry_check_asked_for_is_unchanged():
    c = FakeCartesia(lambda code: f"{code} approve")
    out = relay.handle(BUYER, {"mandate": mandate()}, buyer_address=BUYER, client=c, show_code=lambda code: c.shown.update(code=code),
                       seen=set(), secret="s" * 32, sleep=lambda x: None, poll=0)
    assert out["approved"] is True


def transport(expires_at, *, seen=None, required=True):
    client = TransportClient()
    out = relay.transport(BUYER, {"mandate_hash": "a" * 64, "variables": dict(VARS)}, buyer_address=BUYER, client=client,
                          seen=set() if seen is None else seen, sleep=lambda s: None, expires_at=expires_at, now=now,
                          require_expiry=required)
    return out, client


def test_a_stale_voice_transport_dials_nothing_and_burns_nothing():
    seen = set()
    out, client = transport(at(-1), seen=seen)
    assert out == {"call_id": None, "call": None, "error": "request_expired"} and client.calls == 0 and seen == set()
    fresh, client2 = transport(at(60), seen=seen)
    assert fresh["error"] is None and client2.calls == 1


def test_a_voice_transport_with_no_expiry_dials_only_when_the_operator_has_not_made_it_required():
    out, client = transport("", required=True)
    assert out["error"] == "missing_expires_at" and client.calls == 0
    out, client = transport("", required=False)
    assert out["error"] is None and client.calls == 1


def test_require_expiry_follows_the_operator_flag(monkeypatch):
    monkeypatch.delenv("CALLER_REQUIRE_EXPIRES", raising=False)
    assert relay.expiry_required_for_transport() is False
    monkeypatch.setenv("CALLER_REQUIRE_EXPIRES", "1")
    assert relay.expiry_required_for_transport() is True
    monkeypatch.setenv("CALLER_REQUIRE_EXPIRES", "0")
    assert relay.expiry_required_for_transport() is False


# ---- the agent's handlers --------------------------------------------------------------------------------------------

@pytest.fixture
def agent_mod(monkeypatch):
    pytest.importorskip("uagents")
    for name in ("CALLER_MAILBOX", "AGENTS_MAILBOX"):
        monkeypatch.delenv(name, raising=False)
    asyncio.set_event_loop(asyncio.new_event_loop())
    import importlib

    import common
    mod = importlib.reload(importlib.import_module("caller.caller_agent"))
    monkeypatch.setattr(common, "address", lambda role: BUYER)
    yield mod
    asyncio.set_event_loop(None)


class Ctx:
    def __init__(self):
        self.sent = []

        class L:
            def info(self, *a, **k):
                pass
        self.logger = L()

    async def send(self, to, msg):
        self.sent.append((to, msg))


def handler(mod, name):
    return next(fn for fn in mod.protocol.signed_message_handlers.values() if fn.__name__ == name)


def spy_screen(monkeypatch, mod, verdict="block"):
    seen = []
    monkeypatch.setattr(mod.common, "screen", lambda *a, **k: seen.append(a) or {"verdict": verdict})
    return seen


def run_call(mod, expires_at, sender=BUYER):
    ctx = Ctx()
    msg = mod.CallRequest(mandate_json="{}", expires_at=expires_at)
    asyncio.run(handler(mod, "on_call")(ctx, sender, msg))
    return ctx.sent


def test_the_call_request_has_an_expires_at_field_that_defaults_to_empty(agent_mod):
    assert agent_mod.CallRequest(mandate_json="{}").expires_at == ""


@pytest.mark.parametrize("expires_at,reason", [("", "missing_expires_at"), ("garbage", "bad_expires_at"),
                                               ("2020-01-01T00:00:00Z", "request_expired"),
                                               ("2099-01-01T00:00:00Z", "expires_too_far")])
def test_a_bad_call_request_is_refused_before_shield(monkeypatch, agent_mod, expires_at, reason):
    screens = spy_screen(monkeypatch, agent_mod)
    sent = run_call(agent_mod, expires_at)
    assert sent[0][1].approved is False and sent[0][1].reason == reason and screens == []


def test_a_fresh_call_request_goes_on_to_shield(monkeypatch, agent_mod):
    screens = spy_screen(monkeypatch, agent_mod, verdict="block")
    fresh = (datetime.now(timezone.utc) + timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sent = run_call(agent_mod, fresh)
    assert len(screens) == 1 and sent[0][1].reason == "shield_blocked"


# ---- the voice transport: the OLD message is unchanged, the deadline travels in a NEW one -----------------------------------

MAIN_VOICE_REQUEST_DIGEST = "model:33587d8e1688b2bcacc9e9aab45c049b74e1bfe18ceffabb2b63035f60b1346f"   # origin/main's, Oct 25 02:46
MAIN_VOICE_RESULT_DIGEST = "model:a206a095548bcb7c7d14ec0a328fc7bdd6c69a14db9991a694e0086c9a86bc4f"


def test_voice_transport_digest_is_main_s_so_a_buyer_on_older_code_is_still_heard():
    from uagents import Model

    import common
    assert Model.build_schema_digest(common.VoiceTransportRequest) == MAIN_VOICE_REQUEST_DIGEST
    assert Model.build_schema_digest(common.VoiceTransportResult) == MAIN_VOICE_RESULT_DIGEST
    assert list(common.VoiceTransportRequest.__fields__) == ["mandate_hash", "variables_json"]


def test_the_expiring_request_is_a_different_message_with_the_deadline_required():
    from uagents import Model

    import common
    assert Model.build_schema_digest(common.ExpiringVoiceTransportRequest) != MAIN_VOICE_REQUEST_DIGEST
    assert list(common.ExpiringVoiceTransportRequest.__fields__) == ["mandate_hash", "variables_json", "expires_at"]
    with pytest.raises(Exception):
        common.ExpiringVoiceTransportRequest(mandate_hash="a" * 64, variables_json="{}")


def test_the_caller_listens_for_both_voice_messages_and_the_old_digest_is_still_registered(agent_mod):
    from uagents import Model

    import common
    registered = set(agent_mod.protocol.signed_message_handlers)
    assert Model.build_schema_digest(common.VoiceTransportRequest) in registered
    assert Model.build_schema_digest(common.ExpiringVoiceTransportRequest) in registered


def run_old(mod):
    ctx = Ctx()
    msg = mod.common.VoiceTransportRequest(mandate_hash="a" * 64, variables_json="{}")
    asyncio.run(handler(mod, "on_transport")(ctx, BUYER, msg))
    return ctx.sent


def run_expiring(mod, expires_at):
    ctx = Ctx()
    msg = mod.common.ExpiringVoiceTransportRequest(mandate_hash="a" * 64, variables_json="{}", expires_at=expires_at)
    asyncio.run(handler(mod, "on_expiring_transport")(ctx, BUYER, msg))
    return ctx.sent


def test_a_stale_expiring_request_is_refused_before_shield(monkeypatch, agent_mod):
    screens = spy_screen(monkeypatch, agent_mod)
    sent = run_expiring(agent_mod, "2020-01-01T00:00:00Z")
    assert sent[0][1].error == "request_expired" and screens == []


@pytest.mark.parametrize("value,error", [("", "missing_expires_at"), ("garbage", "bad_expires_at"), ("2099-01-01T00:00:00Z", "expires_too_far")])
def test_a_bad_expiring_request_is_refused_whatever_the_operator_flag(monkeypatch, agent_mod, value, error):
    screens = spy_screen(monkeypatch, agent_mod)
    monkeypatch.delenv("CALLER_REQUIRE_EXPIRES", raising=False)
    assert run_expiring(agent_mod, value)[0][1].error == error and screens == []


def test_a_fresh_expiring_request_goes_on_to_shield(monkeypatch, agent_mod):
    screens = spy_screen(monkeypatch, agent_mod, verdict="block")
    fresh = (datetime.now(timezone.utc) + timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert run_expiring(agent_mod, fresh)[0][1].error == "shield_blocked" and len(screens) == 1


def test_the_old_request_keeps_working_with_no_deadline_until_the_operator_requires_one(monkeypatch, agent_mod):
    screens = spy_screen(monkeypatch, agent_mod, verdict="block")
    monkeypatch.delenv("CALLER_REQUIRE_EXPIRES", raising=False)
    assert run_old(agent_mod)[0][1].error == "shield_blocked" and len(screens) == 1          # reaches Shield: not dropped, not refused
    monkeypatch.setenv("CALLER_REQUIRE_EXPIRES", "1")
    assert run_old(agent_mod)[0][1].error == "missing_expires_at" and len(screens) == 1       # refused before Shield


