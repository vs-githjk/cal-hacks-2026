"""Small, safe summary of the seller round for the buyer chat."""

import re
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit


def _safe(value: object) -> str:
    value = re.split(r"[\x00-\x1f\x7f]", str(value), maxsplit=1)[0].strip()
    return " ".join(value.split())[:160]


def _source(value: object) -> str:
    raw = str(value) if isinstance(value, str) else ""
    if not raw or len(raw) > 2048 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw):
        return "source unavailable"
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return "source unavailable"
    except ValueError:
        return "source unavailable"
    return raw


def round_trace(
    sellers: Sequence[object],
    bids: Sequence[Mapping[str, object]],
    cards: Mapping[str, Mapping[str, object]],
    winner: Mapping[str, object] | None,
) -> str:
    """Return one line from round facts, excluding seller text and approval data."""
    asked = [_safe(s) for s in sellers if _safe(s)]
    by_id = {str(b.get("id")): b for b in bids if isinstance(b, Mapping) and b.get("id") is not None}
    card_by_id = {str(k): v for k, v in cards.items() if isinstance(v, Mapping)} if isinstance(cards, Mapping) else {}

    parts = [f"Round: asked {', '.join(asked) or 'no sellers'}"]
    vetoes = []
    for bid_id, card in sorted(card_by_id.items(), key=lambda item: (_safe(by_id.get(item[0], {}).get("supplier_id", "")), item[0])):
        if card.get("recommendation") != "veto":
            continue
        bid = by_id.get(bid_id, {})
        if not bid:
            continue
        seller = _safe(bid.get("supplier_id", "unknown seller"))
        warnings = card.get("warnings", [])
        source = ""
        if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes)):
            for warning in warnings:
                if isinstance(warning, Mapping) and warning.get("source_url"):
                    source = _source(warning["source_url"])
                    break
        vetoes.append(f"{seller} ({source or 'source unavailable'})")
    if vetoes:
        parts.append("advocate vetoed " + ", ".join(vetoes))

    selected = winner if isinstance(winner, Mapping) else None
    if isinstance(selected, Mapping) and selected.get("supplier_id"):
        price = selected.get("total_landed_price")
        at = f" at ${price:.2f}" if isinstance(price, (int, float)) and not isinstance(price, bool) else ""
        parts.append(f"recommended {_safe(selected['supplier_id'])}{at}")
    else:
        parts.append("no reviewed recommendation")
    return "; ".join(parts) + "."


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def veto_notes(
    bids: Sequence[Mapping[str, object]],
    cards: Mapping[str, Mapping[str, object]],
    pick: Mapping[str, object] | None,
    limit: int = 3,
) -> list[str]:
    """#449 RT-22: one plain line per vetoed bid that was cheaper than `pick`, with the advocate's reason and its source, so the
    owner sees why the cheaper bid did not win. At most `limit` lines: past that, the last line counts the rest. Seller and
    advocate text is cut at the first control character, so it cannot add a line or a command."""
    pick_price = _number(pick.get("total_landed_price")) if isinstance(pick, Mapping) else None
    if pick_price is None or limit < 1 or not isinstance(cards, Mapping):
        return []
    found = []
    for bid in bids:
        card = cards.get(str(bid.get("id"))) if isinstance(bid, Mapping) else None
        price = _number(bid.get("total_landed_price")) if isinstance(bid, Mapping) else None
        if not isinstance(card, Mapping) or card.get("recommendation") != "veto" or price is None or price >= pick_price:
            continue
        reason_row = card.get("call_reason") if isinstance(card.get("call_reason"), Mapping) else {}
        reason = _safe(reason_row.get("summary") or card.get("reason") or "").rstrip(".") or "no reason was given"
        candidates = [reason_row.get("source_url"), card.get("source_url")]
        warnings = card.get("warnings")
        if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes)):
            candidates += [w.get("source_url") for w in warnings if isinstance(w, Mapping)]
        source = next((u for u in map(_source, candidates) if u != "source unavailable"), "source unavailable")
        name = _safe(bid.get("persona")) or _safe(bid.get("supplier_id")) or "a seller"
        found.append((price, str(bid.get("id")), f"The advocate vetoed {name} (${price:.2f}), cheaper than the one I picked: {reason}. Source: {source}"))
    lines = [line for _price, _id, line in sorted(found)]
    if len(lines) > limit:
        lines = lines[:limit - 1] + [f"The advocate vetoed {len(lines) - limit + 1} more cheaper bids too."]
    return lines

