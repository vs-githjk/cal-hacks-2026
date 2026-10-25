"""#257: one real CRS check of the winning payee at the payment gate, before the call and the charge.

A business payee needs a verified CrsCheck (pay.crs_gate.payee_ok), and the mandate carries that check's id
(crs_check_id, inside the mandate hash); bound_ok runs again before the charge. A SIM seller (one the operator's profile
file labels sim, #449 RT-25) is said to be unchecked; a payee with no profile is "not configured" and held. The result is
read on the call. The CRS adapter is faked; no network."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from demo import bridge
from demo.common import Narrator
from demo.run_demo import run_all
from demo.tests.test_bridge import FakeCartesia, clients, market_rows
from pay.crs_gate import check_id


@pytest.fixture(scope="module")
def run():
    return run_all(say=Narrator(False))


def crs_check(seller, verified=True, origin="SANDBOX", codes=None):
    return {"seller_id": seller, "product": "tu_identity", "verified": verified, "origin": origin,
            "reason_codes": codes or (["CRS_IDENTITY_VERIFIED"] if verified else ["CRS_IDENTITY_NOT_VERIFIED"]),
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def gate_with(run, outcome):
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    asked = []

    def checker(payee):
        asked.append(payee)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome(payee) if callable(outcome) else outcome
    gate.crs_check = checker
    return gate, asked


def go(run, gate, says="{code} approve"):
    client = FakeCartesia(lambda code: says.format(code=code))
    approver = bridge.make_live_approver(gate, client, buyer_name="Vidyut",
                                         on_code=lambda code, why: client.shown.update(code=code), secret="s" * 32,
                                         sleep=lambda x: None, poll=0)
    log, notes = [], []
    outcomes = bridge.execute(bridge.plan(run, delay=0, rounds=1, live_call=True), clients(log), delay=0,
                              say=lambda s: None, sleep=lambda x: None, clock=lambda: 0.0, approver=approver,
                              deal_gate=gate, note=notes.append)
    return log, outcomes, notes, client


def kinds(log):
    return [r for _, r, _ in log]


def test_a_verified_business_payee_is_checked_once_bound_into_the_mandate_and_read_on_the_call(run):
    winner = market_rows(run)[0][3]
    check = crs_check(winner)
    gate, asked = gate_with(run, {"business": True, "check": check, "cached": False})
    log, outcomes, notes, client = go(run, gate)
    assert asked == [winner] and outcomes[0]["approved"] is True and "record_payment" in kinds(log)
    assert gate.mandate["crs_check_id"] == check_id(check)
    spoken = client.calls[0][1]
    assert any("checked with CRS" in str(v) and "verified" in str(v) for v in spoken.values()), spoken
    assert any("CRS" in n and "verified" in n for n in notes)


@pytest.mark.parametrize("check,why", [
    (crs_check("best-buy", verified=False), "did not verify"),
    (crs_check("best-buy", verified=False, origin="NOT_CONFIGURED", codes=["CRS_NOT_CONFIGURED"]), "not configured"),
    (crs_check("someone-else"), "different seller"),
    (None, "not checked"),
])
def test_a_business_payee_without_a_verified_check_holds_the_gate_and_nothing_is_paid(run, check, why):
    gate, _ = gate_with(run, {"business": True, "check": check, "cached": False})
    log, outcomes, notes, client = go(run, gate)
    assert outcomes[0]["step"] == "build_mandate" and not outcomes[0]["approved"] and "CRS" in outcomes[0]["reason"]
    assert why in outcomes[0]["reason"].lower()
    assert not any(k in kinds(log) for k in ("create_mandate", "record_approval", "record_payment")) and client.calls == []
    assert any("nothing was paid" in n for n in notes)


def test_a_crs_error_or_timeout_holds_the_gate(run):
    gate, _ = gate_with(run, TimeoutError("CRS timed out"))
    log, outcomes, _, client = go(run, gate)
    assert not outcomes[0]["approved"] and "CRS" in outcomes[0]["reason"] and client.calls == []
    assert "record_payment" not in kinds(log)


def test_a_sim_seller_is_said_to_be_unchecked_and_the_deal_goes_on(run):
    gate, _ = gate_with(run, {"business": False, "check": None, "cached": False})
    log, outcomes, notes, client = go(run, gate)
    assert outcomes[0]["approved"] is True and "record_payment" in kinds(log)
    assert "crs_check_id" not in gate.mandate
    spoken = client.calls[0][1]
    assert any("not checked with CRS" in str(v) for v in spoken.values()), spoken
    assert any("SIM seller" in n for n in notes)


def test_a_swapped_check_after_the_call_is_refused_before_the_charge(run):
    winner = market_rows(run)[0][3]
    gate, _ = gate_with(run, {"business": True, "check": crs_check(winner), "cached": False})
    real_expect = gate.expect_now

    def swap():
        gate.crs = {**gate.crs, "check": crs_check(winner, origin="CACHED")}   # a different check id
        return real_expect()
    gate.expect_now = swap
    log, outcomes, _, _ = go(run, gate)
    assert outcomes[0]["approved"] is False and "crs" in outcomes[0]["reason"]
    assert "record_payment" not in kinds(log) and "record_approval" not in kinds(log)



def test_an_odd_answer_from_the_checker_holds_the_gate(run):
    gate, _ = gate_with(run, lambda payee: "not a dict")
    log, outcomes, _, client = go(run, gate)
    assert not outcomes[0]["approved"] and "CRS" in outcomes[0]["reason"] and client.calls == []


def test_an_unreadable_profile_file_holds_the_gate_through_the_default_checker(run, tmp_path, monkeypatch):
    bad = tmp_path / "private.json"
    bad.write_text("{not json")
    monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(bad))
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    log, outcomes, _, client = go(run, gate)
    assert not outcomes[0]["approved"] and "unreadable" in outcomes[0]["reason"] and client.calls == []
    assert "record_payment" not in kinds(log)


# ---- #449 RT-25: through the default checker, no profile file is "not configured" and held; only a "sim" label passes ----
def test_with_no_profile_file_the_default_checker_holds_the_gate_as_not_configured(run, monkeypatch):
    monkeypatch.delenv("CRS_TEST_IDENTITIES_PATH", raising=False)
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    log, outcomes, _, client = go(run, gate)
    assert not outcomes[0]["approved"] and "crs_not_configured" in outcomes[0]["reason"] and client.calls == []
    assert "record_payment" not in kinds(log) and "record_approval" not in kinds(log)


def test_a_profile_file_that_does_not_name_the_winner_holds_the_gate_as_not_configured(run, tmp_path, monkeypatch):
    other = tmp_path / "private.json"
    other.write_text(json.dumps({"sellers": {"somebody-else": {"seller_type": "sim"}}}))
    monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(other))
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    log, outcomes, _, client = go(run, gate)
    assert not outcomes[0]["approved"] and "crs_not_configured" in outcomes[0]["reason"] and client.calls == []


def test_a_winner_the_profile_file_labels_sim_passes_unchecked_and_says_so(run, tmp_path, monkeypatch):
    winner = market_rows(run)[0][3]
    labelled = tmp_path / "private.json"
    labelled.write_text(json.dumps({"sellers": {winner: {"seller_type": "sim"}}}))
    monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(labelled))
    gate = bridge.DealGate(run)
    gate.typed_approval_present = lambda: False
    log, outcomes, notes, client = go(run, gate)
    assert outcomes[0]["approved"] is True and "crs_check_id" not in gate.mandate
    assert any("SIM seller" in n for n in notes)
