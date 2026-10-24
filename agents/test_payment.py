from datetime import datetime, timedelta, timezone

import pytest

import payment

SELLER = "agent1qseller"


def setup():
    m = payment.make_mandate("deal-1", 589.0, SELLER, buyer_id="joe", within_allowance=False)
    return m, payment.payment_request(m, SELLER), {m["hash"]: {"answer": "approve"}}, set()


def test_commit_only_with_approval_row():
    m, req, _, used = setup()
    with pytest.raises(PermissionError, match="no approval"):
        payment.commit(req, m, {}, used)
    with pytest.raises(PermissionError, match="no approval"):
        payment.commit(req, m, {m["hash"]: {"answer": "deny"}}, used)


def test_happy_path_then_replay_fails():
    m, req, approvals, used = setup()
    c = payment.commit(req, m, approvals, used)
    assert c.reference == m["hash"] and c.funds.amount == "589.00"
    with pytest.raises(PermissionError, match="replay"):
        payment.commit(req, m, approvals, used)


def test_altered_amount_or_payee_fails():
    m, req, approvals, used = setup()
    with pytest.raises(PermissionError, match="altered"):
        payment.commit(req, {**m, "amount": 1.0}, approvals, used)
    swapped = payment.payment_request(m, "agent1qattacker")
    with pytest.raises(PermissionError, match="payee"):
        payment.commit(swapped, m, approvals, used)


def test_expired_fails():
    m, req, approvals, used = setup()
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(PermissionError, match="expired"):
        payment.commit(req, m, approvals, used, now=later)


def test_mandate_matches_contract_and_ttl():
    import common
    m, *_ = setup()
    common.validate("Mandate", m)
    created = datetime.strptime(m["created_at"], payment.TS)
    assert (datetime.strptime(m["expires_at"], payment.TS) - created).total_seconds() <= 600
    assert m["hash"] == payment.mandate_hash({**m, "amount": 589})  # 589.0 and 589 hash the same, as in pay.mandate
