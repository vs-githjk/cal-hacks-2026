"""SHIELD-UNAVAIL-1750: one slow read or one 429/5xx must not quarantine an honest listing. No network here.

Live evidence (Oct 24, run_demo with the real key): 1 or 2 honest sellers per run were held with
shield.classifier.unavailable. Causes seen: a read that stalled to the 1.5 s socket timeout on a random listing
(about 1 call in 15, always fine again a moment later), and a reply whose first block was an empty "thinking" block
or whose text was cut at max_tokens=5 ("SUSPIC").
"""
import io
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from shield.classifier import ClaudeClassifier
from shield.core import screen

HONEST = "new per the listing free shipping eBay seller of item ...082384 (handle not captured): new 1,299.99"
SELLER = {"sender_role": "seller"}


class R:
    def __init__(self, payload):
        self._p = payload

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self._p).encode()


def _script(monkeypatch, steps):
    """Each call to urlopen takes the next step: an exception to raise or a payload to return."""
    calls = []

    def fake(req, timeout=None, context=None):
        calls.append(json.loads(req.data))
        step = steps[min(len(calls) - 1, len(steps) - 1)]
        if isinstance(step, BaseException):
            raise step
        return R(step)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def _http(code):
    return urllib.error.HTTPError("https://api.anthropic.com/v1/messages", code, "x", {}, io.BytesIO(b"{}"))


SAFE = {"content": [{"type": "text", "text": "SAFE"}]}


def test_one_read_timeout_is_retried_and_an_honest_listing_is_allowed(monkeypatch):
    calls = _script(monkeypatch, [TimeoutError("The read operation timed out"), SAFE])
    out = screen(HONEST, SELLER, classifier=ClaudeClassifier("k"))
    assert out["verdict"] == "allow" and out["rule_ids"] == []
    assert len(calls) == 2


@pytest.mark.parametrize("code", [429, 500, 503, 529])
def test_one_rate_limit_or_overload_is_retried(monkeypatch, code):
    calls = _script(monkeypatch, [_http(code), SAFE])
    assert ClaudeClassifier("k").classify(HONEST, {}) == "SAFE"
    assert len(calls) == 2


def test_one_connection_error_is_retried(monkeypatch):
    calls = _script(monkeypatch, [urllib.error.URLError("connection reset"), SAFE])
    assert ClaudeClassifier("k").classify(HONEST, {}) == "SAFE"
    assert len(calls) == 2


def test_the_secret_ask_call_is_retried_too(monkeypatch):
    tool = {"content": [{"type": "tool_use", "name": "report",
                         "input": {"ask_for_secret": False, "reason_code": "describes_item"}}]}
    calls = _script(monkeypatch, [TimeoutError("timed out"), tool])
    out = ClaudeClassifier("k").classify_secret_ask("State: like new, no password set", {})
    assert out["ask_for_secret"] is False and len(calls) == 2


def test_two_failures_in_a_row_still_fail_closed(monkeypatch):
    calls = _script(monkeypatch, [TimeoutError("t1"), TimeoutError("t2"), SAFE])
    out = screen(HONEST, SELLER, classifier=ClaudeClassifier("k"))
    assert out["verdict"] == "quarantine" and out["rule_ids"] == ["shield.classifier.unavailable"]
    assert len(calls) == 2  # one retry, not a loop


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_a_client_error_is_a_real_failure_and_is_not_retried(monkeypatch, code):
    calls = _script(monkeypatch, [_http(code), SAFE])
    out = screen(HONEST, SELLER, classifier=ClaudeClassifier("k"))
    assert out["verdict"] == "quarantine" and out["rule_ids"] == ["shield.classifier.unavailable"]
    assert len(calls) == 1


def test_no_retry_once_the_total_deadline_has_passed(monkeypatch):
    gate = threading.Event()
    calls = []

    def slow(req, timeout=None, context=None):
        calls.append(1)
        gate.wait(2)
        raise TimeoutError("late")
    monkeypatch.setattr(urllib.request, "urlopen", slow)
    clf = ClaudeClassifier("k", deadline=0.2)
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        clf.classify(HONEST, {})
    took = time.monotonic() - t0
    gate.set()
    assert len(calls) == 1 and took < 0.6, (len(calls), took)


def test_the_retry_fits_inside_the_total_deadline():
    from shield import classifier as c
    assert 2 * c.TIMEOUT_S <= c.DEADLINE_S  # two socket timeouts still end before the deadline


def test_a_leading_thinking_block_does_not_hide_the_text_answer(monkeypatch):
    _script(monkeypatch, [{"content": [{"type": "thinking", "thinking": "", "signature": "x"},
                                       {"type": "text", "text": "SAFE"}]}])
    assert ClaudeClassifier("k").classify(HONEST, {}) == "SAFE"


def test_a_reply_with_no_text_block_fails_closed(monkeypatch):
    _script(monkeypatch, [{"content": [{"type": "thinking", "thinking": "", "signature": "x"}]}])
    out = screen(HONEST, SELLER, classifier=ClaudeClassifier("k"))
    assert out["verdict"] == "quarantine" and out["rule_ids"] == ["shield.classifier.unavailable"]


def test_the_request_leaves_room_for_the_whole_word_and_turns_thinking_off(monkeypatch):
    calls = _script(monkeypatch, [SAFE])
    ClaudeClassifier("k").classify(HONEST, {})
    # "SUSPICIOUS\n\n" took 10 tokens live; at 5 the model's answer came back as "SUSPIC". test_core pins <= 10.
    assert calls[0]["max_tokens"] == 10
    assert calls[0]["thinking"] == {"type": "disabled"}


def test_a_full_suspicious_answer_is_read_as_suspicious(monkeypatch):
    _script(monkeypatch, [{"content": [{"type": "text", "text": "SUSPICIOUS\n\n"}]}])
    out = screen(HONEST, SELLER, classifier=ClaudeClassifier("k"))
    assert out["verdict"] == "quarantine" and out["rule_ids"] == ["shield.classifier.suspicious"]
