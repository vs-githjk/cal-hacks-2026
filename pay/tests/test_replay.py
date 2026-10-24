"""d2 used-nonce store tests."""
import hashlib
import os
import threading
from datetime import datetime, timedelta, timezone

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


def attempt(**overrides):
    return {"mandate_hash": "a" * 64, "buyer_id": "buyer-1", "deal_id": "deal-1",
            "request_sha256": "b" * 64, "amount_cents": 12345, "currency": "USD", "payee": "seller-1",
            "idempotency_key": "mandate:" + "a" * 64, "message_id": "req:one", "receipt_keyid": "key-1",
            "phase": "submitted", **overrides}


def test_attempt_and_mandate_nonce_are_claimed_atomically(tmp_path):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    row = attempt()
    assert store.start_payment_attempt(row, "nonce-1")
    assert store.seen(NS_MANDATE, "nonce-1")
    assert store.get_payment_attempt(row["mandate_hash"])["phase"] == "submitted"
    assert not store.start_payment_attempt(row, "nonce-1")


def test_attempt_claim_race_across_store_connections_has_one_winner(tmp_path):
    path = str(tmp_path / "attempts.sqlite")
    stores = [NonceStore(path), NonceStore(path)]
    row = attempt()
    barrier, wins = threading.Barrier(2), []

    def claim(store):
        barrier.wait()
        wins.append(store.start_payment_attempt(row, "nonce-1"))

    threads = [threading.Thread(target=claim, args=(store,)) for store in stores]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(wins) == [False, True]


def test_uncertain_attempt_can_only_be_claimed_by_same_buyer_and_deal(tmp_path):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    row = attempt()
    store.start_payment_attempt(row, "nonce-1")
    assert store.finish_payment_attempt(row["mandate_hash"], "uncertain", reason="timeout")
    assert store.claim_uncertain_attempt("other-deal", "buyer-1", row["mandate_hash"]) is None
    claimed = store.claim_uncertain_attempt("deal-1", "buyer-1", row["mandate_hash"])
    assert claimed["phase"] == "reconciling" and claimed["idempotency_key"] == row["idempotency_key"]


def test_submitted_attempt_recovers_as_uncertain_without_retry(tmp_path):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    row = attempt()
    store.start_payment_attempt(row, "nonce-1")
    assert store.recover_submitted_attempts() == 1
    assert store.get_payment_attempt(row["mandate_hash"])["phase"] == "uncertain"


def retirement_body(*, amount="123.45", currency="USD", recipient="seller-1", reference="a" * 64,
                    description="deal deal-1"):
    from uagents_core.contrib.protocols.payment import Funds, RequestPayment
    request = RequestPayment(accepted_funds=[Funds(amount=amount, currency=currency, payment_method="stripe")],
        recipient=recipient, deadline_seconds=300, reference=reference, description=description)
    return request.model_dump_json().encode("utf-8")


def test_unsubmitted_retirement_consumes_nonce_and_is_idempotent(tmp_path):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    body = retirement_body()
    row = store.retirement_attempt(mandate_hash="a" * 64, buyer_id="buyer-1", deal_id="deal-1",
        request_body=body, amount_cents=12345, currency="USD", payee="seller-1")
    assert row["message_id"] == "req:" + hashlib.sha256(b"buyer-1\n" + body).hexdigest()
    assert row["receipt_keyid"] == "not-submitted"
    assert store.retire_unsubmitted_attempt(row, "nonce-1") is True
    saved = store.get_payment_attempt(row["mandate_hash"])
    assert saved["phase"] == "refused" and saved["reason"] == "retired_before_submission"
    assert store.seen(NS_MANDATE, "nonce-1")
    assert store.retire_unsubmitted_attempt(row, "nonce-1") is True
    assert store.consume(NS_MANDATE, "nonce-2") is True
    assert store.retire_unsubmitted_attempt(row, "nonce-2") is False


def test_retirement_is_not_proven_by_other_refused_attempt(tmp_path):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    submitted = attempt()
    assert store.start_payment_attempt(submitted, "nonce-1")
    assert store.finish_payment_attempt(submitted["mandate_hash"], "refused", reason="attempt_binding_mismatch")
    retirement = {**submitted, "receipt_keyid": "not-submitted", "phase": "refused"}
    assert store.retire_unsubmitted_attempt(retirement, "nonce-1") is False


def test_generic_attempt_finish_cannot_forge_retirement_proof(tmp_path):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    submitted = attempt(receipt_keyid="not-submitted")
    assert store.start_payment_attempt(submitted, "nonce-1")
    with pytest.raises(ValueError, match="only atomic retirement"):
        store.finish_payment_attempt(submitted["mandate_hash"], "refused",
                                     reason="retired_before_submission")
    retirement = {**submitted, "phase": "refused"}
    assert store.retire_unsubmitted_attempt(retirement, "nonce-1") is False


@pytest.mark.parametrize("phase", ["submitted", "reconciling", "uncertain", "charged"])
def test_retirement_refuses_every_attempt_that_may_have_reached_charger(tmp_path, phase):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    submitted = attempt()
    assert store.start_payment_attempt(submitted, "nonce-1")
    if phase == "uncertain":
        assert store.finish_payment_attempt(submitted["mandate_hash"], "uncertain", reason="timeout")
    elif phase == "reconciling":
        assert store.finish_payment_attempt(submitted["mandate_hash"], "uncertain", reason="timeout")
        assert store.claim_uncertain_attempt("deal-1", "buyer-1", submitted["mandate_hash"])
    elif phase == "charged":
        assert store.finish_payment_attempt(submitted["mandate_hash"], "charged", charge_id="pi_test_cached")
    retirement = {**submitted, "receipt_keyid": "not-submitted", "phase": "refused"}
    assert store.retire_unsubmitted_attempt(retirement, "nonce-1") is False


def test_retirement_and_submission_race_has_one_terminal_winner(tmp_path):
    path = str(tmp_path / "attempts.sqlite")
    stores = [NonceStore(path), NonceStore(path)]
    body = retirement_body()
    message_id = "req:" + hashlib.sha256(b"buyer-1\n" + body).hexdigest()
    submission = attempt(request_sha256=hashlib.sha256(body).hexdigest(), message_id=message_id)
    retirement = stores[0].retirement_attempt(mandate_hash=submission["mandate_hash"], buyer_id="buyer-1",
        deal_id="deal-1", request_body=body, amount_cents=12345, currency="USD", payee="seller-1")
    barrier, outcomes = threading.Barrier(2), {}

    def submit():
        barrier.wait()
        outcomes["submit"] = stores[0].start_payment_attempt(submission, "nonce-1")

    def retire():
        barrier.wait()
        outcomes["retire"] = stores[1].retire_unsubmitted_attempt(retirement, "nonce-1")

    threads = [threading.Thread(target=submit), threading.Thread(target=retire)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert outcomes["submit"] != outcomes["retire"]
    saved = stores[0].get_payment_attempt(submission["mandate_hash"])
    assert saved["phase"] == ("submitted" if outcomes["submit"] else "refused")
    if saved["phase"] == "refused":
        assert saved["reason"] == "retired_before_submission"


@pytest.mark.parametrize("field,value", [("buyer_id", "other"), ("request_sha256", "c" * 64),
                                          ("receipt_keyid", "key-1")])
def test_retirement_rejects_changed_identity_or_receipt_binding(tmp_path, field, value):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    body = retirement_body()
    row = store.retirement_attempt(mandate_hash="a" * 64, buyer_id="buyer-1", deal_id="deal-1",
        request_body=body, amount_cents=12345, currency="USD", payee="seller-1")
    changed = {**row, field: value}
    assert store.retire_unsubmitted_attempt(row, "nonce-1")
    if field == "buyer_id":
        assert store.retire_unsubmitted_attempt(changed, "nonce-1") is False
    elif field == "request_sha256":
        assert store.retire_unsubmitted_attempt(changed, "nonce-1") is False
    else:
        with pytest.raises(ValueError):
            store.retire_unsubmitted_attempt(changed, "nonce-1")


@pytest.mark.parametrize("body", [
    retirement_body(amount="123.46"),
    retirement_body(currency="CAD"),
    retirement_body(recipient="other-seller"),
    retirement_body(reference="b" * 64),
    retirement_body(description="deal other-deal"),
    b'{"reference":"' + b"a" * 64 + b'","reference":"' + b"a" * 64 + b'"}',
    b'{"accepted_funds": NaN}',
    b"not json",
])
def test_retirement_requires_strict_request_body_matching_metadata(tmp_path, body):
    store = NonceStore(str(tmp_path / "attempts.sqlite"))
    with pytest.raises(ValueError, match="RequestPayment"):
        store.retirement_attempt(mandate_hash="a" * 64, buyer_id="buyer-1", deal_id="deal-1",
            request_body=body, amount_cents=12345, currency="USD", payee="seller-1")


def test_goal_call_budget_persists_by_buyer_and_parent_goal(tmp_path):
    path = str(tmp_path / "goal-calls.sqlite")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = "a" * 64
    second = "b" * 64
    store = NonceStore(path)
    assert store.claim_goal_call("buyer-1", "parent-goal", first, now)
    assert not store.claim_goal_call("buyer-1", "parent-goal", second, now + timedelta(minutes=29))
    assert NonceStore(path).claim_goal_call("buyer-1", "parent-goal", second, now + timedelta(minutes=30))
    assert not store.claim_goal_call("buyer-1", "parent-goal", first, now + timedelta(hours=1))
    assert store.claim_goal_call("buyer-2", "parent-goal", first, now)
    assert store.claim_goal_call("buyer-1", "another-goal", first, now)


def test_goal_call_budget_denies_clock_rollback_and_bad_inputs():
    store = NonceStore()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert store.claim_goal_call("buyer-1", "goal-1", "a" * 64, now)
    assert not store.claim_goal_call("buyer-1", "goal-1", "b" * 64, now - timedelta(seconds=1))
    for args in (("", "goal-1", "c" * 64, now), ("buyer-1", "", "c" * 64, now),
                 ("buyer-1", "goal-1", "not-a-hash", now),
                 ("buyer-1", "goal-1", "c" * 64, now.replace(tzinfo=None)),
                 ("buyer-1", "goal-1", "c" * 64,
                  now.astimezone(timezone(timedelta(hours=1))))):
        assert not store.claim_goal_call(*args)


def test_goal_call_budget_two_connections_have_one_winner(tmp_path):
    path = str(tmp_path / "goal-race.sqlite")
    stores = [NonceStore(path), NonceStore(path)]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    barrier, results = threading.Barrier(2), []

    def claim(store, mandate_hash):
        barrier.wait()
        results.append(store.claim_goal_call("buyer", "parent", mandate_hash, now))

    threads = [threading.Thread(target=claim, args=(stores[i], c * 64))
               for i, c in enumerate(("a", "b"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(results) == [False, True]
