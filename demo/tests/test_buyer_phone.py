"""#374: the approval call goes to the buyer's own phone. Only the default buyer has a configured number today; above the allowance a buyer
with none gets a clear denial: no call, no mandate, no payment, and no scripted fallback (the phone call is the only approval)."""
from __future__ import annotations

import types

from demo import bridge, build
from demo.build_sim import FakeMarket, make_clients
from demo.tests.test_build import calls, kinds, sim_catalog
from pay import voice_cartesia as vc

ENV = {vc.KEY_ENV: "k" * 20, vc.AGENT_ENV: "agent-1", vc.TO_ENV: "+14155550123"}
ABOVE = {"per_purchase_limit": 10.0, "period_limit": 10.0, "period": "week"}


class _Out:
    def __init__(self):
        self.lines = []

    def note(self, text):
        self.lines.append(text)


def test_cartesia_for_the_default_buyer_is_a_client_for_the_env_number():
    out = _Out()
    client, reason = build.cartesia_for(bridge.DB_BUYER_ID, ENV, out.note)
    assert client is not None and client.approval_call_to == "+14155550123" and reason == ""
    assert "+14155550123" not in " ".join(out.lines)   # the number is masked in every line


def test_cartesia_for_another_buyer_is_no_client_and_the_no_phone_reason():
    out = _Out()
    client, reason = build.cartesia_for("someone-else", ENV, out.note)
    assert client is None and reason == "no_phone"
    assert "someone-else" in " ".join(out.lines) and "+14155550123" not in " ".join(out.lines)


def test_a_build_for_a_buyer_with_no_phone_above_the_allowance_is_denied_with_no_call_no_mandate_no_payment(tmp_path):
    notes = []
    plan = build.demo_plan(buyer_id="someone-else")
    m = FakeMarket()
    m.buyer_id = "someone-else"
    r = build.BuildRun(plan, make_clients(m), catalog=sim_catalog, allowance=dict(ABOVE), cartesia=None, no_call_reason="no_phone",
                       real_gpu_round=False, secret="s" * 32, out_dir=tmp_path, note=notes.append, sleep=lambda x: None, clock=lambda: 0.0,
                       delay=0)
    out = r.run()
    assert out["status"] == "denied" and out["reason"] == "no_phone"
    line = out["view"]["approval"]["reason"]
    assert "phone" in line.lower() and "nothing was paid" in line.lower()
    assert not set(kinds(m)) & {"create_mandate", "record_approval", "record_payment"}
    assert calls(m, "record_approval") == [] and m.approvals == {} and m.payments == {}


def test_a_build_without_a_client_for_another_reason_keeps_the_not_configured_denial(tmp_path):
    m = FakeMarket()
    r = build.BuildRun(build.demo_plan(), make_clients(m), catalog=sim_catalog, allowance=dict(ABOVE), cartesia=None, real_gpu_round=False,
                       secret="s" * 32, out_dir=tmp_path, sleep=lambda x: None, clock=lambda: 0.0, delay=0)
    assert r.run()["reason"] == "not_configured"


def test_the_bridge_denies_a_no_phone_buyer_at_the_approval_beat(monkeypatch):
    monkeypatch.setattr(vc, "load_env", lambda *a, **k: dict(ENV))
    out = _Out()
    args = types.SimpleNamespace(env_file=None, buyer_id="someone-else")
    gate = types.SimpleNamespace(mandate={"hash": "h"})
    approver, where = bridge.live_approver_for(args, {}, gate, out)
    assert "no phone" in where.lower() and "+14155550123" not in where
    res = approver(types.SimpleNamespace())
    assert res["approved"] is False and res["reason"].startswith("no_phone") and res["call_id"] is None


def test_the_bridge_still_dials_the_default_buyer(monkeypatch):
    monkeypatch.setattr(vc, "load_env", lambda *a, **k: dict(ENV))
    args = types.SimpleNamespace(env_file=None, buyer_id=bridge.DB_BUYER_ID)
    approver, where = bridge.live_approver_for(args, {}, types.SimpleNamespace(mandate=None), _Out())
    assert "ONE call to" in where and "+14155550123" not in where
