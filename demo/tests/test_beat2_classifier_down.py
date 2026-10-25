"""Beat 2 when the Shield classifier cannot answer (fail closed), no network.

Two Lows from the #376 review:
1. The classifier down for EVERY seller held every bid, there was no winner, and beat 2 crashed with a TypeError
   (w["seller_id"] on None). It must say no seller could be screened, rank and pay nothing, and not crash.
2. The "vetoed as cheaper" line said "caught by Shield" even when the hold came from an unavailable classifier;
   that is a hold, not a catch, and the line must say "held by Shield (classifier unavailable)".
"""
import io
from datetime import datetime, timezone

import pytest

from demo import run_demo
from demo.common import Narrator
from shield import core

NOW = datetime(2026, 10, 24, 5, 40, 0, tzinfo=timezone.utc)
SAM = "shady-sam"


class DownClassifier:
    """Every call fails, as an outage or a timeout would. Never touches the network."""

    def classify(self, message, context):
        raise TimeoutError("classifier down")

    def classify_secret_ask(self, text, context):
        raise TimeoutError("classifier down")


class SamOnlyDown:
    """The classifier is down for Shady Sam's text only; every other seller is SAFE."""

    def classify(self, message, context):
        if "shady" in message.lower():
            raise TimeoutError("classifier down")
        return "SAFE"

    def classify_secret_ask(self, text, context):
        return {"ask_for_secret": False, "reason_code": "describes_item"}


def _run(classifier, beats=frozenset({2})):
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(core, "default_classifier", lambda: classifier)
        buf = io.StringIO()
        run = run_demo.run_all(beats=set(beats), now=NOW, say=Narrator(True, buf))
        return run, buf.getvalue()
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def all_down():
    return _run(DownClassifier())


@pytest.fixture(scope="module")
def sam_down():
    return _run(SamOnlyDown())


def test_classifier_down_for_every_seller_does_not_crash_and_ranks_and_pays_nothing(all_down):
    run, _ = all_down
    b2 = run["beats"]["2"]
    assert b2["winner"] is None and b2["winner_bid"] is None
    assert b2["winner_seller_id"] is None and b2["winner_note"] is None
    assert b2["ranking"]["ranked"] == [] and b2["cards"] == []
    assert {v["verdict"] for v in b2["shield"]} == {"quarantine"}
    assert all("shield.classifier.unavailable" in v["rule_ids"] for v in b2["shield"])


def test_classifier_down_for_every_seller_says_no_seller_could_be_screened(all_down):
    _, text = all_down
    assert "no seller could be screened" in text.lower()
    assert "nothing is ranked or paid" in text.lower()
    assert "winner:" not in text
    assert "Caught by Shield" not in text          # a hold from an outage is never called a catch


def test_classifier_down_for_every_seller_the_demo_checks_fail_honestly_not_crash(all_down):
    run, _ = all_down
    assert run["checks"]["beat2_cheapest_eligible_vetoed_with_source"] is False
    assert run["checks"]["beat2_winner_is_a_real_mirror_seller"] is False
    assert run["checks"]["beat2_caught_listing_never_ranked_or_payable"] is True


def test_vetoed_line_says_held_not_caught_when_the_hold_came_from_an_unavailable_classifier(sam_down):
    run, text = sam_down
    b2 = run["beats"]["2"]
    assert [e["seller_id"] for e in b2["caught"]] == [SAM]
    assert b2["caught"][0]["rule"] == "shield.classifier.unavailable"
    line = next(l for l in text.splitlines() if "vetoed as cheaper" in l)
    assert "held by Shield (classifier unavailable)" in line
    assert "caught by Shield" not in line


def test_vetoed_line_still_says_caught_when_the_classifier_called_it_suspicious():
    class Suspicious(SamOnlyDown):
        def classify(self, message, context):
            return "SUSPICIOUS" if "shady" in message.lower() else "SAFE"

    run, text = _run(Suspicious())
    assert run["beats"]["2"]["caught"][0]["rule"] == "shield.classifier.suspicious"
    line = next(l for l in text.splitlines() if "vetoed as cheaper" in l)
    assert "caught by Shield" in line and "classifier unavailable" not in line
