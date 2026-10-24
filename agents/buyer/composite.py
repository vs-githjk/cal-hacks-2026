"""Bounded GPU/PSU/case feasibility checks for an upstream selected build snapshot."""
from decimal import Decimal, InvalidOperation
import json
from numbers import Real

from data.fit_checker import check_fit
from pay.callscript import ScriptError, _cents

PARTS = ("gpu", "psu", "case")
FIT_UNCHECKED = {"verdict": "uncertain", "rule_id": "fit.not_checked", "reasons": ["fit not checked"]}


def _nonnegative_cents(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        cents = Decimal(str(value)) * 100
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not cents.is_finite() or cents < 0 or cents != cents.to_integral_value():
        return None
    return int(cents)


def _integer_cents(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _valid_attrs(card):
    attrs = card.get("attrs") if isinstance(card, dict) else None
    if not isinstance(attrs, dict) or not attrs:
        return False
    try:
        json.dumps(attrs, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False
    return True


def _blocked(reason, parts=None, total=0, fit=None, cap=0):
    return {"status": "blocked", "parts": parts or [], "planned_total_cents": total,
            "cap_cents": cap, "remaining_cap_cents": max(0, cap - total),
            "fit": fit or FIT_UNCHECKED, "blocked_reasons": [reason]}


def _valid_goal(goal):
    if not isinstance(goal, dict) or goal.get("type") != "build_by_date" or not isinstance(goal.get("items"), list):
        return None
    by_part = {}
    for item in goal["items"]:
        if not isinstance(item, dict) or item.get("part") not in PARTS or item["part"] in by_part:
            return None
        quantity = item.get("quantity")
        if isinstance(quantity, bool) or quantity != 1:
            return None
        if not isinstance(item.get("sku_spec"), str) or not item["sku_spec"].strip():
            return None
        if "skipped_owned_part_id" in item and (
                not isinstance(item["skipped_owned_part_id"], str) or not item["skipped_owned_part_id"].strip()):
            return None
        by_part[item["part"]] = item
    return by_part if set(by_part) == set(PARTS) else None


def _owned_psu(goal_item, owned_parts, owned_cards, buyer_id):
    owned_id = goal_item.get("skipped_owned_part_id")
    if not isinstance(owned_id, str) or not owned_id:
        return None
    matches = [part for part in owned_parts if part.get("id") == owned_id]
    card = owned_cards.get(owned_id) if isinstance(owned_cards, dict) else None
    owned_sku = matches[0].get("sku_spec") if len(matches) == 1 else None
    if (not isinstance(owned_sku, str) or not owned_sku.split() or owned_sku.split()[0] != "psu"
            or matches[0].get("buyer_id") != buyer_id
            or not isinstance(card, dict) or card.get("category") != "psu"):
        return False
    owned_attrs = matches[0].get("attrs")
    card_attrs = card.get("attrs")
    origin, source = card.get("origin"), card.get("source")
    if not isinstance(owned_attrs, dict) or not owned_attrs or not _valid_attrs(card) \
            or not isinstance(origin, str) or origin not in {"LIVE", "MIRROR", "SIM"} \
            or not isinstance(source, str) or not source.strip():
        return False
    if any(card_attrs.get(key) != value for key, value in owned_attrs.items()):
        return False
    return {"part": "psu", "owned_part_id": owned_id, "spec_card": card, "amount_cents": 0,
            "source": card.get("source"), "origin": card.get("origin")}


def _selected_part(part, goal_item, candidate):
    if not isinstance(candidate, dict):
        return None, "selected bid snapshot is missing"
    bid, line, spec = candidate.get("bid"), candidate.get("line"), candidate.get("spec_card")
    quote = candidate.get("quote")
    index = candidate.get("line_index")
    if not isinstance(bid, dict) or not isinstance(line, dict) or not isinstance(spec, dict) or not isinstance(quote, dict):
        return None, "selected bid, line, SpecCard, or landed quote is missing"
    lines = bid.get("lines")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or not isinstance(lines, list) \
            or index >= len(lines) or lines[index] != line:
        return None, "selected line does not match the original bid line"
    if line.get("sku_spec") != goal_item["sku_spec"]:
        return None, "selected line SKU does not match the goal"
    allowed = goal_item.get("allowed_conditions", [goal_item.get("condition")])
    if not isinstance(allowed, list) or not allowed or any(not isinstance(c, str) for c in allowed):
        return None, "goal condition is invalid"
    condition = line.get("offered_condition", line.get("condition"))
    if condition not in allowed or not condition or condition == "unknown":
        return None, "selected line condition is not allowed by the goal"
    available = line.get("qty_available", line.get("quantity"))
    if isinstance(available, bool) or not isinstance(available, Real):
        return None, "selected line does not have quantity 1 available"
    try:
        available_ok = Decimal(str(available)).is_finite() and available >= 1
    except (InvalidOperation, OverflowError, TypeError, ValueError):
        available_ok = False
    if not available_ok:
        return None, "selected line does not have quantity 1 available"
    if spec.get("category") != part or not _valid_attrs(spec):
        return None, "selected SpecCard category or attributes are missing"
    origin, source = bid.get("origin"), bid.get("source")
    if not isinstance(origin, str) or origin not in {"LIVE", "MIRROR", "SIM"} \
            or not isinstance(source, str) or not source.strip():
        return None, "selected bid provenance is missing"
    spec_origin = spec.get("origin")
    if not isinstance(spec_origin, str) or spec_origin not in {"LIVE", "MIRROR", "SIM"} \
            or not isinstance(spec.get("source"), str) or not spec["source"].strip():
        return None, "selected SpecCard provenance is missing"
    if origin == "MIRROR":
        snapshot_id = bid.get("mirror_snapshot_id") or spec.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            return None, "MIRROR snapshot identity is missing"
    if not isinstance(bid.get("id"), str) or not bid["id"].strip() \
            or quote.get("bid_id") != bid.get("id") \
            or not isinstance(spec.get("id"), str) or not spec["id"].strip() \
            or quote.get("spec_card_id") != spec.get("id") \
            or quote.get("currency") != "USD" \
            or ("currency" in bid and bid.get("currency") != quote.get("currency")) \
            or not isinstance(quote.get("line_index"), int) or isinstance(quote.get("line_index"), bool) \
            or quote.get("line_index") != index \
            or quote.get("sku_spec") != line.get("sku_spec") or quote.get("condition") != condition \
            or quote.get("quantity") != 1 or isinstance(quote.get("quantity"), bool):
        return None, "landed quote is not bound to the selected bid line and quantity"
    shipping, tax, landed = (_integer_cents(quote.get(key)) for key in ("shipping_cents", "tax_cents", "landed_total_cents"))
    if shipping is None or tax is None or landed is None or landed <= 0:
        return None, "landed quote needs explicit nonnegative shipping, tax, and positive landed cents"
    try:
        unit_cents = _cents(line.get("unit_price"))
    except (ScriptError, TypeError):
        unit_cents = None
    if unit_cents is None or landed != unit_cents + shipping + tax:
        return None, "landed cents do not equal the selected line price plus explicit shipping and tax"
    return {"part": part, "bid": bid, "line": line, "spec_card": spec,
            "amount_cents": landed, "source": source, "origin": origin}, None


def plan_build(goal, selected, owned_parts, owned_cards, remaining_cap):
    """Check one upstream-selected GPU/PSU/case snapshot; this never selects, reserves, or buys."""
    by_part = _valid_goal(goal)
    if by_part is None:
        return _blocked("goal must contain exactly one quantity-1 GPU, PSU, and case")
    buyer_id = goal.get("buyer_id")
    if not isinstance(goal.get("id"), str) or not goal["id"].strip() \
            or not isinstance(buyer_id, str) or not buyer_id.strip():
        return _blocked("goal ID and buyer ID are required")
    if not isinstance(owned_parts, list) or any(not isinstance(part, dict) for part in owned_parts) \
            or not isinstance(owned_cards, dict) or any(not isinstance(card, dict) for card in owned_cards.values()):
        return _blocked("owned part records and cards have invalid shape")
    goal_cap = _nonnegative_cents(goal.get("cap"))
    remaining = _nonnegative_cents(remaining_cap)
    if goal_cap is None or remaining is None:
        return _blocked("goal and remaining cap must be finite nonnegative whole-cent amounts")
    cap = min(goal_cap, remaining)
    skipped = {part for part, item in by_part.items() if item.get("skipped_owned_part_id")}
    if skipped - {"psu"}:
        return _blocked("only an exactly identified owned PSU is supported")
    expected_selected = set(PARTS) - skipped
    if not isinstance(selected, dict) or set(selected) != expected_selected:
        return _blocked("selected snapshots must cover every unowned goal part exactly once")

    plans, cards, total, fit = [], [], 0, FIT_UNCHECKED
    for part in PARTS:
        item = by_part[part]
        if part in skipped:
            owned = _owned_psu(item, owned_parts, owned_cards, buyer_id)
            if not owned:
                return _blocked("owned PSU ID must match one owned record and a PSU SpecCard", plans, total, fit, cap)
            plans.append(owned)
            cards.append(owned["spec_card"])
        else:
            entry, error = _selected_part(part, item, selected[part])
            if error:
                return _blocked(f"{part}: {error}", plans, total, fit, cap)
            if total + entry["amount_cents"] > cap:
                return _blocked(f"{part}: selected landed amount exceeds the combined cap", plans, total, fit, cap)
            total += entry["amount_cents"]
            plans.append(entry)
            cards.append(entry["spec_card"])
        try:
            fit = check_fit(cards)
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as error:
            return _blocked(f"{part}: fit check could not validate the selected specs ({type(error).__name__})",
                            plans, total, FIT_UNCHECKED, cap)
        verdict = fit.get("verdict") if isinstance(fit, dict) else None
        if not isinstance(verdict, str) or verdict not in {"pass", "fail", "uncertain"}:
            return _blocked(f"{part}: fit checker returned an invalid result", plans, total, FIT_UNCHECKED, cap)
        if fit.get("verdict") == "fail":
            return _blocked(f"{part}: {fit.get('rule_id')} {fit.get('reasons', [])}", plans, total, fit, cap)

    if fit.get("verdict") != "pass":
        return _blocked(f"complete build fit is {fit.get('verdict')}", plans, total, fit, cap)
    return {"status": "plan_ready", "parts": plans, "planned_total_cents": total,
            "cap_cents": cap, "remaining_cap_cents": cap - total, "fit": fit, "blocked_reasons": []}
