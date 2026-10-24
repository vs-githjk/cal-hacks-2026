"""d2 used-nonce store tests."""
import json
import os

import pytest

from pay.replay import NS_MANDATE, NS_TAP, NonceStore


def test_first_use_true_second_false():
    s = NonceStore()
    assert not s.seen(NS_TAP, "n1")
    assert s.consume(NS_TAP, "n1") is True
    assert s.seen(NS_TAP, "n1")
    assert s.consume(NS_TAP, "n1") is False


def test_namespaces_are_separate():
    s = NonceStore()
    assert s.consume(NS_TAP, "n1")
    assert s.consume(NS_MANDATE, "n1")


def test_persists_to_json_file(tmp_path):
    p = str(tmp_path / "nonces.json")
    a = NonceStore(p)
    assert a.consume(NS_TAP, "n1")
    assert json.load(open(p))[NS_TAP].keys() == {"n1"}
    b = NonceStore(p)  # a restart
    assert b.consume(NS_TAP, "n1") is False
    assert b.consume(NS_TAP, "n2") is True
    assert os.listdir(tmp_path) == ["nonces.json"]  # no temp files left


def test_corrupt_file_fails_closed(tmp_path):
    p = tmp_path / "nonces.json"
    p.write_text("{not json")
    with pytest.raises(ValueError):
        NonceStore(str(p))
    p.write_text("[1,2]")
    with pytest.raises(ValueError):
        NonceStore(str(p))


def test_empty_nonce_refused():
    with pytest.raises(ValueError):
        NonceStore().consume(NS_TAP, "")
