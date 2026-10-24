from data.claim_check import check_claim
from data.fit_checker import check_fit


def card(cat, **attrs):
    return {"id": cat, "category": cat, "name": cat, "attrs": attrs, "origin": "SIM", "source": "test"}


def test_fit_io_shape():
    out = check_fit([card("cpu", socket="AM5"), card("motherboard", socket="AM4")])
    assert out["verdict"] == "fail" and out["rule_id"] == "fit.cpu_socket" and out["reasons"]


def test_claim_io_shape():
    out = check_claim({"id": "c1", "kind": "price", "text": "$749", "evidence_url": "https://example.test/p"})
    assert out["result"] in {"verified", "unverified", "false"}
    assert {"evidence_url", "checked_at", "method"} <= out.keys()
