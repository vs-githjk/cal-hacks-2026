"""H3: a self-serve web buyer (b_...) is called on their OWN phone, read from the market's agent-only agent_buyer_contact view,
through the same client_for_buyer that demo/build.py and demo/bridge.py use. No phone on file is still a denial."""
from __future__ import annotations

import types

from demo import bridge, build
from pay import voice_cartesia as vc

ENV = {vc.KEY_ENV: "k" * 20, vc.AGENT_ENV: "agent-1", vc.TO_ENV: "+14155550123"}
WEB, OTHER = "b_web11111", "b_other222"


class _Out:
    def __init__(self):
        self.lines = []

    def note(self, text):
        self.lines.append(text)


def _lookup(rows):
    return vc.phone_lookup_from_sql(lambda q: [[i, p] for i, p in rows if f"buyer_id = '{i}'" in q])


def test_cartesia_for_a_web_buyer_dials_only_their_own_number_and_masks_it():
    out = _Out()
    client, reason = build.cartesia_for(WEB, ENV, out.note, lookup=_lookup([(WEB, "+14155550111"), (OTHER, "+14155550222")]))
    assert client.approval_call_to == "+14155550111" and reason == ""
    text = " ".join(out.lines)
    assert "+14155550111" not in text and "+14155550222" not in text and "+14155550123" not in text


def test_cartesia_for_a_web_buyer_with_no_phone_is_no_phone():
    out = _Out()
    client, reason = build.cartesia_for(WEB, ENV, out.note, lookup=_lookup([(OTHER, "+14155550222")]))
    assert client is None and reason == "no_phone"
    assert "+14155550222" not in " ".join(out.lines)


def test_the_bridge_dials_a_web_buyers_own_number(monkeypatch):
    monkeypatch.setattr(vc, "load_env", lambda *a, **k: dict(ENV))
    monkeypatch.setattr(bridge, "referee_phone_lookup", lambda args: _lookup([(WEB, "+14155550111")]))
    args = types.SimpleNamespace(env_file=None, buyer_id=WEB)
    _approver, where = bridge.live_approver_for(args, {}, types.SimpleNamespace(mandate=None), _Out())
    assert "ONE call to" in where and "+14155550111" not in where and "+14155550123" not in where


def test_the_bridge_denies_a_web_buyer_with_no_phone(monkeypatch):
    monkeypatch.setattr(vc, "load_env", lambda *a, **k: dict(ENV))
    monkeypatch.setattr(bridge, "referee_phone_lookup", lambda args: _lookup([]))
    args = types.SimpleNamespace(env_file=None, buyer_id=WEB)
    approver, where = bridge.live_approver_for(args, {}, types.SimpleNamespace(mandate={"hash": "h"}), _Out())
    assert "no phone" in where.lower() and "+14155550123" not in where
    assert approver(types.SimpleNamespace())["approved"] is False


def test_the_referee_lookup_fails_closed_without_a_referee_token_and_never_mints_an_identity(monkeypatch, tmp_path):
    args = types.SimpleNamespace(tokens_dir=str(tmp_path), server=None)
    monkeypatch.setattr(bridge, "live_target", lambda a: {"local": True, "server": "local", "db": "x"})
    monkeypatch.setattr(bridge, "find_tokens_dir", lambda explicit, target=None: tmp_path)
    lookup = bridge.referee_phone_lookup(args)   # building it touches nothing
    assert lookup(WEB) is None
    assert list(tmp_path.iterdir()) == []


def test_the_referee_lookup_reads_the_view_with_the_referee_identity(monkeypatch, tmp_path):
    (tmp_path / bridge.REFEREE_TOKEN).write_text("{}")
    seen = []

    class FakeMarket:
        def __init__(self, token_file=None):
            seen.append(token_file)

        def sql(self, q):
            seen.append(q)
            return [[WEB, "+14155550111"]]

    import sys
    monkeypatch.setitem(sys.modules, "stdb", types.SimpleNamespace(Market=FakeMarket))
    monkeypatch.setattr(bridge, "live_target", lambda a: {"local": True, "server": "local", "db": "x"})
    monkeypatch.setattr(bridge, "find_tokens_dir", lambda explicit, target=None: tmp_path)
    lookup = bridge.referee_phone_lookup(types.SimpleNamespace(tokens_dir=None))
    assert lookup(WEB) == "+14155550111"
    assert seen[0] == str(tmp_path / bridge.REFEREE_TOKEN) and "FROM agent_buyer_contact" in seen[1]
