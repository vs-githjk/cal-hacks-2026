import sqlite3

import pytest

from agents.sellers.learning import apply_loss, load_strategy, open_learning_state


@pytest.fixture
def db(tmp_path):
    conn = open_learning_state(tmp_path / ".state" / "state.sqlite3")
    yield conn
    conn.close()


def report(**changes):
    value = {"id": "loss-1", "round_id": "round-1", "seller_id": "seller-a", "won": False,
             "gap_band": "within10", "reason": "price", "source_url": "https://shop.example/item/1",
             "created_at": "2026-10-24T10:00:00Z"}
    value.update(changes)
    return value


def _counts(db):
    return (db.execute("SELECT count(*) FROM seller_learning_strategy").fetchone()[0],
            db.execute("SELECT count(*) FROM seller_learning_reports").fetchone()[0])


@pytest.mark.parametrize("changes,seller", [
    ({"id": ""}, "seller-a"),
    ({"id": "x" * 129}, "seller-a"),
    ({"won": True}, "seller-a"),
    ({"other": "buyer cap"}, "seller-a"),
    ({"seller_id": "seller-b"}, "seller-a"),
    ({"gap_band": "unknown"}, "seller-a"),
    ({"reason": "price", "source_url": "javascript:alert(1)"}, "seller-a"),
    ({"source_url": "https://user:pass@shop.example/item"}, "seller-a"),
    ({"round_id": " "}, "seller-a"),
    ({"created_at": ""}, "seller-a"),
    ({}, " "),
])
def test_invalid_reports_leave_storage_unchanged(db, changes, seller):
    with pytest.raises(ValueError):
        apply_loss(db, report(**changes), seller)
    assert _counts(db) == (0, 0)
    assert load_strategy(db, "seller-a") == {"price_step": 0.0}


def test_missing_report_id_leaves_storage_unchanged(db):
    malformed = report()
    del malformed["id"]
    with pytest.raises(ValueError, match="exactly the LossReport fields"):
        apply_loss(db, malformed, "seller-a")
    assert _counts(db) == (0, 0)


def test_price_loss_uses_shared_deterministic_update(db):
    applied = apply_loss(db, report(), "seller-a")
    assert applied == {
        "report_id": "loss-1", "source_url": "https://shop.example/item/1",
        "strategy": {"price_step": 0.07}, "diff": {"price_step": {"from": 0.0, "to": 0.07}},
        "what_to_change": "You lost on price by less than 10 percent. Lower your price by about 7%, and keep it above your floor.",
    }
    assert load_strategy(db, "seller-a") == {"price_step": 0.07}


@pytest.mark.parametrize("reason", ["fit", "advocate_veto"])
def test_non_price_loss_persists_receipt_without_strategy_change(db, reason):
    applied = apply_loss(db, report(reason=reason), "seller-a")
    assert applied["strategy"] == {"price_step": 0.0}
    assert applied["diff"] == {}
    assert applied["what_to_change"] == f"You lost on {reason.replace('_', ' ')}. Review the cited source."
    assert load_strategy(db, "seller-a") == {"price_step": 0.0}
    assert _counts(db) == (1, 1)


def test_duplicate_is_idempotent_across_reopen(tmp_path):
    path = tmp_path / ".state" / "state.sqlite3"
    first = open_learning_state(path)
    assert apply_loss(first, report(), "seller-a") is not None
    assert apply_loss(first, report(gap_band="over20"), "seller-a") is None
    assert load_strategy(first, "seller-a") == {"price_step": 0.07}
    first.close()

    reopened = open_learning_state(path)
    assert apply_loss(reopened, report(gap_band="over20"), "seller-a") is None
    assert load_strategy(reopened, "seller-a") == {"price_step": 0.07}
    assert _counts(reopened) == (1, 1)
    reopened.close()


def test_existing_report_id_cannot_be_reassigned(db):
    apply_loss(db, report(), "seller-a")
    with pytest.raises(ValueError, match="different seller"):
        apply_loss(db, report(seller_id="seller-b"), "seller-b")
    assert _counts(db) == (1, 1)
    assert load_strategy(db, "seller-b") == {"price_step": 0.0}


def test_strategy_and_report_receipt_roll_back_together(db):
    db.execute("""CREATE TRIGGER fail_report BEFORE INSERT ON seller_learning_reports
        BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected receipt failure"):
        apply_loss(db, report(), "seller-a")
    assert load_strategy(db, "seller-a") == {"price_step": 0.0}
    assert _counts(db) == (0, 0)


@pytest.mark.parametrize("raw", ['{"price_step":NaN}', '{"price_step":0.04}', '{"price_step":true}', '{"price_step":0,"other":1}'])
def test_load_strategy_rejects_corrupt_or_out_of_band_values(db, raw):
    db.execute("INSERT INTO seller_learning_strategy (seller_id, strategy_json) VALUES (?, ?)", ("seller-a", raw))
    with pytest.raises(ValueError, match="strategy is invalid"):
        load_strategy(db, "seller-a")
