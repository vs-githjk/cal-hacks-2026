"""c3 claim check against the SIM liar pages (served from disk through an injected fetcher)."""
import json
from data.claim_check import check_claim, parse_claim
from data.liar_pages.build import SITE, build

build()
BASE = "http://localhost:8765/"


def fetch(url):
    return (SITE / url.removeprefix(BASE)).read_bytes()


def claim(text, page, kind="spec", **extra):
    return {"id": "c", "bid_id": "b", "text": text, "kind": kind, "evidence_url": BASE + page, **extra}


def check(text, page, **kw):
    return check_claim(claim(text, page, **kw), fetch=fetch)


SAM_GPU_LIES = "shady-sam-gpu-5070ti-lies.html"
HAL_GPU = "honest-hal-gpu-5070ti.html"


def test_parse_claim_texts():
    assert parse_claim({"text": "Brand new, sealed", "kind": "spec"}) == ("condition", "new")
    assert parse_claim({"text": "was $1,099", "kind": "price"}) == ("was_price", 1099.0)
    assert parse_claim({"text": "$789.00", "kind": "price"}) == ("price", 789.0)
    assert parse_claim({"text": "Socket AM5", "kind": "spec"}) == ("socket", "AM5")
    assert parse_claim({"text": "in stock", "kind": "stock"}) == ("stock", True)
    assert parse_claim({"text": "30-day returns", "kind": "returns"}) == ("return_days", 30)


def test_open_box_listed_as_new_is_false():
    out = check("Brand new, factory sealed", SAM_GPU_LIES)
    assert out["result"] == "false" and out["evidence_url"].endswith(SAM_GPU_LIES)
    assert "open-box" in out["reason"]


def test_fake_was_price_is_false_against_price_history():
    out = check("was $1,099", SAM_GPU_LIES, kind="price")
    assert out["result"] == "false" and "price history" in out["reason"]


def test_wrong_socket_is_false_against_maker_table():
    out = check("Socket AM5", "shady-sam-cpu-5800x3d-lies.html")
    assert out["result"] == "false" and "AM4" in out["reason"]


def test_honest_claims_verify():
    for text, kind in (("New", "spec"), ("$789", "price"), ("in stock", "stock"), ("30-day returns", "returns")):
        assert check(text, HAL_GPU, kind=kind)["result"] == "verified", text
    assert check("Socket AM4", "honest-hal-cpu-5800x3d.html")["result"] == "verified"


def test_price_mismatch_is_false():
    assert check("$699", HAL_GPU, kind="price")["result"] == "false"


def test_unparseable_claim_is_unverified():
    assert check("best card ever", HAL_GPU)["result"] == "unverified"


def test_unreachable_page_is_unverified_not_false():
    def broken(url):
        raise OSError("down")
    out = check_claim(claim("New", HAL_GPU), fetch=broken)
    assert out["result"] == "unverified" and out["method"].startswith("could not verify")


def test_output_shape_and_hash():
    out = check("New", HAL_GPU)
    assert {"result", "evidence_url", "checked_at", "method", "evidence_hash", "reason"} <= out.keys()
    assert len(out["evidence_hash"]) == 64


def test_wording_never_calls_a_store_a_liar():
    for text, page, kind in (("Brand new", SAM_GPU_LIES, "spec"), ("was $1,099", SAM_GPU_LIES, "price"), ("$699", HAL_GPU, "price")):
        reason = check(text, page, kind=kind)["reason"].lower()
        assert "lie" not in reason and "liar" not in reason and "wrong" not in reason


# review fixes (#9): malformed pages never crash, never "false"
def page_with(body):
    return lambda url: body


def check_body(text, body, kind="price"):
    return check_claim({"id": "c", "bid_id": "b", "text": text, "kind": kind, "evidence_url": BASE + "x.html"}, fetch=page_with(body))


def assert_could_not_verify(out):
    assert out["result"] == "unverified" and out["method"].startswith("could not verify"), out


def test_bad_listing_json_is_unverified():
    assert_could_not_verify(check_body("$789", b'<script type="application/json" id="listing">{not json</script>'))


def test_json_ld_price_na_is_unverified():
    ld = b'<script type="application/ld+json">{"@type": "Product", "offers": {"price": "N/A"}}</script>'
    assert_could_not_verify(check_body("$789", ld))


def test_string_body_is_unverified_or_read():
    out = check_body("$789", '<script type="application/json" id="listing">{"price": 789.0}</script>')
    assert out["result"] in ("verified", "unverified")


def test_list_body_is_unverified():
    assert_could_not_verify(check_body("$789", ["not", "bytes"]))


def test_price_field_with_no_value_is_unverified():
    for v in (b'""', b"null", b'"N/A"'):
        assert check_body("$789", b'<script type="application/json" id="listing">{"price": ' + v + b"}</script>")["result"] == "unverified"


def test_only_http_and_https_urls_are_fetched():
    called = []
    out = check_claim({"id": "c", "bid_id": "b", "text": "$789", "kind": "price", "evidence_url": "file:///etc/hosts"},
                      fetch=lambda url: called.append(url) or b"")
    assert_could_not_verify(out)
    assert not called


def test_not_in_stock_parses_as_out_of_stock():
    assert parse_claim({"text": "Not in stock", "kind": "stock"}) == ("stock", False)
    assert parse_claim({"text": "currently unavailable", "kind": "stock"}) == ("stock", False)


def test_page_saying_not_in_stock_does_not_verify_an_in_stock_claim():
    for text in ("Not in stock", "Currently unavailable", "Sold out", "Out of stock", "OutOfStock"):
        body = b'<script type="application/json" id="listing">{"stock": "' + text.encode() + b'"}</script>'
        assert check_body("in stock", body, kind="stock")["result"] == "false", text


def test_default_fetch_is_the_ssrf_guarded_fetch():
    import pytest
    from data.claim_check import default_fetch
    from data.claim_check.fetch import guarded_get
    assert default_fetch is guarded_get
    with pytest.raises(ValueError):
        default_fetch("http://169.254.169.254/latest/meta-data/")


def test_false_price_inside_a_sentence_is_not_hidden_by_other_fields():  # #76: first match used to win
    for text in ("New RTX 5070 Ti for only $749", "In stock now at $749", "$749 new, 30-day returns"):
        out = check(text, HAL_GPU, kind="price")
        assert out["result"] == "false" and "$749.00" in out["reason"], text


def test_was_price_five_dollars_above_history_high_is_false():
    c = claim("was $1,105", HAL_GPU, kind="price")
    out = check_claim(c, fetch=fetch, history=[{"date": "2026-10-01", "price": 1100.0}])
    assert out["result"] == "false"
    assert check_claim(claim("was $1,100", HAL_GPU, kind="price"), fetch=fetch,
                       history=[{"date": "2026-10-01", "price": 1100.0}])["result"] == "verified"


def test_private_ranges_are_refused_before_connecting():
    import pytest
    from data.claim_check.fetch import guarded_get
    for ip in ("10.1.2.3", "172.16.5.4", "192.168.1.1"):
        calls = []
        with pytest.raises(ValueError, match="address not allowed"):
            guarded_get("http://shop.example/x", resolve=lambda h, ip=ip: [ip], request=lambda *a: calls.append(a))
        assert calls == [], ip


FIX = __import__("pathlib").Path(__file__).resolve().parents[1] / "claim_check" / "fixtures"


def fixture_check(text, name):
    return check_claim({"text": text, "kind": "returns", "evidence_url": f"https://store.example/{name}"},
                       fetch=lambda url: (FIX / url.rsplit("/", 1)[1]).read_bytes())


def test_returns_read_from_json_ld_merchant_return_policy():  # #73 item 6
    assert fixture_check("30-day returns", "sim-return-policy.html")["result"] == "false"
    assert fixture_check("15-day returns", "sim-return-policy.html")["result"] == "verified"
    out = fixture_check("30-day returns", "sim-no-returns.html")
    assert out["result"] == "false" and "not permitted" in out["reason"]


def test_real_page_without_a_return_policy_stays_unverified():
    out = fixture_check("30-day returns", "mirror-canadacomputers-269441.html")
    assert out["result"] == "unverified"
    assert fixture_check("$1,749.99", "mirror-canadacomputers-269441.html")["result"] == "unverified"  # saved page still parses; it prices in CAD (RT-19)

def test_shipping_threshold_dollars_are_not_read_as_the_price():  # #99: never a false flag on an honest page
    from data.claim_check import parse_claims
    assert dict(parse_claims({"text": "New RTX 5070 Ti, free shipping over $35"})) == {"condition": "new"}
    for text in ("Save $50 today, new", "$20 off, new", "New, $5 fee"):
        assert "price" not in dict(parse_claims({"text": text})), text
    assert check("New RTX 5070 Ti, free shipping over $35", HAL_GPU)["result"] == "verified"


def test_two_price_amounts_make_the_price_unverified():
    from data.claim_check import parse_claims
    assert dict(parse_claims({"text": "$789 or $749 with trade-in"}))["price"] is None
    out = check("$789 or $749 with trade-in", HAL_GPU, kind="price")
    assert out["result"] == "unverified" and "more than one amount" in out["reason"]


def test_a_false_price_beside_shipping_or_off_words_is_still_false():  # #106
    for text in ("New RTX 5070 Ti, free shipping, $749", "Payoff price new $749", "Free shipping, new $749",
                 "Free shipping: $749 new", "New $749 shipping included", "$50 off $749 new"):
        out = check(text, HAL_GPU, kind="price")
        assert out["result"] == "false" and "$749.00" in out["reason"], text


def test_non_price_amounts_beside_offer_words_are_unverified_not_false():
    for text in ("New, free shipping on orders of $35 or more", "New, includes $50 gift card", "New, save up to $50",
                 "New, $25 rebate", "New, $10 coupon"):
        assert check(text, HAL_GPU)["result"] == "unverified", text


def _page(offer_extra="", node_extra="", availability="InStock"):
    body = ('{"@type":"Product","name":"X","description":"" %s,"offers":{"@type":"Offer","price":"10","availability":"https://schema.org/%s"%s}}'
            % (node_extra, availability, offer_extra))
    return ('<script type="application/ld+json">%s</script>' % body).encode()


def _res(text, kind, page):
    return check_claim({"text": text, "kind": kind, "evidence_url": "https://store.example/p"}, fetch=lambda u: page)


def test_schema_stock_statuses():  # #126
    for status in ("InStock", "LimitedAvailability", "OnlineOnly", "InStoreOnly"):
        assert _res("in stock", "stock", _page(availability=status))["result"] == "verified", status
        assert _res("sold out", "stock", _page(availability=status))["result"] == "false", status
    for status in ("OutOfStock", "SoldOut", "Discontinued", "PreOrder", "PreSale", "BackOrder"):
        assert _res("in stock", "stock", _page(availability=status))["result"] == "false", status
        assert _res("out of stock", "stock", _page(availability=status))["result"] == "verified", status
    out = _res("in stock", "stock", _page(availability="PreOrder"))
    assert "PreOrder" in out["reason"] and "not available now" in out["reason"]


def _w(value, unit):
    return ',"warranty":{"@type":"WarrantyPromise","durationOfWarranty":{"@type":"QuantitativeValue","value":%s,"unitCode":"%s"}}' % (value, unit)


def test_warranty_from_json_ld_and_text():
    assert _res("3-year warranty", "warranty", _page(node_extra=_w(3, "ANN")))["result"] == "verified"
    assert _res("36 month warranty", "warranty", _page(node_extra=_w(3, "ANN")))["result"] == "verified"
    assert _res("3-year warranty", "warranty", _page(node_extra=_w(24, "MON")))["result"] == "false"
    assert _res("3-year warranty", "warranty", _page(offer_extra=_w(36, "MON")))["result"] == "verified"
    text = _page(node_extra="").replace(b'"description":""', b'"description":"Includes a 2-year limited warranty."')
    assert _res("2 year warranty", "warranty", text)["result"] == "verified"
    assert _res("3-year warranty", "warranty", text)["result"] == "false"
    assert _res("3-year warranty", "warranty", _page())["result"] == "unverified"


def test_hostile_warranty_values_are_unverified_and_never_raise():
    for value, unit in (("Infinity", "ANN"), ("-1", "ANN"), ("true", "ANN"), ("1.5", "ANN"), ("999", "ANN"), ("1e999", "MON"), ("3", "XYZ")):
        assert _res("3-year warranty", "warranty", _page(node_extra=_w(value, unit)))["result"] == "unverified", (value, unit)


def test_warranty_list_must_agree():
    two = ',"warranty":[%s,%s]' % tuple(_w(v, "ANN")[len(',"warranty":'):] for v in (1, 3))
    assert _res("3-year warranty", "warranty", _page(node_extra=two))["result"] == "unverified"
    same = ',"warranty":[%s,%s]' % tuple(_w(3, "ANN")[len(',"warranty":'):] for _ in (1, 2))
    assert _res("3-year warranty", "warranty", _page(node_extra=same))["result"] == "verified"


def test_was_price_history_comes_from_our_record_not_the_served_file():  # #136
    import json
    calls = []

    def poisoned(url):
        calls.append(url)
        if url.endswith("price_history.json"):
            return json.dumps({"series": {"gpu-5070ti": [{"date": "2026-10-01", "price": 5000.0}]}}).encode()
        return fetch(url)

    out = check_claim(claim("was $1,099", SAM_GPU_LIES, kind="price"), fetch=poisoned)
    assert out["result"] == "false" and "price history" in out["reason"]
    assert calls == [BASE + SAM_GPU_LIES]  # only the page is fetched


REAL = b'<script type="application/ld+json">{"@type":"Product","name":"X","offers":{"@type":"Offer","price":"1000"}}</script>'


def test_real_page_without_our_captures_is_unverified_for_a_was_price():
    c = {"text": "was $1,500", "kind": "price", "evidence_url": "https://store.example/p"}
    out = check_claim(c, fetch=lambda u: REAL, observations=[])
    assert out["result"] == "unverified" and "no dated price history from our own captures" in out["reason"]


def test_real_page_is_judged_against_our_dated_observations_of_that_url():
    rows = [{"url": "https://store.example/p", "observed_at": "2026-10-20T05:00:00+00:00", "price": 1400.0},
            {"url": "https://other.example/q", "observed_at": "2026-10-21T05:00:00+00:00", "price": 9999.0}]
    c = lambda t: {"text": t, "kind": "price", "evidence_url": "https://store.example/p"}
    assert check_claim(c("was $1,500"), fetch=lambda u: REAL, observations=rows)["result"] == "false"
    assert check_claim(c("was $1,400"), fetch=lambda u: REAL, observations=rows)["result"] == "verified"


def test_was_price_without_our_records_installed_is_unverified_not_an_error(monkeypatch):  # inside the Actor bundle
    import sys
    monkeypatch.setitem(sys.modules, "data.baselines", None)
    c = {"text": "was $1,500", "kind": "price", "evidence_url": "https://store.example/p"}
    out = check_claim(c, fetch=lambda u: REAL)
    assert out["result"] == "unverified" and "no dated price history from our own captures" in out["reason"]


def test_page_facts_claiming_to_be_sim_do_not_earn_our_sim_history():  # #155: SIM is decided from the evidence URL
    page = b'<script type="application/json" id="listing">{"origin":"SIM","sku":"gpu-5070ti","price":789.0,"condition":"new"}</script>'
    for url in ("https://store.example/p", "http://127.0.0.1:8765.evil.example/p.html", "https://127.0.0.1:8765/p.html"):
        out = check_claim({"text": "was $829", "kind": "price", "evidence_url": url}, fetch=lambda u: page, observations=[])
        assert out["result"] == "unverified", url
    ours = check_claim({"text": "was $829", "kind": "price", "evidence_url": BASE + "shady-sam-gpu-5070ti-lies.html"}, fetch=fetch)
    assert ours["result"] in ("verified", "false") and "price history" in ours["reason"]


# RT-19: the page's priceCurrency. A claim with "$" or no currency is USD; a page in another currency leaves it unverified.
def _priced(price, currency=None, spec_currency=None):
    cur = f',"priceCurrency":{json.dumps(currency)}' if currency is not None else ""
    spec = f',"priceSpecification":{{"@type":"PriceSpecification","price":{price},"priceCurrency":{json.dumps(spec_currency)}}}' if spec_currency else ""
    body = f'{{"@type":"Product","name":"X","offers":{{"@type":"Offer","price":{price}{cur}{spec}}}}}'
    return f'<script type="application/ld+json">{body}</script>'.encode()


def _price_check(text, page, kind="price", url="https://store.example/p"):
    return check_claim({"text": text, "kind": kind, "evidence_url": url}, fetch=lambda u: page)


def test_a_cad_page_leaves_a_dollar_price_claim_unverified_and_names_both_currencies():
    for text in ("$1,749.99", "price $1,749.99", "New, $1,749.99", "$1,699.00"):   # the same number or a different one: never verified, never false
        out = _price_check(text, _priced(1749.99, "CAD"))
        assert out["result"] == "unverified", text
        assert "USD" in out["reason"] and "CAD" in out["reason"], out["reason"]


def test_the_saved_canada_computers_page_does_not_verify_a_dollar_claim():  # the Actor README's own example page
    out = fixture_check("$1,749.99", "mirror-canadacomputers-269441.html")
    assert out["result"] == "unverified" and "USD" in out["reason"] and "CAD" in out["reason"]


def test_a_usd_page_still_verifies_and_still_catches_a_false_price():
    assert _price_check("$1,749.99", _priced(1749.99, "USD"))["result"] == "verified"
    assert _price_check("$1,749.99", _priced(1749.99, "usd"))["result"] == "verified"   # case is ignored
    assert _price_check("$1,699.00", _priced(1749.99, "USD"))["result"] == "false"
    assert fixture_check("$1,249.99", "sim-return-policy.html")["result"] == "verified"   # a saved USD page


def test_a_page_with_no_readable_currency_is_judged_as_before():
    for page in (_priced(1749.99), _priced(1749.99, "$"), _priced(1749.99, "dollars"), _priced(1749.99, 840), _priced(1749.99, "")):
        assert _price_check("$1,749.99", page)["result"] == "verified", page


def test_the_currency_can_sit_on_a_price_specification():
    out = _price_check("$1,749.99", _priced(1749.99, spec_currency="CAD"))
    assert out["result"] == "unverified" and "CAD" in out["reason"]
    assert _price_check("$1,749.99", _priced(1749.99, "USD", spec_currency="CAD"))["result"] == "verified"   # the offer's own code first


def test_a_claim_that_names_its_currency_is_compared_in_that_currency():
    assert _price_check("C$1,749.99", _priced(1749.99, "CAD"))["result"] == "verified"
    assert _price_check("price $1,749.99 CAD", _priced(1749.99, "CAD"))["result"] == "verified"
    assert _price_check("CAD $1,749.99", _priced(1749.99, "CAD"))["result"] == "verified"
    assert _price_check("C$1,699.00", _priced(1749.99, "CAD"))["result"] == "false"
    out = _price_check("C$1,749.99", _priced(1749.99, "USD"))
    assert out["result"] == "unverified" and "CAD" in out["reason"] and "USD" in out["reason"]
    assert _price_check("US$1,749.99", _priced(1749.99, "USD"))["result"] == "verified"
    assert _price_check("1749.99", _priced(1749.99, "CAD"), kind="price") ["result"] == "unverified"   # no amount with a $ at all
    assert check_claim({"field": "price", "value": 1749.99, "currency": "CAD", "evidence_url": "https://store.example/p"},
                       fetch=lambda u: _priced(1749.99, "CAD"))["result"] == "verified"


def test_a_canadian_dollar_claim_is_unverified_on_a_page_with_no_currency():   # RT-19 low: no priceCurrency is not USD-and-CAD-alike
    for page in (_priced(1749.99), _priced(1749.99, "$"), _priced(1749.99, "dollars"), _priced(1749.99, "")):
        out = _price_check("C$1,749.99", page)
        assert out["result"] == "unverified" and "CAD" in out["reason"] and "no currency" in out["reason"], page
    assert _price_check("C$1,749.99", _priced(1749.99, "CAD"))["result"] == "verified"   # a stated CAD page still verifies
    assert _price_check("$1,749.99", _priced(1749.99))["result"] == "verified"            # a USD claim keeps its old reading


def test_an_open_box_page_on_a_used_condition_is_read_as_open_box():   # how our SIM pages state it in JSON-LD (no schema.org term exists)
    page = lambda cond, name: ('<script type="application/ld+json">' + json.dumps({"@type": "Product", "name": name, "offers": {
        "@type": "Offer", "price": 10, "itemCondition": "https://schema.org/" + cond}}) + '</script>').encode()
    assert _price_check("open-box", page("UsedCondition", "X (open-box)"), kind="condition")["result"] == "verified"
    assert _price_check("used", page("UsedCondition", "X (open-box)"), kind="condition")["result"] == "false"
    assert _price_check("used", page("UsedCondition", "X"), kind="condition")["result"] == "verified"
    assert _price_check("new", page("NewCondition", "X (open-box)"), kind="condition")["result"] == "verified"   # only a used page is refined


def test_a_cad_page_does_not_hide_a_false_condition_in_the_same_claim():
    page = b'<script type="application/ld+json">{"@type":"Product","name":"X","offers":{"@type":"Offer","price":1749.99,"priceCurrency":"CAD","itemCondition":"https://schema.org/UsedCondition"}}</script>'
    assert _price_check("New, $1,749.99", page)["result"] == "false"   # the worst field still decides
    page_new = page.replace(b"UsedCondition", b"NewCondition")
    out = _price_check("New, $1,749.99", page_new)
    assert out["result"] == "unverified" and "CAD" in out["reason"]


def test_a_non_usd_was_price_claim_is_not_judged_against_usd_history():
    rows = [{"url": "https://store.example/p", "observed_at": "2026-10-20T00:00:00+00:00", "price": 1500.0}]
    ok = check_claim({"text": "was $1,400", "kind": "price", "evidence_url": "https://store.example/p"}, fetch=lambda u: _priced(1749.99), observations=rows)
    assert ok["result"] == "verified"
    out = check_claim({"text": "was C$1,400", "kind": "price", "evidence_url": "https://store.example/p"}, fetch=lambda u: _priced(1749.99), observations=rows)
    assert out["result"] == "unverified" and "CAD" in out["reason"] and "USD" in out["reason"]


def test_page_facts_carries_the_currency_code():
    from data.claim_check import page_facts
    assert page_facts(_priced(10, "cad").decode(), "https://store.example/p")[0]["currency"] == "CAD"
    assert "currency" not in page_facts(_priced(10, "$").decode(), "https://store.example/p")[0]


# RT-20: the <script id="listing"> block is read only on our own demo liar pages.
LISTING = '<script type="application/json" id="listing">{"price": 789.0, "condition": "new", "stock": "in stock"}</script>'
LD_USED = ('<script type="application/ld+json">{"@type":"Product","name":"X","offers":{"@type":"Offer","price":1299.0,"priceCurrency":"USD",'
           '"itemCondition":"https://schema.org/UsedCondition","availability":"https://schema.org/OutOfStock"}}</script>')


def test_a_listing_block_on_another_host_is_ignored_in_favour_of_the_real_json_ld():
    from data.claim_check import page_facts
    html = LISTING + LD_USED
    facts, how = page_facts(html, "https://shop.example/p/1")
    assert how == "page JSON-LD" and facts["price"] == 1299.0 and facts["condition"] == "used"
    assert _price_check("New", html.encode(), kind="spec")["result"] == "false"       # the seller's block cannot make it new
    assert _price_check("$789", html.encode())["result"] == "false"                    # nor make $789 true
    assert _price_check("in stock", html.encode(), kind="stock")["result"] == "false"


def test_a_page_with_only_a_listing_block_on_another_host_has_no_structured_data():
    from data.claim_check import page_facts
    assert page_facts(LISTING, "https://shop.example/p/1") == ({}, "no structured data")
    assert page_facts(LISTING) == ({}, "no structured data")   # no url: not ours
    assert page_facts(LISTING, "http://localhost:8765.evil.example/p.html") == ({}, "no structured data")
    out = _price_check("$789", LISTING.encode())
    assert out["result"] == "unverified" and out["method"].startswith("could not verify")


def test_a_listing_block_on_our_own_liar_page_is_still_read_first():
    from data.claim_check import page_facts
    for url in ("http://localhost:8765/x.html", "http://127.0.0.1:8765/x.html"):
        facts, how = page_facts(LISTING + LD_USED, url)
        assert how == "page listing JSON" and facts["price"] == 789.0 and facts["condition"] == "new", url
        assert _price_check("$789", (LISTING + LD_USED).encode(), url=url)["result"] == "verified"


def test_a_broken_listing_block_on_another_host_is_not_parsed_at_all():
    from data.claim_check import page_facts
    for bad in ('{not json', '[1]', '"x"', "[" * 100_000 + "]" * 100_000):
        html = f'<script type="application/json" id="listing">{bad}</script>' + LD_USED
        assert page_facts(html, "https://shop.example/p")[1] == "page JSON-LD"   # no ValueError, no parse


# RT-20: a warranty read from free text is marked as the seller's own description.
def _described(description, extra_node=""):
    return (f'<script type="application/ld+json">{{"@type":"Product","name":"X","description":{json.dumps(description)}{extra_node},'
            '"offers":{"@type":"Offer","price":10}}</script>').encode()


def test_a_warranty_from_the_description_says_so_when_verified_or_false():
    page = _described("Includes a 2-year limited warranty.")
    verified = _price_check("2 year warranty", page, kind="spec")
    false = _price_check("3-year warranty", page, kind="spec")
    assert verified["result"] == "verified" and "seller's own description" in verified["reason"]
    assert false["result"] == "false" and "seller's own description" in false["reason"]
    assert "seller's own description" not in _price_check("3-year warranty", _described("", _w(3, "ANN")), kind="spec")["reason"]
    assert "seller's own description" not in _price_check("3-year warranty", _described("", _w(2, "ANN")), kind="spec")["reason"]


def test_a_structured_warranty_wins_over_the_description_and_is_not_marked():
    page = _described("Includes a 1-year limited warranty.", _w(3, "ANN"))
    out = _price_check("3-year warranty", page, kind="spec")
    assert out["result"] == "verified" and "seller's own description" not in out["reason"]
