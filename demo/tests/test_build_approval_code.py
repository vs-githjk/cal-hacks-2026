"""The whole-build approval code reaches the buyer's own /buyer screen while the one call is live (rehearsal 22:17: the code was only
printed to a console, /buyer said "Nothing is waiting for you", the call denied). The runner issues it to the market before dialing
(issue_build_approval_code, keyed by the aggregate mandate hash, which exists before any real mandate), and takes it down when the call
ends, whatever the outcome. The code never goes into the BuildView, so neither the hosted board nor GET /v1/build can carry it.
No network, no live call: the fake market and the fake Cartesia of the other build tests."""
from __future__ import annotations

import json

import pytest

from demo import build
from demo.build_sim import FakeMarket, make_clients
from demo.tests.test_bridge import FakeCartesia
from demo.tests.test_build import calls, kinds, run_build, sim_catalog

ISSUE, CLEAR = "issue_build_approval_code", "clear_build_approval_code"
ALLOW = {"per_purchase_limit": 250.0, "period_limit": 500.0, "period": "month"}


class MarkingCartesia(FakeCartesia):
    """Remembers how many market calls had happened when the phone was dialed."""
    def __init__(self, market, says):
        super().__init__(says)
        self.market, self.log_len_at_dial = market, None

    def create_call(self, to_number, variables):
        self.log_len_at_dial = len(self.market.log)
        return super().create_call(to_number, variables)


def run(m=None, tmp_path=None, says=lambda code: f"{code} approve", cart=None, **kw):
    m = m or FakeMarket()
    cart = cart or MarkingCartesia(m, says)
    return run_build(m, tmp_path=tmp_path, cartesia=cart, allowance=dict(ALLOW), **kw)


def test_one_code_row_is_issued_to_the_buyer_before_the_phone_rings_and_cleared_after(tmp_path):
    r, out, m, cart, notes = run(tmp_path=tmp_path)
    assert out["status"] == "paid"
    issues, clears = calls(m, ISSUE), calls(m, CLEAR)
    assert len(issues) == 1 and len(clears) == 1
    a = issues[0]
    assert a["buyer_id"] == r.plan.buyer_id and a["code"] == cart.shown["code"]
    assert a["amount"] == out["view"]["approval"]["total"] and a["amount"] > 0
    assert a["expiry_minutes"] == 5 and a["origin"] in ("SIM", "MIRROR", "LIVE")
    assert a["payee"].startswith("your whole build") and "6 parts" in a["payee"]
    assert clears[0] == {"mandate_hash": a["mandate_hash"]}
    order = [(n, rd) for n, rd, _ in m.log]
    issue_at, clear_at = order.index(("referee", ISSUE)), order.index(("referee", CLEAR))
    assert issue_at < cart.log_len_at_dial <= clear_at, "issued before the dial, cleared after the call"
    assert clear_at < order.index(("referee", "create_mandate")), "cleared before any per-part mandate exists"
    assert a["mandate_hash"] not in {args["hash"] for args in calls(m, "create_mandate")}, "the build hash is its own key, never a part's mandate"


def test_the_code_is_issued_by_the_referee_only_and_is_not_in_the_build_view_or_its_hosted_copy(tmp_path):
    r, out, m, cart, notes = run(tmp_path=tmp_path)
    assert {n for n, rd, _ in m.log if rd in (ISSUE, CLEAR)} == {"referee"}
    code = cart.shown["code"]
    assert code and code not in json.dumps(out["view"]) and code not in json.dumps(build.public_view(out["view"]))
    on_disk = (tmp_path / build.VIEW_FILE).read_text(encoding="utf-8")
    assert code not in on_disk
    assert code not in json.dumps(cart.calls), "the code is never sent to the call"


def test_a_denied_call_still_takes_the_code_down(tmp_path):
    r, out, m, cart, notes = run(tmp_path=tmp_path, says=lambda code: "no thanks")
    assert out["status"] == "denied" and "create_mandate" not in kinds(m)
    assert len(calls(m, ISSUE)) == 1 and len(calls(m, CLEAR)) == 1


def test_a_call_that_blows_up_still_takes_the_code_down(tmp_path):
    class Boom(MarkingCartesia):
        def get_call(self, call_id):
            raise ValueError("carrier exploded")
    m = FakeMarket()
    with pytest.raises(ValueError):
        run(m, tmp_path=tmp_path, cart=Boom(m, "approve"))
    assert len(calls(m, ISSUE)) == 1 and len(calls(m, CLEAR)) == 1


def test_a_market_that_refuses_the_code_stops_the_build_before_any_call_and_the_console_says_why(tmp_path):
    m = FakeMarket()
    m.fail[ISSUE] = "issue_build_approval_code refused (no buyer with that id)"
    r, out, m, cart, notes = run(m, tmp_path=tmp_path)
    assert out["status"] == "denied" and cart.calls == [], "no call is placed without the code on /buyer"
    assert "create_mandate" not in kinds(m) and "record_payment" not in kinds(m)
    assert calls(m, CLEAR) == [], "nothing was shown, so nothing to take down"
    text = "\n".join(notes)
    assert "NOT on /buyer" in text and "no buyer with that id" in text and "NOT placed" in text
    assert "say approve" not in text and "on this console" not in text


def test_a_market_that_was_not_republished_says_so_and_no_call_is_placed(tmp_path):
    m = FakeMarket()
    m.fail[ISSUE] = "HTTP 404: No such procedure issue_build_approval_code"
    r, out, m, cart, notes = run(m, tmp_path=tmp_path)
    assert out["status"] == "denied" and cart.calls == [] and len(calls(m, CLEAR)) == 0
    assert any("NOT on /buyer" in n and "republished" in n for n in notes)


def test_typed_approval_in_the_module_keeps_the_code_off_the_screen(tmp_path, monkeypatch):
    monkeypatch.setattr("demo.bridge.market_has_typed_approval", lambda *a, **k: True)
    r, out, m, cart, notes = run(tmp_path=tmp_path)
    assert calls(m, ISSUE) == [] and calls(m, CLEAR) == []
    assert out["status"] == "denied" and cart.calls == []
    assert any("NOT on /buyer" in n and "approve_typed" in n for n in notes)


def test_a_code_shown_on_the_screen_says_so_on_the_console(tmp_path):
    r, out, m, cart, notes = run(tmp_path=tmp_path)
    text = "\n".join(notes)
    assert "on /buyer now" in text and "NOT on /buyer" not in text


def test_the_default_console_line_still_prints_the_code_when_the_runner_has_no_custom_on_code(tmp_path):
    m = FakeMarket()
    cart = MarkingCartesia(m, lambda code: f"{code} approve")
    notes = []

    def say_code(text):   # the fake call reads the code off the console line, as Vidyut reads it off the screen
        notes.append(text)
        if "approval code for the call (read it, then say approve): " in text:
            cart.shown["code"] = text.rsplit(": ", 1)[1].strip()
    r = build.BuildRun(build.demo_plan(), make_clients(m), catalog=sim_catalog, allowance=dict(ALLOW), cartesia=cart, real_gpu_round=False,
                       secret="s" * 32, out_dir=tmp_path, note=say_code, sleep=lambda x: None, clock=lambda: 0.0, delay=0,
                       call_timing={"sleep": lambda x: None, "poll": 0})
    out = r.run()
    assert out["status"] == "paid"
    assert calls(m, ISSUE)[0]["code"] == cart.shown["code"], "the console and /buyer show the same code"


def test_a_clear_that_fails_is_a_warning_not_a_crash(tmp_path):
    m = FakeMarket()
    m.fail[CLEAR] = "market unreachable"
    r, out, m, cart, notes = run(m, tmp_path=tmp_path)
    assert out["status"] == "paid"
    assert any("could not be taken off /buyer" in n and "market unreachable" in n for n in notes)


def test_no_call_means_no_code(tmp_path):
    r, out, m, cart, notes = run_build(FakeMarket(), tmp_path=tmp_path, cartesia=None, allowance=dict(ALLOW))
    assert calls(m, ISSUE) == [] and calls(m, CLEAR) == []
