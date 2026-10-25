"""#449 item 1: the approval call is limited to an allowlist of numbers and to a persisted rate cap. No network, no real numbers."""
import json
import re
from unittest.mock import Mock

import pytest

from pay import voice_cartesia as vc
from pay.callscript import ScriptError, is_clean_name
from pay.voice_cartesia import CallLimited, CartesiaClient, CartesiaError

TO = "+14155550111"
OTHER = "+14155550222"
ENV = {"CARTESIA_API_KEY": "k", "CARTESIA_AGENT_ID": "a", "CARTESIA_PHONE_NUMBER_ID": "ap_1", "APPROVAL_CALL_TO": TO}


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(tmp_path, to=TO, *, allow=None, clock=None, rate=True):
    env = {**ENV, "APPROVAL_CALL_TO": to}
    if allow is not None:
        env["APPROVAL_CALL_ALLOWLIST"] = allow
    if rate:
        env["APPROVAL_CALL_RATE_FILE"] = str(tmp_path / "rate.json")
    client = CartesiaClient.from_env(env, **({"clock": clock} if clock else {}))
    client._request = Mock(return_value={"calls": [{"agent_call_id": "call_1"}]})
    return client


def test_names_are_read_by_load_env(tmp_path):
    env = vc.load_env(None, {"APPROVAL_CALL_ALLOWLIST": TO, "APPROVAL_CALL_RATE_FILE": "/x/y.json"})
    assert env == {"APPROVAL_CALL_ALLOWLIST": TO, "APPROVAL_CALL_RATE_FILE": "/x/y.json"}


def test_number_not_on_the_allowlist_gets_no_call_and_no_http(tmp_path):
    client = make(tmp_path, allow=OTHER)
    with pytest.raises(CallLimited) as e:
        client.create_call(TO, {})
    assert e.value.reason == "beta_allowlist" and isinstance(e.value, CartesiaError)
    assert not client._request.called
    assert not re.search(r"\d{4,}", str(e.value))


def test_number_on_the_allowlist_proceeds_and_spaces_and_junk_entries_are_ignored(tmp_path):
    client = make(tmp_path, allow=f" junk , {OTHER} ,  {TO} ,12345")
    assert client.create_call(TO, {}) == "call_1"
    assert client._request.called


def test_unset_or_blank_allowlist_keeps_the_old_behaviour(tmp_path):
    for allow in (None, "", "   ,  "):
        assert make(tmp_path / str(allow), allow=allow).create_call(TO, {}) == "call_1"


def test_a_set_allowlist_with_only_junk_allows_nobody(tmp_path):
    client = make(tmp_path, allow="nope, 123")
    with pytest.raises(CallLimited):
        client.create_call(TO, {})
    assert not client._request.called


def test_parse_allowlist():
    assert vc.parse_allowlist(None) is None and vc.parse_allowlist("  ") is None
    assert vc.parse_allowlist(f"{TO}, {OTHER} ,bad") == frozenset({TO, OTHER})
    assert vc.parse_allowlist("bad") == frozenset()
    assert vc.on_allowlist(TO, None) and vc.on_allowlist(TO, frozenset({TO})) and not vc.on_allowlist(TO, frozenset())


def test_same_number_twice_within_300s_is_refused_then_allowed_after(tmp_path):
    clock = Clock()
    client = make(tmp_path, clock=clock)
    client.create_call(TO, {})
    clock.t += 299
    with pytest.raises(CallLimited) as e:
        client.create_call(TO, {})
    assert e.value.reason == "rate_limited" and client._request.call_count == 1
    assert not re.search(r"\d{4,}", str(e.value))
    clock.t += 2
    assert client.create_call(TO, {}) == "call_1" and client._request.call_count == 2


def test_the_cap_survives_a_new_client_sharing_the_file(tmp_path):
    clock = Clock()
    make(tmp_path, clock=clock).create_call(TO, {})
    second = make(tmp_path, clock=clock)
    with pytest.raises(CallLimited):
        second.create_call(TO, {})
    assert not second._request.called


def test_twenty_calls_in_24h_across_numbers_then_the_21st_is_refused(tmp_path):
    clock = Clock()
    for i in range(20):
        client = make(tmp_path, f"+1415555{i:04d}", clock=clock)
        client.create_call(f"+1415555{i:04d}", {})
        clock.t += 10
    client = make(tmp_path, "+14155559999", clock=clock)
    with pytest.raises(CallLimited) as e:
        client.create_call("+14155559999", {})
    assert e.value.reason == "rate_limited" and not client._request.called
    clock.t += 24 * 3600   # the oldest calls leave the rolling window
    assert client.create_call("+14155559999", {}) == "call_1"


def test_state_file_holds_no_raw_number(tmp_path):
    make(tmp_path).create_call(TO, {})
    raw = (tmp_path / "rate.json").read_text()
    assert TO not in raw and "4155550111" not in raw
    assert vc.hashlib.sha256(TO.encode()).hexdigest() in raw


@pytest.mark.parametrize("junk", ["{not json", "", "[]", '{"calls": "x"}', '{"calls": [{"h": 1, "t": "x"}]}'])
def test_corrupt_or_unreadable_state_file_refuses(tmp_path, junk):
    (tmp_path / "rate.json").write_text(junk)
    client = make(tmp_path)
    with pytest.raises(CallLimited) as e:
        client.create_call(TO, {})
    assert e.value.reason == "rate_limited" and not client._request.called


def test_unwritable_state_location_refuses(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    env = {**ENV, "APPROVAL_CALL_RATE_FILE": str(blocker / "sub" / "rate.json")}
    client = CartesiaClient.from_env(env)
    client._request = Mock()
    with pytest.raises(CallLimited):
        client.create_call(TO, {})
    assert not client._request.called


def test_a_refused_call_is_not_recorded(tmp_path):
    clock = Clock()
    client = make(tmp_path, allow=OTHER, clock=clock)
    with pytest.raises(CallLimited):
        client.create_call(TO, {})
    assert not (tmp_path / "rate.json").exists()


def test_other_number_check_still_comes_first(tmp_path):
    with pytest.raises(vc.NumberNotAllowed):
        make(tmp_path).create_call(OTHER, {})


def test_client_for_buyer_refuses_early_when_the_phone_is_not_allowed():
    env = {**ENV, "APPROVAL_CALL_ALLOWLIST": OTHER}
    with pytest.raises(CallLimited) as e:
        vc.client_for_buyer("b_x", env, lookup=lambda _b: TO)
    assert e.value.reason == "beta_allowlist" and TO not in str(e.value)
    assert vc.client_for_buyer("b_x", {**env, "APPROVAL_CALL_ALLOWLIST": TO}, lookup=lambda _b: TO).approval_call_to == TO
    assert vc.client_for_buyer("b_x", ENV, lookup=lambda _b: TO).approval_call_to == TO


def test_blocked_word_name_is_greeted_as_there_and_refused_by_build_variables():
    assert is_clean_name("Asha") and is_clean_name("Spinner") and not is_clean_name("Approve Now")
    assert vc.greeting_name("b_x", {}, lambda _b: "Approve Now") == "there"
    assert vc.greeting_name("b_x", {}, lambda _b: "Asha") == "Asha"
    script = Mock(deal_line="d", opening="o", why_answer="w")
    with pytest.raises(ScriptError):
        vc.build_variables(script, "Approve Now")
    assert vc.build_variables(script, "Asha")["buyer_name"] == "Asha"
