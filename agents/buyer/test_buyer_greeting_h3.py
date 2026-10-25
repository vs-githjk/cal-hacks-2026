"""H3: the hosted web-buyer path greets with the same rule as the CLI path (pay.voice_cartesia.greeting_name): the buyer's own plain
display_name, else "there"; the default buyer's APPROVAL_BUYER_NAME is never used for anyone else; an accented or digit name must not
make build_variables raise (which would deny the deal before any call)."""
from __future__ import annotations

import pytest

from pay import voice_cartesia as vc
from test_any_buyer import BID, _call
from test_runtime_checkout import runtime  # noqa: F401

PHONE = "+14155550111"


@pytest.mark.parametrize("name", ["José", "Zoë", "Ana2", "", "   ", None, "x" * 80])
def test_a_web_buyer_with_an_unusable_name_is_greeted_as_there_and_the_call_proceeds(runtime, monkeypatch, name):
    buyer, _db = runtime
    client, why, greeted = _call(buyer, monkeypatch, BID, {"display_name": name, "phone": PHONE})
    assert client is not None and client.to == PHONE and why == ""
    assert greeted == "there" != vc.DEFAULT_BUYER_NAME
    vc.build_variables(_script(), greeted)   # the call script accepts it, so the deal is not denied before the call


def test_a_web_buyer_is_never_greeted_by_the_env_buyer_name(runtime, monkeypatch):
    buyer, _db = runtime
    monkeypatch.setattr("pay.voice_cartesia.load_env", lambda *a, **k: {"APPROVAL_CALL_TO": "+14155550999", "APPROVAL_BUYER_NAME": "Vidyut"})
    from unittest.mock import patch
    buyer.MARKET_REFEREE.buyer_contact.return_value = {"display_name": "", "phone": PHONE}
    with patch("pay.voice_cartesia.CartesiaClient.from_env", side_effect=lambda env, **kw: type("C", (), {"to": env["APPROVAL_CALL_TO"]})()):
        _client, _why, greeted = buyer._approval_call(BID)
    assert greeted == "there"


def test_a_plain_name_is_kept_and_the_default_buyer_keeps_the_env_name(runtime, monkeypatch):
    buyer, _db = runtime
    assert _call(buyer, monkeypatch, BID, {"display_name": "Asha", "phone": PHONE})[2] == "Asha"
    client, _why, greeted = _call(buyer, monkeypatch, vc.DEFAULT_APPROVAL_BUYER, {"display_name": "Someone", "phone": None}, default="vidyut")
    assert client is not None and greeted == vc.DEFAULT_BUYER_NAME


def _script():
    from pay.callscript import CallScript
    return CallScript(opening="Hello", deal_line="One purchase", ask_line="Say approve", why_answer="Best price",
                      approved_line="Approved", denied_line="Denied", amount_read_back=100, payee_read_back="Shop")
