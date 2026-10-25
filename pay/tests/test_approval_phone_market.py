"""H3: a self-serve web buyer (id b_...) approves a purchase above the allowance on their OWN phone, read from the market's agent-only
agent_buyer_contact view. Never another buyer's number, never the default buyer's, never logged; a buyer with none is NoPhone."""
from __future__ import annotations

import logging

import pytest

from pay import voice_cartesia as vc

ENV = {vc.KEY_ENV: "k" * 20, vc.AGENT_ENV: "agent-1", vc.TO_ENV: "+14155550123"}
A, B = "b_aaaa1111", "b_bbbb2222"
PHONE_A, PHONE_B = "+14155550111", "+14155550222"


def fake_market(rows):
    """A stdb.Market-shaped sql(query): positional rows, filtered by the WHERE buyer_id the way the view would."""
    seen = []

    def sql(query):
        seen.append(query)
        return [[buyer_id, phone] for buyer_id, phone in rows if f"buyer_id = '{buyer_id}'" in query]
    sql.seen = seen
    return sql


def test_a_web_buyer_with_a_phone_gets_exactly_their_number():
    lookup = vc.phone_lookup_from_sql(fake_market([(A, PHONE_A), (B, PHONE_B)]))
    assert vc.approval_phone(A, ENV, lookup=lookup) == PHONE_A
    assert vc.client_for_buyer(A, ENV, lookup=lookup).approval_call_to == PHONE_A


def test_a_web_buyer_with_no_phone_is_no_phone():
    lookup = vc.phone_lookup_from_sql(fake_market([(A, ""), (B, PHONE_B)]))
    assert vc.approval_phone(A, ENV, lookup=lookup) is None
    with pytest.raises(vc.NoPhone):
        vc.client_for_buyer(A, ENV, lookup=lookup)


def test_a_web_buyer_with_no_profile_row_or_no_lookup_is_no_phone_and_never_the_default_number():
    with pytest.raises(vc.NoPhone) as e:
        vc.client_for_buyer(A, ENV, lookup=vc.phone_lookup_from_sql(fake_market([])))
    assert "+14155550123" not in str(e.value)
    with pytest.raises(vc.NoPhone):
        vc.client_for_buyer(A, ENV)


def test_buyer_a_can_never_get_buyer_bs_number():
    lookup = vc.phone_lookup_from_sql(fake_market([(B, PHONE_B)]))
    assert vc.approval_phone(A, ENV, lookup=lookup) is None
    with pytest.raises(vc.NoPhone):
        vc.client_for_buyer(A, ENV, lookup=lookup)
    # a view that wrongly returns other buyers' rows is ignored: the row's own id must match
    assert vc.approval_phone(A, ENV, lookup=vc.phone_lookup_from_sql(lambda q: [[B, PHONE_B], [A, PHONE_A]])) == PHONE_A
    assert vc.approval_phone(A, ENV, lookup=vc.phone_lookup_from_sql(lambda q: [[B, PHONE_B]])) is None


def test_the_client_can_dial_only_that_buyers_number():
    c = vc.client_for_buyer(A, ENV, lookup=vc.phone_lookup_from_sql(fake_market([(A, PHONE_A), (B, PHONE_B)])))
    for other in (PHONE_B, "+14155550123"):
        with pytest.raises(vc.NumberNotAllowed) as e:
            c.create_call(other, {})
        assert other not in str(e.value)
        with pytest.raises(vc.NumberNotAllowed):
            vc.place_call(c, {}, to=other)


def test_the_default_buyer_keeps_the_env_number_and_never_asks_the_market():
    def boom(q):
        raise AssertionError("the market must not be read for the default buyer")
    assert vc.approval_phone("vidyut", ENV, lookup=vc.phone_lookup_from_sql(boom)) == "+14155550123"
    assert vc.client_for_buyer("vidyut", ENV, lookup=vc.phone_lookup_from_sql(boom)).approval_call_to == "+14155550123"


def test_a_non_e164_phone_is_refused():
    for bad in ("4155550111", "+0123456789", "+1415555011x", "+1 415 555 0111", "+1" + "5" * 20, "'; DROP", None, 4155550111):
        lookup = vc.phone_lookup_from_sql(lambda q, bad=bad: [[A, bad]])
        assert vc.approval_phone(A, ENV, lookup=lookup) is None


def test_the_query_is_one_buyer_and_an_odd_buyer_id_never_reaches_it():
    sql = fake_market([(A, PHONE_A)])
    assert vc.phone_lookup_from_sql(sql)(A) == PHONE_A
    assert "FROM agent_buyer_contact" in sql.seen[0] and f"'{A}'" in sql.seen[0]
    for odd in ("", "x' OR '1'='1", "b_a b", "a" * 200, None, 5):
        sql = fake_market([])
        assert vc.phone_lookup_from_sql(sql)(odd) is None and sql.seen == []


def test_a_failing_market_read_fails_closed():
    def boom(q):
        raise RuntimeError("HTTP 500")
    assert vc.approval_phone(A, ENV, lookup=vc.phone_lookup_from_sql(boom)) is None
    with pytest.raises(vc.NoPhone):
        vc.client_for_buyer(A, ENV, lookup=vc.phone_lookup_from_sql(boom))


def test_nothing_is_printed_or_logged(capsys, caplog):
    with caplog.at_level(logging.DEBUG):
        lookup = vc.phone_lookup_from_sql(fake_market([(A, PHONE_A)]))
        c = vc.client_for_buyer(A, ENV, lookup=lookup)
        with pytest.raises(vc.NoPhone) as e:
            vc.client_for_buyer(B, ENV, lookup=lookup)
        assert PHONE_A not in str(e.value) and PHONE_A not in repr(c)
        vc.approval_phone(A, ENV, lookup=vc.phone_lookup_from_sql(lambda q: [[A, "garbage" + PHONE_A]]))
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err == "" and caplog.text == ""
