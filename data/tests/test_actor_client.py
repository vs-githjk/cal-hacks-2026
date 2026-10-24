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


# review fixes (#233)
def test_a_lone_row_for_another_claim_is_not_used():
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[{"id": "other", "result": "verified", "evidence_hash": "ab"}])[0])
    assert out["result"] == "unverified" and out["method"].startswith(f"{UNAVAILABLE}: empty")


def test_a_claim_with_no_id_does_not_match_a_row_naming_another_claim():
    claim = {k: v for k, v in CLAIM.items() if k != "id"}
    out = check_via_actor(claim, post=fake(status=201, rows=[{"id": "c9", "result": "verified", "evidence_hash": "ab"}])[0])
    assert out["result"] == "unverified"


@pytest.mark.parametrize("row", [{"result": "verified", "evidence_url": "https://ex.com/p", "evidence_hash": "abc"},
                                 {"id": None, "result": "verified", "evidence_url": "https://ex.com/p", "evidence_hash": "abc"}])
def test_a_lone_row_with_no_id_is_not_ours(row):  # #245 item 1
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[row])[0])
    assert out["result"] == "unverified" and out["method"].startswith(f"{UNAVAILABLE}: empty")


@pytest.mark.parametrize("result", ["verified", "false"])
def test_a_verdict_without_a_page_hash_is_unverified(result):
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[{**CLAIM, "result": result}])[0])
    assert out["result"] == "unverified" and out["reason"] == UNAVAILABLE


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", 5, ["https://x.example"]])
def test_a_verdict_with_a_non_http_evidence_url_is_unverified(url):
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[{**CLAIM, "result": "verified", "evidence_hash": "ab", "evidence_url": url}])[0])
    assert out["result"] == "unverified" and out["method"].startswith(f"{UNAVAILABLE}: error")


@pytest.mark.parametrize("exc", [ValueError("x"), RuntimeError("x"), OSError("x"), TypeError("x"),
                                 RuntimeError("token apify_api_SECRET123 in message")])
def test_any_other_exception_fails_safe_without_detail(exc):
    out = check_via_actor(CLAIM, post=fake(exc=exc)[0])
    assert out["result"] == "unverified" and out["method"] == f"{UNAVAILABLE}: error" and "SECRET123" not in repr(out)


@pytest.mark.parametrize("ret", [None, (None, []), ("200", []), (True, [])])
def test_a_missing_or_bad_status_fails_safe(ret):
    out = check_via_actor(CLAIM, post=lambda *a: ret)
    assert out["result"] == "unverified" and out["method"].startswith(f"{UNAVAILABLE}: error")


def test_a_sub_second_bound_is_not_sent_as_zero():
    post, calls = fake(status=201, rows=[])
    check_via_actor(CLAIM, post=post, timeout=0.5)
    assert calls[0][0].endswith("?timeout=1") and calls[0][2] == 0.5


# review fixes (#245)
OK = {**CLAIM, "result": "verified", "evidence_url": "https://www.bestbuy.com/site/x", "evidence_hash": "abc"}


def test_a_well_formed_row_still_passes_through():
    assert check_via_actor(CLAIM, post=fake(status=201, rows=[OK])[0])["result"] == "verified"


@pytest.mark.parametrize("h", ["   ", 123, True, ["x"], {"a": 1}])
def test_a_hash_that_is_not_a_real_string_is_unverified(h):
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[{**OK, "evidence_hash": h}])[0])
    assert out["result"] == "unverified"


@pytest.mark.parametrize("url", ["http://[bad", "http://", "https:///path", None])
def test_a_malformed_or_hostless_url_is_unverified_and_nothing_raises(url):
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[{**OK, "evidence_url": url}])[0])
    assert out["result"] == "unverified"


def test_a_row_without_its_own_url_does_not_borrow_the_claims():  # #245 item 6
    row = {k: v for k, v in OK.items() if k != "evidence_url"}
    assert check_via_actor(CLAIM, post=fake(status=201, rows=[row])[0])["result"] == "unverified"


class Exploding(dict):
    def get(self, *a, **k):
        raise KeyError("boom")


def test_a_row_that_raises_while_read_is_unverified():
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[Exploding(OK)])[0])
    assert out["result"] == "unverified" and out["method"] == f"{UNAVAILABLE}: error"


def test_a_missing_claim_never_raises():
    assert check_via_actor(None, post=fake(status=201, rows=[OK])[0])["result"] == "unverified"


def test_rows_for_one_claim_that_disagree_are_unverified():
    rows = [OK, {**OK, "result": "false"}]
    out = check_via_actor(CLAIM, post=fake(status=201, rows=rows)[0])
    assert out["result"] == "unverified" and "disagree" in out["method"]


def test_identical_duplicate_rows_are_fine():
    assert check_via_actor(CLAIM, post=fake(status=201, rows=[OK, dict(OK)])[0])["result"] == "verified"



# review fixes (#274)
@pytest.mark.parametrize("url", ["http://user@/x", "http://:80/x", "https://@/", "http://[::1"])
def test_a_url_without_a_host_is_unverified(url):
    assert check_via_actor(CLAIM, post=fake(status=201, rows=[{**OK, "evidence_url": url}])[0])["result"] == "unverified"


@pytest.mark.parametrize("other", [{"evidence_hash": "different"}, {"evidence_url": "https://www.bestbuy.com/site/other"}])
def test_duplicate_rows_must_agree_on_page_and_hash_too(other):
    out = check_via_actor(CLAIM, post=fake(status=201, rows=[OK, {**OK, **other}])[0])
    assert out["result"] == "unverified" and "disagree" in out["method"]


def test_a_boolean_id_never_matches_a_numeric_claim_id():
    claim = {**CLAIM, "id": 1}
    out = check_via_actor(claim, post=fake(status=201, rows=[{**OK, "id": True}])[0])
    assert out["result"] == "unverified" and out["method"].startswith(f"{UNAVAILABLE}: empty")
    assert check_via_actor(claim, post=fake(status=201, rows=[{**OK, "id": 1}])[0])["result"] == "verified"



# #270 step 3: an agent's own prepaid token
def test_an_agent_token_is_used_and_the_result_says_the_agent_paid(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_OURS")
    monkeypatch.setenv("APIFY_AGENT_TOKEN", "apify_api_AGENT")
    seen = []

    def post(url, body, headers, timeout):
        seen.append(headers)
        return 201, [OK]
    out = check_via_actor(CLAIM, post=post)
    assert seen[0] == {"Authorization": "Bearer apify_api_AGENT"} and out["paid_by"] == "using a prepaid agent token (set in the env)"
    assert out["result"] == "verified" and "apify_api_AGENT" not in repr(out)


def test_without_an_agent_token_our_account_pays_and_says_so(monkeypatch):
    monkeypatch.delenv("APIFY_AGENT_TOKEN", raising=False)
    monkeypatch.setenv("APIFY_TOKEN", "apify_api_OURS")
    seen = []
    out = check_via_actor(CLAIM, post=lambda url, body, headers, timeout: seen.append(headers) or (201, [OK]))
    assert seen[0] == {"Authorization": "Bearer apify_api_OURS"} and out["paid_by"] == "our Apify account"
