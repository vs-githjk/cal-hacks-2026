import pytest

from hyphenate.ledger import BadEntry, Ledger, Line, PeriodLocked, Unbalanced, UnknownAccount
from hyphenate.money import cents, usd

P = dict(by="ap-agent", at="2026-10-24T01:00:00Z")


def post(led, date="2026-10-05", amt=1000, debit="1500", credit="2000", **kw):
    return led.post(date=date, lines=[Line(debit, debit=amt), Line(credit, credit=amt, party="v1")] if credit in ("2000", "2100") else
                    [Line(debit, debit=amt, party="v1" if debit in ("1200", "1300") else None), Line(credit, credit=amt)],
                    reason=kw.pop("reason", "test"), refs=kw.pop("refs", ["po:1"]), **P)


def test_money_rounds_half_up_and_rejects_junk():
    assert cents(1249.99) == 124999 and cents("0.005") == 1 and cents(10) == 1000
    for bad in (None, True, float("nan"), "abc"):
        with pytest.raises(ValueError):
            cents(bad)
    assert usd(-5) == "-$0.05" and usd(123456789) == "$1,234,567.89"


def test_balanced_entry_posts_and_trial_balance_balances():
    led = Ledger()
    post(led)
    tb = led.trial_balance()
    assert tb["balanced"] and tb["debit"] == 1000 == tb["credit"]
    assert led.balance("1500") == 1000 and led.balance("2000") == 1000


def test_unbalanced_entry_refused_and_nothing_written():
    led = Ledger()
    with pytest.raises(Unbalanced):
        led.post(date="2026-10-05", lines=[Line("1500", debit=1000), Line("2000", credit=999, party="v1")], reason="x", refs=["a"], **P)
    assert led.entries == []


@pytest.mark.parametrize("kw", [
    dict(reason=""), dict(reason="  "), dict(refs=[]),
])
def test_reason_and_refs_required(kw):
    with pytest.raises(BadEntry):
        post(Ledger(), **kw)


def test_unknown_account_and_bad_lines():
    led = Ledger()
    with pytest.raises(UnknownAccount):
        led.post(date="2026-10-05", lines=[Line("9999", debit=5), Line("1000", credit=5)], reason="x", refs=["a"], **P)
    with pytest.raises(BadEntry):  # both sides on one line
        led.post(date="2026-10-05", lines=[Line("1000", debit=5, credit=5), Line("1500", credit=0, debit=0)], reason="x", refs=["a"], **P)
    with pytest.raises(BadEntry):  # payable without a vendor
        led.post(date="2026-10-05", lines=[Line("1500", debit=5), Line("2000", credit=5)], reason="x", refs=["a"], **P)
    with pytest.raises(BadEntry):  # float cents
        led.post(date="2026-10-05", lines=[Line("1500", debit=5.5), Line("1000", credit=5.5)], reason="x", refs=["a"], **P)


def test_close_locks_period_and_next_open_period():
    led = Ledger()
    post(led, date="2026-09-30")
    led.close_period("2026-09", by="controller", at="2026-10-01T09:00:00Z")
    with pytest.raises(PeriodLocked):
        post(led, date="2026-09-30")
    assert led.next_open_period("2026-09") == "2026-10"
    with pytest.raises(PeriodLocked):
        led.close_period("2026-09", by="c", at="x")


def test_periods_close_in_order():
    led = Ledger()
    post(led, date="2026-08-31")
    post(led, date="2026-09-30")
    with pytest.raises(PeriodLocked):
        led.close_period("2026-09", by="c", at="x")
    led.close_period("2026-08", by="c", at="x")
    led.close_period("2026-09", by="c", at="x")


def test_reverse_swaps_sides_once_and_lands_in_open_period():
    led = Ledger()
    e = post(led, date="2026-09-30")
    led.close_period("2026-09", by="c", at="x")
    r = led.reverse(e.id, date="2026-10-01", reason="reverse accrual", refs=["invoice:1"], **P)
    assert r.period == "2026-10" and led.balance("1500") == 0 and led.balance("2000") == 0
    assert r.reverses == e.id and f"entry:{e.id}" in r.refs
    with pytest.raises(BadEntry):
        led.reverse(e.id, date="2026-10-02", reason="again", refs=["x"], **P)
    with pytest.raises(PeriodLocked):  # cannot reverse into the locked period
        e2 = post(led, date="2026-10-03")
        led.close_period("2026-10", by="c", at="x")
        led.reverse(e2.id, date="2026-10-04", reason="r", refs=["x"], **P)


def test_subledger_ties_to_general_ledger():
    led = Ledger()
    post(led, amt=700)
    led.post(date="2026-10-06", lines=[Line("1500", debit=300), Line("2000", credit=300, party="v2")], reason="x", refs=["a"], **P)
    assert led.subledger_ties() == []
    assert led.party_balances("2000") == {"v1": 700, "v2": 300}
