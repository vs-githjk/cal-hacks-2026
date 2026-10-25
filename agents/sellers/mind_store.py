"""Per-seller mind state (the learner's margin, the trickster's history) in the same private sqlite file as the
loss-report ledger. One JSON row per seller; a row that does not parse fails closed instead of resetting a strategy."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable

from agents.sellers import learning


def ensure(db: sqlite3.Connection) -> None:
    """Create the mind table on a connection from learning.open_learning_state."""
    db.execute("""CREATE TABLE IF NOT EXISTS seller_mind_state (
        seller_id TEXT PRIMARY KEY, state_json TEXT NOT NULL)""")
    db.commit()


def open_store(path: str | Path | None = None) -> sqlite3.Connection:
    """The learning ledger's connection plus the mind table. Use it on the creating thread only."""
    db = learning.open_learning_state(path)
    try:
        ensure(db)
        return db
    except Exception:
        db.close()
        raise


def load(db: sqlite3.Connection, seller_id: str, fresh: Callable[[], dict]) -> dict:
    row = db.execute("SELECT state_json FROM seller_mind_state WHERE seller_id = ?", (seller_id,)).fetchone()
    if row is None:
        return fresh()
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError) as exc:
        raise ValueError("saved seller mind state is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("saved seller mind state is invalid")
    return value


def save(db: sqlite3.Connection, seller_id: str, state: dict) -> None:
    db.execute("""INSERT INTO seller_mind_state (seller_id, state_json) VALUES (?, ?)
        ON CONFLICT(seller_id) DO UPDATE SET state_json = excluded.state_json""",
               (seller_id, json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)))
    db.commit()
