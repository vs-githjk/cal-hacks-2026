from hyphenate.matching import match_lines
from hyphenate.org import Policy

P = Policy()


def po(**kw):
    base = dict(sku="GPU", qty=10, unit=124999, condition="new", allowed=["new"], accepted=10, rejected=0, billed=0, accepted_conditions=["new"] * 10)
    return {**base, **kw}


def inv(**kw):
    return {**dict(sku="GPU", qty=10, unit=124999, condition="new"), **kw}


def codes(f):
    return sorted(x.code for x in f)


def test_clean_invoice_has_no_findings():
    assert match_lines([po()], [inv()], P, strict=False) == []


def test_short_shipment_asks_credit_for_missing_units():
    f = match_lines([po(accepted=8, accepted_conditions=["new"] * 8)], [inv()], P, strict=False)
    assert codes(f) == ["qty_short"] and f[0].credit == 2 * 124999 and f[0].hold


def test_nothing_received_is_billed_before_receipt():
    f = match_lines([po(accepted=0, accepted_conditions=[])], [inv()], P, strict=False)
    assert codes(f) == ["billed_before_receipt"]


def test_partial_invoice_for_what_arrived_passes_and_second_over_bills():
    ok = match_lines([po(accepted=6, accepted_conditions=["new"] * 6)], [inv(qty=6)], P, strict=False)
    assert ok == []
    over = match_lines([po(accepted=6, billed=6, accepted_conditions=["new"] * 6)], [inv(qty=4)], P, strict=False)
    assert codes(over) == ["qty_short"]


def test_over_po_quantity():
    f = match_lines([po(qty=10, accepted=10, billed=8)], [inv(qty=4)], P, strict=False)
    assert "qty_over_po" in codes(f)


def test_price_materiality_and_strict_vendor():
    # 10 units at 1249.99: 0.5 percent of the line is 6250 cents; +50 cents a unit is 500 cents total: immaterial
    f = match_lines([po()], [inv(unit=124999 + 50)], P, strict=False)
    assert codes(f) == ["price_variance_immaterial"] and not f[0].hold
    f = match_lines([po()], [inv(unit=124999 + 50)], P, strict=True)
    assert codes(f) == ["price_variance"] and f[0].hold
    f = match_lines([po()], [inv(unit=124999 * 108 // 100)], P, strict=False)
    assert codes(f) == ["price_variance"] and f[0].credit == (124999 * 108 // 100 - 124999) * 10


def test_price_below_po_is_variance_without_credit():
    f = match_lines([po()], [inv(unit=100000)], P, strict=False)
    assert codes(f) == ["price_variance"] and f[0].credit == 0


def test_condition_what_we_inspected_beats_the_claim():
    f = match_lines([po(accepted_conditions=["new"] * 8 + ["open-box"] * 2)], [inv()], P, strict=False)
    assert codes(f) == ["condition_mismatch"] and f[0].credit == 2 * 124999


def test_sku_not_on_po():
    f = match_lines([po()], [inv(sku="OTHER")], P, strict=False)
    assert codes(f) == ["sku_not_on_po"]
