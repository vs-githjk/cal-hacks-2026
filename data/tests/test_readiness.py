"""Seller Agent-Readiness Report (#271): what a shopping agent sees on a listing page, and the Actor's charging. apify is
stubbed; the real page is the saved Canada Computers JSON-LD (MIRROR, Oct 24 2026); everything else is a SIM page; no network."""
import asyncio
import functools
import importlib.util
import json
import socket
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.readiness import check_listing, check_page

ACTOR = Path(__file__).resolve().parents[1] / "readiness_actor"
REAL = (Path(__file__).resolve().parents[1] / "claim_check" / "fixtures" / "mirror-canadacomputers-269441.html").read_text()
REAL_URL = json.loads((ACTOR / ".actor" / "input_schema.json").read_text())["properties"]["listingUrls"]["prefill"][0]
NOW = datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


def page(name="SIM 27in Monitor M27Q", price=299.99, condition="NewCondition", availability="InStock", shipping=0, returns=30, mpn="M27Q"):
    """A SIM schema.org Product page (not a real store)."""
    offer = {"@type": "Offer", "price": price, "priceCurrency": "USD"}
    if condition:
        offer["itemCondition"] = f"https://schema.org/{condition}"
    if availability:
        offer["availability"] = f"https://schema.org/{availability}"
    if shipping is not None:
        offer["shippingDetails"] = {"@type": "OfferShippingDetails", "shippingRate": {"@type": "MonetaryAmount", "value": shipping, "currency": "USD"}}
    if returns is not None:
        offer["hasMerchantReturnPolicy"] = {"@type": "MerchantReturnPolicy", "merchantReturnDays": returns,
                                           "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow"}
    product = {"@context": "https://schema.org/", "@type": "Product", "name": name, "offers": offer}
    if mpn:
        product["mpn"] = mpn
    return f'<html><script type="application/ld+json">{json.dumps(product)}</script></html>'


def rules(r):
    return [f["rule_id"] for f in r["findings"]]


def test_the_real_canada_computers_page_warns_on_returns_and_shipping_only():
    r = check_page(REAL_URL, REAL, now=NOW)
    assert r["status"] == "warns" and sorted(rules(r)) == ["listing.returns_unknown", "listing.shipping_unknown"]
    assert r["facts_read"] == {"title": "MSI RTX 5070 TI 16G SHADOW 3X OC GDDR7 Triple Fans", "price": 1749.99, "condition": "new",
                               "stock": "SoldOut", "currency": "CAD"}
    assert r["read_from"] == "page JSON-LD" and r["origin"] == "LIVE" and all(f["source_url"] == REAL_URL for f in r["findings"])


def test_a_complete_listing_is_ready():
    r = check_page("https://shop.example/m27q", page(), now=NOW)
    assert r["status"] == "ready" and r["findings"] == [] and r["facts_read"]["shipping"] == 0.0 and r["summary"].startswith("READY")


def test_a_page_with_no_product_data_blocks():
    r = check_page("https://shop.example/x", "<html><h1>Great monitor $299</h1></html>", now=NOW)
    assert r["status"] == "blocks" and rules(r) == ["listing.no_structured_data"] and r["read_from"] == "no structured data"


def test_no_price_blocks_and_missing_fields_warn():
    r = check_page("https://shop.example/x", page(price=None, condition=None, availability=None, shipping=None, returns=None, mpn=None), now=NOW)
    assert r["status"] == "blocks" and set(rules(r)) == {"listing.price_unreadable", "listing.condition_unknown", "listing.returns_unknown",
                                                         "listing.model_unknown", "listing.shipping_unknown", "listing.stock_unknown"}


def test_a_title_claim_the_page_contradicts_blocks():  # "NEW" in the title, used in the Product data
    r = check_page("https://shop.example/x", page(name="SIM 27in Monitor M27Q NEW", condition="UsedCondition"), now=NOW)
    assert r["status"] == "blocks" and "claim.condition" in rules(r)


def test_gpu_fit_rows_never_run_because_our_maker_table_is_not_the_sellers_to_fix():
    r = check_page(REAL_URL, REAL, now=NOW)
    assert not [x for x in rules(r) if x.startswith("fit.")]


def test_every_finding_says_what_an_agent_sees_and_how_to_fix_it():
    r = check_page("https://shop.example/x", page(price=None, condition=None, returns=None, mpn=None), now=NOW)
    for f in r["findings"]:
        assert f["severity"] in ("blocks", "warns") and f["what_an_agent_sees"] and f["fix"] and f["source_url"]
        assert "—" not in f["what_an_agent_sees"] + f["fix"] and "–" not in f["what_an_agent_sees"] + f["fix"]


@pytest.mark.parametrize("err", [OSError("down"), ValueError("private address"), TimeoutError()])
def test_a_page_that_cannot_be_fetched_is_unreadable_never_ready(err):
    def fetch(url):
        raise err
    r = check_listing("https://shop.example/x", fetch=fetch, now=NOW)
    assert r["status"] == "unreadable" and r["findings"] == [] and r["summary"].startswith("UNREADABLE")


def test_a_non_http_url_is_unreadable_with_no_fetch():
    assert check_listing("file:///etc/passwd", fetch=lambda u: pytest.fail("must not fetch"))["status"] == "unreadable"


def test_the_default_fetch_is_the_guarded_one(monkeypatch):
    from data.claim_check import fetch as guarded
    seen = []
    monkeypatch.setattr(guarded, "guarded_get", lambda url: seen.append(url) or page().encode())
    assert check_listing("https://shop.example/m27q")["status"] == "ready" and seen == ["https://shop.example/m27q"]


# --- the Actor ------------------------------------------------------------------------------------------------------
class FakeActor:
    def __init__(self, inp, limit=99, fail_charge=False):
        self.inp, self.rows, self.kv, self.status, self.charges = inp, [], {}, [], []
        self.limit, self.fail_charge = limit, fail_charge

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_input(self):
        return self.inp

    async def push_data(self, row):
        self.rows.append(row)

    async def get_value(self, k):
        return self.kv.get(k)

    async def set_value(self, k, v):
        self.kv[k] = v

    async def set_status_message(self, msg, is_terminal=None):
        self.status.append((msg, is_terminal))

    async def charge(self, event_name, count):
        if self.fail_charge:
            raise RuntimeError("charge endpoint down")
        self.charges.append(event_name)
        return types.SimpleNamespace(event_charge_limit_reached=len(self.charges) >= self.limit, charged_count=count)

    class log:
        warning = staticmethod(print)


PAGES = {REAL_URL: REAL, "https://shop.example/ok": page(), "https://shop.example/bare": "<html>no data</html>"}


def fake_fetch(url):
    if url not in PAGES:
        raise OSError("not found")
    return PAGES[url].encode()


def run(monkeypatch, inp, actor=None, **kw):
    actor = actor or FakeActor(inp, **kw)
    apify = types.ModuleType("apify")
    apify.Actor = actor
    monkeypatch.setitem(sys.modules, "apify", apify)
    spec = importlib.util.spec_from_file_location("readiness_actor_main", ACTOR / "src" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "check_listing", functools.partial(check_listing, fetch=fake_fetch))
    asyncio.run(mod.main())
    return actor, mod


def test_the_default_form_reports_the_real_page(monkeypatch):
    form = {"listingUrls": [REAL_URL]}
    a, _ = run(monkeypatch, form)
    assert a.rows[0]["status"] == "warns" and a.charges == ["listing-reported"]
    assert a.status[-1] == (a.rows[0]["summary"], True) and a.kv["OUTPUT"]["results"] == a.rows


def test_a_batch_charges_every_read_page_and_never_an_unreadable_one(monkeypatch):
    urls = [REAL_URL, "https://shop.example/ok", "https://shop.example/bare", "https://shop.example/gone"]
    a, _ = run(monkeypatch, {"listingUrls": urls})
    assert [r["status"] for r in a.rows] == ["warns", "ready", "blocks", "unreadable"] and len(a.charges) == 3
    assert a.status[-1][0] == "4 listing(s): 1 blocks, 1 warns, 1 ready, 1 unreadable"


def test_urls_are_deduplicated_and_read_from_lines_or_request_objects(monkeypatch):
    _, mod = run(monkeypatch, {"listingUrls": ["https://shop.example/ok"]})
    assert mod.urls_from({"listingUrls": "https://a.example/1\n\n https://a.example/1 \nhttps://a.example/2"}) == ["https://a.example/1", "https://a.example/2"]
    assert mod.urls_from({"listingUrls": [{"url": "https://a.example/1"}, "https://a.example/1"]}) == ["https://a.example/1"]
    assert len(mod.urls_from({"listingUrls": [f"https://a.example/{i}" for i in range(500)]})) == mod.MAX_LISTINGS


def test_the_limit_stops_the_run_and_says_what_was_not_checked(monkeypatch):
    a, _ = run(monkeypatch, {"listingUrls": [REAL_URL, "https://shop.example/ok", "https://shop.example/bare"]}, limit=1)
    assert len(a.rows) == 1 and a.status[-1][0].endswith("2 not checked: your charge limit was reached")


def test_a_failed_charge_stops_and_delivers_nothing_unpaid(monkeypatch):
    a, _ = run(monkeypatch, {"listingUrls": [REAL_URL, "https://shop.example/ok"]}, fail_charge=True)
    assert a.rows == [] and "the charge failed" in a.status[-1][0]


def test_a_paid_listing_is_redelivered_on_restart_without_a_second_charge(monkeypatch):
    actor = FakeActor({"listingUrls": [REAL_URL, "https://shop.example/ok"]})
    actor.kv["STATE_next_listing"] = {"index": 0, "paid": True}  # charged, then the container died before delivery
    a, _ = run(monkeypatch, None, actor=actor)
    assert len(a.rows) == 2 and a.charges == ["listing-reported"]


def test_no_url_ends_with_a_clear_message(monkeypatch):
    a, _ = run(monkeypatch, {})
    assert a.rows == [] and a.status[-1] == ("No listing URL given: add one or more product page URLs", True)


def test_every_row_passes_the_dataset_schema_apify_validates(monkeypatch):
    import jsonschema
    fields = json.loads((ACTOR / ".actor" / "dataset_schema.json").read_text())["fields"]
    a, _ = run(monkeypatch, {"listingUrls": [REAL_URL, "https://shop.example/ok", "https://shop.example/bare", "https://shop.example/gone"]})
    for row in a.rows:
        jsonschema.validate(row, fields)


def test_the_bundled_actor_code_runs_on_its_own(tmp_path):
    subprocess.run(["sh", str(ACTOR / "bundle.sh")], check=True)
    code = (f"import sys; sys.path.insert(0, {str(ACTOR / 'src')!r}); "
            "from data.readiness import check_page; "
            f"print(check_page('https://x.example/p', open({str(ACTOR.parent / 'claim_check' / 'fixtures' / 'mirror-canadacomputers-269441.html')!r}).read())['status'])")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=tmp_path)
    assert out.stdout.strip() == "warns", out.stderr
