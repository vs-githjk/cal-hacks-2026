"""Used-nonce store: SQLite, in memory or in a file, so a restart does not forget and two processes agree.

One store holds several namespaces ("mandate" for mandate nonces, "tap" for signed-request nonces).
`consume` is the only way to record a use. It is one `INSERT` against a UNIQUE (namespace, nonce)
constraint, so the database decides the winner: the first caller, in this process or another one
sharing the file, gets True and every later caller gets False (a replay). A corrupt or non-SQLite file
raises instead of loading empty, because an empty store would let every old nonce be replayed (fail closed).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

NS_MANDATE = "mandate"
NS_TAP = "tap"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS used_nonce (
    namespace TEXT NOT NULL,
    nonce     TEXT NOT NULL,
    used_at   REAL NOT NULL,
    UNIQUE (namespace, nonce)
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
            self._db.execute(_SCHEMA)
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
