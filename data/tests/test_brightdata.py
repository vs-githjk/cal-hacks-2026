"""Bright Data Scraper API source (T6). No network: every call goes through httpx.MockTransport."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from data.baselines import brightdata as bd

KEY = "bd-test-key-0123456789abcdef"
NOW = datetime(2026, 10, 24, 11, 30, 0, tzinfo=timezone.utc)
ASUS_BB = "https://www.bestbuy.com/product/asus-prime-nvidia-geforce-rtx-5070-ti-oc-edition-16gb-gddr7-pci-express-5-0-graphics-card-black/JJGGLHJX4K/sku/6614742"


def record(price=1299.99, availability="In Stock", **extra):
    r = {"url": ASUS_BB, "title": "ASUS - PRIME NVIDIA GeForce RTX 5070 Ti OC Edition", "final_price": price,
         "availability": availability, "sku": "6614742"}
    r.update(extra)
    return r


class Fake:
    """A scripted transport: one response (or callable) per request, every request recorded."""

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
    fake = Fake(httpx.Response(200, json=[record()]))
    with pytest.raises(bd.NotConfigured):
        bd.observations(client=fake.client(), now=NOW)
    assert fake.requests == []
    s = bd.status()
    assert s == {"sponsor": "brightdata", "configured": False, "last_call": None, "last_result": "not_configured"}


def test_b_200_maps_to_apify_shaped_rows(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(200, json=[record()]))
    rows = bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB])
    assert len(rows) == 1
    r = rows[0]
    assert r["provider"] == "brightdata" and r["store"] == "bestbuy" and r["sku"] == "rtx 5070 ti"
    assert r["price"] == 1299.99 and r["in_stock"] is True and r["condition"] == "new" and r["kind"] == "ask"
    assert r["origin"] == "LIVE" and r["observed_at"] == "2026-10-24T11:30:00+00:00" and r["url"] == ASUS_BB
    # same keys the Apify rows carry, so baseline() needs no change
    from data.baselines import observations as apify_rows
    assert set(apify_rows()[0]) <= set(r)
    req = fake.requests[0]
    assert req.method == "POST" and req.url.path == "/datasets/v3/scrape"
    q = dict(req.url.params)
    assert q == {"dataset_id": "gd_ltre1jqe1jfr7cccf", "format": "json", "include_errors": "true"}
    body = json.loads(req.content)
    assert body == {"input": [{"url": ASUS_BB}], "custom_output_fields": "url|title|final_price|availability|sku"}
    assert bd.status()["last_result"] == "ok" and bd.status()["last_call"] == "2026-10-24T11:30:00+00:00"


def test_b2_availability_words_and_price_strings(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    for word, expect in (("In Stock", True), ("Sold Out", False), ("Out of Stock", False), ("Unavailable", False),
                         ("Available", True), (None, False), ("", False), ("Coming Soon", False)):
        bd.reset()
        fake = Fake(httpx.Response(200, json=[record(price="$1,299.99", availability=word)]))
        rows = bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB])
        assert rows[0]["price"] == 1299.99 and rows[0]["in_stock"] is expect, word
        assert rows[0]["availability"] == word, word   # the raw value rides along


def test_c_202_polls_at_most_three_times_then_slow(monkeypatch, clean):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(202, json={"snapshot_id": "s_123"}, headers={"retry-after": "4"}),
                httpx.Response(200, json={"status": "running"}, headers={"retry-after": "2"}))
    rows = bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB])
    assert rows == []
    paths = [r.url.path for r in fake.requests]
    assert paths == ["/datasets/v3/scrape"] + ["/datasets/v3/progress/s_123"] * 3
    assert clean == [4, 2, 2]  # honored retry-after, never a fabricated price
    assert bd.status()["last_result"] == "slow"


def test_c1_read_timeout_outlasts_the_servers_one_minute_wait():
    # Bright Data's sync /scrape holds the request up to 60 s before it answers 202; a shorter client timeout would give up first.
    assert bd.TIMEOUT.read > 60


def test_c1b_read_timeout_on_the_scrape_is_slow_not_error(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)

    def boom(request):
        raise httpx.ReadTimeout("no answer yet", request=request)

    fake = Fake(boom)
    assert bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB]) == []
    assert bd.status()["last_result"] == "slow"
    assert bd.last_error() == "ReadTimeout" and len(fake.requests) == 1  # one request, never retried


def test_c1c_connect_timeout_is_still_an_error(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)

    def boom(request):
        raise httpx.ConnectTimeout("unreachable", request=request)

    assert bd.observations(client=Fake(boom).client(), now=NOW, urls=[ASUS_BB]) == []
    assert bd.status()["last_result"] == "error"


def test_c2_202_ready_downloads_the_snapshot(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(202, json={"snapshot_id": "s_9"}),
                httpx.Response(200, json={"status": "ready"}),
                httpx.Response(200, json=[record()]))
    rows = bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB])
    assert [r.url.path for r in fake.requests] == ["/datasets/v3/scrape", "/datasets/v3/progress/s_9", "/datasets/v3/snapshot/s_9"]
    assert rows[0]["price"] == 1299.99 and rows[0]["snapshot_id"] == "s_9"
    assert bd.status()["last_result"] == "ok"


def test_c3_failed_snapshot_is_an_error_not_a_price(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(202, json={"snapshot_id": "s_9"}), httpx.Response(200, json={"status": "failed"}))
    assert bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB]) == []
    assert bd.status()["last_result"] == "error"


def test_d_empty_and_dead_page_return_nothing(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    assert bd.observations(client=Fake(httpx.Response(200, json=[])).client(), now=NOW, urls=[ASUS_BB]) == []
    assert bd.status()["last_result"] == "empty"
    bd.reset()
    dead = [{"url": ASUS_BB, "error": "Page not found", "error_code": "dead_page"}]
    assert bd.observations(client=Fake(httpx.Response(200, json=dead)).client(), now=NOW, urls=[ASUS_BB]) == []
    assert bd.status()["last_result"] == "empty"
    bd.reset()
    assert bd.observations(client=Fake(httpx.Response(200, json=[record(price=None)])).client(), now=NOW, urls=[ASUS_BB]) == []
    assert bd.status()["last_result"] == "empty"


def test_e_429_is_blocked_after_one_request_and_cools_down(monkeypatch, clean):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(429, text="slow down"))
    assert bd.observations(client=fake.client(), now=NOW) == []  # all six default targets
    assert len(fake.requests) == 1 and clean == []
    assert bd.status()["last_result"] == "blocked"
    assert bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB]) == []  # still cooling down
    assert len(fake.requests) == 1


def test_e2_customer_not_active_is_reported_and_not_retried(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    fake = Fake(httpx.Response(400, text="Customer is not active"))
    assert bd.observations(client=fake.client(), now=NOW) == []
    assert len(fake.requests) == 1
    assert bd.status()["last_result"] == "not_active"


def test_e3_other_failures_are_errors(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    for resp in (httpx.Response(401, text="bad key"), httpx.Response(500, text="boom"), httpx.Response(200, text="not json")):
        bd.reset()
        fake = Fake(resp)
        assert bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB]) == []
        assert bd.status()["last_result"] == "error" and len(fake.requests) == 1


def test_f_call_budget_stops_calls(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    monkeypatch.setenv("BRIGHT_DATA_MAX_CALLS", "2")
    fake = Fake(httpx.Response(200, json=[record()]))
    rows = bd.observations(client=fake.client(), now=NOW)
    assert len(fake.requests) == 2 and len(rows) == 2
    assert bd.observations(client=fake.client(), now=NOW) == []
    assert len(fake.requests) == 2
    assert bd.status()["last_result"] == "budget"


def test_f2_default_budget_is_eight_and_bad_values_fall_back(monkeypatch):
    assert bd.max_calls() == 8
    monkeypatch.setenv("BRIGHT_DATA_MAX_CALLS", "many")
    assert bd.max_calls() == 8
    monkeypatch.setenv("BRIGHT_DATA_MAX_CALLS", "0")
    assert bd.max_calls() == 0


def test_g_bearer_header_and_the_key_never_leaks(monkeypatch, caplog):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    echo = httpx.Response(401, text=f"invalid key {KEY}")
    fake = Fake(echo)
    caplog.set_level("DEBUG")
    bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB])
    assert fake.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in json.dumps(bd.status()) and KEY not in caplog.text

    def boom(request):
        raise httpx.ConnectError(f"cannot reach host with Bearer {KEY}", request=request)

    bd.reset()
    fake = Fake(boom)
    assert bd.observations(client=fake.client(), now=NOW, urls=[ASUS_BB]) == []
    assert bd.status()["last_result"] == "error"
    assert KEY not in json.dumps(bd.status()) and KEY not in caplog.text
    assert KEY not in repr(bd.last_error())


def test_targets_are_real_urls_from_the_mirror_snapshots():
    t = bd.load_targets()
    assert any(x["url"] == ASUS_BB and x["store"] == "bestbuy" for x in t)
    assert {x["store"] for x in t} <= {"bestbuy", "microcenter", "bh", "newegg"}
    snap_text = "".join(p.read_text() for p in (bd.ROOT / "data" / "mirror" / "snapshots").glob("*.json"))
    for x in t:
        assert x["url"] in snap_text, x["url"]  # copied, never invented
    stores = bd.load_stores()
    assert stores["bestbuy"]["dataset_id"] == "gd_ltre1jqe1jfr7cccf" and stores["bestbuy"]["mapping"] == "verified"
    for s in ("newegg", "microcenter", "bh"):
        assert stores[s]["mapping"] == "unverified"


def test_unverified_store_rows_say_so(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", KEY)
    mc = next(x["url"] for x in bd.load_targets() if x["store"] == "microcenter")
    fake = Fake(httpx.Response(200, json=[record(url=mc)]))
    rows = bd.observations(client=fake.client(), now=NOW, urls=[mc])
    assert rows[0]["store"] == "microcenter" and rows[0]["mapping"] == "unverified"
    assert dict(fake.requests[0].url.params)["dataset_id"] == "gd_mkckexq2uquhupguv"
