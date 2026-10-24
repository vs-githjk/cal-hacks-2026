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
