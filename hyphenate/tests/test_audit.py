import dataclasses

import pytest

from hyphenate.audit import AuditError, AuditLog

BASE = dict(at="2026-10-24T01:00:00Z", kind="invoice_match", subject="invoice:I1", outcome="hold", reason="2 of 10 units short",
            actor={"kind": "rule", "id": "match.qty"})


def test_decision_needs_reason_actor_and_a_trace():
    log = AuditLog()
    with pytest.raises(AuditError):
        log.record(**{**BASE, "reason": " "}, rule={"id": "r", "text": "t"})
    with pytest.raises(AuditError):
        log.record(**{**BASE, "actor": {"kind": "robot", "id": "x"}}, rule={"id": "r", "text": "t"})
    with pytest.raises(AuditError):  # a rule actor with no rule, no data, no parents traces to nothing
        log.record(**BASE)
    log.record(**BASE, evidence=[{"type": "receiving", "id": "R1", "detail": "8 units"}])
    log.record(**{**BASE, "actor": {"kind": "person", "id": "pepper"}})  # a person is a trace by itself


def test_chain_detects_edit_and_unknown_parent():
    log = AuditLog()
    a = log.record(**BASE, rule={"id": "r", "text": "t"})
    b = log.record(**BASE, rule={"id": "r", "text": "t"}, parents=[a.id])
    assert log.verify_chain() == []
    log.decisions[0] = dataclasses.replace(a, outcome="matched")
    assert log.verify_chain() == [a.id]
    with pytest.raises(AuditError):
        log.record(**BASE, rule={"id": "r", "text": "t"}, parents=["dec_9999"])


def test_explain_walks_parents_oldest_first_and_names_the_actor():
    log = AuditLog()
    a = log.record(**{**BASE, "kind": "receiving"}, evidence=[{"type": "receiving", "id": "R1", "detail": "8 units"}])
    b = log.record(**BASE, rule={"id": "match.qty", "text": "billed units may not exceed received units"}, parents=[a.id])
    x = log.explain(b.id)
    assert [c["id"] for c in x["chain"]] == [a.id]
    assert "match.qty" in x["text"] and "dec_0001" in x["text"] and "rule" in x["text"]
    with pytest.raises(AuditError):
        log.explain("dec_0042")
