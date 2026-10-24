"""SIM-only driver for observed rows and Market-owned scheduled replay callbacks."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Awaitable, Callable

from agents.buyer import state

MAX_ROWS = 10_000
MAX_DISPATCHES = 10_000
MAX_EVENTS = 10_000
_SCENARIO_KEYS = {"run_id", "buyer_id", "goal_id", "mode", "transport", "input_origin", "until"}
_EVENT_KINDS = {"observation", "round_started", "bid_received", "advocate_veto", "goal_progress",
                "deal_found", "deadline", "retry", "quote_expired", "round_complete", "goal_expired"}
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class ReplayError(ValueError):
    """Invalid replay input, schedule, state, or callback contract."""


def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ReplayError(f"{label} must be an aware UTC datetime")
    return value.astimezone(timezone.utc)


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReplayError("row observed_at must be an ISO timestamp")
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")), "row observed_at")
    except (ValueError, OverflowError) as exc:
        raise ReplayError("row observed_at must be an aware UTC timestamp") from None


def _scenario(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SCENARIO_KEYS:
        raise ReplayError("scenario fields do not match the replay contract")
    for field in ("run_id", "buyer_id", "goal_id"):
        if not isinstance(value[field], str) or not _ID_RE.fullmatch(value[field]):
            raise ReplayError(f"scenario {field} is invalid")
    if value["mode"] != "SIM" or value["transport"] != "SIM":
        raise ReplayError("replay requires SIM mode and SIM transport")
    if value["input_origin"] not in ("MIRROR", "SIM"):
        raise ReplayError("replay input origin must be MIRROR or SIM")
    checked = dict(value)
    checked["until"] = _utc(value["until"], "scenario until")
    return MappingProxyType(checked)


def _rows(values: Any, input_origin: str) -> tuple[list[dict], list[datetime], str, dict[str, int]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values or len(values) > MAX_ROWS:
        raise ReplayError("rows must be a non-empty bounded sequence")
    cloned: list[dict] = []
    stamps: list[datetime] = []
    sources: Counter[str] = Counter()
    for raw in values:
        if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
            raise ReplayError("each replay row must be a string-keyed mapping")
        try:
            row = copy.deepcopy(dict(raw))
        except Exception:
            raise ReplayError("replay row could not be copied safely") from None
        for name in ("provider", "store", "sku", "kind", "url", "snapshot_id", "origin"):
            if not isinstance(row.get(name), str) or not row[name]:
                raise ReplayError("replay row is missing required provenance")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", row["provider"]):
            raise ReplayError("row provider is invalid")
        if row["origin"] != input_origin:
            raise ReplayError("row origin does not match the scenario")
        price = row.get("price")
        try:
            valid_price = (not isinstance(price, bool) and isinstance(price, (int, float))
                           and math.isfinite(price) and price > 0)
        except OverflowError:
            valid_price = False
        if not valid_price:
            raise ReplayError("row price must be finite and positive")
        stamp = _timestamp(row.get("observed_at"))
        if stamps and stamp < stamps[-1]:
            raise ReplayError("rows must be in nondecreasing observation order")
        cloned.append(row)
        stamps.append(stamp)
        sources[row["provider"]] += 1
    try:
        encoded = json.dumps(cloned, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ReplayError("rows are not safe JSON data") from None
    return cloned, stamps, hashlib.sha256(encoded).hexdigest(), dict(sorted(sources.items()))


def _state_path(value: Any) -> Path:
    if not isinstance(value, (str, Path)) or not value:
        raise ReplayError("state_path is required")
    path = Path(value)
    try:
        if path.resolve() == state.DEFAULT_DB_PATH.resolve():
            raise ReplayError("replay state must not use the live default database")
    except (OSError, RuntimeError):
        raise ReplayError("replay state path is invalid") from None
    if path.parent.name != ".state":
        raise ReplayError("replay state must use a dedicated .state directory")
    return path


def _dispatch_result(value: Any, *, now: datetime, scenario: Mapping[str, Any], total_events: int) -> tuple[datetime | None, list[dict]]:
    if not isinstance(value, Mapping) or set(value) != {"next_wakeup_at", "events"}:
        raise ReplayError("dispatch result does not match the replay contract")
    wakeup = value["next_wakeup_at"]
    if wakeup is not None:
        wakeup = _utc(wakeup, "next_wakeup_at")
        if wakeup <= now:
            raise ReplayError("next_wakeup_at must advance beyond the dispatch time")
    events = value["events"]
    if not isinstance(events, list) or total_events + len(events) > MAX_EVENTS:
        raise ReplayError("dispatch events must be a bounded list")
    safe: list[dict] = []
    expected = {"kind", "at", "run_id", "buyer_id", "goal_id"}
    for event in events:
        if not isinstance(event, Mapping) or set(event) != expected:
            raise ReplayError("event summary does not match the safe report contract")
        kind = event["kind"]
        if not isinstance(kind, str) or kind not in _EVENT_KINDS:
            raise ReplayError("event kind is not in the safe summary vocabulary")
        at = _utc(event["at"], "event at")
        if (at != now or event["run_id"] != scenario["run_id"]
                or event["buyer_id"] != scenario["buyer_id"]
                or event["goal_id"] != scenario["goal_id"]):
            raise ReplayError("event identity or timestamp does not match the active replay")
        safe.append({"kind": kind, "at": at.isoformat().replace("+00:00", "Z"),
                     "run_id": scenario["run_id"], "buyer_id": scenario["buyer_id"],
                     "goal_id": scenario["goal_id"]})
    return wakeup, safe


async def run_replay(rows: Sequence[Mapping[str, Any]], scenario: Mapping[str, Any],
                     dispatch: Callable[..., Awaitable[Mapping[str, Any]]], clock: Any,
                     state_path: str | Path) -> dict:
    """Drive a required async adapter on injected UTC time and a dedicated protected SQLite state file."""
    sc = _scenario(scenario)
    copied_rows, stamps, input_digest, source_counts = _rows(rows, sc["input_origin"])
    if stamps[-1] > sc["until"]:
        raise ReplayError("scenario horizon ends before the final row")
    if not callable(dispatch) or not (inspect.iscoroutinefunction(dispatch)
                                      or inspect.iscoroutinefunction(getattr(dispatch, "__call__", None))):
        raise ReplayError("dispatch must be a required async Market adapter")
    if not callable(getattr(clock, "now", None)) or not callable(getattr(clock, "advance_to", None)):
        raise ReplayError("clock must provide now() and advance_to()")
    path = _state_path(state_path)
    now = _utc(clock.now(), "clock now")
    if now > stamps[0]:
        raise ReplayError("clock starts after the first observation")

    db = state.open_state(path)
    row_index = 0
    next_wakeup: datetime | None = None
    dispatch_count = 0
    wakeup_count = 0
    events: list[dict] = []
    pending_wakeup = False
    try:
        if state.load_goal(db, sc["goal_id"], sc["buyer_id"]) is None:
            raise ReplayError("scenario goal is not present for the requested buyer")
        while row_index < len(copied_rows) or (next_wakeup is not None and next_wakeup <= sc["until"]):
            row_at = stamps[row_index] if row_index < len(stamps) else None
            if next_wakeup is not None and next_wakeup <= sc["until"] and (row_at is None or next_wakeup <= row_at):
                when = next_wakeup
                event = {"kind": "wakeup", "scheduled_at": when}
                wakeup_count += 1
            else:
                when = row_at
                event = {"kind": "observation", "row": copy.deepcopy(copied_rows[row_index])}
                row_index += 1
            if when is None:
                break
            if when < now:
                raise ReplayError("replay event would move business time backwards")
            if dispatch_count >= MAX_DISPATCHES:
                raise ReplayError("replay exceeded the dispatch limit")
            try:
                clock.advance_to(when)
                now = _utc(clock.now(), "clock now")
            except ReplayError:
                raise
            except Exception:
                raise ReplayError("business clock could not advance") from None
            if now != when:
                raise ReplayError("clock did not advance to the requested UTC event time")
            dispatch_count += 1
            try:
                pending = dispatch(event, now=now, db=db, scenario=sc)
                if not inspect.isawaitable(pending):
                    raise ReplayError("dispatch must be async")
                result = await pending
            except Exception:
                raise ReplayError("SIM dispatch failed") from None
            next_wakeup, safe_events = _dispatch_result(result, now=now, scenario=sc, total_events=len(events))
            events.extend(safe_events)
            pending_wakeup = next_wakeup is not None and next_wakeup > sc["until"]
    finally:
        db.close()

    return {
        "run_id": sc["run_id"], "buyer_id": sc["buyer_id"], "goal_id": sc["goal_id"],
        "mode": "SIM", "transport": "SIM", "input_origin": sc["input_origin"],
        "row_count": len(copied_rows), "source_counts": source_counts,
        "from": copied_rows[0]["observed_at"], "to": copied_rows[-1]["observed_at"],
        "input_rows_sha256": input_digest,
        "input_digest_basis": "canonical rows argument; not source file bytes",
        "dispatch_count": dispatch_count, "wakeup_count": wakeup_count,
        "pending_wakeup": pending_wakeup, "events": events,
    }
