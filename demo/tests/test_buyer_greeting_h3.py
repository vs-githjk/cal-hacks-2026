"""H3: the approval call greets a non-default buyer by their own display_name (same agent_buyer_contact row as their phone), never by the
default buyer's APPROVAL_BUYER_NAME. "there" when the name is empty. APPROVAL_BUYER_NAME stays for the default buyer only."""
from __future__ import annotations

import types

import pytest

from demo import bridge
from pay import voice_cartesia as vc

ENV = {vc.KEY_ENV: "k" * 20, vc.AGENT_ENV: "agent-1", vc.TO_ENV: "+14155550123", vc.NAME_ENV: "Vidyut"}
WEB, OTHER = "b_web11111", "b_other222"


def _names(rows):
    return vc.name_lookup_from_sql(lambda q: [[i, n] for i, n in rows if f"buyer_id = '{i}'" in q])


def test_the_default_buyer_is_greeted_by_the_env_name_then_vidyut():
    assert vc.greeting_name("vidyut", ENV) == "Vidyut"
    assert vc.greeting_name("vidyut", {**ENV, vc.NAME_ENV: "Vid"}) == "Vid"
    assert vc.greeting_name("vidyut", {}) == vc.DEFAULT_BUYER_NAME


def test_a_web_buyer_is_greeted_by_their_own_display_name_never_the_default_name():
    lookup = _names([(WEB, "Asha"), (OTHER, "Ravi")])
    assert vc.greeting_name(WEB, ENV, lookup) == "Asha"
    assert vc.greeting_name(OTHER, ENV, lookup) == "Ravi"


@pytest.mark.parametrize("rows", [[(WEB, "")], [(WEB, "   ")], [(OTHER, "Ravi")], [], [(WEB, "Asha 3000")], [(WEB, "x" * 80)], [(WEB, None)]])
def test_a_web_buyer_with_no_usable_name_is_greeted_as_there_never_as_the_default_name(rows):
    assert vc.greeting_name(WEB, ENV, _names(rows)) == "there"
    assert vc.greeting_name(WEB, ENV) == "there"   # no lookup at all
    assert vc.greeting_name(WEB, ENV, _names(rows)) != ENV[vc.NAME_ENV]


def test_a_failing_name_read_is_there():
    def boom(q):
        raise RuntimeError("HTTP 500")
    assert vc.greeting_name(WEB, ENV, vc.name_lookup_from_sql(boom)) == "there"


def test_the_bridge_greets_a_web_buyer_by_name(monkeypatch):
    monkeypatch.setattr(vc, "load_env", lambda *a, **k: dict(ENV))
    monkeypatch.setattr(bridge, "referee_phone_lookup", lambda args: vc.phone_lookup_from_sql(lambda q: [[WEB, "+14155550111"]]))
    monkeypatch.setattr(bridge, "referee_name_lookup", lambda args: _names([(WEB, "Asha")]))
    seen = {}
    monkeypatch.setattr(bridge, "make_live_approver", lambda gate, client, **kw: seen.update(kw) or (lambda s: {}))
    bridge.live_approver_for(types.SimpleNamespace(env_file=None, buyer_id=WEB), {}, types.SimpleNamespace(mandate=None), types.SimpleNamespace(note=lambda t: None))
    assert seen["buyer_name"] == "Asha"


def test_the_bridge_greets_a_web_buyer_with_an_empty_name_as_there_and_the_default_buyer_as_vidyut(monkeypatch):
    monkeypatch.setattr(vc, "load_env", lambda *a, **k: dict(ENV))
    monkeypatch.setattr(bridge, "referee_phone_lookup", lambda args: vc.phone_lookup_from_sql(lambda q: [[WEB, "+14155550111"]]))
    monkeypatch.setattr(bridge, "referee_name_lookup", lambda args: _names([(WEB, "")]))
    seen = {}
    monkeypatch.setattr(bridge, "make_live_approver", lambda gate, client, **kw: seen.update(kw) or (lambda s: {}))
    out = types.SimpleNamespace(note=lambda t: None)
    bridge.live_approver_for(types.SimpleNamespace(env_file=None, buyer_id=WEB), {}, types.SimpleNamespace(mandate=None), out)
    assert seen["buyer_name"] == "there"
    bridge.live_approver_for(types.SimpleNamespace(env_file=None, buyer_id=bridge.DB_BUYER_ID), {}, types.SimpleNamespace(mandate=None), out)
    assert seen["buyer_name"] == "Vidyut"
