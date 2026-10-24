"""Used-nonce store: SQLite, in memory or in a file, so a restart does not forget and two processes agree.

One store holds several namespaces ("mandate" for mandate nonces, "tap" for signed-request nonces).
`consume` is the only way to record a use. It is one `INSERT` against a UNIQUE (namespace, nonce)
constraint, so the database decides the winner: the first caller, in this process or another one
sharing the file, gets True and every later caller gets False (a replay). A corrupt or non-SQLite file
raises instead of loading empty, because an empty store would let every old nonce be replayed (fail closed).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from decimal import Decimal, InvalidOperation, Overflow
from typing import Optional

NS_MANDATE = "mandate"
NS_TAP = "tap"
RETIRED_BEFORE_SUBMISSION = "retired_before_submission"


def _retirement_request_matches(request_body: bytes, *, mandate_hash: str, deal_id: str,
                                amount_cents: int, currency: str, payee: str) -> bool:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("invalid JSON constant")

    try:
        if len(request_body) > 32 * 1024:
            return False
        request = json.loads(request_body.decode("utf-8"), object_pairs_hook=unique_pairs,
                             parse_constant=reject_constant)
        funds = request.get("accepted_funds") if isinstance(request, dict) else None
        if (not isinstance(request, dict)
                or set(request) - {"accepted_funds", "recipient", "deadline_seconds", "reference",
                                   "description", "metadata"}
                or not isinstance(funds, list) or len(funds) != 1 or not isinstance(funds[0], dict)
                or set(funds[0]) != {"amount", "currency", "payment_method"}
                or not isinstance(funds[0]["amount"], str)
                or not re.fullmatch(r"[0-9]+\.[0-9]{2}", funds[0]["amount"])
                or funds[0]["currency"] != currency or funds[0]["payment_method"] != "stripe"
                or request.get("recipient") != payee or request.get("reference") != mandate_hash
                or request.get("description") != "deal " + deal_id
                or isinstance(request.get("deadline_seconds"), bool)
                or not isinstance(request.get("deadline_seconds"), int) or request["deadline_seconds"] <= 0
                or ("metadata" in request and request["metadata"] is not None
                    and not isinstance(request["metadata"], dict))):
            return False
        try:
            parsed_amount = Decimal(funds[0]["amount"])
            return (parsed_amount.is_finite() and parsed_amount.adjusted() <= 11
                    and parsed_amount * 100 == amount_cents)
        except (InvalidOperation, Overflow, TypeError, ValueError):
            return False
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS used_nonce (
    namespace TEXT NOT NULL,
    nonce     TEXT NOT NULL,
    used_at   REAL NOT NULL,
    UNIQUE (namespace, nonce)
)
;
CREATE TABLE IF NOT EXISTS payment_attempt (
    mandate_hash TEXT PRIMARY KEY,
    buyer_id TEXT NOT NULL,
    deal_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    payee TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    message_id TEXT NOT NULL,
    receipt_keyid TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('submitted', 'reconciling', 'uncertain', 'charged', 'refused')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    charge_id TEXT,
    reason TEXT
)
;
CREATE TABLE IF NOT EXISTS payment_attempt_nonce (
    mandate_hash TEXT PRIMARY KEY,
    mandate_nonce TEXT NOT NULL UNIQUE
)
"""


class NonceStore:
    def __init__(self, path: Optional[str] = None):
        self._path = path
        self._lock = threading.Lock()
        try:
            # autocommit: each statement is its own transaction, committed (and fsynced) before it returns
            self._db = sqlite3.connect(path or ":memory:", timeout=30, isolation_level=None,
                                       check_same_thread=False)
            self._db.executescript(_SCHEMA)
            self._db.execute("SELECT COUNT(*) FROM used_nonce").fetchone()
        except sqlite3.DatabaseError as e:
            raise ValueError(f"nonce store file is corrupt: {path}") from e

    def seen(self, namespace: str, nonce: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT 1 FROM used_nonce WHERE namespace = ? AND nonce = ?",
                                   (namespace, nonce)).fetchone()
            return row is not None

    def consume(self, namespace: str, nonce: str, now: Optional[float] = None) -> bool:
        """Record a use. True if this is the first use, False if it was already used."""
        if not isinstance(nonce, str) or not nonce:
            raise ValueError("nonce must be a non-empty string")
        with self._lock:
            try:
                self._db.execute("INSERT INTO used_nonce (namespace, nonce, used_at) VALUES (?, ?, ?)",
                                 (namespace, nonce, time.time() if now is None else now))
            except sqlite3.IntegrityError:
                return False
            return True

    @staticmethod
    def _attempt_row(row) -> Optional[dict]:
        if row is None:
            return None
        names = ("mandate_hash", "buyer_id", "deal_id", "request_sha256", "amount_cents", "currency", "payee",
                 "idempotency_key", "message_id", "receipt_keyid", "phase", "created_at", "updated_at", "charge_id", "reason")
        return dict(zip(names, row))

    def get_payment_attempt(self, mandate_hash: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM payment_attempt WHERE mandate_hash=?", (mandate_hash,)).fetchone()
            return self._attempt_row(row)

    def start_payment_attempt(self, attempt: dict, mandate_nonce: str) -> bool:
        """Atomically persist the immutable attempt and consume the mandate nonce before network submission."""
        required = {"mandate_hash", "buyer_id", "deal_id", "request_sha256", "amount_cents", "currency", "payee",
                    "idempotency_key", "message_id", "receipt_keyid", "phase"}
        if not isinstance(attempt, dict) or set(attempt) != required or attempt["phase"] != "submitted":
            raise ValueError("invalid payment attempt")
        for field in ("mandate_hash", "buyer_id", "deal_id", "request_sha256", "currency", "payee", "message_id", "receipt_keyid"):
            if not isinstance(attempt[field], str) or not attempt[field]:
                raise ValueError(f"{field} must be a non-empty string")
        if (isinstance(attempt["amount_cents"], bool) or not isinstance(attempt["amount_cents"], int)
                or attempt["amount_cents"] <= 0
                or attempt["idempotency_key"] != "mandate:" + attempt["mandate_hash"]
                or not isinstance(mandate_nonce, str) or not mandate_nonce):
            raise ValueError("invalid payment attempt binding")
        now = time.time()
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute("INSERT INTO payment_attempt VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?, NULL, NULL)",
                    (attempt["mandate_hash"], attempt["buyer_id"], attempt["deal_id"], attempt["request_sha256"],
                     attempt["amount_cents"], attempt["currency"], attempt["payee"], attempt["idempotency_key"],
                     attempt["message_id"], attempt["receipt_keyid"], now, now))
                self._db.execute("INSERT INTO used_nonce (namespace, nonce, used_at) VALUES (?, ?, ?)",
                                 (NS_MANDATE, mandate_nonce, now))
                self._db.execute("INSERT INTO payment_attempt_nonce (mandate_hash, mandate_nonce) VALUES (?, ?)",
                                 (attempt["mandate_hash"], mandate_nonce))
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                self._db.rollback()
                return False
            except BaseException:
                self._db.rollback()
                raise

    @staticmethod
    def retirement_attempt(*, mandate_hash: str, buyer_id: str, deal_id: str,
                           request_body: bytes, amount_cents: int, currency: str,
                           payee: str) -> dict:
        """Build the exact local no-submission proof binding for a cancelled request."""
        if not isinstance(request_body, bytes):
            raise ValueError("request_body must be exact RequestPayment bytes")
        if (isinstance(amount_cents, bool) or not isinstance(amount_cents, int)
                or amount_cents <= 0):
            raise ValueError("amount_cents must be a positive integer")
        for field, value in (("mandate_hash", mandate_hash), ("buyer_id", buyer_id),
                             ("deal_id", deal_id), ("currency", currency), ("payee", payee)):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")
        if len(mandate_hash) != 64 or any(c not in "0123456789abcdef" for c in mandate_hash):
            raise ValueError("mandate_hash must be lowercase SHA-256 hex")
        if not _retirement_request_matches(request_body, mandate_hash=mandate_hash, deal_id=deal_id,
                                           amount_cents=amount_cents, currency=currency, payee=payee):
            raise ValueError("RequestPayment bytes do not match retirement binding")
        request_digest = hashlib.sha256(request_body).hexdigest()
        message_id = "req:" + hashlib.sha256(buyer_id.encode("utf-8") + b"\n" + request_body).hexdigest()
        return {"mandate_hash": mandate_hash, "buyer_id": buyer_id, "deal_id": deal_id,
                "request_sha256": request_digest, "amount_cents": amount_cents,
                "currency": currency, "payee": payee,
                "idempotency_key": "mandate:" + mandate_hash, "message_id": message_id,
                "receipt_keyid": "not-submitted", "phase": "refused"}

    def retire_unsubmitted_attempt(self, attempt: dict, mandate_nonce: str) -> bool:
        """Atomically consume a mandate and record positive proof that no charge was submitted.

        True is a no-charge proof only for this operation's terminal marker. Other refused attempts
        may follow an ambiguous charge result and are deliberately not accepted as proof.
        """
        required = {"mandate_hash", "buyer_id", "deal_id", "request_sha256", "amount_cents", "currency",
                    "payee", "idempotency_key", "message_id", "receipt_keyid", "phase"}
        if not isinstance(attempt, dict) or set(attempt) != required or attempt.get("phase") != "refused":
            raise ValueError("invalid unsubmitted payment attempt")
        for field in ("mandate_hash", "buyer_id", "deal_id", "request_sha256", "currency", "payee", "message_id"):
            if not isinstance(attempt[field], str) or not attempt[field]:
                raise ValueError(f"{field} must be a non-empty string")
        if (isinstance(attempt["amount_cents"], bool) or not isinstance(attempt["amount_cents"], int)
                or attempt["amount_cents"] <= 0
                or not isinstance(attempt["request_sha256"], str) or len(attempt["request_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in attempt["request_sha256"])
                or attempt["idempotency_key"] != "mandate:" + attempt["mandate_hash"]
                or attempt["receipt_keyid"] != "not-submitted"
                or not isinstance(mandate_nonce, str) or not mandate_nonce):
            raise ValueError("invalid unsubmitted attempt binding")
        now = time.time()
        immutable = (attempt["mandate_hash"], attempt["buyer_id"], attempt["deal_id"],
                     attempt["request_sha256"], attempt["amount_cents"], attempt["currency"],
                     attempt["payee"], attempt["idempotency_key"], attempt["message_id"],
                     attempt["receipt_keyid"])
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                existing = self._db.execute(
                    "SELECT mandate_hash,buyer_id,deal_id,request_sha256,amount_cents,currency,payee,"
                    "idempotency_key,message_id,receipt_keyid,phase,reason FROM payment_attempt WHERE mandate_hash=?",
                    (attempt["mandate_hash"],)).fetchone()
                if existing is not None:
                    same_immutable = tuple(existing[:10]) == immutable
                    nonce_binding = self._db.execute(
                        "SELECT mandate_nonce FROM payment_attempt_nonce WHERE mandate_hash=?",
                        (attempt["mandate_hash"],)).fetchone()
                    already_retired = (same_immutable and existing[10] == "refused"
                                       and existing[11] == RETIRED_BEFORE_SUBMISSION
                                       and nonce_binding == (mandate_nonce,)
                                       and self._db.execute(
                                           "SELECT 1 FROM used_nonce WHERE namespace=? AND nonce=?",
                                           (NS_MANDATE, mandate_nonce)).fetchone() is not None)
                    self._db.commit()
                    return already_retired
                self._db.execute(
                    "INSERT INTO payment_attempt VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'refused', ?, ?, NULL, ?)" ,
                    (*immutable, now, now, RETIRED_BEFORE_SUBMISSION))
                self._db.execute("INSERT INTO used_nonce (namespace, nonce, used_at) VALUES (?, ?, ?)",
                                 (NS_MANDATE, mandate_nonce, now))
                self._db.execute("INSERT INTO payment_attempt_nonce (mandate_hash, mandate_nonce) VALUES (?, ?)",
                                 (attempt["mandate_hash"], mandate_nonce))
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                self._db.rollback()
                return False
            except BaseException:
                self._db.rollback()
                raise

    def finish_payment_attempt(self, mandate_hash: str, phase: str, charge_id: Optional[str] = None,
                               reason: Optional[str] = None) -> bool:
        if phase not in ("uncertain", "charged", "refused"):
            raise ValueError("invalid terminal payment attempt phase")
        if reason == RETIRED_BEFORE_SUBMISSION:
            raise ValueError("only atomic retirement may record a no-submission proof")
        if phase == "charged" and (not isinstance(charge_id, str) or not charge_id):
            raise ValueError("charged attempt requires charge_id")
        with self._lock:
            cur = self._db.execute("UPDATE payment_attempt SET phase=?, charge_id=?, reason=?, updated_at=? "
                "WHERE mandate_hash=? AND phase IN ('submitted', 'reconciling')",
                (phase, charge_id, reason, time.time(), mandate_hash))
            return cur.rowcount == 1

    def claim_uncertain_attempt(self, deal_id: str, buyer_id: str, mandate_hash: str) -> Optional[dict]:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                cur = self._db.execute("UPDATE payment_attempt SET phase='reconciling', updated_at=? "
                    "WHERE deal_id=? AND buyer_id=? AND mandate_hash=? AND phase='uncertain'",
                    (time.time(), deal_id, buyer_id, mandate_hash))
                self._db.commit()
                if cur.rowcount != 1:
                    return None
                row = self._db.execute("SELECT * FROM payment_attempt WHERE mandate_hash=?", (mandate_hash,)).fetchone()
                return self._attempt_row(row)
            except BaseException:
                self._db.rollback()
                raise

    def recover_submitted_attempts(self) -> int:
        """Mark crash-interrupted submissions uncertain; this never calls the charger."""
        with self._lock:
            cur = self._db.execute("UPDATE payment_attempt SET phase='uncertain', updated_at=? "
                "WHERE phase IN ('submitted', 'reconciling')", (time.time(),))
            return cur.rowcount
