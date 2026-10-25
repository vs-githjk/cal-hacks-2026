"""#355 item 3: the dated baseline refresh. Fakes only: no Apify call, no network, no spend."""
import json
from datetime import datetime, timezone

import pytest

import data.baselines as baselines
from data.baselines import refresh
from data.mirror import price_spread, run_actors

SECRET = "apify_api_DO_NOT_PRINT_123"


class Out:
    def __init__(self):
        self.lines = []

    def __call__(self, *a):
        self.lines.append(" ".join(str(x) for x in a))

    @property
    def text(self):
        return "\n".join(self.lines)


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """Point every path the pipeline writes or reads at tmp_path, so the repo's snapshots and feed are never touched."""
    for d in ("raw", "snapshots", "snapshots_b"):
        (tmp_path / d).mkdir()
    (tmp_path / "runs.json").write_text("[]")
    monkeypatch.setattr(run_actors, "HERE", tmp_path)
    monkeypatch.setattr(price_spread, "SNAPS", tmp_path / "snapshots")
    monkeypatch.setattr(baselines, "SECOND", tmp_path / "snapshots_b")
    monkeypatch.setattr(baselines, "HERE", tmp_path)
    monkeypatch.setattr(baselines, "RECORDED", tmp_path / "recorded")
    monkeypatch.setattr(refresh, "DOTENV", tmp_path / ".env")  # no .env: only the env dict given counts
    return tmp_path


def no_runner(*a, **k):
    raise AssertionError("no Apify run may start here")


def test_dry_run_shows_the_plan_and_cost_and_never_runs_or_needs_a_token(tmp_data):
    out = Out()
    code = refresh.main(["--dry-run"], env={}, runner=no_runner, out=out)
    assert code == 0
    for store, _ in refresh.DEFAULT_PLAN:
        assert store in out.text
    assert "benthepythondev/bestbuy-scraper" in out.text and "axlymxp/bestbuy-scraper" in out.text
    assert "estimated Apify cost" in out.text and "dry run: nothing was run" in out.text
    assert json.loads((tmp_data / "runs.json").read_text()) == [] and not (tmp_data / "feed.json").exists()


def test_without_a_token_it_fails_clearly_and_runs_nothing(tmp_data):
    out = Out()
    assert refresh.main(["--yes-spend"], env={}, runner=no_runner, out=out) == 2
    assert "APIFY_TOKEN is not set" in out.text


def test_without_yes_spend_and_no_terminal_it_refuses(tmp_data):
    out = Out()
    assert refresh.main([], env={"APIFY_TOKEN": SECRET}, runner=no_runner, out=out, isatty=lambda: False) == 2
    assert "--yes-spend" in out.text and SECRET not in out.text


def test_a_typed_confirmation_other_than_spend_refuses(tmp_data):
    out = Out()
    code = refresh.main([], env={"APIFY_TOKEN": SECRET}, runner=no_runner, out=out, isatty=lambda: True, confirm=lambda prompt: "yes")
    assert code == 2 and "not confirmed" in out.text


def test_an_estimate_over_the_spend_cap_refuses_even_with_yes_spend(tmp_data):
    out = Out()
    assert refresh.main(["--yes-spend", "--max-usd", "0.01"], env={"APIFY_TOKEN": SECRET}, runner=no_runner, out=out) == 2
    assert "over the --max-usd cap" in out.text


def test_max_items_is_capped(tmp_data):
    out = Out()
    with pytest.raises(SystemExit):
        refresh.main(["--dry-run", "--max-items", str(refresh.HARD_MAX_ITEMS + 1)], env={}, runner=no_runner, out=out)


def test_the_estimate_is_the_highest_logged_cost_per_actor_with_a_floor():
    log = [{"store": "microcenter", "actor": "sian.agency/microcenter-product-scraper", "cost_usd": 0.09275},
           {"store": "microcenter", "actor": "sian.agency/microcenter-product-scraper", "cost_usd": 0.05},
           {"store": "bestbuy", "actor": "benthepythondev/bestbuy-scraper", "cost_usd": 0.00005}]
    plan = refresh.estimate([("microcenter", False), ("bestbuy", False), ("bh", False)], log)
    assert [p["est_usd"] for p in plan] == [0.09275, refresh.FLOOR_USD, refresh.UNLOGGED_USD]


def test_stale_at_is_when_the_newest_retail_ask_leaves_the_24_h_window():  # the issue's case: 09:38Z -> 02:38 PDT Oct 25
    def r(store, price, at, kind="ask", provider="apify", sold=None):
        return {"provider": provider, "store": store, "sku": "rtx 5070 ti", "price": price, "in_stock": True, "condition": "new",
                "kind": kind, "observed_at": at, "sold_date": sold, "url": f"https://{store}.example/{price}"}
    rows = [r("microcenter", 1259.99, "2026-10-24T05:09:29Z"), r("microcenter", 1199.99, "2026-10-24T09:38:02Z"),
            r("microcenter", 1299.99, "2026-10-24T09:38:02Z"), r("bestbuy", 1249.99, "2026-10-24T09:36:33Z"),
            r("ebay_sold", 880.0, "2026-10-24T05:08:00Z", "sold", "ebay-sold", "2026-10-20T00:00:00Z"),
            r("ebay_sold", 900.0, "2026-10-24T05:08:00Z", "sold", "ebay-sold", "2026-10-21T00:00:00Z")]
    noon = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    at = refresh.stale_at("rtx 5070 ti", rows, noon)
    assert at == datetime(2026, 10, 25, 9, 38, 2, tzinfo=timezone.utc)
    assert refresh.pacific(at) == "2026-10-25 02:38 PDT"
    # with one 09:38 ask, the baseline goes thin (under 2 retail asks) when the 09:36 ask leaves, before the last one does
    assert refresh.stale_at("rtx 5070 ti", rows[:2] + rows[3:], noon) == datetime(2026, 10, 25, 9, 36, 33, tzinfo=timezone.utc)


def fake_apify(calls):
    """Stands in for run_actors.call: every Actor run succeeds with small dated items (SIM fixtures, not real listings)."""
    items = {
        "benthepythondev~bestbuy-scraper": [{"title": "ASUS Prime GeForce RTX 5070 Ti 16GB OC", "url": "https://bestbuy.test/a", "price": 1299.99, "condition": "new"},
                                            {"title": "MSI GeForce RTX 5070 Ti 16G Ventus 3X", "url": "https://bestbuy.test/b", "price": 1249.99, "condition": "new"}],
        "sian.agency~microcenter-product-scraper": [{"title": "Gigabyte GeForce RTX 5070 Ti Windforce", "url": "https://microcenter.test/c", "price": 1199.99}],
        "shahidirfan~B-H-Photo-Scraper": [],
        "caffein.dev~ebay-sold-listings": [{"title": "RTX 5070 Ti 16GB used", "url": "https://ebay.test/s1", "soldPrice": 900.0, "soldDate": "2026-10-20"},
                                           {"title": "RTX 5070 Ti 16GB", "url": "https://ebay.test/s2", "soldPrice": 950.0, "soldDate": "2026-10-21"}],
        "axlymxp~bestbuy-scraper": [{"title": "MSI GeForce RTX 5070 Ti 16G Ventus 3X", "url": "https://bestbuy.test/b", "price": 1249.99}],
    }
    state = {}

    def call(method, path, body=None, timeout=330):
        calls.append((method, path))
        if method == "POST" and path.startswith("/acts/"):
            actor = path.split("/")[2]
            state[actor] = items[actor]
            return {"data": {"id": f"RUN-{actor}", "status": "SUCCEEDED", "usageTotalUsd": 0.01, "defaultDatasetId": actor}}
        if path.startswith("/datasets/"):
            return state[path.split("/")[2]]
        raise AssertionError(path)
    return call


def test_a_confirmed_refresh_writes_dated_snapshots_regenerates_the_feed_and_prints_the_new_baseline(tmp_data, monkeypatch):
    calls = []
    monkeypatch.setattr(run_actors, "call", fake_apify(calls))
    out = Out()
    code = refresh.main(["--yes-spend", "--max-items", "5"], env={"APIFY_TOKEN": SECRET}, out=out)
    assert code == 0, out.text
    posts = [p for m, p in calls if m == "POST"]
    assert len(posts) == len(refresh.DEFAULT_PLAN) and all("maxItems=5" in p and "maxTotalChargeUsd=" in p for p in posts)
    assert sorted(f.name.rsplit("-", 1)[0] for f in (tmp_data / "snapshots").glob("*.json")) == ["bestbuy", "bh", "ebay_sold", "microcenter"]
    assert [f.name.rsplit("-", 1)[0] for f in (tmp_data / "snapshots_b").glob("*.json")] == ["bestbuy"]
    feed = json.loads((tmp_data / "feed.json").read_text())
    assert feed["origin"] == "MIRROR" and len(feed["rows"]) == 6
    assert len(json.loads((tmp_data / "runs.json").read_text())) == len(refresh.DEFAULT_PLAN)
    text = out.text
    assert "status ok" in text and "median $1249.99" in text and "n=3" in text
    assert "eBay sold" in text and "retailer listings (Apify)" in text and "goes stale at" in text and "PDT" in text
    assert "logged Apify cost this refresh: $0.05" in text
    assert SECRET not in text


def test_a_refresh_whose_runs_all_fail_says_so_and_exits_nonzero(tmp_data, monkeypatch):
    def down(method, path, body=None, timeout=330):
        raise OSError("apify down")
    monkeypatch.setattr(run_actors, "call", down)
    out = Out()
    assert refresh.main(["--yes-spend"], env={"APIFY_TOKEN": SECRET}, out=out) == 1
    assert "ERROR OSError" in out.text and "status empty" in out.text and SECRET not in out.text
