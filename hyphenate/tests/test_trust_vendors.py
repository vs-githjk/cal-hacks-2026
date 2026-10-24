from hyphenate.trust import resolve
from hyphenate.vendors import Vendor, assess


def test_bank_beats_ledger_and_reason_names_both():
    r = resolve("cash_amount", [{"source": "ledger", "value": 129499, "ref": "je_1"}, {"source": "bank", "value": 124999, "ref": "ba_1"}])
    assert r["trusted"]["source"] == "bank" and r["trusted"]["value"] == 124999 and not r["agreed"]
    assert "bank" in r["reason"] and "ledger says 129499" in r["reason"]


def test_receiving_beats_seller_on_condition_and_agreement_is_reported():
    r = resolve("goods_condition", [{"source": "seller_claim", "value": "new"}, {"source": "receiving", "value": "open-box"}])
    assert r["trusted"]["source"] == "receiving"
    r2 = resolve("goods_condition", [{"source": "seller_claim", "value": "new"}, {"source": "receiving", "value": "new"}])
    assert r2["agreed"] and "agree" in r2["reason"]


def test_stale_mirror_is_ignored_and_said():
    r = resolve("market_price", [{"source": "mirror", "value": 124999, "as_of": "2026-09-01T00:00:00Z"}], now="2026-10-24T00:00:00Z")
    assert r["trusted"] is None and "stale" in r["reason"]
    fresh = resolve("market_price", [{"source": "mirror", "value": 124999, "as_of": "2026-10-20T00:00:00Z"}], now="2026-10-24T00:00:00Z")
    assert fresh["trusted"]["value"] == 124999


def test_contract_price_beats_invoice_and_mirror():
    r = resolve("agreed_price", [{"source": "mirror", "value": 100}, {"source": "seller_claim", "value": 130}, {"source": "contract", "value": 120}])
    assert r["trusted"]["source"] == "contract" and len(r["disagreeing"]) == 2


def test_vendor_history_changes_level_over_time():
    v = Vendor("v1", "Acme", "acme@pay.example.test", "acct_1111")
    v.add("completed_order", "2026-01-10T00:00:00Z", "ap")
    assert assess(v, "2026-10-24T00:00:00Z").level == "normal"
    v.add("failed_receiving", "2026-09-20T00:00:00Z", "happy", "wrong condition")
    r = assess(v, "2026-10-24T00:00:00Z")
    assert r.level == "strict" and r.price_tolerance_zero and r.extra_approval and "34 days ago" in r.reasons[0]
    assert assess(v, "2027-02-01T00:00:00Z").level == "watch"  # 134 days later: out of the strict window
    assert assess(v, "2028-01-01T00:00:00Z").level == "normal"  # over a year: forgotten
    v.add("failed_receiving", "2026-03-01T00:00:00Z", "happy")
    assert assess(v, "2026-11-30T00:00:00Z").level == "strict"  # two failures in a year


def test_new_vendor_flag_clears_after_a_completed_order():
    v = Vendor("v2", "Newco", "n@pay.example.test", "acct_2222")
    assert assess(v, "2026-10-24T00:00:00Z").new_vendor
    v.add("completed_order", "2026-10-01T00:00:00Z", "ap")
    assert not assess(v, "2026-10-24T00:00:00Z").new_vendor
