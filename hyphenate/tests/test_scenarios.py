"""The runner itself must be able to say MISSED: break one control at a time and watch the matching cases fail."""
import copy

import pytest

from hyphenate import matching, payables, procurement
from hyphenate.ledger import Ledger
from hyphenate.scenarios import dev_cases
from hyphenate.scenarios.runner import load, run_case, run_set, summarize


def verdicts(ids):
    by = {c["id"]: c for c in load("dev_cases")}
    return {i: run_case(by[i])["verdict"] for i in ids}


def test_dev_set_is_big_enough_and_all_caught_clean_ok():
    cases = load("dev_cases")
    assert sum(c["planted"] for c in cases) >= 20 and sum(not c["planted"] for c in cases) >= 6
    s = summarize(run_set("dev_cases", "dev"))
    assert s["missed"] == [] and s["false_positives"] == [] and s["explained"] == s["decisions"]


def test_wrong_answer_key_is_reported_as_missed():
    c = copy.deepcopy(next(c for c in dev_cases.CASES if c["id"] == "D01"))
    c["key"]["forbid_facts"] = ["invoice_status:{i1}:held"]
    assert run_case(c)["verdict"] == "missed"
    c = copy.deepcopy(next(c for c in dev_cases.CASES if c["id"] == "D01"))
    c["steps"].append({"do": "pay", "invoice": "nope", "at": "10-12"})
    assert run_case(c)["verdict"] == "error"


def test_without_the_three_way_match_the_match_cases_are_missed(monkeypatch):
    monkeypatch.setattr(payables, "match_lines", lambda *a, **k: [])
    v = verdicts(["D01", "D02", "D04", "D14", "D19", "D26"])
    assert set(v.values()) == {"missed"}


def test_without_the_mandate_guard_tampering_is_missed(monkeypatch):
    class Ok:
        ok = True
        reason = "ok"
        detail = ""

        def __bool__(self):
            return True

    monkeypatch.setattr(payables, "can_charge", lambda *a, **k: Ok())
    monkeypatch.setattr(payables, "mark_used", lambda *a, **k: None)
    assert set(verdicts(["D21", "D22"]).values()) == {"missed"}


def test_without_the_period_lock_the_bill_lands_in_a_closed_month(monkeypatch):
    monkeypatch.setattr(Ledger, "is_locked", lambda self, p: False)
    assert verdicts(["D25"])["D25"] != "caught"  # the ledger itself still refuses, so the run errors instead of passing
