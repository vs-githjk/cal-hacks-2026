"""d2 used-nonce store tests."""
import os
import threading

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


def test_persists_to_a_file_and_survives_a_restart(tmp_path):
    p = str(tmp_path / "nonces.db")
    a = NonceStore(p)
    assert a.consume(NS_TAP, "n1")
    assert os.path.exists(p)
    b = NonceStore(p)  # a restart
    assert b.seen(NS_TAP, "n1")
    assert b.consume(NS_TAP, "n1") is False
    assert b.consume(NS_TAP, "n2") is True


def test_corrupt_file_fails_closed(tmp_path):
    p = tmp_path / "nonces.db"
    p.write_text("{not a database")
    with pytest.raises(ValueError):
        NonceStore(str(p))
    p.write_bytes(b"\x00" * 4096)
    with pytest.raises(ValueError):
        NonceStore(str(p))


def test_two_instances_on_one_file_race_and_only_one_wins_each_nonce(tmp_path):
    p = str(tmp_path / "nonces.db")
    stores = [NonceStore(p), NonceStore(p)]
    nonces = [f"n{i}" for i in range(200)]
    wins = [[], []]
    barrier = threading.Barrier(2)

    def worker(idx):
        barrier.wait()
        for n in nonces:
            if stores[idx].consume(NS_MANDATE, n):
                wins[idx].append(n)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(wins[0] + wins[1]) == sorted(nonces)  # every nonce won exactly once
    assert not set(wins[0]) & set(wins[1])


def test_two_instances_second_cannot_reuse_what_the_first_consumed(tmp_path):
    p = str(tmp_path / "nonces.db")
    a, b = NonceStore(p), NonceStore(p)
    assert a.consume(NS_TAP, "x") is True
    assert b.seen(NS_TAP, "x")
    assert b.consume(NS_TAP, "x") is False


def test_empty_nonce_refused():
    with pytest.raises(ValueError):
        NonceStore().consume(NS_TAP, "")
