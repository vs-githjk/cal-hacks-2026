"""c3 claim check against the SIM liar pages (served from disk through an injected fetcher)."""
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
