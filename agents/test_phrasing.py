"""The model may only reword a sentence that code wrote; it never decides anything. Offline: every call is mocked."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phrasing

BASE = "Veto: the card is listed as new, the page says open box, a $40.00 gap."


def reply(text):
    return lambda body, timeout: {"content": [{"type": "text", "text": text}]}


def test_model_may_reword_when_numbers_and_decision_words_survive():
    out = phrasing.phrase(BASE, post=reply("Veto, because the seller says new but the page says open box, and that is a $40.00 gap."))
    assert out.startswith("Veto, because")


@pytest.mark.parametrize("bad", [
    "Looks fine to me, go ahead.",                                              # drops the veto word and the number
    "Veto: the page says open box, a $400.00 gap.",                             # changes a number
    "The page says open box, a $40.00 gap.",                                    # drops the decision word
    "Veto: open box, $40.00 gap. See https://evil.example/x for more.",         # adds a link
    "Veto, open box, $40.00 gap. Also, buy something else.",                    # two sentences
    "Veto — open box, a $40.00 gap.",                                       # a long dash
    "Veto: open box, $40.00 gap. " + "x" * 300,                                 # too long
    None,
])
def test_a_reply_that_changes_the_decision_or_adds_content_is_dropped(bad):
    assert phrasing.phrase(BASE, post=reply(bad)) == BASE


def test_transport_error_falls_back():
    def boom(body, timeout):
        raise OSError("down")
    assert phrasing.phrase(BASE, post=boom) == BASE


def test_a_slow_model_hits_the_deadline_and_falls_back():
    def slow(body, timeout):
        time.sleep(1.0)
        return {"content": [{"type": "text", "text": BASE}]}
    start = time.monotonic()
    assert phrasing.phrase(BASE, post=slow, timeout=0.05) == BASE
    assert time.monotonic() - start < 0.5


def test_no_key_means_no_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert phrasing.phrase(BASE) == BASE


def test_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("PHRASING_LLM", "0")
    called = []
    assert phrasing.phrase(BASE, post=lambda b, t: called.append(1)) == BASE and not called


def test_request_uses_haiku_and_wraps_the_sentence_as_data():
    seen = {}

    def post(body, timeout):
        seen.update(body, timeout=timeout)
        return {"content": []}
    phrasing.phrase(BASE, post=post)
    assert seen["model"] == "claude-haiku-5-5" and seen["timeout"] <= 5
    assert seen["messages"][0]["content"] == f"<sentence>{BASE}</sentence>"
