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


# --- #317: a bad page never reads as ready, and no page can hang or crash the check ------------------------------------
def raw_page(product_json: str) -> str:
    return f'<html><script type="application/ld+json">{product_json}</script></html>'


def product_of(html: str) -> dict:
    return json.loads(html.split(">", 2)[2].rsplit("</script>", 1)[0])


def with_price(raw: str) -> str:
    """page() with offers.price replaced by raw JSON text (so 1e400 and NaN reach the parser as written)."""
    return page(price=123456.5).replace("123456.5", raw)


@pytest.mark.parametrize("raw", ["0", "-5", "1e400", "-1e400", "NaN", "Infinity", "[1]", '{"a": 1}', '"1.749,99"', '"1,749.99"',
                                 '"$5"', '"0"', '"-5"', '"abc"', '"nan"', '"1e400"', "true", '""', "null"])
def test_a_bad_price_blocks(raw):
    r = check_page("https://shop.example/x", with_price(raw), now=NOW)
    assert r["status"] == "blocks" and "listing.price_unreadable" in rules(r) and "price" not in r["facts_read"], raw


@pytest.mark.parametrize("raw,value", [("299.99", 299.99), ("5", 5.0), ('"299.99"', 299.99), ('" 1749 "', 1749.0)])
def test_a_plain_price_is_read(raw, value):
    r = check_page("https://shop.example/x", with_price(raw), now=NOW)
    assert r["status"] == "ready" and r["facts_read"]["price"] == value


def test_an_adversarial_script_soup_finishes_fast():
    import time
    from data.claim_check import page_facts
    for soup in ("<script x application/ld+json" * 70_000, "<script " * 250_000 + ">", "<script application/ld+json>" * 72_000,
                 '<script type="application/json" id="listing">' * 45_000, "<SCRIPT x application/ld+json>" + "</scrip" * 300_000):
        assert len(soup) >= 2_000_000
        t = time.monotonic()
        r = check_page("https://shop.example/x", soup, now=NOW)
        try:
            page_facts(soup)
        except ValueError:
            pass
        assert time.monotonic() - t < 2 and r["status"] != "ready"


def test_script_blocks_are_still_found_in_any_case_and_with_other_attributes():
    html = page().replace('<script type="application/ld+json">', '<SCRIPT nonce="ab" TYPE="Application/LD+JSON">').replace("</script>", "</SCRIPT >")
    assert check_page("https://shop.example/m27q", html, now=NOW)["status"] == "ready"


@pytest.mark.parametrize("html", [raw_page("[" * 100_000 + "]" * 100_000), raw_page('{"a":' * 100_000 + "1" + "}" * 100_000),
                                  '<script type="application/json" id="listing">' + "[" * 100_000 + "]" * 100_000 + "</script>",
                                  '<script type="application/json" id="listing">[1]</script>',
                                  '<script type="application/json" id="listing">"x"</script>',
                                  '<script type="application/json" id="listing">{bad</script>'])
def test_a_page_that_cannot_be_parsed_is_unreadable_never_ready(html):
    r = check_page("https://shop.example/x", html, now=NOW)
    assert r["status"] == "unreadable" and r["findings"] == [] and r["summary"].startswith("UNREADABLE")
    assert check_listing("https://shop.example/x", fetch=lambda u: html.encode(), now=NOW)["status"] == "unreadable"


@pytest.mark.parametrize("listing", ["[1]", '"x"', "7", "[" * 100_000 + "]" * 100_000])
def test_page_facts_handles_listing_json_that_is_not_an_object(listing):
    from data.claim_check import check_claim
    html = f'<script type="application/json" id="listing">{listing}</script>'
    r = check_claim({"text": "In stock", "evidence_url": "https://shop.example/x"}, fetch=lambda u: html.encode())
    assert r["result"] == "unverified"


def test_the_full_product_node_wins_over_a_bare_one_first():
    bare = {"@context": "https://schema.org/", "@type": "Product", "name": "SIM breadcrumb"}
    alone = check_page("https://shop.example/m27q", page(), now=NOW)
    both = check_page("https://shop.example/m27q", raw_page(json.dumps(bare)) + page(), now=NOW)
    graph = check_page("https://shop.example/m27q", raw_page(json.dumps({"@graph": [bare, product_of(page())]})), now=NOW)
    assert both["status"] == graph["status"] == alone["status"] == "ready" and both["facts_read"] == graph["facts_read"] == alone["facts_read"]


def test_the_product_whose_url_is_the_page_wins():
    other, mine = product_of(page(name="SIM Other Monitor", price=10)), product_of(page())
    mine["url"] = "https://shop.example/m27q"
    r = check_page("https://shop.example/m27q", raw_page(json.dumps([other, mine])), now=NOW)
    assert r["facts_read"]["price"] == 299.99 and r["facts_read"]["title"] == "SIM 27in Monitor M27Q"


@pytest.mark.parametrize("name", [["SIM 27in Monitor"], {"a": "SIM"}, 5, "", "  "])
def test_a_name_that_is_not_text_is_not_ready(name):
    r = check_page("https://shop.example/x", page(name="NAMEHERE").replace('"NAMEHERE"', json.dumps(name)), now=NOW)
    assert r["status"] != "ready" and "listing.name_unreadable" in rules(r) and "title" not in r["facts_read"]


@pytest.mark.parametrize("avail", [5, ["https://schema.org/InStock"], {"a": 1}, "https://schema.org/Banana", "InStockish", True])
def test_an_availability_that_is_not_a_schema_org_value_is_not_ready(avail):
    r = check_page("https://shop.example/x", page(availability="AVAIL").replace('"https://schema.org/AVAIL"', json.dumps(avail)), now=NOW)
    assert r["status"] != "ready" and "listing.stock_unknown" in rules(r) and "stock" not in r["facts_read"]


@pytest.mark.parametrize("avail", ["https://schema.org/InStock", "http://schema.org/InStock", "InStock", "schema:InStock",
                                   "https://schema.org/LimitedAvailability"])
def test_schema_org_availability_values_are_read(avail):
    r = check_page("https://shop.example/x", page(availability="AVAIL").replace('"https://schema.org/AVAIL"', json.dumps(avail)), now=NOW)
    assert r["status"] == "ready"


@pytest.mark.parametrize("t,ok", [(["Product", "Thing"], True), ("https://schema.org/Product", True), ("Product", True),
                                  ("NotAProduct", False), (["Thing"], False), ({"Product": 1}, False), (5, False), ("ProductCollection", False)])
def test_only_a_real_product_type_is_read(t, ok):
    r = check_page("https://shop.example/m27q", page().replace('"@type": "Product"', '"@type": ' + json.dumps(t)), now=NOW)
    assert (r["status"] == "ready") is ok and (r["read_from"] == "page JSON-LD") is ok


def test_a_restarted_run_summary_counts_the_listings_from_before_the_restart(monkeypatch):
    urls = [REAL_URL, "https://shop.example/ok", "https://shop.example/bare", "https://shop.example/gone"]
    actor = FakeActor({"listingUrls": urls})
    # the first run delivered two rows (warns, ready) and saved its counts, then the container died before OUTPUT was written
    actor.kv["STATE_next_listing"] = {"index": 2, "paid": False, "counts": {"blocks": 0, "warns": 1, "ready": 1, "unreadable": 0}}
    a, _ = run(monkeypatch, None, actor=actor)
    assert a.status[-1][0] == "4 listing(s): 1 blocks, 1 warns, 1 ready, 1 unreadable" and len(a.rows) == 2
    assert a.kv["OUTPUT"]["checked"] == 4


def test_the_state_saves_running_counts(monkeypatch):
    a, _ = run(monkeypatch, {"listingUrls": [REAL_URL, "https://shop.example/ok"]})
    assert a.kv["STATE_next_listing"]["counts"] == {"blocks": 0, "warns": 1, "ready": 1, "unreadable": 0}


def test_the_readme_says_it_is_not_published_yet():
    assert (ACTOR / "README.md").read_text().count("Not published on Apify yet") >= 2


def test_a_slow_drip_body_hits_the_overall_deadline():
    from data.claim_check import fetch as guarded
    clock = [0.0]

    class Drip:  # one byte every 10 s: never one socket timeout, but far past the overall deadline
        def read1(self, n):
            clock[0] += 10
            return b"x"
    with pytest.raises(ValueError, match="deadline"):
        guarded._read_body(Drip(), None, 1000, end=30.0, clock=lambda: clock[0])
    assert clock[0] <= 40


def test_a_redirect_chain_past_the_overall_deadline_stops():
    from data.claim_check import fetch as guarded
    clock = [0.0]

    def request(scheme, host, port, path, ip, timeout):
        assert timeout <= 30
        clock[0] += 12
        return 302, {"location": "/next"}, None
    with pytest.raises(ValueError, match="deadline"):
        guarded.guarded_get("https://shop.example/x", resolve=lambda h: ["93.184.216.34"], request=request, clock=lambda: clock[0])
