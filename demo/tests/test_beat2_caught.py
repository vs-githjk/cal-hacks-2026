"""Beat 2 with the Shield classifier on (option C, locked Oct 24 18:20): Shield screens every round and records the
catch; a caught listing is never ranked or payable, but the advocate still judges it and its veto card, with its
sources, is shown labelled "Caught by Shield in round N". No network: a stub classifier stands in for Claude.

Live evidence behind it: with SHIELD_CLASSIFIER=1 and a key the classifier quarantines Shady Sam
(shield.classifier.suspicious) and, before this change, he vanished from beat 2 (no veto card, no sources).
Keyless the rules allow Sam and the advocate vetoes him from the ranking, as before.
"""
import copy
import io
from datetime import datetime, timezone

import pytest

from demo import run_demo
from demo.common import Narrator
from shield import core

NOW = datetime(2026, 10, 24, 5, 40, 0, tzinfo=timezone.utc)
SAM = "shady-sam"
SUSPICIOUS_RULE = "shield.classifier.suspicious"


class StubClassifier:
    """SUSPICIOUS for Shady Sam's page (it names the seller), SAFE for everyone else. Never touches the network."""

    def classify(self, message, context):
        return "SUSPICIOUS" if "shady" in message.lower() else "SAFE"

    def classify_secret_ask(self, text, context):
        return {"ask_for_secret": False, "reason_code": "describes_item"}


def _run(monkeypatch, classifier):
    monkeypatch.setattr(core, "default_classifier", lambda: classifier)
    buf = io.StringIO()
    run = run_demo.run_all(beats={2}, now=NOW, say=Narrator(True, buf))
    return run, buf.getvalue()


@pytest.fixture(scope="module")
def keyed(monkeypatch_module=None):
    mp = pytest.MonkeyPatch()
    try:
        yield _run(mp, StubClassifier())
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def keyless():
    mp = pytest.MonkeyPatch()
    try:
        yield _run(mp, None)
    finally:
        mp.undo()


def test_keyed_sam_is_caught_by_shield_and_never_ranked_or_payable(keyed):
    run, _ = keyed
    b2 = run["beats"]["2"]
    sv = next(v for v in b2["shield"] if v["seller_id"] == SAM)
    assert sv["verdict"] == "quarantine" and sv["rule_ids"] == [SUSPICIOUS_RULE]
    assert all(r["seller_id"] != SAM for r in b2["ranking"]["ranked"])
    assert any(d["seller_id"] == SAM and d["kind"] == "rejected" for d in b2["ranking"]["disqualified"])
    assert all(c["bid_id"] != sv["bid_id"] for c in b2["cards"])           # the ranked cards, winner and mandates never see him
    assert b2["winner"]["seller_id"] == "best-buy" and b2["winner"]["bid_id"] != sv["bid_id"]


def test_keyed_the_advocate_still_judges_the_caught_listing_and_the_veto_cites_sources(keyed):
    run, _ = keyed
    b2 = run["beats"]["2"]
    assert [c["seller_id"] for c in b2["caught"]] == [SAM]
    entry = b2["caught"][0]
    card = entry["card"]
    assert card["caught"] == {"by": "shield", "rule": SUSPICIOUS_RULE, "round": 1}
    assert entry["rule_ids"] == [SUSPICIOUS_RULE] and entry["round"] == 1
    assert card["recommendation"] == "veto" and card["call_reason"]["rule_id"] == "advocate.condition"
    assert {w["rule_id"] for w in card["warnings"]} == {"advocate.condition", "advocate.price"}
    assert all(w["source_url"].startswith("http") for w in card["warnings"])
    assert card["call_reason"]["source_url"].endswith("shady-sam-gpu-5070ti-lies.html")
    assert entry["landed"] < min(r["landed"] for r in b2["ranking"]["ranked"])   # he was the cheapest bid in the room


def test_keyed_beat2_prints_the_catch_and_the_veto_with_its_sources(keyed):
    _, text = keyed
    assert "Caught by Shield in round 1" in text
    assert SUSPICIOUS_RULE in text
    caught_at = text.index("Caught by Shield in round 1")
    assert "source: http" in text[caught_at:caught_at + 900]


def test_keyed_every_check_passes_and_the_beat2_check_counts_caught_and_vetoed(keyed):
    run, _ = keyed
    assert run["checks"]["beat2_cheapest_eligible_vetoed_with_source"] is True
    assert run["checks"]["beat2_caught_listing_never_ranked_or_payable"] is True
    assert all(run["checks"].values()), run["checks"]
    assert run["artifacts"]["verdicts"]["caught"][0]["seller_id"] == SAM


def test_keyed_a_caught_listing_that_is_not_vetoed_fails_the_beat2_check(keyed):
    run = copy.deepcopy(keyed[0])
    run["beats"]["2"]["caught"][0]["card"]["recommendation"] = "buy"
    assert run_demo.checks_of(run)["beat2_cheapest_eligible_vetoed_with_source"] is False


def test_keyed_a_caught_veto_without_a_source_fails_the_beat2_check(keyed):
    run = copy.deepcopy(keyed[0])
    run["beats"]["2"]["caught"][0]["card"]["warnings"][0]["source_url"] = ""
    assert run_demo.checks_of(run)["beat2_cheapest_eligible_vetoed_with_source"] is False


def test_keyed_a_caught_listing_that_got_ranked_fails_the_never_payable_check(keyed):
    run = copy.deepcopy(keyed[0])
    b2 = run["beats"]["2"]
    b2["ranking"]["ranked"].append({"bid_id": b2["caught"][0]["bid_id"], "seller_id": SAM, "landed": 1.0})
    assert run_demo.checks_of(run)["beat2_caught_listing_never_ranked_or_payable"] is False


def test_keyless_sam_is_not_caught_and_the_advocate_vetoes_him_from_the_ranking(keyless):
    run, text = keyless
    b2 = run["beats"]["2"]
    assert b2["caught"] == [] and "Caught by Shield" not in text
    assert b2["ranking"]["ranked"][0]["seller_id"] == SAM and b2["cards"][0]["recommendation"] == "veto"
    assert "caught" not in b2["cards"][0]
    assert run["checks"]["beat2_cheapest_eligible_vetoed_with_source"] is True
    assert "beat2_caught_listing_never_ranked_or_payable" not in run["checks"]
    assert all(run["checks"].values()), run["checks"]
