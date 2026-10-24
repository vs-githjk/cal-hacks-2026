"""Bright Data discovery (T16): leads from the Google Shopping scraper. No network: httpx.MockTransport only."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from data.baselines import brightdata as bd
from data.baselines import brightdata_discover as disc

KEY = "bd-test-key-0123456789abcdef"
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
NEWEGG = "https://www.newegg.com/p/N82E16814126666"
SHOP = "https://www.example-gpu-shop.com/products/prime-5070-ti"
LABEL = "found by Bright Data, not a seller agent"


class Fake:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return r(request) if callable(r) else r

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False)
    monkeypatch.delenv("BRIGHT_DATA_MAX_CALLS", raising=False)
    bd.reset()
    slept = []
    monkeypatch.setattr(bd, "_sleep", slept.append)
    return slept


def test_a_no_key_raises_and_makes_no_request():
    fake = Fake(httpx.Response(200, json=[{"url": NEWEGG}]))
    with pytest.raises(bd.NotConfigured):
        disc.discover("rtx 5070 ti", client=fake.client(), now=NOW)
    assert fake.requests == []
    assert bd.status()["last_result"] == "not_configured" and bd.status()["last_call"] is None


def test_b_200_maps_to_leads_that_are_not_bids(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(200, json=[
        {"url": NEWEGG, "title": "ASUS Prime RTX 5070 Ti", "country": "US", "input": {"keyword": "rtx 5070 ti"}},
        {"url": SHOP, "country": "US"},
    ]))
    leads = disc.discover("rtx 5070 ti", client=fake.client(), now=NOW)
    assert [(l["url"], l["store"], l["title"]) for l in leads] == [
        (NEWEGG, "newegg", "ASUS Prime RTX 5070 Ti"), (SHOP, "example-gpu-shop.com", None)]
    for l in leads:
        assert l["origin"] == "LIVE" and l["kind"] == "lead" and l["label"] == LABEL
        assert l["observed_at"] == "2026-10-24T12:00:00+00:00" and l["sku"] == "rtx 5070 ti"
        assert "price" not in l  # discovery returns no price: a lead is priced only by a store scrape later
        assert "seller_id" not in l and "bid" not in l  # never shaped like a bid
    req = fake.requests[0]
    assert req.method == "POST" and req.url.path == "/datasets/v3/scrape"
    assert dict(req.url.params) == {"dataset_id": "gd_ltppk50q18kdw67omz", "format": "json", "include_errors": "true",
                                    "type": "discover_new", "discover_by": "keyword"}
    body = json.loads(req.content)
    assert body["input"] == [{"keyword": "rtx 5070 ti", "country": "US"}]
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert bd.status()["last_result"] == "ok" and bd.status()["last_call"] == "2026-10-24T12:00:00+00:00"


def test_c_429_stops_after_one_request_and_cools_down(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(429, text="slow down"))
    assert disc.discover("rtx 5070 ti", client=fake.client(), now=NOW) == []
    assert len(fake.requests) == 1 and bd.status()["last_result"] == "blocked"
    assert disc.discover("rtx 5070 ti", client=fake.client(), now=NOW) == []
    assert len(fake.requests) == 1  # cooldown: no second call
    # the cooldown is shared with T6, so a price re-check does not call either
    assert bd.observations(client=fake.client(), now=NOW) == [] and len(fake.requests) == 1


def test_d_untrusted_records_are_dropped_or_cleaned(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    long_title = "A" * 500
    fake = Fake(httpx.Response(200, json=[
        {"url": "javascript:alert(1)", "title": "x"},
        {"url": "ftp://files.example.com/gpu"},
        {"url": "not a url"},
        {"url": NEWEGG, "error": "dead page", "error_code": "dead_page"},
        {"url": NEWEGG, "warning": "no results", "warning_code": "no_results"},
        {"url": 5},
        "junk",
        {"url": NEWEGG, "title": long_title},
        {"url": NEWEGG, "title": "duplicate"},
    ]))
    leads = disc.discover("rtx 5070 ti", client=fake.client(), now=NOW)
    assert [l["url"] for l in leads] == [NEWEGG]
    assert leads[0]["title"] == "A" * 200


def test_e_empty_and_non_list_answers(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    for payload in ([], {"error": "x"}, [{"error": "bad", "warning": "none"}]):
        bd.reset()
        fake = Fake(httpx.Response(200, json=payload))
        assert disc.discover("rtx 5070 ti", client=fake.client(), now=NOW) == []
        assert bd.status()["last_result"] == "empty"


def test_f_202_polls_at_most_three_times_then_slow(monkeypatch, clean):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    running = httpx.Response(200, json={"status": "running"}, headers={"retry-after": "4"})
    fake = Fake(httpx.Response(202, json={"snapshot_id": "s_1"}, headers={"retry-after": "2"}), running)
    assert disc.discover("rtx 5070 ti", client=fake.client(), now=NOW) == []
    paths = [r.url.path for r in fake.requests]
    assert paths == ["/datasets/v3/scrape"] + ["/datasets/v3/progress/s_1"] * 3
    assert clean == [2.0, 4.0, 4.0] and bd.status()["last_result"] == "slow"


def test_g_202_then_ready_downloads_the_snapshot(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(202, json={"snapshot_id": "s_2"}), httpx.Response(200, json={"status": "ready"}),
                httpx.Response(200, json=[{"url": NEWEGG}]))
    leads = disc.discover("rtx 5070 ti", client=fake.client(), now=NOW)
    assert [l["url"] for l in leads] == [NEWEGG]
    assert fake.requests[-1].url.path == "/datasets/v3/snapshot/s_2"
    assert bd.status()["last_result"] == "ok"


def test_h_read_timeout_is_slow_and_other_failures_are_errors(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)

    def timeout(request):
        raise httpx.ReadTimeout("too slow, key " + KEY)

    fake = Fake(timeout)
    assert disc.discover("rtx 5070 ti", client=fake.client(), now=NOW) == []
    assert bd.status()["last_result"] == "slow"
    assert KEY not in repr(bd.last_error()) and bd.last_error() == "ReadTimeout"
    bd.reset()
    fake = Fake(httpx.Response(500, text="boom"))
    assert disc.discover("rtx 5070 ti", client=fake.client(), now=NOW) == []
    assert bd.status()["last_result"] == "error"
    bd.reset()
    fake = Fake(httpx.Response(400, text="Customer is not active"))
    assert disc.discover("rtx 5070 ti", client=fake.client(), now=NOW) == []
    assert bd.status()["last_result"] == "not_active" and len(fake.requests) == 1


def test_i_budget_is_shared_with_the_price_source(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    monkeypatch.setenv("BRIGHT_DATA_MAX_CALLS", "1")
    fake = Fake(httpx.Response(200, json=[{"url": NEWEGG}]))
    assert len(disc.discover("rtx 5070 ti", client=fake.client(), now=NOW)) == 1
    assert disc.discover("rtx 5070 ti", client=fake.client(), now=NOW) == []
    assert len(fake.requests) == 1 and bd.status()["last_result"] == "budget"


def test_j_blank_keyword_is_refused_before_any_request(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(200, json=[{"url": NEWEGG}]))
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            disc.discover(bad, client=fake.client(), now=NOW)
    assert fake.requests == []


def test_k_key_never_in_exception_or_state(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)

    def boom(request):
        raise httpx.ConnectError("connect failed for " + request.headers["authorization"])

    assert disc.discover("rtx 5070 ti", client=Fake(boom).client(), now=NOW) == []
    assert KEY not in json.dumps(bd.status()) and bd.last_error() == "ConnectError"
