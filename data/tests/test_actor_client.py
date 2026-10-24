"""#205: every way the claim-check Actor can fail gives 'unverified' with 'claim check unavailable', in one call. Fake client only."""
import pytest

from data.claim_check.actor_client import UNAVAILABLE, Down, Slow, check_via_actor

CLAIM = {"id": "c1", "text": "was $1,499.99", "kind": "price", "evidence_url": "https://www.bestbuy.com/site/x"}


def fake(status=200, rows=None, exc=None):
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body, timeout))
        if exc:
            raise exc
        return status, rows
    return post, calls


@pytest.mark.parametrize("case,kwargs", [
    ("down", {"exc": Down("ConnectError")}),
    ("down", {"status": 503, "rows": None}),
    ("slow", {"exc": Slow("ReadTimeout")}),
    ("slow", {"status": 408, "rows": None}),
    ("quota", {"status": 402, "rows": {"error": {"type": "not-enough-usage-to-run-paid-actor"}}}),
    ("quota", {"status": 429, "rows": None}),
    ("empty", {"status": 201, "rows": []}),
    ("error", {"status": 201, "rows": [{"id": "c1", "result": "maybe"}]}),
    ("error", {"status": 400, "rows": None}),
])
def test_each_failure_is_unverified_with_one_honest_line_and_one_call(case, kwargs):
    post, calls = fake(**kwargs)
    out = check_via_actor(CLAIM, post=post)
    assert out["result"] == "unverified" and out["result"] != "verified"
    assert out["reason"] == UNAVAILABLE and out["method"].startswith(f"{UNAVAILABLE}: {case}")
    assert out["evidence_url"] == CLAIM["evidence_url"]
    assert len(calls) == 1  # no retry, so a slow run is never started twice and never charged twice


def test_the_call_is_bounded():
    post, calls = fake(status=201, rows=[{**CLAIM, "result": "verified"}])
    check_via_actor(CLAIM, post=post, timeout=5)
    url, body, timeout = calls[0]
    assert timeout == 5 and url.endswith("?timeout=5") and body == {"claims": [CLAIM]}


def test_a_real_answer_passes_through_and_matches_the_claim_id():
    rows = [{"id": "other", "result": "verified"}, {**CLAIM, "result": "false", "reason": "differs from the listing", "evidence_hash": "ab"}]
    out = check_via_actor(CLAIM, post=fake(status=201, rows=rows)[0])
    assert out["result"] == "false" and out["evidence_hash"] == "ab"


def test_a_row_for_another_claim_is_not_used():
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[{"id": "x", "result": "verified"}, {"id": "y", "result": "verified"}])[0])
    assert out["result"] == "unverified" and out["method"].startswith(f"{UNAVAILABLE}: empty")


def test_the_token_is_never_in_the_result(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_SECRET123")
    post, calls = fake(exc=Down("ConnectError"))
    out = check_via_actor(CLAIM, post=post)
    assert "SECRET123" not in repr(out)
