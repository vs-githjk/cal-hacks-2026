"""Persist addressed seller LossReports and their deterministic price strategy."""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from agents.buyer.state import open_state
from demo.learning import STEP_BY_BAND, update_strategy, what_to_change

_REPORT_FIELDS = {"id", "round_id", "seller_id", "won", "gap_band", "reason", "source_url", "created_at"}
_REASONS = {"price", "fit", "condition", "delivery", "record", "advocate_veto"}
_BANDS = set(STEP_BY_BAND)
_STEPS = {0.0, *STEP_BY_BAND.values()}


def _text(value: object, field: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be a non-empty string of at most {limit} characters")
    return value


def _validate_report(report: dict, seller_id: str) -> dict:
    _text(seller_id, "seller_id")
    if not isinstance(report, dict) or set(report) != _REPORT_FIELDS:
        raise ValueError("report must contain exactly the LossReport fields")
    report_id = _text(report["id"], "report id", 128)
    _text(report["round_id"], "round id")
    if _text(report["seller_id"], "report seller id") != seller_id:
        raise ValueError("report is addressed to a different seller")
    if report["won"] is not False:
        raise ValueError("only losing reports can update strategy")
    if not isinstance(report["gap_band"], str) or report["gap_band"] not in _BANDS:
        raise ValueError("invalid gap band")
    if not isinstance(report["reason"], str) or report["reason"] not in _REASONS:
        raise ValueError("invalid loss reason")
    _text(report["created_at"], "created_at")
    source = _text(report["source_url"], "source_url", 2048)
    try:
        parsed = urlsplit(source)
        valid_url = (parsed.scheme in {"http", "https"} and parsed.hostname is not None
                     and parsed.username is None and parsed.password is None and parsed.port != 0)
    except ValueError:
        valid_url = False
    if not valid_url or any(ord(char) <= 0x20 or ord(char) == 0x7f for char in source):
        raise ValueError("source_url must be a safe absolute HTTP(S) URL")
    return {**report, "id": report_id}


def _strategy(raw: str | None) -> dict:
    if raw is None:
        return {"price_step": 0.0}
    try:
        value = json.loads(raw)
        step = value["price_step"]
        if (set(value) != {"price_step"} or isinstance(step, bool) or not isinstance(step, (int, float))
                or not math.isfinite(step) or step not in _STEPS):
            raise ValueError
        return {"price_step": float(step)}
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("saved seller strategy is invalid") from exc


def open_learning_state(path: str | Path | None = None) -> sqlite3.Connection:
    db = open_state(path)
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS seller_learning_strategy (
            seller_id TEXT PRIMARY KEY, strategy_json TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS seller_learning_reports (
            report_id TEXT PRIMARY KEY, seller_id TEXT NOT NULL, source_url TEXT NOT NULL,
            diff_json TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.commit()
        return db
    except Exception:
        db.rollback()
        db.close()
        raise


def load_strategy(db: sqlite3.Connection, seller_id: str) -> dict:
    _text(seller_id, "seller_id")
    row = db.execute("SELECT strategy_json FROM seller_learning_strategy WHERE seller_id = ?", (seller_id,)).fetchone()
    return _strategy(row[0] if row else None)


def apply_loss(db: sqlite3.Connection, report: dict, seller_id: str) -> dict | None:
    report = _validate_report(report, seller_id)
    begun = False
    try:
        db.execute("BEGIN IMMEDIATE")
        begun = True
        prior = db.execute("SELECT seller_id FROM seller_learning_reports WHERE report_id = ?", (report["id"],)).fetchone()
        if prior:
            if prior[0] != seller_id:
                raise ValueError("report id is already associated with a different seller")
            db.commit()
            return None

        strategy = load_strategy(db, seller_id)
        updated, diff = update_strategy(strategy, report)
        updated = _strategy(json.dumps(updated, allow_nan=False))
        explanation = what_to_change(report, diff)
        db.execute("""INSERT INTO seller_learning_strategy (seller_id, strategy_json) VALUES (?, ?)
            ON CONFLICT(seller_id) DO UPDATE SET strategy_json = excluded.strategy_json""",
                   (seller_id, json.dumps(updated, sort_keys=True, separators=(",", ":"), allow_nan=False)))
        db.execute("INSERT INTO seller_learning_reports (report_id, seller_id, source_url, diff_json) VALUES (?, ?, ?, ?)",
                   (report["id"], seller_id, report["source_url"],
                    json.dumps(diff, sort_keys=True, separators=(",", ":"), allow_nan=False)))
        db.commit()
        return {"report_id": report["id"], "source_url": report["source_url"], "strategy": updated,
                "diff": diff, "what_to_change": explanation}
    except Exception:
        if begun and db.in_transaction:
            db.rollback()
        raise
