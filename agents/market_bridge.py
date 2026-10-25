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

# Agent-only buyer contact view; names are tentative until the market confirms them. Swap here only.
GOAL_STATES = ("HUNTING", "HOLD_FOR_CALL", "DONE", "EXPIRED", "PAUSED", "FAILED")  # what set_goal_state accepts (#449 item 3)
BUYER_CONTACT_VIEW = "agent_buyer_contact"
BUYER_CONTACT_COLUMNS = ("buyer_id", "display_name", "phone")

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_META_KEYS = ("lineIndex", "shipping", "listingId", "listingHash", "source", "snapshotId", "provenance", "attrs")
# #447: only columns the published market module has (my_bids, round_result); #165's line_meta_json and binding_hash are not live
_BID_COLUMNS = ("id", "round_id", "seller_id", "persona", "lines", "stated_total", "perks", "claims", "origin", "source")
_RESULT_COLUMNS = ("bid_id", "seller_id", "rank", "landed", "reasons", "lines", "origin", "source")
_LINE_COLUMNS = ("sku_spec", "offered_spec", "offered_condition", "unit_price", "quantity")


def _rank_key(row: Mapping[str, Any]) -> float:
    rank = row.get("rank")
    return float(rank) if isinstance(rank, (int, float)) and not isinstance(rank, bool) else float("inf")


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
        rows = self._sql("SELECT " + ", ".join(_BID_COLUMNS) + " FROM my_bids WHERE id = " + _quote(bid_id))
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
        # The referee may post a need only for a web buyer's ACTIVE goal (market enforces it); same reducer and args.
        if self.role not in {"buyer", "referee"} or not isinstance(need, Mapping):
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
        # #447: the published module goes open -> closed (ranked at close); there is no review state or review_deadline
        rows = self._sql("SELECT id, need_id, state, deadline FROM round WHERE id = " + _quote(round_id))
        if len(rows) != 1:
            raise MarketBridgeError("round_readback_missing")
        row = _project(rows[0], ("id", "need_id", "state", "deadline"))
        if row.get("id") != round_id or row.get("state") not in {"open", "closed"}:
            raise MarketBridgeError("round_readback_invalid")
        if row.get("deadline") is not None:
            row["deadline"] = _timestamp_iso(row["deadline"])
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

    def buyer_contact(self, buyer_id: str) -> dict[str, Any] | None:
        """The buyer's contact (name, approval phone) from the agent-only market view; None when absent or on any failure."""
        columns = BUYER_CONTACT_COLUMNS
        try:
            rows = self._sql("SELECT " + ", ".join(columns) + " FROM " + BUYER_CONTACT_VIEW + " WHERE buyer_id = " + _quote(buyer_id))
            row = _project(rows[0], columns) if rows else None
        except Exception:
            return None
        if not row or row.get("buyer_id") != buyer_id:
            return None
        return {"buyer_id": buyer_id, "display_name": row.get("display_name") or None, "phone": row.get("phone") or None}

    def open_goals(self) -> list[dict[str, Any]]:
        """ACTIVE goals with their items from the referee-only agent views; [] for any other role or on any failure."""
        if self.role != "referee":
            return []
        try:
            goal_columns = ("id", "buyer_id", "type", "cap", "deadline", "state")
            item_columns = ("goal_id", "sku_spec", "condition", "variant", "quantity", "skipped_owned_part_id")
            goals = [_project(r, goal_columns) for r in self._sql("SELECT " + ", ".join(goal_columns) + " FROM agent_open_goals")]
            items = [_project(r, item_columns) for r in self._sql("SELECT " + ", ".join(item_columns) + " FROM agent_goal_items")]
        except Exception:
            return []
        return [dict(g, items=[{k: v for k, v in i.items() if k != "goal_id"} for i in items if i.get("goal_id") == g.get("id")])
                for g in goals if g.get("id") and g.get("buyer_id")]

    def claim_goal(self, goal_id: str) -> None:
        """#449 item 3 PL-9: take an ACTIVE goal off every agent's poll (referee-only reducer). The first writer wins; a goal
        already claimed or closed makes the reducer refuse, which is a MarketBridgeError here."""
        if self.role != "referee":
            raise MarketBridgeError("market_role_mismatch")
        self._call("claim_goal", goal_id=_safe_id(goal_id, "goal_id"))

    def set_goal_state(self, goal_id: str, state: str, text: str) -> None:
        """#449 item 3 PL-4: move a goal and tell its buyer in plain words (referee-only reducer; the text is cut to 200)."""
        if self.role != "referee":
            raise MarketBridgeError("market_role_mismatch")
        if state not in GOAL_STATES or not isinstance(text, str):
            raise MarketBridgeError("goal_state_invalid")
        self._call("set_goal_state", goal_id=_safe_id(goal_id, "goal_id"), state=state, text=text.strip()[:200])

    def approval_row(self, mandate_hash: str) -> dict[str, Any] | None:
        """#449 item 3: the approval row for a mandate from the referee-only agent_approvals view; None when there is none.
        A read failure raises (never reads as 'no approval'), so the caller can tell 'refused' from 'could not look'."""
        columns = ("mandate_hash", "method", "approved_by", "at", "voice_approval_id")
        row = self._agent_row("agent_approvals", columns, mandate_hash)
        if row is None:
            return None
        row["at"] = _timestamp_iso(row.get("at"))
        return row

    def payment_row(self, mandate_hash: str) -> dict[str, Any] | None:
        """#449 item 3: the payment row for a mandate from the referee-only agent_payments view; None when there is none."""
        columns = ("mandate_hash", "payment_ref", "amount", "mode", "at")
        row = self._agent_row("agent_payments", columns, mandate_hash)
        if row is None:
            return None
        row["amount"] = _finite(row.get("amount"), "payment_amount")
        row["at"] = _timestamp_iso(row.get("at"))
        return row

    def _agent_row(self, view: str, columns: Sequence[str], mandate_hash: str) -> dict[str, Any] | None:
        if self.role != "referee":
            raise MarketBridgeError("market_role_mismatch")
        if not _HASH.fullmatch(str(mandate_hash)):
            raise MarketBridgeError("mandate_hash_invalid")
        rows = self._sql("SELECT " + ", ".join(columns) + " FROM " + view + " WHERE mandate_hash = " + _quote(mandate_hash))
        if not rows:
            return None
        row = _project(rows[0], columns)
        if len(rows) != 1 or row.get("mandate_hash") != mandate_hash or any(c not in row for c in columns):
            raise MarketBridgeError("market_readback_invalid")
        return {c: row[c] for c in columns}

    def issue_approval_code(self, mandate_hash: str, code: str) -> None:
        """Show the spoken approval code on the buyer's /buyer screen (referee-only reducer). Never logs the code."""
        if self.role != "referee" or not _HASH.fullmatch(str(mandate_hash)) or not isinstance(code, str) or not code:
            raise MarketBridgeError("approval_code_binding_invalid")
        self._call("issue_approval_code", mandate_hash=mandate_hash, code=code)

    def deny_approval(self, mandate_hash: str, reason: str) -> None:
        """Release the units held for a mandate whose approval call failed or was denied (referee or the buyer; the market refuses it
        once approved). The market writes its own notification and floor event; the reason is a short plain sentence."""
        if self.role not in {"buyer", "referee"}:
            raise MarketBridgeError("market_role_mismatch")
        if not _HASH.fullmatch(str(mandate_hash)) or not isinstance(reason, str) or not reason.strip():
            raise MarketBridgeError("approval_denial_invalid")
        self._call("deny_approval", mandate_hash=mandate_hash, reason=reason.strip()[:200])

    def create_mandate(self, mandate: Mapping[str, Any], *, need_id: str, buyer_id: str,
                       requested_by: str = "", now: datetime) -> dict[str, Any]:
        if self.role != "referee" or not isinstance(mandate, Mapping):
            raise MarketBridgeError("market_role_mismatch")
        required = ("hash", "id", "deal_id", "buyer_id", "payee", "nonce", "expires_at", "origin", "goal_id")
        if (any(not isinstance(mandate.get(k), str) or not mandate[k] for k in required)
                or _finite(mandate.get("amount"), "mandate_amount", minimum=0.000000001) <= 0):
            raise MarketBridgeError("mandate_binding_invalid")
        if (not _HASH.fullmatch(mandate["hash"]) or mandate["buyer_id"] != _safe_id(buyer_id, "buyer_id")
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
                }  # #447: the module's create_mandate takes no goal_id or need_id
        # The market only creates a mandate through the referee, and the reducer is the check (it binds the winner, payee and amount);
        # the referee cannot read a buyer-private row, and main's module has none (no my_purchase_status).
        self._call("create_mandate", **args)
        return {"mandate_hash": mandate["hash"]}

    def record_approval(self, *, mandate_hash: str, method: str, approved_by: str,
                        voice_approval_id: str = "", code: str = "") -> dict[str, Any]:
        """`code` is the word pair issued for the call (#449 item 3 RT-11); the market compares it with its own row. Never logged."""
        if self.role != "referee" or method != "voice_code":
            raise MarketBridgeError("approval_binding_invalid")
        if not voice_approval_id or not isinstance(code, str) or not code.strip():
            raise MarketBridgeError("approval_binding_invalid")
        self._call("record_approval", mandate_hash=mandate_hash, method=method, approved_by=_safe_id(approved_by, "buyer_id"),
                   voice_approval_id=_safe_id(voice_approval_id, "voice_approval_id"), code=code)
        return {"mandate_hash": mandate_hash, "approval_method": method}

    def record_payment(self, *, mandate_hash: str, payment_ref: str, amount: float, mode: str) -> dict[str, Any]:
        if self.role != "referee" or mode not in {"sim", "stripe_test"}:
            raise MarketBridgeError("payment_binding_invalid")
        args = {"mandate_hash": mandate_hash, "payment_ref": _safe_id(payment_ref, "payment_ref"),
                "amount": _finite(amount, "payment_amount", minimum=0.000000001), "mode": mode}
        self._call("record_payment", **args)
        # The caller confirms with payment_row (the referee-only agent_payments view) before it goes on.
        return {"recorded": True}

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
        # #447: the published module has no set_bid_line_meta; the line metadata stays with the seller and the buyer's copy
        observed = self._own_bid(bid_id)
        if observed is None:
            raise MarketBridgeError("bid_readback_missing")
        if not self._same_bid(observed, bid_id=bid_id, round_id=round_id, seller_id=seller_id,
                              persona=persona, lines=wire_lines, stated_total=total, perks=perks,
                              claims=claims, origin=origin, source=source):
            raise MarketBridgeError("bid_readback_mismatch")
        return {"bid_id": bid_id, "round_id": round_id, "seller_id": seller_id, "line_metadata": metadata}

    def attach_advocate_card(self, *, bid_id: str, recommendation: str, rule_id: str, text: str,
                             source_url: str, origin: str, binding_hash: str) -> None:
        if not _HASH.fullmatch(binding_hash):
            raise MarketBridgeError("candidate_binding_invalid")
        # #447: binding_hash is checked here and kept by the buyer; the module's reducer does not take it
        self._call("attach_advocate_card", bid_id=_safe_id(bid_id, "bid_id"), recommendation=recommendation,
                   rule_id=rule_id, text=text, source_url=source_url, origin=origin)

    def attach_claim_check(self, *, bid_id: str, claim: str, check: str, evidence_url: str, origin: str,
                           binding_hash: str, line_index: int, listing_id: str, listing_hash: str) -> None:
        if isinstance(line_index, bool) or not isinstance(line_index, int) or line_index < 0 or not _HASH.fullmatch(binding_hash) or not _HASH.fullmatch(listing_hash):
            raise MarketBridgeError("candidate_binding_invalid")
        # #447: the line binding is checked here and kept by the buyer; the module's reducer takes only these
        self._call("attach_claim_check", bid_id=_safe_id(bid_id, "bid_id"), claim=claim, check=check,
                   evidence_url=evidence_url, origin=origin)

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
        # #447: only round_result columns the published module has. It ranks at close on unit price x requested quantity
        # (no shipping, no line metadata), so the buyer binds these lines to its own reviewed copy of the bid.
        query = ("SELECT " + ", ".join(_RESULT_COLUMNS) + " FROM round_result WHERE round_id = " + _quote(round_id))
        rows = self._sql(query)  # no ORDER BY: Maincloud sql answers 400 Unsupported, so rank order is applied here
        result = [_project(raw, _RESULT_COLUMNS) for raw in rows]
        result.sort(key=_rank_key)
        ranked = [row for row in result if row.get("rank") == 1]
        if not ranked:
            return None
        if len(ranked) != 1:
            raise MarketBridgeError("winner_readback_ambiguous")
        winner = ranked[0]
        reasons = _decode(winner.get("reasons"))
        lines = _normalized_lines(winner.get("lines"))
        if reasons != []:
            raise MarketBridgeError("winner_readback_invalid")
        if len(lines) != len(expected):
            return None
        order_lines = []
        seen: set[str] = set()
        total_cents = 0
        for bid_line in lines:
            sku = _field(bid_line, "sku_spec")
            if sku not in expected or sku in seen:
                return None
            seen.add(sku)
            stock = _finite(_field(bid_line, "quantity"), "quantity", minimum=0.000000001)
            quantity = expected[sku]
            if stock < quantity:
                return None
            price = _finite(_field(bid_line, "unit_price"), "unit_price")
            try:
                exact_line = Decimal(str(price)) * Decimal(str(quantity))
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                raise MarketBridgeError("winner_amount_invalid") from None
            total_cents += _decimal_cents(exact_line, "winner_amount")
            order_lines.append({"sku_spec": sku, "unit_price": price, "quantity": quantity, "qty_available": stock,
                                "offered_condition": bid_line["offered_condition"], "offered_spec": bid_line["offered_spec"]})
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
                "lines": order_lines, "origin": winner.get("origin"), "source": winner.get("source")}

