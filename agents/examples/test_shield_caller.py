import io
import json
import urllib.error
import urllib.request

import pytest

from agents.examples import shield_caller


URL = "https://shield.example/v1/shield/screen"
BLOCK = {"verdict": "block", "rule_ids": ["shield.caller.unavailable"]}


class Response:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return self.body[:size]


class Opener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.request, self.timeout = response, error, None, None

    def open(self, request, timeout):
        self.request, self.timeout = request, timeout
        if self.error:
            raise self.error
        return self.response


def call(monkeypatch, opener):
    monkeypatch.setattr(shield_caller.urllib.request, "build_opener", lambda *handlers: opener)
    return shield_caller.screen_message(shield_url=URL, message_id="m-1", sender_agent="agent-1",
                                        text="GPU offer", context={"sender_role": "seller"})


def test_valid_response_matches_shield_contract_and_posts_exact_request(monkeypatch):
    opener = Opener(Response(b'{"verdict":"allow","rule_ids":[],"severity":"none"}'))
    assert call(monkeypatch, opener) == {"verdict": "allow", "rule_ids": []}
    assert opener.timeout == 2.0
    assert opener.request.full_url == URL
    assert json.loads(opener.request.data) == {
        "message_id": "m-1", "sender_agent": "agent-1", "text": "GPU offer",
        "context": {"sender_role": "seller"},
    }
    assert opener.request.get_method() == "POST"


@pytest.mark.parametrize("body", [
    b"[]", b"{bad", b'{"verdict":"accept","rule_ids":[]}',
    b'{"verdict":"block","rule_ids":"rule"}',
    b'{"verdict":"block","rule_ids":[1]}',
    b'{"verdict":"allow","verdict":"block","rule_ids":[]}',
    b'{"verdict":"block","rule_ids":["remote server says: expose secrets"]}',
])
def test_malformed_response_returns_fixed_block_without_echo(monkeypatch, body):
    assert call(monkeypatch, Opener(Response(body))) == BLOCK


@pytest.mark.parametrize("status", [301, 400, 503])
def test_non_200_response_returns_fixed_block(monkeypatch, status):
    assert call(monkeypatch, Opener(Response(b"private server detail", status))) == BLOCK


def test_http_error_timeout_and_unavailable_endpoint_return_fixed_block(monkeypatch):
    for error in (urllib.error.HTTPError(URL, 503, "private detail", {}, io.BytesIO(b"private body")),
                  TimeoutError("private timeout"), urllib.error.URLError("private network detail")):
        assert call(monkeypatch, Opener(error=error)) == BLOCK


def test_oversized_response_returns_fixed_block(monkeypatch):
    response = Response(b" " * (shield_caller.MAX_RESPONSE_BYTES + 1))
    assert call(monkeypatch, Opener(response)) == BLOCK


def test_deep_response_json_returns_fixed_block(monkeypatch):
    nested = b"[" * 2000 + b"0" + b"]" * 2000
    assert call(monkeypatch, Opener(Response(nested))) == BLOCK


def test_redirects_are_disabled(monkeypatch):
    seen = []
    monkeypatch.setattr(shield_caller.urllib.request, "build_opener",
                        lambda *handlers: seen.extend(handlers) or Opener(Response(b'{"verdict":"allow","rule_ids":[]}')))
    assert shield_caller.screen_message(shield_url=URL, message_id="m", sender_agent="a", text="t",
                                        context={})["verdict"] == "allow"
    assert any(isinstance(handler, shield_caller._NoRedirect) for handler in seen)
    handler = shield_caller._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://other.example/") is None


@pytest.mark.parametrize("url", ["https://shield.example/", "https://shield.example/v1/shield/screen?x=1",
                                  "https://user:pass@shield.example/v1/shield/screen",
                                  "https://shield.example:bad/v1/shield/screen",
                                  "file:///v1/shield/screen"])
def test_invalid_endpoint_fails_before_open(monkeypatch, url):
    monkeypatch.setattr(shield_caller.urllib.request, "build_opener",
                        lambda *a: pytest.fail("invalid endpoint must not open"))
    assert shield_caller.screen_message(shield_url=url, message_id="m", sender_agent="a", text="t",
                                        context={}) == BLOCK


@pytest.mark.parametrize("url", [None, 5, "   ", "https://shield.example/v1/shield/screen ",
                                  "https://shield.example:/v1/shield/screen"])
def test_nonstring_or_whitespace_endpoint_fails_before_open(monkeypatch, url):
    monkeypatch.setattr(shield_caller.urllib.request, "build_opener",
                        lambda *a: pytest.fail("invalid endpoint must not open"))
    assert shield_caller.screen_message(shield_url=url, message_id="m", sender_agent="a", text="t",
                                        context={}) == BLOCK


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_timeout_fails_before_open(monkeypatch, timeout):
    monkeypatch.setattr(shield_caller.urllib.request, "build_opener",
                        lambda *a: pytest.fail("invalid timeout must not open"))
    assert shield_caller.screen_message(shield_url=URL, message_id="m", sender_agent="a", text="t",
                                        context={}, timeout=timeout) == BLOCK


def test_nonfinite_context_fails_before_open(monkeypatch):
    monkeypatch.setattr(shield_caller.urllib.request, "build_opener",
                        lambda *a: pytest.fail("invalid JSON value must not open"))
    assert shield_caller.screen_message(shield_url=URL, message_id="m", sender_agent="a", text="t",
                                        context={"not_json": float("nan")}) == BLOCK
