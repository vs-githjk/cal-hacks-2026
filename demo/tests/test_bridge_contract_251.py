"""#251: the bridge speaks #240's approval and mandate contract (docs/changes/1131-B-approval-mandate.md on lane-b-191).

A strict fake referee enforces #240's reducer checks (market/spacetimedb/src/market.ts createMandate and recordApproval):
- create_mandate: deal_id names the rank 1 bid, payee is that bid's seller id, amount is its landed price exactly, and
  expiry_minutes is an integer from 1 to 10;
- record_approval: method is voice_code or allowance, and voice_code carries the VoiceApproval id from the call.
There is no scripted approval (#251 item 1, Vidyut 12:15): a run without --live-call ends at the approval gate."""
from __future__ import annotations

import pytest

from demo import bridge
from demo.common import Narrator
from demo.run_demo import run_all
from demo.tests.test_bridge import FakeCartesia, market_rows

APPROVAL_METHODS = ("voice_code", "allowance")
MAX_EXPIRY_MIN = 10


@pytest.fixture(scope="module")
def run():
    return run_all(say=Narrator(False))


class StrictReferee:
    """The referee as #240's module sees it: refuses what createMandate and recordApproval refuse."""

    def __init__(self, log, rows):
        self.log, self.rows, self.mandates = log, rows, {}

    def sql(self, query):
        assert query == "SELECT * FROM round_result"
        return self.rows

    def call(self, reducer, **a):
        self.log.append(("referee", reducer, a))
        if reducer == "create_mandate":
            rank1 = next(r for r in self.rows if r[5] == 1)
            if a["deal_id"] != f"deal-{rank1[2]}":
                raise RuntimeError("a mandate needs the rank 1 bid of a closed round")
            if a["payee"] != rank1[3]:
                raise RuntimeError(f"payee must be the winning seller ({rank1[3]})")
            if abs(a["amount"] - rank1[6]) > 1e-9:
                raise RuntimeError("amount must equal the winning landed price")
            if not (isinstance(a["expiry_minutes"], int) and 1 <= a["expiry_minutes"] <= MAX_EXPIRY_MIN):
                raise RuntimeError("expiry must be 1 to 10 minutes")
            self.mandates[a["hash"]] = a
        if reducer == "record_approval":
            assert set(a) == {"mandate_hash", "method", "approved_by", "voice_approval_id"}, sorted(a)
            if a["method"] not in APPROVAL_METHODS:
                raise RuntimeError(f"method must be one of {', '.join(APPROVAL_METHODS)}")
            if a["method"] == "voice_code" and not str(a["voice_approval_id"]).strip():
                raise RuntimeError("a voice approval needs the VoiceApproval id from the call")
            if a["mandate_hash"] not in self.mandates:
                raise RuntimeError("no mandate with that hash")


class Loose:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def call(self, reducer, **a):
        self.log.append((self.name, reducer, a))


def clients(log, rows):
    r = run_all(say=Narrator(False))
    names = ["buyer"] + sorted({s.actor for s in bridge.plan(r) if s.actor.startswith("seller:")})
    return {"referee": StrictReferee(log, rows), **{n: Loose(log, n) for n in names}}


def live(run, says="{code} approve"):
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    client = FakeCartesia(lambda code: says.format(code=code))

    def show(code, why_not):
        client.shown["code"] = code

    approver = bridge.make_live_approver(gate, client, buyer_name="Vidyut", on_code=show, secret="s" * 32,
                                         sleep=lambda x: None, poll=0)
    return gate, approver


def go(run, rows, gate, approver):
    log = []
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), clients(log, rows), delay=0,
                              say=lambda s: None, sleep=lambda x: None, clock=lambda: 0.0, approver=approver, deal_gate=gate)
    return log, outcomes


@pytest.mark.parametrize("first,second", [("best-buy", "gadget-grove"), ("gadget-grove", "best-buy")])
def test_a_live_call_run_passes_240s_mandate_and_approval_checks(run, first, second):
    rows = market_rows(run, first=first, second=second)
    gate, approver = live(run)
    log, outcomes = go(run, rows, gate, approver)
    made = next(a for _, r, a in log if r == "create_mandate")
    assert made["payee"] == first and made["amount"] == rows[0][6] and made["expiry_minutes"] == bridge.MANDATE_MINUTES
    appr = next(a for _, r, a in log if r == "record_approval")
    assert appr["method"] == "voice_code" and appr["voice_approval_id"] == outcomes[0]["voice_approval_id"]
    assert appr["voice_approval_id"].startswith("apr_")
    assert "record_payment" in [r for _, r, _ in log] and outcomes[0]["approved"] is True


def test_the_mandate_amount_is_the_landed_price_as_the_market_holds_it(run):
    rows = market_rows(run)
    gate, approver = live(run)
    log, _ = go(run, rows, gate, approver)
    made = next(a for _, r, a in log if r == "create_mandate")
    assert made["amount"] == rows[0][6] and gate.mandate["amount"] == rows[0][6]


@pytest.mark.parametrize("landed", [1299.987, 1199.99 + 100.000001])
def test_a_landed_price_with_more_than_cents_makes_no_mandate_and_pays_nothing(run, landed):
    """#240 compares the mandate to the landed price to 1e-9 and the call reads the amount in whole cents: a price that is
    not whole cents cannot satisfy both, so the bridge makes no mandate (fail closed) rather than rounding."""
    rows = [list(r) for r in market_rows(run)]
    rows[0][6] = landed
    gate, approver = live(run)
    log, outcomes = go(run, [tuple(r) for r in rows], gate, approver)
    assert outcomes[0]["step"] == "build_mandate" and "whole number of cents" in outcomes[0]["reason"]
    assert not any(r in ("create_mandate", "record_approval", "record_payment") for _, r, _ in log)


def test_the_payee_is_the_seller_id_in_the_mandate_hash_and_the_charge_check(run):
    from pay.mandate import mandate_hash
    rows = market_rows(run)
    gate, approver = live(run)
    go(run, rows, gate, approver)
    m = gate.mandate
    assert m["payee"] == rows[0][3] and mandate_hash(m) == m["hash"]
    assert gate.expect_now()["payee"] == rows[0][3]


def test_an_approved_call_with_no_voice_approval_id_is_denied_and_nothing_is_recorded(run, monkeypatch):
    import pay.voice_cartesia as vc
    real = vc.run_approval_call

    def no_record(*a, **k):
        res = real(*a, **k)
        res.record = None
        return res

    monkeypatch.setattr(vc, "run_approval_call", no_record)
    gate, approver = live(run)
    log, outcomes = go(run, market_rows(run), gate, approver)
    assert outcomes[0]["approved"] is False and "voice_approval_id" in outcomes[0]["reason"]
    assert not any(r in ("record_approval", "record_payment") for _, r, _ in log)


def test_the_planned_approval_is_never_a_scripted_method(run):
    """No scripted approval (#251, Vidyut 12:15): the only method the plan can name is the real call's, with an id slot for it."""
    for live_call in (False, True):
        appr = next(s for s in bridge.plan(run, delay=0, rounds=1, live_call=live_call) if s.reducer == "record_approval")
        assert set(appr.args) == {"mandate_hash", "method", "approved_by", "voice_approval_id"}
        assert appr.args["method"] == "voice_code" and appr.args["voice_approval_id"] == ""
    assert "sim_script" not in repr(bridge.plan(run, delay=0, rounds=2)) and "sim_script" not in repr(bridge.plan(run, delay=0, rounds=2, live_call=True))


def test_a_run_without_a_call_stops_at_the_approval_gate_and_pays_nothing(run):
    """No --live-call: the mandate is made and held, then the run ends at the gate. No record_approval, no payment, no beat 5."""
    rows, log, notes = market_rows(run), [], []
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=False), clients(log, rows), delay=0, say=lambda s: None,
                              sleep=lambda x: None, clock=lambda: 0.0, deal_gate=bridge.DealGate(run), note=notes.append)
    kinds = [r for _, r, _ in log]
    assert "create_mandate" in kinds
    assert not any(k in kinds for k in ("record_approval", "record_payment", "record_loss_report"))
    assert [(o["step"], o["approved"]) for o in outcomes] == [("approval_call", False)] and outcomes[0]["reason"].startswith("no_live_call")
    assert any("approval needs the real phone call (--live-call); nothing was paid" in n for n in notes)


def test_a_run_without_a_call_releases_the_held_unit(run):
    rows, log = market_rows(run), []
    bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=False), clients(log, rows), delay=0, say=lambda s: None,
                   sleep=lambda x: None, clock=lambda: 0.0, deal_gate=bridge.DealGate(run))
    assert [r for _, r, _ in log].count("deny_approval") == 1


HELD = "held back: advocate caution (fit.unconfirmed: card length not on the listing)"


def with_reasons(rows, index, reasons):
    rows = [list(r) for r in rows]
    rows[index][7] = reasons
    return [tuple(r) for r in rows]


def test_a_held_back_rank_one_makes_no_mandate_and_places_no_call(run):
    """The market writes 'held back: advocate caution (...)' on rank 1 when every bid carries a caution. The agent buys nothing."""
    rows = with_reasons(market_rows(run), 0, [HELD])
    gate, approver = live(run)
    log, outcomes = go(run, rows, gate, approver)
    assert outcomes[0]["step"] == "build_mandate" and not outcomes[0]["approved"] and "held back" in outcomes[0]["reason"]
    assert gate.mandate is None
    assert not any(r in ("create_mandate", "record_approval", "record_payment", "issue_approval_code") for _, r, _ in log)


def test_the_gate_refuses_a_held_back_rank_one_whatever_else_its_reasons_say(run):
    gate = bridge.DealGate(run)
    for reasons in ([HELD], ["within budget", HELD]):
        with pytest.raises(bridge.GateRefused, match="held back"):
            gate.expectations(with_reasons(market_rows(run), 0, reasons))
    assert gate.expectations(with_reasons(market_rows(run), 0, ["within budget"]))["payee"] == "best-buy"


def test_only_rank_ones_reasons_hold_the_gate(run):
    """A held-back rank 2 is the market doing its job (it ranks below every bid not held back): rank 1 still gets its mandate."""
    gate, approver = live(run)
    log, outcomes = go(run, with_reasons(market_rows(run), 1, [HELD]), gate, approver)
    assert outcomes[0]["approved"] is True and "create_mandate" in [r for _, r, _ in log]


def test_a_rank_one_that_turns_held_back_after_the_call_is_not_paid(run):
    """expect_now reads the market again after the call; a row that changed to held back denies the charge."""
    rows = market_rows(run)
    gate, approver = live(run)
    gate.prepare(StrictReferee([], rows))
    gate._referee = StrictReferee([], with_reasons(rows, 0, [HELD]))
    with pytest.raises(bridge.GateRefused, match="held back"):
        gate.expect_now()
