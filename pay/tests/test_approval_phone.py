"""Whose phone the approval call rings (#374). Today one number is configured (APPROVAL_CALL_TO) and it belongs to the default buyer;
any other buyer has no number until #374's buyer_profile phone lands, and a buyer with no number is never called and never approved."""
from __future__ import annotations

import pytest

from pay import voice_cartesia as vc

ENV = {vc.KEY_ENV: "k" * 20, vc.AGENT_ENV: "agent-1", vc.TO_ENV: "+14155550123"}


def test_the_default_buyer_gets_the_env_configured_number():
    assert vc.approval_phone("vidyut", ENV) == "+14155550123"


def test_any_other_buyer_has_no_number_yet():
    assert vc.approval_phone("someone-else", ENV) is None
    assert vc.approval_phone("someone-else", {}) is None
    assert vc.approval_phone("", ENV) is None


def test_the_default_buyer_without_a_configured_number_has_none():
    assert vc.approval_phone("vidyut", {}) is None


def test_the_default_buyer_id_is_the_one_the_demo_pairs_with():
    from demo import bridge
    assert vc.DEFAULT_APPROVAL_BUYER == bridge.DB_BUYER_ID


def test_the_client_for_the_default_buyer_dials_only_the_env_number():
    c = vc.client_for_buyer("vidyut", ENV)
    assert c.approval_call_to == "+14155550123"


def test_the_client_for_another_buyer_is_refused_with_a_no_phone_error_and_never_borrows_the_default_number():
    with pytest.raises(vc.NoPhone) as e:
        vc.client_for_buyer("someone-else", ENV)
    assert "+14155550123" not in str(e.value) and "someone-else" in str(e.value)
    assert isinstance(e.value, vc.CartesiaError)


def test_a_missing_cartesia_setup_for_the_default_buyer_is_still_the_old_error():
    with pytest.raises(vc.CartesiaError) as e:
        vc.client_for_buyer("vidyut", {})
    assert not isinstance(e.value, vc.NoPhone)


def test_the_denial_line_for_no_phone_says_so_and_that_nothing_was_paid():
    line = vc.denial_line("no_phone: no number on file")
    assert "phone" in line.lower() and "nothing was paid" in line.lower()
