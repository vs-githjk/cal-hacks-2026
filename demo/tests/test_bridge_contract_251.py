"""#251: the bridge speaks #240's approval and mandate contract (docs/changes/1131-B-approval-mandate.md on lane-b-191).

A strict fake referee enforces #240's reducer checks (market/spacetimedb/src/market.ts createMandate and recordApproval):
- create_mandate: deal_id names the rank 1 bid, payee is that bid's seller id, amount is its landed price exactly, and
  expiry_minutes is an integer from 1 to 10;
- record_approval: method is voice_code or allowance, and voice_code carries the VoiceApproval id from the call.
Item 1 of #251 (the scripted run's sim_script method, which #240 refuses) is held for a product answer, so only the
shape of its arguments is checked here."""
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


def test_the_scripted_record_approval_carries_every_240_argument(run):
    """Item 1 is held (sim_script vs #240), but the call already has the shape #240 reads."""
    appr = next(s for s in bridge.plan(run, delay=0, rounds=1) if s.reducer == "record_approval")
    assert set(appr.args) == {"mandate_hash", "method", "approved_by", "voice_approval_id"}
    assert appr.args["voice_approval_id"] == "" and appr.args["method"] == "sim_script"



def test_a_scripted_run_on_a_240_market_stops_at_the_approval_with_no_payment(run):
    """#251 item 1 is held: #240 refuses sim_script, so the scripted run stops there. Nothing is paid."""
    rows = market_rows(run)
    log = []
    with pytest.raises(RuntimeError, match="method must be one of"):
        bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=False), clients(log, rows), delay=0, say=lambda s: None,
                       sleep=lambda x: None, clock=lambda: 0.0, deal_gate=bridge.DealGate(run))
    kinds = [r for _, r, _ in log]
    assert "create_mandate" in kinds and kinds[-1] == "record_approval" and "record_payment" not in kinds
