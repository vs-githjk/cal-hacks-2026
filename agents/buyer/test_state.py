import os
import sys
import threading
import sqlite3
import stat
import subprocess
import ctypes
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from buyer import state
from pay.replay import NonceStore


def state_path(tmp_path):
    return tmp_path / ".state" / "private.sqlite3"


@pytest.fixture
def db(tmp_path):
    conn = state.open_state(state_path(tmp_path))
    yield conn
    conn.close()


def owned(buyer_id, sku, name):
    return {"id": name, "buyer_id": buyer_id, "sku_spec": sku, "item_name": name,
            "condition": "unknown", "acquired_on": "", "source": "told_by_user", "attrs": {}, "notes": "user note"}


def goal(goal_id, buyer_id, cap=500):
    return {"id": goal_id, "buyer_id": buyer_id, "type": "budget_cap", "items": [], "cap": cap,
            "deadline": "2099-01-01T00:00:00Z", "state": "ACTIVE", "reserved_amount": 0,
            "created_at": "2026-10-24T00:00:00+00:00"}


def transaction(deal_id, buyer_id, phase="pending_approval"):
    return {"deal_id": deal_id, "buyer_id": buyer_id, "goal_id": "goal-1", "need_id": "need-1",
            "bid_id": "bid-1", "phase": phase,
            "deal": {"id": deal_id, "goal_id": "goal-1", "bid_id": "bid-1", "need_id": "need-1",
                     "amount": 400, "payee": "seller-1"}, "order": None,
            "mandate": {"id": f"mandate-{deal_id}", "deal_id": deal_id, "buyer_id": buyer_id,
                        "goal_id": "goal-1", "amount": 400, "currency": "USD", "payee": "seller-1",
                        "nonce": f"nonce-{deal_id}", "created_at": "2026-10-24T00:00:00Z",
                        "expires_at": "2026-10-24T00:10:00Z", "hash": "a" * 64,
                        "within_allowance": False, "status": "pending", "origin": "SIM"},
            "advocate_card": {"need_id": "need-1", "bid_id": "bid-1", "warnings": [],
                              "recommendation": "buy", "wait_until": "",
                              "call_reason": {"rule_id": "advocate.ok", "summary": "The bid fits the goal.",
                                              "source_url": "https://example.com/review"}}
            }


def test_owned_parts_round_trip_per_buyer_and_replace_same_kind(db):
    state.remember_owned(db, "buyer-a", [owned("buyer-a", "psu 550w", "old PSU")])
    parts = state.remember_owned(db, "buyer-a", [owned("buyer-a", "psu 750w", "new PSU")])
    state.remember_owned(db, "buyer-b", [owned("buyer-b", "psu 650w", "other PSU")])

    assert [p["item_name"] for p in parts] == ["new PSU"]
    assert state.load_owned_parts(db, "buyer-a") == parts
    assert [p["item_name"] for p in state.load_owned_parts(db, "buyer-b")] == ["other PSU"]


def test_goals_and_transactions_survive_reopen_and_are_owner_bound(tmp_path):
    path = state_path(tmp_path)
    first = state.open_state(path)
    state.save_goal(first, goal("goal-1", "buyer-a"))
    state.save_transaction(first, transaction("deal-1", "buyer-a"))
    first.close()

    second = state.open_state(path)
    assert state.load_goal(second, "goal-1", "buyer-a")["cap"] == 500
    assert state.load_goal(second, "goal-1", "buyer-b") is None
    assert state.load_transaction(second, "deal-1", "buyer-a")["advocate_card"]["bid_id"] == "bid-1"
    assert state.load_transaction(second, "deal-1", "buyer-b") is None
    second.close()


def test_goal_and_transaction_ids_cannot_be_reassigned_to_another_owner(db):
    state.save_goal(db, goal("goal-1", "buyer-a"))
    state.save_transaction(db, transaction("deal-1", "buyer-a"))

    with pytest.raises(ValueError):
        state.save_goal(db, goal("goal-1", "buyer-b"))
    with pytest.raises(ValueError):
        state.save_transaction(db, transaction("deal-1", "buyer-b"))

    assert state.load_goal(db, "goal-1", "buyer-a")["buyer_id"] == "buyer-a"
    assert state.load_transaction(db, "deal-1", "buyer-a")["buyer_id"] == "buyer-a"


def test_load_rejects_state_rows_whose_payload_disagrees_with_indexed_columns(db):
    state.remember_owned(db, "buyer-a", [owned("buyer-a", "psu 750w", "PSU")])
    state.save_transaction(db, transaction("deal-1", "buyer-a"))
    db.execute("UPDATE owned_parts SET kind='gpu' WHERE buyer_id='buyer-a'")
    db.execute("UPDATE transactions SET phase='submitted' WHERE deal_id='deal-1'")
    db.commit()

    with pytest.raises(ValueError):
        state.load_owned_parts(db, "buyer-a")
    with pytest.raises(ValueError):
        state.load_transaction(db, "deal-1", "buyer-a")
    with pytest.raises(ValueError):
        state.recover_on_start(db)


@pytest.mark.parametrize("bad", [
    {"context": object()}, {"approval_code": "CANARY"}, {"password": "secret"},
    {"api_key": "secret"}, {"voice_approval": {"code": "CANARY"}},
])
def test_transaction_rejects_runtime_context_codes_and_credentials(db, bad):
    value = transaction("deal-1", "buyer-a")
    value.update(bad)
    with pytest.raises((TypeError, ValueError)):
        state.save_transaction(db, value)
    assert state.load_transaction(db, "deal-1", "buyer-a") is None


def test_transaction_rejects_id_mismatch_and_non_json_numbers(db):
    mismatched = transaction("deal-1", "buyer-a")
    mismatched["mandate"]["deal_id"] = "other-deal"
    with pytest.raises(ValueError):
        state.save_transaction(db, mismatched)
    invalid = transaction("deal-2", "buyer-a")
    invalid["mandate"]["amount"] = float("nan")
    with pytest.raises(ValueError):
        state.save_transaction(db, invalid)
    coded = transaction("deal-3", "buyer-a")
    coded["deal"]["code_hash"] = "c" * 64
    with pytest.raises(ValueError):
        state.save_transaction(db, coded)


def test_transaction_requires_persisted_review_bound_to_same_bid(db):
    missing = transaction("deal-1", "buyer-a")
    del missing["advocate_card"]
    with pytest.raises(ValueError, match="AdvocateCard"):
        state.save_transaction(db, missing)

    mismatch = transaction("deal-2", "buyer-a")
    mismatch["deal"]["bid_id"] = "bid-other"
    with pytest.raises(ValueError, match="bid"):
        state.save_transaction(db, mismatch)


def test_voice_approval_stores_hash_and_timestamps_but_never_raw_code(db):
    value = transaction("deal-1", "buyer-a")
    mandate = value["mandate"]
    value["voice_approval"] = {
        "id": "approval-1", "mandate_id": mandate["id"], "mandate_hash": mandate["hash"],
        "channel": "typed", "code_issued_at": "2026-10-24T00:00:00Z",
        "code_expires_at": "2026-10-24T00:02:00Z", "code_hash": "b" * 64,
        "attempts": 1, "amount_read_back": 400, "payee_read_back": "seller-1",
        "result": "approved", "deny_reason": None,
        "decided_at": "2026-10-24T00:01:00Z", "recording_ref": None,
    }
    state.save_transaction(db, value)
    assert state.load_transaction(db, "deal-1", "buyer-a")["voice_approval"]["code_hash"] == "b" * 64

    value["voice_approval"]["code"] = "CANARY"
    with pytest.raises(ValueError):
        state.save_transaction(db, value)


def test_sqlite_connection_rejects_use_from_worker_thread(db):
    errors = []

    def read_from_worker():
        try:
            db.execute("SELECT 1")
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=read_from_worker)
    worker.start()
    worker.join()
    assert len(errors) == 1
    assert isinstance(errors[0], sqlite3.ProgrammingError)


def test_startup_recovery_is_explicit_and_preserves_nonce_replay(tmp_path):
    path = state_path(tmp_path)
    first = state.open_state(path)
    state.save_transaction(first, transaction("deal-pending", "buyer-a", "pending_approval"))
    state.save_transaction(first, transaction("deal-submitted", "buyer-a", "submitted"))
    assert NonceStore(str(path)).consume("tap", "one-time")
    first.close()

    second = state.open_state(path)
    assert state.load_transaction(second, "deal-pending", "buyer-a")["phase"] == "pending_approval"
    state.recover_on_start(second)
    assert state.load_transaction(second, "deal-pending", "buyer-a")["phase"] == "paused"
    assert state.load_transaction(second, "deal-submitted", "buyer-a")["phase"] == "uncertain"
    second.close()

    replay = NonceStore(str(path))
    assert replay.seen("tap", "one-time")
    assert not replay.consume("tap", "one-time")


def test_corrupt_state_file_fails_closed_without_replacing_bytes(tmp_path):
    path = state_path(tmp_path)
    path.parent.mkdir()
    path.write_bytes(b"not a sqlite database")

    with pytest.raises((ValueError, OSError)):
        state.open_state(path)

    assert path.read_bytes() == b"not a sqlite database"


def test_legacy_default_state_blocks_empty_startup_without_migrating(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    legacy_path = agents_dir / ".state.sqlite3"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"preserve legacy data")
    new_path = agents_dir / ".state" / "state.sqlite3"
    monkeypatch.setattr(state, "DEFAULT_DB_PATH", new_path)
    monkeypatch.setattr(state, "LEGACY_DB_PATH", legacy_path)

    with pytest.raises(ValueError, match="legacy buyer state exists"):
        state.open_state()

    assert legacy_path.read_bytes() == b"preserve legacy data"
    assert not new_path.parent.exists()


def test_state_file_permissions_are_private_for_current_platform(tmp_path):
    path = state_path(tmp_path)
    db = state.open_state(path)
    db.close()
    if os.name == "nt":
        acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True).stdout
        assert "(I)" not in acl
        assert "BUILTIN\\Users:" not in acl
        assert "Everyone:" not in acl
        assert "Authenticated Users:" not in acl
        assert "Successfully processed 1 files" in acl
    else:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("conversion_succeeds,apply_succeeds", [(True, True), (False, True), (True, False)])
@pytest.mark.skipif(os.name != "nt", reason="Windows ACL implementation")
def test_windows_acl_replacement_is_single_protected_dacl_mutation(
    monkeypatch, tmp_path, conversion_succeeds, apply_succeeds
):
    class ApiFunction:
        argtypes = None
        restype = None

        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    descriptor_sd = ""
    set_calls = []
    frees = []

    def convert(sddl, revision, descriptor_out, size_out):
        nonlocal descriptor_sd
        descriptor_sd = sddl
        ctypes.cast(descriptor_out, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(1234)
        return conversion_succeeds

    advapi32 = type("Advapi", (), {
        "ConvertStringSecurityDescriptorToSecurityDescriptorW": ApiFunction(convert),
        "SetFileSecurityW": ApiFunction(lambda *args: set_calls.append(args) or apply_succeeds),
    })()
    kernel32 = type("Kernel", (), {"LocalFree": ApiFunction(lambda ptr: frees.append(ptr) or None)})()
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **kwargs: advapi32 if name == "advapi32" else kernel32,
                        raising=False)
    monkeypatch.setattr(state.subprocess, "run", lambda *args, **kwargs: type("Result", (), {
        "stdout": '"DOMAIN\\user","S-1-5-21-123"\n', "returncode": 0})())

    if not conversion_succeeds or not apply_succeeds:
        with pytest.raises(OSError):
            state._restrict_windows_acl(tmp_path / "private.sqlite3")
        assert len(set_calls) == int(conversion_succeeds)
        assert len(frees) == int(conversion_succeeds)
        return

    state._restrict_windows_acl(tmp_path / "private.sqlite3")

    assert descriptor_sd == "D:P(A;;FA;;;S-1-5-21-123)"
    assert len(set_calls) == 1
    assert set_calls[0][1] == 0x00000004 | 0x80000000
    assert [ptr.value for ptr in frees] == [1234]


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL regression")
def test_state_open_removes_preexisting_broad_read_acl(tmp_path):
    path = state_path(tmp_path)
    state.open_state(path).close()
    subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:(R)"],
                   capture_output=True, text=True, check=True)

    state.open_state(path).close()
    acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True).stdout
    assert "(I)" not in acl
    assert "Everyone:" not in acl
    assert "S-1-1-0" not in acl
    assert "Successfully processed 1 files" in acl


@pytest.mark.skipif(os.name != "nt", reason="Windows SQLite sidecar ACL regression")
def test_state_journal_sidecar_is_private_when_parent_acl_is_broad(tmp_path):
    directory = tmp_path / "broad-parent"
    directory.mkdir()
    subprocess.run(["icacls", str(directory), "/grant", "*S-1-1-0:(OI)(CI)(R)"],
                   capture_output=True, text=True, check=True)
    path = directory / ".state" / "private.sqlite3"
    db = state.open_state(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO owned_parts VALUES (?, ?, ?)", ("buyer-a", "widget", "{}"))
        journal = Path(str(path) + "-journal")
        assert journal.exists()
        acl = subprocess.run(["icacls", str(journal)], capture_output=True, text=True, check=True).stdout
        assert "S-1-1-0" not in acl
        assert "Everyone:" not in acl
    finally:
        db.rollback()
        db.close()
