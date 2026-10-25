"""Fail-closed adapter for the Python agents' existing SpacetimeDB Market client.

This module owns bid publication/readback and the narrow candidate/result projections used by
the agents. Reducer authorization remains in the Market module; reducer/SQL error bodies are
never returned to chat or logs by this adapter.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Sequence

_SCRIPTS = Path(__file__).resolve().parents[1] / "market" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from stdb import Market  # noqa: E402

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_META_KEYS = ("lineIndex", "shipping", "listingId", "listingHash", "source", "snapshotId", "provenance", "attrs")
_BID_COLUMNS = ("id", "round_id", "seller_id", "persona", "lines", "stated_total", "perks", "claims", "origin", "source", "line_meta_json")
_RESULT_COLUMNS = ("bid_id", "seller_id", "rank", "landed", "reasons", "lines", "line_meta_json", "origin", "source", "binding_hash")
_CANDIDATE_COLUMNS = ("round_id", "need_id", "bid_id", "seller_id", "origin", "rank", "landed", "lines_json", "line_meta_json", "binding_hash")
_LINE_COLUMNS = ("sku_spec", "offered_spec", "offered_condition", "unit_price", "quantity")


class MarketBridgeError(RuntimeError):
    """A safe, fixed-label failure suitable for user-facing handling."""


def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise MarketBridgeError(f"invalid_{label}")
    return value


def _quote(value: str) -> str:
    # Inputs are also constrained by _safe_id; escaping is retained as defense in depth.
    return "'" + value.replace("'", "''") + "'"


def _timestamp_iso(value: Any) -> str:
    """Normalize only aware ISO adapters or the SDK's exact one-field SATN timestamp product."""
    try:
        if isinstance(value, datetime):
            stamp = value
        elif isinstance(value, str):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, list) and len(value) == 1:
            micros = value[0]
            if (isinstance(micros, Mapping) and set(micros) ==
                    {"__timestamp_micros_since_unix_epoch__"}):
                micros = micros["__timestamp_micros_since_unix_epoch__"]
            if isinstance(micros, bool) or not isinstance(micros, int):
                raise ValueError
            stamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=micros)
        else:
            raise ValueError
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError, OSError):
        raise MarketBridgeError("market_timestamp_invalid") from None


def _option_value(value: Any) -> Any:
    """Decode only documented SATS SumValue option arms; malformed products fail closed."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or len(value) != 1:
        raise MarketBridgeError("market_option_invalid")
    key, payload = next(iter(value.items()))
    if key in {"0", "some"}:
        return payload
    if key in {"1", "none"} and payload == []:
        return None
    raise MarketBridgeError("market_option_invalid")


def _same_deadline(actual: Any, expected: Any) -> bool:
    try:
        left = datetime.fromisoformat(_timestamp_iso(actual).replace("Z", "+00:00"))
        right = datetime.fromisoformat(_timestamp_iso(expected).replace("Z", "+00:00"))
        return left == right
    except (TypeError, ValueError, OverflowError, MarketBridgeError):
        return False


def _finite(value: Any, label: str, *, minimum: float = 0.0) -> float:
    try:
        valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                 and math.isfinite(value) and value >= minimum)
    except (OverflowError, TypeError, ValueError):
        valid = False
    if not valid:
        raise MarketBridgeError(f"invalid_{label}")
    return float(value)


def _finite_scalar(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        try:
            return math.isfinite(value)
        except (OverflowError, TypeError, ValueError):
            return False
    return value is None or isinstance(value, str)


def _decimal_cents(value: Any, label: str) -> int:
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount != amount.to_integral_value():
            raise ValueError
        return int(amount)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise MarketBridgeError(f"invalid_{label}_cents") from None


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _project(row: Any, columns: Sequence[str]) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).lower(): value for key, value in row.items()}
    if isinstance(row, (list, tuple)) and len(row) == len(columns):
        return dict(zip(columns, row))
    raise MarketBridgeError("market_readback_invalid")


def _field(row: Mapping[str, Any], snake_name: str) -> Any:
    if snake_name in row:
        return row[snake_name]
    camel_name = re.sub(r"_([a-z])", lambda match: match.group(1).upper(), snake_name)
    return row.get(camel_name)


def _normalized_lines(raw: Any) -> list[dict[str, Any]]:
    lines = _decode(raw)
    if not isinstance(lines, list):
        raise MarketBridgeError("bid_readback_invalid")
    normalized = []
    for line in lines:
        if isinstance(line, (list, tuple)) and len(line) == len(_LINE_COLUMNS):
            line = dict(zip(_LINE_COLUMNS, line))
        if not isinstance(line, Mapping):
            raise MarketBridgeError("bid_readback_invalid")
        normalized.append({
            "sku_spec": _field(line, "sku_spec"), "offered_spec": _field(line, "offered_spec") or "",
            "offered_condition": _field(line, "offered_condition") or "",
            "unit_price": _finite(_field(line, "unit_price"), "unit_price"),
            "quantity": _finite(_field(line, "quantity"), "quantity", minimum=0.000000001),
        })
    return normalized


def _canonical_meta(rows: Sequence[Mapping[str, Any]], line_count: int) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(rows, (list, tuple)) or len(rows) != line_count or not line_count:
        raise MarketBridgeError("line_metadata_incomplete")
    output: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != set(_META_KEYS):
            raise MarketBridgeError("line_metadata_shape_invalid")
        index = row.get("lineIndex")
        shipping = row.get("shipping")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < line_count or index in seen:
            raise MarketBridgeError("line_metadata_index_invalid")
        _finite(shipping, "shipping")
        for key, limit in (("listingId", 512), ("source", 512), ("snapshotId", 256)):
            value = row.get(key)
            if not isinstance(value, str) or len(value) > limit or (key != "snapshotId" and not value.strip()):
                raise MarketBridgeError(f"line_metadata_{key.lower()}_invalid")
        if not isinstance(row.get("listingHash"), str) or not _HASH.fullmatch(row["listingHash"]):
            raise MarketBridgeError("line_metadata_hash_invalid")
        for key in ("provenance", "attrs"):
            value = row.get(key)
            if not isinstance(value, Mapping):
                raise MarketBridgeError("line_metadata_object_invalid")
            for field, item in value.items():
                if (not isinstance(field, str) or not field or len(field) > 64
                        or (isinstance(item, str) and len(item) > 512)
                        or not (_finite_scalar(item)
                                or (isinstance(item, list) and len(item) <= 32
                                    and all(_finite_scalar(entry)
                                            and (not isinstance(entry, str) or len(entry) <= 128)
                                            for entry in item)))):
                    raise MarketBridgeError("line_metadata_value_invalid")
        seen.add(index)
        # Match parseLineMeta's fixed row shape and sorted nested object keys.
        output.append({key: ({nested: value for nested, value in sorted(row[key].items())}
                             if key in ("provenance", "attrs") else row[key]) for key in _META_KEYS})
    output.sort(key=lambda item: item["lineIndex"])
    try:
        serialized = json.dumps(output, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise MarketBridgeError("line_metadata_serialization_failed") from None
    return output, serialized


def _json_equal(left: Any, right: Any) -> bool:
    # JSON number equality treats 1 and 1.0 as the same, matching the module's parsed Number values.
    try:
        return json.loads(left) == right if isinstance(left, str) else left == right
    except (json.JSONDecodeError, TypeError):
        return False


class MarketBridge:
    """A single role-bound Market client; missing credentials never trigger identity creation."""

    def __init__(self, role: str, *, token_file: str | os.PathLike[str] | None = None,
                 client: Any | None = None, market_factory: Callable[..., Any] | None = None):
        if role not in {"buyer", "referee", "seller"}:
            raise MarketBridgeError("invalid_market_role")
        self.role = role
        self._client = client
        if client is not None:
            self.identity = getattr(client, "identity", None)
            return

        path = Path(token_file) if token_file is not None else None
        if path is None:
            role_path = os.environ.get(f"SPACETIMEDB_{role.upper()}_TOKEN_FILE")
            path = Path(role_path) if role_path else None
        if path is None:
            raise MarketBridgeError("market_identity_not_configured")
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raise MarketBridgeError("market_identity_unavailable") from None
        if (not isinstance(saved, Mapping) or not isinstance(saved.get("token"), str) or not saved["token"]
                or not isinstance(saved.get("identity"), str) or not saved["identity"]):
            raise MarketBridgeError("market_identity_invalid")
        self.identity = saved["identity"]
        factory = market_factory or Market
        try:
            self._client = factory(token_file=str(path))
        except Exception:
            raise MarketBridgeError("market_client_unavailable") from None

    def _call(self, reducer: str, **args: Any) -> None:
        try:
            self._client.call(reducer, **args)
        except Exception:
            raise MarketBridgeError("market_reducer_failed") from None

    def _sql(self, query: str) -> list[Any]:
        try:
            rows = self._client.sql(query)
        except Exception:
            raise MarketBridgeError("market_readback_failed") from None
        if not isinstance(rows, list):
            raise MarketBridgeError("market_readback_invalid")
        return rows

    def _own_bid(self, bid_id: str) -> dict[str, Any] | None:
        rows = self._sql("SELECT id, round_id, seller_id, persona, lines, stated_total, perks, claims, origin, source, "
                         "line_meta_json FROM my_bids WHERE id = " + _quote(bid_id))
        if not rows:
            return None
        if len(rows) != 1:
            raise MarketBridgeError("bid_readback_ambiguous")
        return _project(rows[0], _BID_COLUMNS)

    def post_goal(self, goal: Mapping[str, Any], *, buyer_id: str) -> None:
        """Persist the buyer's parsed goal without sending its cap to sellers."""
        if self.role != "buyer" or not isinstance(goal, Mapping):
            raise MarketBridgeError("market_role_mismatch")
        goal_id = _safe_id(goal.get("id"), "goal_id")
        items = []
        for item in goal.get("items", []):
            if not isinstance(item, Mapping):
                raise MarketBridgeError("goal_items_invalid")
            items.append({"sku_spec": item.get("sku_spec"), "condition": item.get("condition", "new"),
                          "variant": item.get("variant", "retail"),
                          "quantity": _finite(item.get("quantity"), "goal_quantity", minimum=0.000000001),
                          "skipped_owned_part_id": item.get("skipped_owned_part_id", "")})
        expected = {"id": goal_id, "buyer_id": buyer_id, "type": goal.get("type"),
                    "cap": _finite(goal.get("cap"), "goal_cap", minimum=0.000000001),
                    "deadline": goal.get("deadline"), "items": items}
        if self._goal_readback(goal_id, expected):
            return
        try:
            self._call("post_goal", id=goal_id, buyer_id=_safe_id(buyer_id, "buyer_id"), type=goal.get("type"),
                       cap=expected["cap"], deadline=goal.get("deadline"), po_number="", origin="SIM", items=items)
        except MarketBridgeError:
            if self._goal_readback(goal_id, expected):
                return
            raise
        if not self._goal_readback(goal_id, expected):
            raise MarketBridgeError("goal_readback_missing")

    def _goal_readback(self, goal_id: str, expected: Mapping[str, Any]) -> bool:
        rows = self._sql("SELECT id, buyer_id, type, cap, deadline FROM my_goals WHERE id = " + _quote(goal_id))
        if not rows:
            return False
        if len(rows) != 1:
            raise MarketBridgeError("goal_readback_ambiguous")
        row = _project(rows[0], ("id", "buyer_id", "type", "cap", "deadline"))
        try:
            matches = (row.get("id") == expected["id"] and row.get("buyer_id") == expected["buyer_id"]
                       and row.get("type") == expected["type"]
                       and _finite(row.get("cap"), "goal_cap") == expected["cap"]
                       and _same_deadline(row.get("deadline"), expected["deadline"]))
        except MarketBridgeError:
            matches = False
        if not matches:
            raise MarketBridgeError("goal_readback_mismatch")
        item_rows = self._sql("SELECT sku_spec, condition, variant, quantity, skipped_owned_part_id "
                              "FROM my_goal_items WHERE goal_id = " + _quote(goal_id))
        actual = [_project(item, ("sku_spec", "condition", "variant", "quantity", "skipped_owned_part_id"))
                  for item in item_rows]
        for item in actual:
            item["quantity"] = _finite(item.get("quantity"), "goal_quantity", minimum=0.000000001)
        actual.sort(key=lambda item: (item["sku_spec"], item["condition"], item["variant"]))
        expected_items = sorted(expected["items"], key=lambda item: (item["sku_spec"], item["condition"], item["variant"]))
        return _json_equal(actual, expected_items)

    def post_need(self, need: Mapping[str, Any], *, buyer_id: str, goal_id: str) -> None:
        if self.role != "buyer" or not isinstance(need, Mapping):
            raise MarketBridgeError("market_role_mismatch")
        need_id = _safe_id(need.get("id"), "need_id")
        items = []
        for item in need.get("items", []):
            if not isinstance(item, Mapping):
                raise MarketBridgeError("need_items_invalid")
            items.append({"sku_spec": item.get("sku_spec"), "condition": item.get("condition", "new"),
                          "allowed_conditions": list(item.get("allowed_conditions", [item.get("condition", "new")])),
                          "variant": item.get("variant", "retail"),
                          "quantity": _finite(item.get("quantity"), "need_quantity", minimum=0.000000001),
                          "unit": item.get("unit", "each")})
        if not items:
            raise MarketBridgeError("need_items_invalid")
        self._call("post_need", id=need_id, buyer_id=_safe_id(buyer_id, "buyer_id"), goal_id=_safe_id(goal_id, "goal_id"),
                   delivery_window=need.get("delivery_window", ""),
                   spend_limit=_finite(need.get("spend_limit"), "spend_limit", minimum=0.000000001),
                   consent=bool(need.get("consent", True)),
                   auction_window_s=int(_finite(need.get("auction_window_s"), "auction_window", minimum=1)),
                   origin="SIM", items=items)

    def open_round(self, round_id: str, need_id: str, window_s: int) -> None:
        if self.role != "referee":
            raise MarketBridgeError("market_role_mismatch")
        self._call("open_round", round_id=_safe_id(round_id, "round_id"), need_id=_safe_id(need_id, "need_id"),
                   window_s=int(_finite(window_s, "auction_window", minimum=1)))

    def round_status(self, round_id: str) -> dict[str, Any]:
        round_id = _safe_id(round_id, "round_id")
        rows = self._sql("SELECT id, need_id, state, deadline, review_deadline FROM round WHERE id = " + _quote(round_id))
        if len(rows) != 1:
            raise MarketBridgeError("round_readback_missing")
        row = _project(rows[0], ("id", "need_id", "state", "deadline", "review_deadline"))
        if row.get("id") != round_id or row.get("state") not in {"open", "review", "closed"}:
            raise MarketBridgeError("round_readback_invalid")
        if row.get("deadline") is not None:
            row["deadline"] = _timestamp_iso(row["deadline"])
        if row.get("review_deadline") is not None:
            value = _option_value(row["review_deadline"])
            row["review_deadline"] = _timestamp_iso(value) if value is not None else None
        return row

    def close_round(self, round_id: str) -> None:
        if self.role != "referee":
            raise MarketBridgeError("market_role_mismatch")
        self._call("close_round", round_id=_safe_id(round_id, "round_id"))

    def attach_verdict(self, *, bid_id: str, verdict: str, rule_ids: Sequence[str], origin: str = "SIM") -> None:
        if (self.role != "referee" or verdict not in {"allow", "quarantine", "block"}
                or not isinstance(origin, str) or origin not in {"LIVE", "MIRROR", "SIM"}):
            raise MarketBridgeError("market_review_invalid")
        self._call("attach_verdict", bid_id=_safe_id(bid_id, "bid_id"), verdict=verdict,
                   rule_ids=[str(rule)[:128] for rule in rule_ids[:32]], origin=origin)

    @staticmethod
    def _same_bid(row: Mapping[str, Any] | None, *, bid_id: str, round_id: str, seller_id: str,
                  persona: str, lines: list[dict[str, Any]], stated_total: float, perks: Sequence[str],
                  claims: Sequence[str], origin: str, source: str) -> bool:
        if not row:
            return False
        try:
            stored_lines = _normalized_lines(row.get("lines"))
        except MarketBridgeError:
            return False
        return (row.get("id") == bid_id and row.get("round_id") == round_id and row.get("seller_id") == seller_id
                and row.get("persona") == persona and stored_lines == lines
                and _finite(row.get("stated_total"), "stated_total") == stated_total
                and _decode(row.get("perks")) == list(perks) and _decode(row.get("claims")) == list(claims)
                and row.get("origin") == origin and row.get("source") == source)

    def my_loss_reports(self) -> list[dict[str, Any]]:
        """Read only reports addressed to this authenticated seller through its private view."""
        if self.role != "seller":
            raise MarketBridgeError("loss_reports_role_mismatch")
        columns = ("id", "round_id", "seller_id", "won", "gap_band", "reason", "source_url", "created_at")
        rows = self._sql("SELECT " + ", ".join(columns) + " FROM my_loss_reports")
        output = []
        for raw in rows:
            row = _project(raw, columns)
            row["created_at"] = _timestamp_iso(row.get("created_at"))
            if (any(not isinstance(row.get(key), str) or not row[key] for key in
                    ("id", "round_id", "seller_id", "source_url", "created_at"))
                    or not isinstance(row.get("won"), bool)
                    or row.get("gap_band") not in {"within5", "within10", "within20", "over20"}
                    or row.get("reason") not in {"price", "fit", "condition", "delivery", "record", "advocate_veto"}
                    or row.get("won") is not False):
                raise MarketBridgeError("loss_report_readback_invalid")
            output.append(row)
        return output

    def buyer_profile(self, buyer_id: str) -> dict[str, Any] | None:
        """The buyer's own profile (name, approval phone); None when absent or the column is not on the market yet."""
        columns = ("buyer_id", "display_name", "phone")
        try:
            rows = self._sql("SELECT " + ", ".join(columns) + " FROM my_buyer_profile WHERE buyer_id = " + _quote(buyer_id))
            row = _project(rows[0], columns) if rows else None
        except Exception:
            return None
        if not row or row.get("buyer_id") != buyer_id:
            return None
        return {"buyer_id": buyer_id, "display_name": row.get("display_name") or None, "phone": row.get("phone") or None}

    def purchase_status(self, mandate_hash: str) -> dict[str, Any]:
        """Read the exact buyer-private purchase projection; never query raw money tables."""
        if self.role != "buyer" or not _HASH.fullmatch(str(mandate_hash)):
            raise MarketBridgeError("purchase_status_binding_invalid")
        columns = ("mandate_hash", "mandate_id", "deal_id", "goal_id", "need_id", "amount", "payee",
                   "expiry", "origin", "within_allowance", "retired", "reservation_matches", "settled",
                   "approval_method", "approved_at", "payment_ref", "payment_amount", "payment_mode", "paid_at")
        rows = self._sql("SELECT " + ", ".join(columns) + " FROM my_purchase_status WHERE mandate_hash = "
                         + _quote(mandate_hash))
        if len(rows) != 1:
            raise MarketBridgeError("purchase_status_readback_missing")
        row = _project(rows[0], columns)
        for field in ("approval_method", "approved_at", "payment_ref", "payment_amount", "payment_mode", "paid_at"):
            row[field] = _option_value(row.get(field))
        for field in ("expiry", "approved_at", "paid_at"):
            if row.get(field) is not None:
                row[field] = _timestamp_iso(row[field])
        if (row.get("mandate_hash") != mandate_hash or not isinstance(row.get("mandate_id"), str)
                or not isinstance(row.get("deal_id"), str) or not isinstance(row.get("goal_id"), str)
                or not isinstance(row.get("need_id"), str) or _decimal_cents(row.get("amount"), "purchase_amount") <= 0
                or not isinstance(row.get("payee"), str) or not row["payee"]
                or row.get("origin") not in {"SIM", "MIRROR", "LIVE"}
                or any(not isinstance(row.get(k), bool) for k in
                       ("within_allowance", "retired", "reservation_matches", "settled"))):
            raise MarketBridgeError("purchase_status_readback_invalid")
        return row

    def create_mandate(self, mandate: Mapping[str, Any], *, need_id: str, buyer_id: str,
                       requested_by: str = "", now: datetime) -> dict[str, Any]:
        if self.role != "buyer" or not isinstance(mandate, Mapping):
            raise MarketBridgeError("market_role_mismatch")
        required = ("hash", "id", "deal_id", "buyer_id", "payee", "nonce", "expires_at", "origin", "goal_id")
        if (any(not isinstance(mandate.get(k), str) or not mandate[k] for k in required)
                or _finite(mandate.get("amount"), "mandate_amount", minimum=0.000000001) <= 0):
            raise MarketBridgeError("mandate_binding_invalid")
        if (not _HASH.fullmatch(mandate["hash"]) or mandate["buyer_id"] != _safe_id(buyer_id, "buyer_id")
                or self.role != "buyer"
                or mandate.get("status") != "pending" or mandate.get("within_allowance") is not False):
            raise MarketBridgeError("mandate_binding_invalid")
        current = now
        try:
            expires = datetime.fromisoformat(mandate["expires_at"].replace("Z", "+00:00"))
            if (not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() != timezone.utc.utcoffset(current)
                    or expires.tzinfo is None or expires.utcoffset() != timezone.utc.utcoffset(expires)):
                raise ValueError
            remaining = (expires.astimezone(timezone.utc) - current.astimezone(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            raise MarketBridgeError("mandate_expiry_invalid") from None
        if not 0 < remaining <= 600:
            raise MarketBridgeError("mandate_expiry_invalid")
        args = {"hash": mandate["hash"], "id": mandate["id"], "deal_id": mandate["deal_id"],
                "buyer_id": mandate["buyer_id"], "amount": _finite(mandate["amount"], "mandate_amount", minimum=0.000000001),
                "payee": mandate["payee"], "expiry_minutes": max(1, min(10, int(remaining // 60))),
                "nonce": mandate["nonce"], "requested_by": requested_by, "origin": mandate["origin"],
                "goal_id": mandate["goal_id"], "need_id": _safe_id(need_id, "need_id")}
        try:
            self._call("create_mandate", **args)
        except MarketBridgeError:
            status = self.purchase_status(mandate["hash"])
            if not self._mandate_matches(status, mandate, need_id, current):
                raise
            return status
        status = self.purchase_status(mandate["hash"])
        if not self._mandate_matches(status, mandate, need_id, current):
            raise MarketBridgeError("mandate_readback_mismatch")
        return status

    @staticmethod
    def _mandate_matches(row: Mapping[str, Any], mandate: Mapping[str, Any], need_id: str,
                         now: datetime) -> bool:
        try:
            server_expiry = datetime.fromisoformat(_timestamp_iso(row.get("expiry")).replace("Z", "+00:00"))
            local_expiry = datetime.fromisoformat(mandate["expires_at"].replace("Z", "+00:00"))
            current = now.astimezone(timezone.utc)
            return (row.get("mandate_hash") == mandate.get("hash") and row.get("mandate_id") == mandate.get("id")
                    and row.get("deal_id") == mandate.get("deal_id")
                    and row.get("goal_id") == mandate.get("goal_id") and row.get("need_id") == need_id
                    and _decimal_cents(row.get("amount"), "purchase_amount") == _decimal_cents(mandate.get("amount"), "mandate_amount")
                    and row.get("payee") == mandate.get("payee") and row.get("origin") == mandate.get("origin")
                    and row.get("reservation_matches") is True and row.get("retired") is False
                    and row.get("settled") is False and row.get("within_allowance") is False
                    and current < server_expiry <= local_expiry)
        except (MarketBridgeError, ValueError, TypeError, OverflowError):
            return False

    def record_approval(self, *, mandate_hash: str, method: str, approved_by: str) -> dict[str, Any]:
        if self.role != "buyer" or method != "voice_code":
            raise MarketBridgeError("approval_binding_invalid")
        before = self.purchase_status(mandate_hash)
        if before.get("approval_method") is not None or before.get("retired"):
            raise MarketBridgeError("approval_not_pending")
        try:
            self._call("record_approval", mandate_hash=mandate_hash, method=method, approved_by=_safe_id(approved_by, "buyer_id"))
        except MarketBridgeError:
            after = self.purchase_status(mandate_hash)
            if after.get("approval_method") != method:
                raise
            return after
        after = self.purchase_status(mandate_hash)
        if after.get("approval_method") != method or not after.get("approved_at") or after.get("retired"):
            raise MarketBridgeError("approval_readback_mismatch")
        return after

    def record_payment(self, *, mandate_hash: str, payment_ref: str, amount: float, mode: str) -> dict[str, Any]:
        if self.role != "referee" or mode not in {"sim", "stripe_test"}:
            raise MarketBridgeError("payment_binding_invalid")
        args = {"mandate_hash": mandate_hash, "payment_ref": _safe_id(payment_ref, "payment_ref"),
                "amount": _finite(amount, "payment_amount", minimum=0.000000001), "mode": mode}
        self._call("record_payment", **args)
        # The referee can mutate this row but cannot read the buyer-private confirmation view.
        # The caller must verify through its buyer-role client before proceeding.
        return {"recorded": True}

    def settle_goal(self, *, goal_id: str, deal_id: str, mandate_hash: str, payment_ref: str) -> dict[str, Any]:
        if self.role != "buyer":
            raise MarketBridgeError("market_role_mismatch")
        self._call("settle_goal", goal_id=_safe_id(goal_id, "goal_id"), deal_id=_safe_id(deal_id, "deal_id"),
                   mandate_hash=mandate_hash, payment_ref=_safe_id(payment_ref, "payment_ref"))
        status = self.purchase_status(mandate_hash)
        if not status.get("settled") or status.get("payment_ref") != payment_ref:
            raise MarketBridgeError("goal_settlement_readback_mismatch")
        return status

    def publish_bid(self, *, bid_id: str, round_id: str, seller_id: str, persona: str, lines: Sequence[Mapping[str, Any]],
                    line_metadata: Sequence[Mapping[str, Any]], stated_total: float = 0.0,
                    perks: Sequence[str] = (), claims: Sequence[str] = (), origin: str = "SIM",
                    source: str = "simulated") -> dict[str, Any]:
        bid_id, round_id, seller_id = (_safe_id(bid_id, "bid_id"), _safe_id(round_id, "round_id"),
                                       _safe_id(seller_id, "seller_id"))
        if (not isinstance(persona, str) or not persona or len(persona) > 128
                or not isinstance(origin, str) or origin not in {"SIM", "MIRROR"}
                or not isinstance(source, str) or not source or len(source) > 512):
            raise MarketBridgeError("bid_metadata_invalid")
        if not isinstance(lines, (list, tuple)) or not lines or len(lines) > 64:
            raise MarketBridgeError("bid_lines_invalid")
        wire_lines = []
        for line in lines:
            if not isinstance(line, Mapping):
                raise MarketBridgeError("bid_line_invalid")
            sku = line.get("sku_spec")
            if not isinstance(sku, str) or not sku or len(sku) > 256:
                raise MarketBridgeError("bid_sku_invalid")
            wire_lines.append({
                "sku_spec": sku,
                "offered_spec": line.get("offered_spec", ""),
                "offered_condition": line.get("offered_condition", ""),
                "unit_price": _finite(line.get("unit_price"), "unit_price"),
                "quantity": _finite(line.get("quantity"), "quantity", minimum=0.000000001),
            })
        metadata, serialized = _canonical_meta(line_metadata, len(wire_lines))
        total = _finite(stated_total, "stated_total")
        if (not isinstance(perks, (list, tuple)) or not all(isinstance(x, str) and len(x) <= 512 for x in perks)
                or not isinstance(claims, (list, tuple)) or not all(isinstance(x, str) and len(x) <= 512 for x in claims)):
            raise MarketBridgeError("bid_claims_invalid")

        existing = self._own_bid(bid_id)
        if existing is not None:
            if not self._same_bid(existing, bid_id=bid_id, round_id=round_id, seller_id=seller_id,
                                  persona=persona, lines=wire_lines, stated_total=total, perks=perks,
                                  claims=claims, origin=origin, source=source):
                raise MarketBridgeError("existing_bid_mismatch")
        else:
            try:
                self._client.call("place_bid", id=bid_id, round_id=round_id, persona=persona, lines=wire_lines,
                                  stated_total=total, perks=list(perks), claims=list(claims), origin=origin, source=source)
            except Exception:
                # An HTTP timeout may happen after the reducer committed. Resume only on an exact own-bid readback.
                observed = self._own_bid(bid_id)
                if not self._same_bid(observed, bid_id=bid_id, round_id=round_id, seller_id=seller_id,
                                      persona=persona, lines=wire_lines, stated_total=total, perks=perks,
                                      claims=claims, origin=origin, source=source):
                    raise MarketBridgeError("market_reducer_failed") from None
        self._call("set_bid_line_meta", bid_id=bid_id, line_meta_json=serialized)
        observed = self._own_bid(bid_id)
        if observed is None:
            raise MarketBridgeError("bid_readback_missing")
        if (not self._same_bid(observed, bid_id=bid_id, round_id=round_id, seller_id=seller_id,
                               persona=persona, lines=wire_lines, stated_total=total, perks=perks,
                               claims=claims, origin=origin, source=source)
                or not _json_equal(observed.get("line_meta_json"), metadata)):
            raise MarketBridgeError("bid_readback_mismatch")
        return {"bid_id": bid_id, "round_id": round_id, "seller_id": seller_id, "line_metadata": metadata}

    def review_candidates(self, round_id: str) -> list[dict[str, Any]]:
        round_id = _safe_id(round_id, "round_id")
        query = ("SELECT round_id, need_id, bid_id, seller_id, origin, rank, landed, lines_json, "
                 "line_meta_json, binding_hash FROM review_candidates WHERE round_id = " + _quote(round_id))
        rows = self._sql(query)
        candidates: list[dict[str, Any]] = []
        for raw in rows:
            candidate = _project(raw, _CANDIDATE_COLUMNS)
            candidate["lines"] = _decode(candidate.pop("lines_json"))
            candidate["line_metadata"] = _decode(candidate.pop("line_meta_json"))
            if (candidate.get("round_id") != round_id or not _HASH.fullmatch(str(candidate.get("binding_hash", "")))
                    or not isinstance(candidate.get("lines"), list)
                    or not isinstance(candidate.get("line_metadata"), list)):
                raise MarketBridgeError("candidate_readback_invalid")
            # No cap, goal, floor, or unselected bid rows are queried or returned.
            candidates.append(candidate)
        return candidates

    def attach_advocate_card(self, *, bid_id: str, recommendation: str, rule_id: str, text: str,
                             source_url: str, origin: str, binding_hash: str) -> None:
        if not _HASH.fullmatch(binding_hash):
            raise MarketBridgeError("candidate_binding_invalid")
        self._call("attach_advocate_card", bid_id=_safe_id(bid_id, "bid_id"), recommendation=recommendation,
                   rule_id=rule_id, text=text, source_url=source_url, origin=origin, binding_hash=binding_hash)

    def attach_claim_check(self, *, bid_id: str, claim: str, check: str, evidence_url: str, origin: str,
                           binding_hash: str, line_index: int, listing_id: str, listing_hash: str) -> None:
        if isinstance(line_index, bool) or not isinstance(line_index, int) or line_index < 0 or not _HASH.fullmatch(binding_hash) or not _HASH.fullmatch(listing_hash):
            raise MarketBridgeError("candidate_binding_invalid")
        self._call("attach_claim_check", bid_id=_safe_id(bid_id, "bid_id"), claim=claim, check=check,
                   evidence_url=evidence_url, origin=origin, binding_hash=binding_hash, line_index=line_index,
                   listing_id=listing_id, listing_hash=listing_hash)

    def authoritative_winner(self, round_id: str, need_items: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
        """Return exact server winner with requested purchase quantities, never seller stock quantity."""
        round_id = _safe_id(round_id, "round_id")
        expected: dict[str, float] = {}
        if not isinstance(need_items, (list, tuple)) or not need_items:
            raise MarketBridgeError("need_items_invalid")
        for item in need_items:
            if not isinstance(item, Mapping) or not isinstance(item.get("sku_spec"), str):
                raise MarketBridgeError("need_items_invalid")
            sku = item["sku_spec"]
            if sku in expected:
                raise MarketBridgeError("need_items_duplicate")
            expected[sku] = _finite(item.get("quantity"), "need_quantity", minimum=0.000000001)
        query = ("SELECT bid_id, seller_id, rank, landed, reasons, lines, line_meta_json, origin, source, binding_hash "
                 "FROM round_result WHERE round_id = " + _quote(round_id) + " ORDER BY rank ASC")
        rows = self._sql(query)
        result = [_project(raw, _RESULT_COLUMNS) for raw in rows]
        ranked = [row for row in result if row.get("rank") == 1]
        if not ranked:
            return None
        if len(ranked) != 1:
            raise MarketBridgeError("winner_readback_ambiguous")
        winner = ranked[0]
        binding_hash = winner.get("binding_hash")
        if not isinstance(binding_hash, str) or not _HASH.fullmatch(binding_hash):
            raise MarketBridgeError("winner_binding_missing")
        reasons = _decode(winner.get("reasons"))
        lines = _normalized_lines(winner.get("lines"))
        metadata = _decode(winner.get("line_meta_json"))
        if reasons != [] or not isinstance(metadata, list) or len(lines) != len(metadata):
            raise MarketBridgeError("winner_readback_invalid")
        if len(lines) != len(expected):
            return None
        order_lines = []
        seen: set[str] = set()
        total_cents = 0
        for bid_line, meta in zip(lines, metadata):
            if not isinstance(meta, Mapping):
                raise MarketBridgeError("winner_line_invalid")
            sku = _field(bid_line, "sku_spec")
            if sku not in expected or sku in seen:
                return None
            seen.add(sku)
            stock = _finite(_field(bid_line, "quantity"), "quantity", minimum=0.000000001)
            quantity = expected[sku]
            if stock < quantity:
                return None
            if isinstance(meta.get("lineIndex"), bool) or not isinstance(meta.get("lineIndex"), int):
                raise MarketBridgeError("winner_line_metadata_invalid")
            price = _finite(_field(bid_line, "unit_price"), "unit_price")
            shipping = _finite(meta.get("shipping"), "shipping")
            try:
                exact_line = Decimal(str(price)) * Decimal(str(quantity)) + Decimal(str(shipping))
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                raise MarketBridgeError("winner_amount_invalid") from None
            total_cents += _decimal_cents(exact_line, "winner_amount")
            order_lines.append({"sku_spec": sku, "unit_price": price, "quantity": quantity,
                                "qty_available": stock, "original_line_index": meta["lineIndex"],
                                "listing_id": meta.get("listingId"), "listing_hash": meta.get("listingHash"),
                                "shipping": shipping})
        if seen != set(expected):
            return None
        landed = _finite(winner.get("landed"), "landed")
        authoritative_total = Decimal(total_cents) / 100
        try:
            canonical_total = float(authoritative_total)
            if not math.isfinite(canonical_total) or canonical_total <= 0:
                raise ValueError
            float_ulp = Decimal(str(math.ulp(canonical_total)))
            if float_ulp >= Decimal("0.005"):
                raise ValueError
            server_total = Decimal(str(landed))
        except (InvalidOperation, ValueError, OverflowError):
            raise MarketBridgeError("winner_amount_unrepresentable") from None
        if abs(server_total - authoritative_total) > float_ulp * 2:
            raise MarketBridgeError("winner_amount_mismatch")
        return {"round_id": round_id, "bid_id": winner.get("bid_id"), "seller_id": winner.get("seller_id"),
                "landed": canonical_total, "landed_cents": total_cents,
                "lines": order_lines, "origin": winner.get("origin"), "source": winner.get("source"),
                "binding_hash": binding_hash}

